"""
Jarvis V2 — Voice AI Server
FastAPI backend: receives speech text, thinks with Claude Haiku,
speaks with ElevenLabs, controls browser with Playwright.
"""

# PEP 563: lazy annotation evaluation. Needed because the Mac Mini
# still runs Python 3.9 (macOS system python) and `dict | None` /
# `str | None` union syntax is a 3.10+ feature that would otherwise
# crash the import at load time with
#   TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'
# With __future__ annotations all type hints are stored as strings and
# only evaluated by tools that actually ask for them, so runtime is
# version-agnostic.
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import time

import anthropic
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Load .env first, then config.json. The .env file always wins over
# shell-env (override=True), because users sometimes have empty shadow
# vars like ANTHROPIC_API_KEY="" in their .zshrc which would otherwise
# silently block dotenv loading.
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
with open(CONFIG_PATH, "r") as f:
    config = json.load(f)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY") or config.get("anthropic_api_key", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY") or config.get("elevenlabs_api_key", "")

if not ANTHROPIC_API_KEY or not ELEVENLABS_API_KEY:
    raise RuntimeError(
        "Missing API keys. Set ANTHROPIC_API_KEY and ELEVENLABS_API_KEY in .env "
        "or config.json."
    )
ELEVENLABS_VOICE_ID = config.get("elevenlabs_voice_id", "rDmv3mOhK6TnhYWckFaD")
USER_NAME = config.get("user_name", "Julian")
USER_ADDRESS = config.get("user_address", "Sir")
CITY = config.get("city", "Hamburg")
TASKS_FILE = config.get("obsidian_inbox_path", "")
PROFILE_FILE = config.get("obsidian_profile_path", "")

ai = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
http = httpx.AsyncClient(timeout=30)

app = FastAPI()

import browser_tools
import screen_capture
import home_assistant

ha_client = home_assistant.build_client_from_config(config)

# Window monitor config
WINDOW_MONITOR_SENSORS = config.get("window_monitor_sensors", [])
WINDOW_MONITOR_PERSONS = config.get("window_monitor_persons", [])
WINDOW_MONITOR_NOTIFY = config.get("window_monitor_notify", "")


def get_weather_sync():
    """Fetch raw weather data at startup (for the fixed home CITY)."""
    import urllib.request
    try:
        req = urllib.request.Request(f"https://wttr.in/{CITY}?format=j1", headers={"User-Agent": "curl"})
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read())
        c = data["current_condition"][0]
        return {
            "temp": c["temp_C"],
            "feels_like": c["FeelsLikeC"],
            "description": c["weatherDesc"][0]["value"],
            "humidity": c["humidity"],
            "wind_kmh": c["windspeedKmph"],
        }
    except:
        return None


def get_weather_for_coords_sync(lat: float, lon: float) -> dict | None:
    """Fetch weather + reverse-geocoded city name for a lat/lon pair.

    Used by the mobile geolocation override: the iPhone sends its current
    position, and we look up wttr.in with "{lat},{lon}". wttr's j1 JSON
    response always includes a nearest_area[0].areaName[0].value string,
    which we treat as the user's current city so Jarvis can greet them
    with the right place name ("in Hamburg" instead of "in Kisdorf").
    Blocking urllib.request call, wrapped in asyncio.to_thread at the
    async call site.
    """
    import urllib.request
    try:
        url = f"https://wttr.in/{lat},{lon}?format=j1"
        req = urllib.request.Request(url, headers={"User-Agent": "curl"})
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read())
        c = data["current_condition"][0]
        # Reverse-geocoded area name from wttr. Fall back to a generic
        # "Ihrem aktuellen Standort" if the shape is unexpected, because
        # anything here is more useful than crashing.
        city_name = "Ihrem aktuellen Standort"
        try:
            city_name = data["nearest_area"][0]["areaName"][0]["value"] or city_name
        except (KeyError, IndexError, TypeError):
            pass
        return {
            "temp": c["temp_C"],
            "feels_like": c["FeelsLikeC"],
            "description": c["weatherDesc"][0]["value"],
            "humidity": c["humidity"],
            "wind_kmh": c["windspeedKmph"],
            "city": city_name,
            "lat": lat,
            "lon": lon,
        }
    except Exception as e:
        print(f"[jarvis] Geo weather lookup failed: {e}", flush=True)
        return None


