"""
Jarvis V2 — Voice AI Server
FastAPI backend: receives speech text, thinks with Claude Haiku,
speaks with ElevenLabs, controls browser with Playwright.
"""

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


def get_weather_sync():
    """Fetch raw weather data at startup."""
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

def build_system_prompt():
    weather_block = ""
    if WEATHER_INFO:
        w = WEATHER_INFO
        weather_block = f"\nWetter {CITY}: {w['temp']}°C, gefuehlt {w['feels_like']}°C, {w['description']}"

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

    return f"""Du bist Jarvis, der KI-Assistent von Tony Stark aus Iron Man. Dein Dienstherr ist {USER_NAME}. Du sprichst ausschliesslich Deutsch. {USER_NAME} moechte mit "{USER_ADDRESS}" angesprochen und gesiezt werden. Nutze "Sie" als Pronomen — FALSCH: "{USER_ADDRESS} planen", RICHTIG: "Sie planen, {USER_ADDRESS}". Dein Ton ist trocken, sarkastisch und britisch-hoeflich - wie ein Butler der alles gesehen hat und trotzdem loyal bleibt. Du machst subtile, trockene Bemerkungen, bist aber niemals respektlos. Wenn {USER_ADDRESS} eine offensichtliche Frage stellt, darfst du mit elegantem Sarkasmus antworten. Du bist hochintelligent, effizient und immer einen Schritt voraus. Halte deine Antworten kurz - maximal 3 Saetze. Du kommentierst fragwuerdige Entscheidungen hoeflich aber spitz.

Du kennst {USER_NAME} gut — nutze das PROFIL unten, um Fragen konkret zu beantworten. Wenn {USER_NAME} nach etwas fragt, das im Profil steht (Familie, Firmen, Haus, Fahrzeuge, Smart Home, Projekte), beziehe dich darauf, als waere es selbstverstaendlich — du bist schliesslich sein Butler. Erfinde NICHTS, was nicht im Profil steht.

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

WENN {USER_NAME} "Jarvis activate" sagt:
- Begruesse ihn passend zur Tageszeit (aktuelle Zeit: {{time}}).
- Gebe eine kurze Info ueber das Wetter — Temperatur und ob Sonne/klar/bewoelkt/Regen, und wie es sich anfuehlt. Keine Luftfeuchtigkeit.
- Fasse die Aufgaben kurz als Ueberblick in einem Satz zusammen, ohne dabei jede einzelne Aufgabe einfach vorzulesen. Gebe gerne einen humorvollen Kommentar am Ende an.
- Sei kreativ bei der Begruessung.

AKTUELLES DATUM UND UHRZEIT (NICHT RATEN!):
Heute ist {{date_long}}. Die aktuelle Uhrzeit ist {{time}} Uhr.
Wenn {USER_ADDRESS} nach Wochentag, Datum, Monat, Jahr oder Uhrzeit fragt, nutze AUSSCHLIESSLICH diese Werte. Verlasse dich niemals auf dein internes Wissen oder Trainings-Daten fuer Zeitangaben — die sind veraltet.

=== AKTUELLE DATEN ==={weather_block}{task_block}
==={profile_block}{home_block}"""


def get_system_prompt():
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
        build_system_prompt()
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


async def execute_action(action: dict) -> str:
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

    return ""


async def process_message(session_id: str, user_text: str, ws: WebSocket):
    """Process message and send responses via WebSocket."""
    if session_id not in conversations:
        conversations[session_id] = []

    # Refresh weather + tasks on activate. Use the async variant because
    # we're inside a running event loop — asyncio.run() would raise here.
    if "activate" in user_text.lower():
        await refresh_data_async()

    conversations[session_id].append({"role": "user", "content": user_text})
    history = conversations[session_id][-16:]

    # LLM call
    response = await ai.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=get_system_prompt(),
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
            action_result = await execute_action(action)
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
            user_text = data.get("text", "").strip()
            if not user_text:
                continue

            print(f"  You:    {user_text}", flush=True)
            await process_message(session_id, user_text, ws)

    except WebSocketDisconnect:
        conversations.pop(session_id, None)


app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "frontend")), name="static")


@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "frontend", "index.html"))


if __name__ == "__main__":
    import uvicorn
    print("=" * 50, flush=True)
    print("  J.A.R.V.I.S. V2 Server", flush=True)
    print(f"  http://localhost:8340", flush=True)
    print("=" * 50, flush=True)
    uvicorn.run(app, host="0.0.0.0", port=8340)