def get_tasks_sync():
    """Read open tasks from Obsidian (sync)."""
    if not TASKS_FILE:
        return []
    try:
        tasks_path = os.path.join(TASKS_FILE, "Tasks.md")
        with open(tasks_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return [l.strip().replace("- [ ]", "").strip() for l in lines if l.strip().startswith("- [ ]")]
    except:
        return []


def get_profile_sync():
    """Read a personal profile markdown file from Obsidian.

    Gives Jarvis persistent context about the user — name, family,
    companies, preferences, devices, whatever the user wants to put
    there. Strips the YAML frontmatter so we don't waste tokens on
    tags/aliases that don't help the LLM.
    """
    if not PROFILE_FILE:
        return ""
    try:
        with open(PROFILE_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        # Strip YAML frontmatter if present: first --- block at top of file.
        if content.startswith("---"):
            end = content.find("\n---", 3)
            if end != -1:
                content = content[end + 4:]
        return content.strip()
    except Exception as e:
        print(f"[jarvis] Profile load error: {e}", flush=True)
        return ""


def get_home_sync():
    """Fetch a compact Home Assistant dashboard snapshot (sync wrapper).

    ONLY safe to call at module-load time, where no event loop is running
    yet. Inside async handlers (e.g. the WebSocket message loop) use
    refresh_data_async() / await ha_client.get_dashboard_status() instead,
    because asyncio.run() cannot be called from a running event loop.
    """
    if not ha_client.configured:
        return ""
    try:
        return asyncio.run(ha_client.get_dashboard_status())
    except Exception as e:
        print(f"[jarvis] HA load error: {e}", flush=True)
        return ""


def _log_refresh():
    print(f"[jarvis] Wetter: {WEATHER_INFO}", flush=True)
    print(f"[jarvis] Tasks: {len(TASKS_INFO)} geladen", flush=True)
    print(f"[jarvis] Profil: {len(PROFILE_INFO)} Zeichen geladen", flush=True)
    print(f"[jarvis] Home Assistant: {len(HOME_INFO)} Zeichen geladen", flush=True)


def refresh_data():
    """Sync refresh — for the initial module-load call only."""
    global WEATHER_INFO, TASKS_INFO, PROFILE_INFO, HOME_INFO
    WEATHER_INFO = get_weather_sync()
    TASKS_INFO = get_tasks_sync()
    PROFILE_INFO = get_profile_sync()
    HOME_INFO = get_home_sync()
    _log_refresh()


async def refresh_data_async():
    """Async refresh — safe to call from inside a running event loop
    (e.g. the WebSocket handler when the user says 'Jarvis activate').
    Uses `await` directly on the HA client instead of asyncio.run(), which
    would raise 'cannot be called from a running event loop'.
    """
    global WEATHER_INFO, TASKS_INFO, PROFILE_INFO, HOME_INFO
    WEATHER_INFO = get_weather_sync()
    TASKS_INFO = get_tasks_sync()
    PROFILE_INFO = get_profile_sync()
    if ha_client.configured:
        try:
            HOME_INFO = await ha_client.get_dashboard_status()
        except Exception as e:
            print(f"[jarvis] HA load error: {e}", flush=True)
            HOME_INFO = ""
    else:
        HOME_INFO = ""
    _log_refresh()

WEATHER_INFO = ""
TASKS_INFO = []
PROFILE_INFO = ""
HOME_INFO = ""
refresh_data()

# Action parsing
ACTION_PATTERN = re.compile(r'\[ACTION:(\w+)\]\s*(.*?)$', re.DOTALL | re.MULTILINE)

conversations: dict[str, list] = {}

# Throttle full "Jarvis activate" greeting to max once every 2 hours.
# Subsequent activations within the window get a short acknowledgment.
GREETING_COOLDOWN_SECS = 7200  # 2 hours
_last_full_greeting_ts: float = 0.0

# Per-session overrides keyed by session_id. The mobile frontend sends
# {"type": "location", "lat": ..., "lon": ...} once at startup; the server
# looks up current weather + reverse-geocoded city for that position and
# stores the result here. build_system_prompt(session_id) then prefers
# this over the global CITY/WEATHER_INFO so Jarvis talks about "Hamburg"
# when the user is in Hamburg, but still defaults to Kisdorf on the Mac
# Mini where no location override is sent.
session_context: dict[str, dict] = {}

# Pending screenshot requests: session_id -> asyncio.Future.
# When [ACTION:SCREEN] runs, we ask the client for a screenshot and
# await the future until the client answers (or a timeout hits).
pending_screenshots: dict[str, asyncio.Future] = {}


def build_system_prompt(session_id: str | None = None, short_greeting: bool = False):
    # Per-session override for mobile geolocation. If the client sent a
    # {type:location} message, we use its reverse-geocoded city + fresh
    # weather reading; otherwise we fall back to the home CITY / startup
    # WEATHER_INFO.
    override = session_context.get(session_id or "", {}) if session_id else {}
    session_weather = override.get("weather")
    session_city = override.get("city")

    effective_city = session_city or CITY
    effective_weather = session_weather or WEATHER_INFO

    weather_block = ""
    if effective_weather:
        w = effective_weather
        weather_block = f"\nWetter {effective_city}: {w['temp']}°C, gefuehlt {w['feels_like']}°C, {w['description']}"
        if session_weather:
            weather_block += f" (aktueller Standort von {USER_NAME})"

    task_block = ""
    if TASKS_INFO:
        task_block = f"\nOffene Aufgaben ({len(TASKS_INFO)}): " + ", ".join(TASKS_INFO[:5])

    profile_block = ""
    if PROFILE_INFO:
        profile_block = (
            "\n\n=== PROFIL DES DIENSTHERRN ===\n"
            f"{PROFILE_INFO}\n"
            "=== ENDE PROFIL ==="
        )

    home_block = ""
    if HOME_INFO:
        home_block = (
            "\n\n=== SMART HOME STATUS (Home Assistant) ===\n"
            f"{HOME_INFO}\n"
            "=== ENDE SMART HOME ==="
        )

    if short_greeting:
        activate_instructions = (
            f"- Begruesse {USER_NAME} KURZ mit einem einzigen Satz, z.B. 'Willkommen zurueck, {USER_ADDRESS}.' oder 'Zu Diensten, {USER_ADDRESS}.' oder eine aehnliche kurze, charmante Begruessungsformel.\n"
            "- KEIN Wetter, KEINE Aufgaben, KEIN Smart-Home-Status. Nur die kurze Begruessungsformel.\n"
            "- Halte es auf maximal 1 Satz."
        )
    else:
        activate_instructions = (
            "- Begruesse ihn passend zur Tageszeit (aktuelle Zeit: {time}).\n"
            "- Gebe eine kurze Info ueber das Wetter — Temperatur und ob Sonne/klar/bewoelkt/Regen, und wie es sich anfuehlt. Keine Luftfeuchtigkeit.\n"
            "- Fasse die Aufgaben kurz als Ueberblick in einem Satz zusammen, ohne dabei jede einzelne Aufgabe einfach vorzulesen. Gebe gerne einen humorvollen Kommentar am Ende an.\n"
            "- Sei kreativ bei der Begruessung."
        )

    return f"""Du bist Jarvis, der KI-Assistent von Tony Stark aus Iron Man. Dein Dienstherr ist {USER_NAME}. Du sprichst ausschliesslich Deutsch. {USER_NAME} moechte mit "{USER_ADDRESS}" angesprochen und gesiezt werden. Nutze "Sie" als Pronomen — FALSCH: "{USER_ADDRESS} planen", RICHTIG: "Sie planen, {USER_ADDRESS}". Dein Ton ist trocken, sarkastisch und britisch-hoeflich - wie ein Butler der alles gesehen hat und trotzdem loyal bleibt. Du machst subtile, trockene Bemerkungen, bist aber niemals respektlos. Wenn {USER_ADDRESS} eine offensichtliche Frage stellt, darfst du mit elegantem Sarkasmus antworten. Du bist hochintelligent, effizient und immer einen Schritt voraus. Halte deine Antworten kurz - maximal 3 Saetze. Du kommentierst fragwuerdige Entscheidungen hoeflich aber spitz.

Du kennst {USER_NAME} gut — nutze das PROFIL unten, um Fragen konkret zu beantworten. Wenn {USER_NAME} nach etwas fragt, das im Profil steht (Familie, Firmen, Haus, Fahrzeuge, Smart Home, Projekte), beziehe dich darauf, als waere es selbstverstaendlich — du bist schliesslich sein Butler. Erfinde NICHTS, was nicht im Profil steht.

GOLDENE REGEL DATENLAGE: Wenn ein Wert oder ein Geraet NICHT im Block SMART HOME STATUS auftaucht, heisst das NUR "ich habe dazu gerade keine Daten" — NICHT "es existiert nicht". Verneine NIEMALS die Existenz von Geraeten, Sensoren, Batterien oder Anlagen, nur weil sie im Status-Block fehlen. In dem Fall sage ehrlich "Dazu liegen mir gerade keine Live-Daten vor, {USER_ADDRESS}" oder rufe [ACTION:HOME] mit einem Suchbegriff auf, um frische Daten zu holen. {USER_NAME} hat einen vollstaendigen Hausstack (PV E3DC 20,5 kWp MIT Hausakku ca. 19,7 kWh, Zappi Wallboxen, Pool, BMW iX1, Volvo XC90 T8) — diese Dinge sind alle real vorhanden, auch wenn ein einzelner Sensor gerade nicht durchkommt.

GOLDENE REGEL PLAUSIBILITAET: Smart-Home-Sensoren koennen veraltete Werte melden, besonders: BMW Connected Drive aktualisiert Ladedaten NICHT wenn das Auto unterwegs ist (zeigt letzten Wert). Wallbox-Status kann haengenbleiben. Pruefe IMMER ob die Daten logisch zusammenpassen. Wenn im SMART HOME STATUS ein Block "PLAUSIBILITAETS-HINWEISE" erscheint, nutze diese Hinweise intern — lies sie NICHT woertlich vor, aber korrigiere deine Aussagen entsprechend. Beispiel: Wenn person.britta = "not_home" aber BMW Ladeleistung > 0, dann ist der BMW-Wert veraltet — sage NICHT "der BMW laedt gerade". Vertraue bei Widerspruechen der Anwesenheitserkennung mehr als den Fahrzeug-/Wallbox-Sensoren.

WICHTIG: Schreibe NIEMALS Regieanweisungen, Emotionen oder Tags in eckigen Klammern wie [sarcastic] [formal] [amused] [dry] oder aehnliches. Dein Sarkasmus muss REIN durch die Wortwahl kommen. Alles was du schreibst wird laut vorgelesen.

Du hast die volle Kontrolle ueber den Browser von {USER_NAME}. Du kannst im Internet suchen, Webseiten oeffnen und den Bildschirm sehen. Wenn {USER_ADDRESS} dich bittet etwas nachzuschauen, zu recherchieren, zu googeln, eine Seite zu oeffnen, oder irgendetwas im Internet zu tun — nutze IMMER eine Aktion. Frag nicht ob du es tun sollst, tu es einfach.

AKTIONEN - Schreibe die passende Aktion ans ENDE deiner Antwort. Der Text VOR der Aktion wird vorgelesen, die Aktion selbst wird still ausgefuehrt.
[ACTION:SEARCH] suchbegriff - Internet durchsuchen und Ergebnisse zusammenfassen
[ACTION:OPEN] url - URL im Browser oeffnen
[ACTION:SCREEN] - Bildschirm ansehen und beschreiben. WICHTIG: Bei SCREEN schreibe NUR die Aktion, KEINEN Text davor. Also NUR "[ACTION:SCREEN]" und sonst nichts.
[ACTION:NEWS] - Aktuelle Weltnachrichten abrufen. Nutze diese Aktion wenn nach News, Nachrichten, was in der Welt passiert, aktuelle Lage oder Weltgeschehen gefragt wird. Schreibe einen kurzen Satz davor wie "Ich schaue nach den aktuellen Nachrichten."
[ACTION:HOME] - Kompletten Smart Home Dashboard-Status aus Home Assistant abrufen (Solar, PV, Wallbox, Pool, Fahrzeuge, Alarm, Anwesenheit, Klima, Garten). Schreibe die Aktion EXAKT so: "[ACTION:HOME]" — KEINE weiteren Zeichen dahinter, KEINE Platzhalter wie <blank> oder <empty>, KEINE neue Zeile mit Inhalt, einfach nur die Aktion.
[ACTION:HOME] suchbegriff - Nur passende Sensoren abrufen. Beispiele: "[ACTION:HOME] pool", "[ACTION:HOME] volvo", "[ACTION:HOME] solar". Nutze die Variante mit Suchbegriff, wenn {USER_NAME} nach einem bestimmten Bereich fragt.
Nutze diese Aktion bei Fragen nach Solar, PV, Batterie, Wallbox, Pool, Garten, Bewässerung, Auto/Fahrzeug-Akku, Alarm, ob jemand zu Hause ist, CO2, Außentemperatur oder Smart Home allgemein. Der aktuelle Stand steht unten auch schon im Block SMART HOME STATUS — bei einfachen Fragen kannst du direkt daraus antworten, bei detaillierten oder Live-Fragen nutze die Aktion fuer frische Daten.
ECHTZEIT-PFLICHT: Bei Fragen zur Wallbox (Ladestatus, Ladeleistung, ob ein Auto laedt, Stecker-Status, Lademodus) nutze IMMER "[ACTION:HOME] wallbox" fuer frische Live-Daten. Antworte bei Wallbox-Fragen NIEMALS nur aus dem SMART HOME STATUS Cache — Wallbox-Sensoren koennen veraltet sein.
[ACTION:LIGHT] service entity_id [parameter=wert] - Philips Hue Lichter steuern. Services: turn_on, turn_off, toggle. Optionale Parameter: brightness (0-255), color_temp (153-500 Mired). Beispiele: "[ACTION:LIGHT] turn_on light.kuche", "[ACTION:LIGHT] turn_off light.wohnzimmer", "[ACTION:LIGHT] turn_on light.schlafzimmer brightness=128", "[ACTION:LIGHT] toggle light.garage". Raeume: Kueche (light.kuche), Wohnzimmer (light.wohnzimmer), Schlafzimmer (light.schlafzimmer), Flur oben/unten (light.flur_oben, light.flur_unten), Veranda (light.veranda), Garage (light.garage), Kinderzimmer (light.kinderzimmer), Arbeitszimmer (light.arbeitszimmer_maure), HWR (light.hwr), Nebeneingang (light.nebeneingang), Muellhaus (light.mullhaus), Sofa Go (light.sofa_links_go, light.sofa_rechts_go), Leselampe (light.leselampe), Fernsehschrank (light.fernsehschrank), Anrichte (light.anrichte_links, light.anrichte_rechts), Bett Schlafzimmer (light.bett_schlafzimmer). Nutze diese Aktion wenn {USER_NAME} Licht an/aus/dimmen will. Wenn unklar welches Licht gemeint ist, frage nach.
[ACTION:CLAUDE] task - Delegiere eine Coding- oder Entwickler-Aufgabe an Claude Code (das CLI laeuft im Jarvis-Workspace). Nutze diese Aktion wenn {USER_NAME} sagt: "sag Claude er soll...", "lass Claude das machen", "Claude soll...", oder wenn eine Aufgabe klar Entwickler-Arbeit ist (Code refactoren, Bug fixen, Feature bauen, Datei anlegen, Tests schreiben). Formuliere die Aufgabe als klaren Auftrag fuer Claude. Beispiele: "[ACTION:CLAUDE] Refactore die Wallbox-Integration und trenne die myenergi-spezifische Logik in eine eigene Datei", "[ACTION:CLAUDE] Fuege einen Unit-Test fuer die search_entities-Funktion in home_assistant.py hinzu". Schreibe einen kurzen Satz davor wie "Ich gebe das an Claude weiter, Sir." — der Lauf kann mehrere Minuten dauern.

WENN {USER_NAME} "Jarvis activate" sagt:
{activate_instructions}

AKTUELLES DATUM UND UHRZEIT (NICHT RATEN!):
Heute ist {{date_long}}. Die aktuelle Uhrzeit ist {{time}} Uhr.
Wenn {USER_ADDRESS} nach Wochentag, Datum, Monat, Jahr oder Uhrzeit fragt, nutze AUSSCHLIESSLICH diese Werte. Verlasse dich niemals auf dein internes Wissen oder Trainings-Daten fuer Zeitangaben — die sind veraltet.

=== AKTUELLE DATEN ==={weather_block}{task_block}
==={profile_block}{home_block}"""


def get_system_prompt(session_id: str | None = None, short_greeting: bool = False):
    # German locale-independent date formatting — we build the string
    # manually so the output is always correct German regardless of
    # whether the macOS de_DE locale is installed and set.
    now = time.localtime()
    weekdays_de = ["Montag", "Dienstag", "Mittwoch", "Donnerstag",
                   "Freitag", "Samstag", "Sonntag"]
    months_de = ["Januar", "Februar", "März", "April", "Mai", "Juni",
                 "Juli", "August", "September", "Oktober", "November", "Dezember"]
    weekday = weekdays_de[now.tm_wday]
    month = months_de[now.tm_mon - 1]
    date_long = f"{weekday}, der {now.tm_mday}. {month} {now.tm_year}"
    return (
        build_system_prompt(session_id, short_greeting=short_greeting)
        .replace("{time}", time.strftime("%H:%M"))
        .replace("{date_long}", date_long)
    )


def extract_action(text: str):
    match = ACTION_PATTERN.search(text)
    if match:
        clean = text[:match.start()].strip()
        return clean, {"type": match.group(1), "payload": match.group(2).strip()}
    return text, None


async def synthesize_speech(text: str) -> bytes:
    if not text.strip():
        return b""

    # Split long text into chunks at sentence boundaries to avoid ElevenLabs cutoff
    chunks = []
    if len(text) > 250:
        sentences = re.split(r'(?<=[.!?])\s+', text)
        current = ""
        for s in sentences:
            if len(current) + len(s) > 250 and current:
                chunks.append(current.strip())
                current = s
            else:
                current = (current + " " + s).strip()
        if current:
            chunks.append(current.strip())
    else:
        chunks = [text]

    audio_parts = []
    for chunk in chunks:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
        try:
            resp = await http.post(url, headers={
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            }, json={
                "text": chunk,
                "model_id": "eleven_turbo_v2_5",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.85},
            })
            print(f"  TTS chunk status: {resp.status_code}, size: {len(resp.content)}", flush=True)
            if resp.status_code == 200:
                audio_parts.append(resp.content)
            else:
                print(f"  TTS error body: {resp.text[:200]}", flush=True)
        except Exception as e:
            print(f"  TTS EXCEPTION: {e}", flush=True)

    return b"".join(audio_parts)


async def execute_action(action: dict,
                          session_id: str | None = None,
                          ws: "WebSocket | None" = None) -> str:
    t = action["type"]
    p = action["payload"]

    if t == "SEARCH":
        result = await browser_tools.search_and_read(p)
        if "error" not in result:
            return f"Seite: {result.get('title', '')}\nURL: {result.get('url', '')}\n\n{result.get('content', '')[:2000]}"
        return f"Suche fehlgeschlagen: {result.get('error', '')}"

    elif t == "BROWSE":
        result = await browser_tools.visit(p)
        if "error" not in result:
            return f"Seite: {result.get('title', '')}\n\n{result.get('content', '')[:2000]}"
        return f"Seite nicht erreichbar: {result.get('error', '')}"

    elif t == "OPEN":
        await browser_tools.open_url(p)
        return f"Geoeffnet: {p}"

    elif t == "SCREEN":
        # Ask the connected client (macOS app, PWA) for a screenshot.
        # The Mac Mini itself is usually headless, so a server-side
        # capture wouldn't help — we only fall back to it for text
        # clients (no screen capabilities at all) or if the client
        # silently disappears.
        if session_id and ws is not None:
            loop = asyncio.get_running_loop()
            future: asyncio.Future = loop.create_future()
            pending_screenshots[session_id] = future
            try:
                await ws.send_json({"type": "request_screenshot"})
                png_bytes = await asyncio.wait_for(future, timeout=15)
                print(f"[jarvis] Describing client screenshot ({len(png_bytes)} bytes)", flush=True)
                return await screen_capture.describe_bytes(ai, png_bytes)
            except asyncio.TimeoutError:
                print("[jarvis] Client didn't send screenshot within 15s", flush=True)
                return "Der Bildschirm-Screenshot hat zu lange gedauert, Sir. Ist die macOS-App offen und hat Screen-Recording-Rechte?"
            except RuntimeError as e:
                msg = str(e)
                if "permission" in msg.lower() or "rechte" in msg.lower():
                    return (
                        "Ich darf Ihren Bildschirm nicht ansehen, Sir. "
                        "Bitte aktivieren Sie Screen Recording fuer Jarvis in "
                        "Systemeinstellungen → Datenschutz & Sicherheit → Bildschirmaufnahme "
                        "und starten Sie die App neu."
                    )
                return f"Der Client konnte keinen Screenshot machen: {msg}"
            except Exception as e:
                print(f"[jarvis] Client screenshot error: {e}", flush=True)
                return f"Beim Screenshot ist etwas schiefgegangen: {e}"
            finally:
                pending_screenshots.pop(session_id, None)

        # No active WebSocket — try a local capture as a last resort.
        return await screen_capture.describe_screen(ai)

    elif t == "NEWS":
        result = await browser_tools.fetch_news()
        return result

    elif t == "HOME":
        # Optional payload = search query. Empty payload = full dashboard.
        # Defensive parsing: Claude Haiku sometimes emits literal placeholder
        # tokens like "<blank>" / "<empty>" / "-" / "none" when the prompt
        # says "ohne Suchbegriff". Treat all of these as an empty payload so
        # we return the full dashboard instead of a "Keine Sensoren" error.
        query = (p or "").strip().strip("<>").strip().lower()
        if query in ("", "blank", "empty", "none", "null", "-", "—", "leer"):
            query = ""
        if query:
            hits = await ha_client.search_entities(query)
            if not hits:
                return f"Keine Sensoren zu '{query}' gefunden."
            return "\n".join(
                f"{fn or eid}: {state}" for eid, fn, state in hits
            )
        dashboard = await ha_client.get_dashboard_status()
        return dashboard or "Home Assistant nicht erreichbar."

    elif t == "LIGHT":
        # Format: "service entity_id [key=val ...]"
        parts = p.split()
        if len(parts) < 2:
            return "Fehler: Bitte Service und Entity angeben (z.B. turn_on light.kuche)."
        service = parts[0]
        entity_id = parts[1]
        if service not in ("turn_on", "turn_off", "toggle"):
            return f"Fehler: Unbekannter Service '{service}'. Erlaubt: turn_on, turn_off, toggle."
        if not entity_id.startswith("light."):
            return f"Fehler: Nur Lichter steuerbar, '{entity_id}' ist kein light.*-Entity."
        kwargs = {}
        for part in parts[2:]:
            if "=" in part:
                k, v = part.split("=", 1)
                try:
                    kwargs[k] = int(v)
                except ValueError:
                    kwargs[k] = v
        result = await ha_client.call_service("light", service, entity_id, **kwargs)
        if isinstance(result, dict) and "error" in result:
            return f"Fehler beim Steuern: {result['error']}"
        friendly = entity_id.replace("light.", "").replace("_", " ").title()
        action_de = {"turn_on": "eingeschaltet", "turn_off": "ausgeschaltet", "toggle": "umgeschaltet"}
        return f"{friendly} wurde {action_de.get(service, service)}."

    elif t == "CLAUDE":
        # Delegate a coding task to Claude Code as a subprocess. Runs in
        # the workspace directory from config.json and returns a short
        # summary for TTS. Full output is written to logs/ for later
        # inspection.
        task_text = (p or "").strip()
        if not task_text:
            return "Was soll Claude denn machen, Sir?"

        workspace = config.get("workspace_path", "")
        if not workspace or not os.path.isdir(workspace):
            return "Workspace-Pfad ist nicht konfiguriert."

        # Write full output to a timestamped log file so nothing is lost.
        logs_dir = os.path.join(os.path.dirname(__file__), "logs", "claude")
        os.makedirs(logs_dir, exist_ok=True)
        log_path = os.path.join(
            logs_dir,
            f"claude-{time.strftime('%Y%m%d-%H%M%S')}.log"
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "-p", task_text,
                cwd=workspace,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=600)
            except asyncio.TimeoutError:
                proc.kill()
                return "Claude hat ueber zehn Minuten gebraucht — ich habe ihn gestoppt, Sir."

            output = stdout.decode(errors="replace") if stdout else ""
            with open(log_path, "w") as f:
                f.write(f"# Task: {task_text}\n\n{output}")

            if proc.returncode != 0:
                return f"Claude ist mit Fehler {proc.returncode} ausgestiegen. Details in {os.path.basename(log_path)}."

            # Last non-empty line is usually the summary
            lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
            tail = "\n".join(lines[-6:]) if lines else "Keine Ausgabe."
            # Keep it short enough for TTS
            if len(tail) > 800:
                tail = tail[-800:]
            return f"Claude ist fertig, Sir. Hier das Ergebnis:\n{tail}"
        except FileNotFoundError:
            return "Das Claude-CLI ist nicht installiert oder nicht im PATH."
        except Exception as e:
            return f"Claude konnte nicht ausgefuehrt werden: {e}"

    return ""


async def process_message(session_id: str, user_text: str, ws: WebSocket):
    """Process message and send responses via WebSocket."""
    global _last_full_greeting_ts

    if session_id not in conversations:
        conversations[session_id] = []

    # Throttle the full "Jarvis activate" greeting to max once every 2 hours.
    # Within the cooldown window, skip the data refresh and tell the LLM to
    # give a short acknowledgment instead of the full weather/tasks briefing.
    short_greeting = False
    if "activate" in user_text.lower():
        now = time.time()
        if now - _last_full_greeting_ts >= GREETING_COOLDOWN_SECS:
            # Full greeting: set timestamp FIRST (before await) to prevent race condition
            # where two concurrent activations both pass the cooldown check.
            _last_full_greeting_ts = now
            await refresh_data_async()
            print(f"[jarvis] Full greeting (cooldown reset)", flush=True)
        else:
            # Short greeting: skip refresh, use short prompt variant
            short_greeting = True
            remaining = int(GREETING_COOLDOWN_SECS - (now - _last_full_greeting_ts))
            print(f"[jarvis] Short greeting (full greeting cooldown: {remaining}s remaining)", flush=True)

    conversations[session_id].append({"role": "user", "content": user_text})
    history = conversations[session_id][-16:]

    # LLM call
    response = await ai.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=get_system_prompt(session_id, short_greeting=short_greeting),
        messages=history,
    )
    reply = response.content[0].text
    print(f"  LLM raw: {reply[:200]}", flush=True)
    spoken_text, action = extract_action(reply)

    # Speak the main response immediately
    if spoken_text:
        audio = await synthesize_speech(spoken_text)
        print(f"  Jarvis: {spoken_text[:80]}", flush=True)
        print(f"  Audio bytes: {len(audio)}", flush=True)
        conversations[session_id].append({"role": "assistant", "content": spoken_text})
        await ws.send_json({
            "type": "response",
            "text": spoken_text,
            "audio": base64.b64encode(audio).decode("utf-8") if audio else "",
        })

    # Execute action if any
    if action:
        print(f"  Action: {action['type']} -> {action['payload'][:100]}", flush=True)

        # Quick voice feedback for SCREEN so user knows Jarvis is working
        if action["type"] == "SCREEN":
            hint = "Lassen Sie mich einen Blick auf Ihren Bildschirm werfen."
            hint_audio = await synthesize_speech(hint)
            await ws.send_json({
                "type": "response",
                "text": hint,
                "audio": base64.b64encode(hint_audio).decode("utf-8") if hint_audio else "",
            })

        try:
            action_result = await execute_action(action, session_id=session_id, ws=ws)
            print(f"  Result: {action_result}", flush=True)
        except Exception as e:
            print(f"  Action error: {e}", flush=True)
            action_result = f"Fehler: {e}"

        if action["type"] == "OPEN":
            # Just opened browser, nothing to summarize
            return

        # SEARCH, BROWSE, SCREEN — summarize results
        if action_result and "fehlgeschlagen" not in action_result:
            summary_resp = await ai.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=250,
                system=f"Du bist Jarvis. Fasse die folgenden Informationen KURZ auf Deutsch zusammen, maximal 3 Saetze, im Jarvis-Stil. Sprich den Nutzer als {USER_ADDRESS} an. KEINE Tags in eckigen Klammern. KEINE ACTION-Tags.",
                messages=[{"role": "user", "content": f"Fasse zusammen:\n\n{action_result}"}],
            )
            summary = summary_resp.content[0].text
            summary, _ = extract_action(summary)
        else:
            summary = f"Das hat leider nicht funktioniert, {USER_ADDRESS}."

        audio2 = await synthesize_speech(summary)
        conversations[session_id].append({"role": "assistant", "content": summary})
        await ws.send_json({
            "type": "response",
            "text": summary,
            "audio": base64.b64encode(audio2).decode("utf-8") if audio2 else "",
        })


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    session_id = str(id(ws))
    print(f"[jarvis] Client connected", flush=True)

    try:
        while True:
            data = await ws.receive_json()

            # Mobile geolocation handshake. The iPhone frontend sends
            # this BEFORE the first "Jarvis activate" message so that
            # build_system_prompt already has the override ready when
            # the greeting is generated.
            # Screenshot response from the client — resolve the pending
            # future so [ACTION:SCREEN] can continue.
            if data.get("type") == "screenshot":
                b64 = data.get("data", "")
                future = pending_screenshots.get(session_id)
                if future is not None and not future.done():
                    try:
                        png_bytes = base64.b64decode(b64)
                        if len(png_bytes) < 100:
                            future.set_exception(
                                ValueError(f"Screenshot payload too small ({len(png_bytes)} bytes)")
                            )
                        else:
                            print(f"[jarvis] Got screenshot from client: {len(png_bytes)} bytes", flush=True)
                            future.set_result(png_bytes)
                    except Exception as e:
                        future.set_exception(e)
                continue

            # Screenshot error from the client (e.g. permission missing).
            if data.get("type") == "screenshot_error":
                err = data.get("error", "unknown error")
                print(f"[jarvis] Client screenshot_error: {err}", flush=True)
                future = pending_screenshots.get(session_id)
                if future is not None and not future.done():
                    future.set_exception(RuntimeError(err))
                continue

            if data.get("type") == "location":
                try:
                    lat = float(data.get("lat"))
                    lon = float(data.get("lon"))
                except (TypeError, ValueError):
                    print(f"[jarvis] Invalid location payload: {data}", flush=True)
                    continue
                # wttr.in lookup is a blocking urllib call — push it to
                # a thread so we don't stall the event loop if the API
                # is slow.
                weather = await asyncio.to_thread(get_weather_for_coords_sync, lat, lon)
                if weather:
                    session_context[session_id] = {
                        "weather": weather,
                        "city": weather.get("city"),
                    }
                    print(
                        f"[jarvis] Location override: {weather.get('city')} "
                        f"({lat:.4f},{lon:.4f}) -> {weather['temp']}°C "
                        f"{weather['description']}",
                        flush=True,
                    )
                else:
                    print(f"[jarvis] Location {lat},{lon} — weather lookup failed", flush=True)
                continue

            user_text = data.get("text", "").strip()
            if not user_text:
                continue

            print(f"  You:    {user_text}", flush=True)
            await process_message(session_id, user_text, ws)

    except WebSocketDisconnect:
        conversations.pop(session_id, None)
        session_context.pop(session_id, None)
        # Cancel any pending screenshot request so [ACTION:SCREEN]
        # falls back immediately instead of waiting for the timeout.
        pending = pending_screenshots.pop(session_id, None)
        if pending is not None and not pending.done():
            pending.cancel()


# Static files — wrapped with a no-cache middleware so iOS Safari /
# Tailscale serve don't keep an old build of main.js / style.css on
# mobile after we ship a fix. The UI ships as a couple of tiny files,
# so the revalidation cost is negligible compared to the debugging
# cost of chasing phantom cache bugs on remote devices.
class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


# ── Push Notification device token storage ──────────────────────
# The iOS app posts its APNs device token here on startup. We store
# all registered tokens in a JSON file so they survive server restarts.
# The actual push-sending code will use these tokens with the APNs
# key configured in config.json.

PUSH_TOKENS_FILE = os.path.join(os.path.dirname(__file__), "push_tokens.json")

def _load_push_tokens() -> list[dict]:
    try:
        with open(PUSH_TOKENS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def _save_push_tokens(tokens: list[dict]):
    with open(PUSH_TOKENS_FILE, "w") as f:
        json.dump(tokens, f, indent=2)


from fastapi import Request

@app.post("/api/push/register")
async def register_push_token(request: Request):
    """Register an iOS device token for APNs push notifications."""
    body = await request.json()
    token = body.get("device_token", "").strip()
    device_name = body.get("device_name", "unknown")
    platform = body.get("platform", "ios")

    if not token:
        return {"error": "missing device_token"}, 400

    tokens = _load_push_tokens()
    # Upsert: replace existing entry for same token
    tokens = [t for t in tokens if t.get("device_token") != token]
    tokens.append({
        "device_token": token,
        "device_name": device_name,
        "platform": platform,
        "registered_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    _save_push_tokens(tokens)
    print(f"[jarvis] Push token registered: {device_name} ({token[:12]}...)", flush=True)
    return {"status": "ok", "registered_devices": len(tokens)}


app.mount("/static", NoCacheStaticFiles(directory=os.path.join(os.path.dirname(__file__), "frontend")), name="static")


@app.get("/")
async def serve_index():
    return FileResponse(
        os.path.join(os.path.dirname(__file__), "frontend", "index.html"),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


# ---------------------------------------------------------------------------
# Window Monitor — background task that checks for open windows/doors when
# nobody is home and sends an iPhone push notification via HA.
# ---------------------------------------------------------------------------

_window_monitor_last_notified: float = 0.0
_window_monitor_was_home: bool = True
WINDOW_MONITOR_INTERVAL = 60       # seconds between checks
WINDOW_MONITOR_COOLDOWN = 900      # 15 minutes between notifications


async def window_monitor():
    """Background coroutine: poll HA for presence + window sensors."""
    global _window_monitor_last_notified, _window_monitor_was_home

    if not (WINDOW_MONITOR_SENSORS and WINDOW_MONITOR_PERSONS and WINDOW_MONITOR_NOTIFY):
        print("[jarvis] Window monitor: disabled (config incomplete)", flush=True)
        return

    print(
        f"[jarvis] Window monitor: active, {len(WINDOW_MONITOR_SENSORS)} sensors, "
        f"checking every {WINDOW_MONITOR_INTERVAL}s",
        flush=True,
    )
    await asyncio.sleep(10)  # Let the server finish startup

    while True:
        try:
            anyone_home = await ha_client.is_anyone_home(WINDOW_MONITOR_PERSONS)

            if anyone_home:
                _window_monitor_was_home = True
                await asyncio.sleep(WINDOW_MONITOR_INTERVAL)
                continue

            # Nobody home — check if this is the transition moment or
            # if we already notified recently.
            now = time.time()
            if now - _window_monitor_last_notified < WINDOW_MONITOR_COOLDOWN:
                await asyncio.sleep(WINDOW_MONITOR_INTERVAL)
                continue

            open_windows = await ha_client.get_open_windows(WINDOW_MONITOR_SENSORS)

            if open_windows and _window_monitor_was_home:
                # Transition: was home → now nobody home, windows open
                names = [fn for _, fn in open_windows]
                msg = (
                    f"Niemand zu Hause, aber noch offen: {', '.join(names)}. "
                    f"Bitte prüfen, {USER_ADDRESS}."
                )
                result = await ha_client.send_notification(
                    WINDOW_MONITOR_NOTIFY, msg
                )
                if isinstance(result, dict) and "error" in result:
                    print(f"[jarvis] Window monitor notify error: {result}", flush=True)
                else:
                    print(f"[jarvis] Window monitor: notified — {', '.join(names)}", flush=True)
                    _window_monitor_last_notified = now

            _window_monitor_was_home = False

        except Exception as e:
            print(f"[jarvis] Window monitor error: {e}", flush=True)

        await asyncio.sleep(WINDOW_MONITOR_INTERVAL)


@app.on_event("startup")
async def start_window_monitor():
    asyncio.create_task(window_monitor())


if __name__ == "__main__":
    import uvicorn
    print("=" * 50, flush=True)
    print("  J.A.R.V.I.S. V2 Server", flush=True)
    print(f"  http://localhost:8340", flush=True)
    print("=" * 50, flush=True)
    uvicorn.run(app, host="0.0.0.0", port=8340)
