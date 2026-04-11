"""
Home Assistant client for Jarvis.

Talks to a Home Assistant instance (typically via Nabu Casa Cloud) using
a Long-Lived Access Token. Exposes these async helpers:

- get_dashboard_status()  -> compact dict/string snapshot of all curated
                             entities, used both at startup (system prompt)
                             and on demand via [ACTION:HOME].
- get_entity(entity_id)   -> raw state dict for a single entity.
- search_entities(query)  -> keyword filter over the curated entity list,
                             returns a list of (entity_id, friendly_name,
                             state) tuples.
- list_lights()           -> all light.* entities discovered via /api/states
                             (used for the LIGHT action + system prompt).
- control_light(...)      -> turn a light on/off/toggle, set brightness,
                             set color / color temperature.
- call_service(...)       -> low-level HA service call (used by control_light
                             and usable for future write integrations).

The token is read from the HOMEASSISTANT_TOKEN environment variable. The
base URL and the curated entity list live in config.json. If either is
missing, the helpers degrade gracefully: get_dashboard_status() returns
"" so the system prompt simply omits the block, and get_entity() returns
an {"error": ...} dict.

Read-path (dashboard, search) covers the curated entity list. Write-path
(control_light, call_service) targets the light.* domain for Philips Hue
integration — Jarvis can now actually turn lights on/off, dim them, and
change colours.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

# Per-event-loop httpx client. httpx.AsyncClient is not safe to share
# across event loops (the connection pool is bound to the loop that
# created it), and Jarvis creates multiple loops over its lifetime:
#   1. The synchronous startup refresh uses asyncio.run() which creates
#      a short-lived loop that gets closed immediately.
#   2. uvicorn then starts its own long-lived main loop for serving.
# Sharing a single module-level AsyncClient between those causes some
# parallel requests to fail silently (we observed 29 curated entities
# shrinking to ~8 after the first "Jarvis activate" refresh). Fix:
# keep one AsyncClient per loop and create it lazily on first use.
_clients: dict[int, httpx.AsyncClient] = {}


# Named colours Jarvis understands when the user says "mach das Wohnzimmer
# blau" etc. Maps to RGB triplets for HA's light.turn_on service. German
# and English aliases both resolve to the same tuple so Claude Haiku can
# emit either form without us having to canonicalise first.
LIGHT_COLOR_MAP: dict[str, tuple[int, int, int]] = {
    "rot": (255, 0, 0),
    "red": (255, 0, 0),
    "gruen": (0, 255, 0),
    "grün": (0, 255, 0),
    "green": (0, 255, 0),
    "blau": (0, 0, 255),
    "blue": (0, 0, 255),
    "gelb": (255, 220, 0),
    "yellow": (255, 220, 0),
    "orange": (255, 140, 0),
    "pink": (255, 20, 147),
    "magenta": (255, 0, 255),
    "lila": (148, 0, 211),
    "purple": (148, 0, 211),
    "violett": (138, 43, 226),
    "violet": (138, 43, 226),
    "tuerkis": (0, 200, 200),
    "türkis": (0, 200, 200),
    "turquoise": (0, 200, 200),
    "cyan": (0, 255, 255),
    "weiss": (255, 255, 255),
    "weiß": (255, 255, 255),
    "white": (255, 255, 255),
}

# Colour-temperature keywords. Values are Kelvin — warm ≈ candle-ish,
# neutral ≈ paper-white, cool ≈ daylight. Hue bulbs clamp to their
# supported range automatically.
LIGHT_COLOR_TEMP_MAP: dict[str, int] = {
    "warm": 2200,
    "warmweiss": 2200,
    "warmweiß": 2200,
    "warmwhite": 2200,
    "neutral": 3500,
    "kalt": 6500,
    "kaltweiss": 6500,
    "kaltweiß": 6500,
    "cool": 6500,
    "daylight": 6500,
    "tageslicht": 6500,
}


def _client() -> httpx.AsyncClient:
    """Return an httpx.AsyncClient bound to the current running loop."""
    loop = asyncio.get_running_loop()
    key = id(loop)
    client = _clients.get(key)
    if client is None or client.is_closed:
        # Home Assistant via Nabu Casa Cloud can be slow on cold
        # connections, so give it a generous timeout.
        client = httpx.AsyncClient(timeout=15)
        _clients[key] = client
    return client


class HomeAssistantClient:
    """Thin async client for the HA REST API."""

    def __init__(self, base_url: str, token: str, entities: list[str]):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.entities = entities
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.token and self.entities)

    async def _get(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        resp = await _client().get(url, headers=self._headers)
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, body: dict) -> Any:
        url = f"{self.base_url}{path}"
        resp = await _client().post(url, headers=self._headers, json=body)
        resp.raise_for_status()
        # HA returns a list of changed state dicts for service calls, or
        # {} on no-op. We do not use it programmatically, just pass it
        # through for callers that want to inspect it.
        try:
            return resp.json()
        except Exception:
            return {}

    async def get_entity(self, entity_id: str) -> dict:
        """Return raw HA state dict for a single entity, or {'error': ...}."""
        if not self.configured:
            return {"error": "Home Assistant nicht konfiguriert"}
        try:
            return await self._get(f"/api/states/{entity_id}")
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP {e.response.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    async def get_all_states(self) -> list[dict]:
        """Return every state in HA — only used internally / for debugging."""
        if not self.configured:
            return []
        try:
            return await self._get("/api/states")
        except Exception:
            return []

    async def get_curated_states(self) -> list[dict]:
        """Fetch only the curated entities in parallel."""
        if not self.configured:
            return []
        import asyncio
        results = await asyncio.gather(
            *(self.get_entity(eid) for eid in self.entities),
            return_exceptions=True,
        )
        out: list[dict] = []
        for r in results:
            if isinstance(r, dict) and "error" not in r:
                out.append(r)
        return out

    async def get_dashboard_status(self) -> str:
        """Return a compact German summary of all curated entities.

        Designed to be embedded into the Jarvis system prompt and to be
        returned verbatim from [ACTION:HOME]. Groups entities by category
        for readability, keeps everything on few lines, drops any entity
        that is unavailable/unknown.
        """
        states = await self.get_curated_states()
        if not states:
            return ""

        by_id = {s["entity_id"]: s for s in states}

        def val(eid: str, unit: str = "") -> str | None:
            s = by_id.get(eid)
            if not s:
                return None
            state = s.get("state", "")
            if state in ("unknown", "unavailable", "none", "None", ""):
                return None
            return f"{state}{unit}"

        lines: list[str] = []

        # Energie (PV + Netz)
        energy_parts = []
        if v := val("sensor.solar_bilanz", " kW"):
            energy_parts.append(f"PV-Bilanz {v}")
        if v := val("sensor.s10e_pro_solar_production", " kW"):
            energy_parts.append(f"PV {v}")
        if v := val("sensor.s10e_pro_house_consumption", " kW"):
            energy_parts.append(f"Haus {v}")
        if v := val("sensor.s10e_pro_consumption_from_grid", " kW"):
            energy_parts.append(f"Netzbezug {v}")
        if v := val("sensor.s10e_pro_export_to_grid", " kW"):
            energy_parts.append(f"Einspeisung {v}")
        if v := val("sensor.solar_prognose_heute_gesamt", " kWh"):
            energy_parts.append(f"Prognose heute {v}")
        if energy_parts:
            lines.append("Energie: " + ", ".join(energy_parts))

        # Hausbatterie (E3DC S10E Pro)
        # Auf einer eigenen Zeile, damit Jarvis sie bei Batterie-Fragen
        # sofort sieht — und nicht behauptet, es gäbe keine Batterie.
        battery_parts = []
        soc_raw = by_id.get("sensor.s10e_pro_state_of_charge", {}).get("state")
        if soc_raw not in (None, "", "unknown", "unavailable"):
            battery_parts.append(f"SoC {soc_raw}%")
        # Nur eine Richtung zeigen: entweder lädt oder entlädt, nicht
        # beides gleichzeitig. Wenn einer > 0 kW, hat er Vorrang.
        charge_raw = by_id.get("sensor.s10e_pro_battery_charge", {}).get("state")
        discharge_raw = by_id.get("sensor.s10e_pro_battery_discharge", {}).get("state")
        try:
            charge_kw = float(charge_raw) if charge_raw not in (None, "", "unknown", "unavailable") else 0.0
        except (TypeError, ValueError):
            charge_kw = 0.0
        try:
            discharge_kw = float(discharge_raw) if discharge_raw not in (None, "", "unknown", "unavailable") else 0.0
        except (TypeError, ValueError):
            discharge_kw = 0.0
        if charge_kw > 0.05:
            battery_parts.append(f"lädt mit {charge_kw:.2f} kW")
        elif discharge_kw > 0.05:
            battery_parts.append(f"entlädt mit {discharge_kw:.2f} kW")
        else:
            battery_parts.append("idle")
        if v := val("sensor.s10e_pro_battery_charge_today", " kWh"):
            battery_parts.append(f"heute geladen {v}")
        if v := val("sensor.s10e_pro_battery_discharge_today", " kWh"):
            battery_parts.append(f"heute entladen {v}")
        autarky_raw = by_id.get("sensor.s10e_pro_autarky_today", {}).get("state")
        if autarky_raw not in (None, "", "unknown", "unavailable"):
            try:
                battery_parts.append(f"Autarkie heute {float(autarky_raw):.1f}%")
            except (TypeError, ValueError):
                battery_parts.append(f"Autarkie heute {autarky_raw}%")
        if v := val("sensor.s10e_pro_installed_battery_capacity", " kWh"):
            battery_parts.append(f"Kapazität {v}")
        if battery_parts:
            lines.append("Hausakku E3DC S10E Pro: " + ", ".join(battery_parts))

        # Wallbox
        wb_parts = []
        if v := val("sensor.myenergi_zappi_links_status"):
            wb_parts.append(f"Status {v}")
        if v := val("sensor.myenergi_zappi_links_energy_used_today", " kWh"):
            wb_parts.append(f"heute geladen {v}")
        if wb_parts:
            lines.append("Wallbox links: " + ", ".join(wb_parts))

        # Klima
        climate_parts = []
        if v := val("sensor.arbeitszimmer_oben_aussen_temperatur", "°C"):
            climate_parts.append(f"Außen {v}")
        if v := val("sensor.arbeitszimmer_oben_aussen_luftfeuchtigkeit", "%"):
            climate_parts.append(f"Luftfeuchte {v}")
        if v := val("sensor.arbeitszimmer_oben_innen_wohnzimmer_kohlendioxid", " ppm"):
            climate_parts.append(f"CO₂ Wohnzimmer {v}")
        if v := val("sensor.homematic_ip_wettersensor_pro_windspeed", " km/h"):
            climate_parts.append(f"Wind {v}")
        raining = by_id.get("binary_sensor.homematic_ip_wettersensor_pro_raining", {}).get("state")
        if raining == "on":
            climate_parts.append("regnet gerade")
        if v := val("sensor.homematic_ip_wettersensor_pro_today_rain", " mm"):
            climate_parts.append(f"Regen heute {v}")
        if climate_parts:
            lines.append("Klima: " + ", ".join(climate_parts))

        # Pool
        pool_parts = []
        if v := val("sensor.pool_wassertemperatur", "°C"):
            pool_parts.append(f"Wasser {v}")
        if v := val("sensor.pool_ph_wert"):
            pool_parts.append(f"pH {v}")
        if v := val("sensor.pool_chlor_frei", " mg/l"):
            pool_parts.append(f"Chlor {v}")
        if v := val("input_select.pool_filteranlage_status"):
            pool_parts.append(f"Filter {v}")
        if pool_parts:
            lines.append("Pool: " + ", ".join(pool_parts))

        # Fahrzeuge
        volvo_parts = []
        if v := val("sensor.volvo_akku_ladestand", "%"):
            volvo_parts.append(f"Akku {v}")
        if v := val("sensor.volvo_akku_reichweite", " km"):
            volvo_parts.append(f"E-Reichweite {v}")
        if v := val("sensor.volvo_tankfuellstand", "%"):
            volvo_parts.append(f"Tank {v}")
        if v := val("sensor.volvo_kilometerstand", " km"):
            volvo_parts.append(f"km {v}")
        if volvo_parts:
            lines.append("Volvo XC90: " + ", ".join(volvo_parts))

        bmw_parts = []
        if v := val("sensor.ix1_xdrive30_battery_ev_charging_power", " W"):
            bmw_parts.append(f"Ladeleistung {v}")
        if v := val("sensor.ix1_xdrive30_charging_ev_time_to_full_charge", " min"):
            bmw_parts.append(f"voll in {v}")
        if bmw_parts:
            lines.append("BMW iX1: " + ", ".join(bmw_parts))

        # Sicherheit & Anwesenheit
        sec_parts = []
        if v := val("alarm_control_panel.pustans_status"):
            sec_parts.append(f"Alarm Haus {v}")
        if v := val("alarm_control_panel.blink_zuhause"):
            sec_parts.append(f"Blink {v}")
        if v := val("person.maure"):
            sec_parts.append(f"Mario {v}")
        if v := val("person.britta"):
            sec_parts.append(f"Britta {v}")
        if sec_parts:
            lines.append("Sicherheit: " + ", ".join(sec_parts))

        # Garten
        if v := val("sensor.pustans_garten_tagliche_aktive_bewasserungszeit", " min"):
            lines.append(f"Garten: Bewässerung heute {v}")

        # Gesundheit (Apple Watch via HA Companion App HealthKit-Bridge)
        #
        # TODO (geplant, blockiert durch HealthKit-Permission-Flow):
        # Die iOS HA Companion App liefert Apple Watch Health-Daten als
        # Sensoren, sobald der HealthKit-Zugriff einmalig gewährt wurde.
        # Aktuell hängt der Permission-Dialog — siehe Session-Handoff.
        #
        # Sobald das läuft:
        #   1. In HA prüfen welche sensor.*-IDs neu erscheinen
        #      (Developer Tools → States, filter: "iphone" oder "mario")
        #   2. Interessante IDs in config.json unter home_assistant_entities
        #      eintragen (Herzfrequenz, Ruhepuls, HRV, Schlaf, VO2Max,
        #      Blutsauerstoff, Aktive Kalorien, Schritte, Stehstunden,
        #      Trainingsminuten)
        #   3. Diese Sektion hier mit val()-Lookups füllen, analog zu
        #      Klima/Pool/Fahrzeuge oben. Beispiel-Skelett:
        #
        #   health_parts = []
        #   if v := val("sensor.<device>_heart_rate", " bpm"):
        #       health_parts.append(f"Puls {v}")
        #   if v := val("sensor.<device>_resting_heart_rate", " bpm"):
        #       health_parts.append(f"Ruhepuls {v}")
        #   if v := val("sensor.<device>_heart_rate_variability", " ms"):
        #       health_parts.append(f"HRV {v}")
        #   if v := val("sensor.<device>_sleep_analysis"):
        #       health_parts.append(f"Schlaf {v}")
        #   if v := val("sensor.<device>_vo2_max", " ml/kg/min"):
        #       health_parts.append(f"VO₂max {v}")
        #   if v := val("sensor.<device>_active_energy", " kcal"):
        #       health_parts.append(f"Aktive kcal {v}")
        #   if health_parts:
        #       lines.append("Gesundheit: " + ", ".join(health_parts))

        return "\n".join(lines)

    async def search_entities(self, query: str) -> list[tuple[str, str, str]]:
        """Keyword search across curated entities.

        Returns list of (entity_id, friendly_name, state) for anything
        whose entity_id or friendly_name contains the query (case-insensitive).
        """
        q = query.lower().strip()
        if not q:
            return []
        states = await self.get_curated_states()
        hits: list[tuple[str, str, str]] = []
        for s in states:
            eid = s.get("entity_id", "")
            fn = s.get("attributes", {}).get("friendly_name", "") or ""
            if q in eid.lower() or q in fn.lower():
                hits.append((eid, fn, s.get("state", "")))
        return hits

    async def get_home_weather(self) -> dict | None:
        """Return a wttr-compatible weather dict built from local HA sensors.

        Uses the curated Homematic / outdoor sensors that already feed
        the Klima section of the dashboard. Only returns a dict if we at
        least have an outdoor temperature — without that there is nothing
        meaningful to say. The 'description' field is synthesised from
        the rain binary + wind speed so the system prompt still gets a
        natural-language snippet ("regnet gerade, windig") instead of a
        bare number.
        """
        if not self.configured:
            return None
        states = await self.get_curated_states()
        by_id = {s["entity_id"]: s for s in states}

        def raw(eid: str) -> str | None:
            s = by_id.get(eid)
            if not s:
                return None
            v = s.get("state", "")
            if v in ("unknown", "unavailable", "none", "None", ""):
                return None
            return v

        temp = raw("sensor.arbeitszimmer_oben_aussen_temperatur")
        if temp is None:
            return None

        humidity = raw("sensor.arbeitszimmer_oben_aussen_luftfeuchtigkeit")
        wind = raw("sensor.homematic_ip_wettersensor_pro_windspeed")
        rain_today = raw("sensor.homematic_ip_wettersensor_pro_today_rain")
        raining_now = raw("binary_sensor.homematic_ip_wettersensor_pro_raining")

        parts: list[str] = []
        if raining_now == "on":
            parts.append("regnet gerade")
        else:
            had_rain_today = False
            if rain_today:
                try:
                    had_rain_today = float(rain_today) > 0.1
                except (TypeError, ValueError):
                    had_rain_today = False
            parts.append("trocken mit Regen heute früher" if had_rain_today else "trocken")

        if wind:
            try:
                wind_val = float(wind)
                if wind_val >= 40:
                    parts.append("stürmisch")
                elif wind_val >= 20:
                    parts.append("windig")
                elif wind_val >= 10:
                    parts.append("leichter Wind")
            except (TypeError, ValueError):
                pass

        description = ", ".join(parts)

        return {
            "temp": temp,
            # HA does not give us a proper "feels like" — null it out and
            # let the prompt builder skip the 'gefuehlt ...' phrase.
            "feels_like": None,
            "description": description,
            "humidity": humidity or "",
            "wind_kmh": wind or "",
            "rain_today_mm": rain_today or "",
            "source": "ha",
        }

    # ------------------------------------------------------------------
    # Write-path: service calls + Philips Hue lighting control
    # ------------------------------------------------------------------

    async def call_service(
        self, domain: str, service: str, data: dict | None = None
    ) -> dict:
        """Call an HA service. Returns {'ok': True} or {'error': ...}.

        Low-level — used by control_light and available for any future
        write integrations (covers, switches, media_player, ...).
        """
        if not self.configured:
            return {"error": "Home Assistant nicht konfiguriert"}
        try:
            result = await self._post(
                f"/api/services/{domain}/{service}", data or {}
            )
            return {"ok": True, "result": result}
        except httpx.HTTPStatusError as e:
            return {
                "error": f"HTTP {e.response.status_code}: "
                f"{e.response.text[:200]}"
            }
        except Exception as e:
            return {"error": str(e)}

    async def list_lights(self) -> list[dict]:
        """Return every light.* entity HA knows about, as flat dicts.

        Uses /api/states rather than the curated list, because Philips
        Hue exposes a lot of individual bulbs + rooms, and users almost
        never want to hand-curate each one. Missing / unavailable lights
        are skipped.
        """
        if not self.configured:
            return []
        all_states = await self.get_all_states()
        out: list[dict] = []
        for s in all_states:
            eid = s.get("entity_id", "")
            if not eid.startswith("light."):
                continue
            state = s.get("state", "")
            if state in ("unavailable", "unknown"):
                continue
            attrs = s.get("attributes", {}) or {}
            out.append(
                {
                    "entity_id": eid,
                    "friendly_name": attrs.get("friendly_name") or eid,
                    "state": state,
                    "brightness": attrs.get("brightness"),  # 0-255 or None
                    "supported_color_modes": attrs.get(
                        "supported_color_modes", []
                    ),
                }
            )
        out.sort(key=lambda x: x["friendly_name"].lower())
        return out

    async def control_light(
        self,
        entity_id: str,
        state: str = "on",
        brightness_pct: int | None = None,
        rgb_color: tuple[int, int, int] | list[int] | None = None,
        color_temp_kelvin: int | None = None,
    ) -> dict:
        """Turn a light on/off/toggle with optional brightness and colour.

        Arguments:
            entity_id: e.g. "light.wohnzimmer" or the literal string "all"
                       to target every light in the house.
            state:     "on", "off", or "toggle".
            brightness_pct: 0-100, clamped.
            rgb_color: (r, g, b), each 0-255.
            color_temp_kelvin: e.g. 2200 (warm) .. 6500 (cool).
        """
        state = (state or "on").lower()

        # "all" expands to every light we can see — HA does accept
        # entity_id="all" for service calls targeting a single domain,
        # but passing an explicit list is more predictable and works
        # even on older HA core versions.
        if entity_id == "all":
            lights = await self.list_lights()
            if not lights:
                return {"error": "Keine Lampen gefunden."}
            target_entity: str | list[str] = [l["entity_id"] for l in lights]
        else:
            target_entity = entity_id

        data: dict[str, Any] = {"entity_id": target_entity}

        if state == "off":
            return await self.call_service("light", "turn_off", data)

        service = "toggle" if state == "toggle" else "turn_on"

        if brightness_pct is not None:
            data["brightness_pct"] = max(0, min(100, int(brightness_pct)))
        if rgb_color is not None:
            data["rgb_color"] = [
                max(0, min(255, int(c))) for c in list(rgb_color)[:3]
            ]
        if color_temp_kelvin is not None:
            data["color_temp_kelvin"] = int(color_temp_kelvin)

        return await self.call_service("light", service, data)


def parse_light_payload(payload: str) -> dict:
    """Parse the payload of an [ACTION:LIGHT] tag.

    The grammar is intentionally tolerant so Claude Haiku can produce it
    without a strict schema. Example payloads:

        light.wohnzimmer on
        light.wohnzimmer on 80
        light.wohnzimmer 80
        light.wohnzimmer off
        light.wohnzimmer on rot
        light.wohnzimmer on warm 50
        all off

    Returns a dict with keys: entity_id, state, brightness_pct, rgb_color,
    color_temp_kelvin, error. Any field may be None.
    """
    tokens = (payload or "").strip().split()
    result: dict[str, Any] = {
        "entity_id": None,
        "state": None,
        "brightness_pct": None,
        "rgb_color": None,
        "color_temp_kelvin": None,
        "error": None,
    }
    if not tokens:
        result["error"] = "Leere Licht-Anweisung."
        return result

    first = tokens[0].lower().strip(",:")
    if first in ("all", "alle", "alles"):
        result["entity_id"] = "all"
    elif first.startswith("light."):
        result["entity_id"] = first
    else:
        result["error"] = f"Unbekannte Lampen-ID: {tokens[0]}"
        return result

    on_words = {"on", "an", "ein", "anschalten", "einschalten"}
    off_words = {"off", "aus", "ausschalten", "abschalten"}
    toggle_words = {"toggle", "umschalten", "wechseln"}

    for tok in tokens[1:]:
        tl = tok.lower().strip(",:%")
        if not tl:
            continue
        if tl in on_words:
            result["state"] = "on"
            continue
        if tl in off_words:
            result["state"] = "off"
            continue
        if tl in toggle_words:
            result["state"] = "toggle"
            continue
        # Brightness as a bare integer (0-100).
        if tl.isdigit():
            n = int(tl)
            if 0 <= n <= 100:
                result["brightness_pct"] = n
                continue
        # Named colour.
        if tl in LIGHT_COLOR_MAP:
            result["rgb_color"] = LIGHT_COLOR_MAP[tl]
            continue
        # Colour temperature keyword.
        if tl in LIGHT_COLOR_TEMP_MAP:
            result["color_temp_kelvin"] = LIGHT_COLOR_TEMP_MAP[tl]
            continue
        # Unknown token — ignore silently so a stray word doesn't break
        # the whole command.

    # If the user only passed a brightness / colour, assume they meant
    # "turn on with this setting". If they passed nothing at all, default
    # to "on".
    if result["state"] is None:
        result["state"] = "on"

    return result


def format_lights_for_prompt(lights: list[dict]) -> str:
    """Render a list of lights as a compact multi-line string for the
    system prompt. Each line shows entity_id, friendly name, and current
    state so Jarvis can match spoken-room references to entity_ids.
    """
    if not lights:
        return ""
    parts: list[str] = []
    for l in lights:
        eid = l["entity_id"]
        name = l["friendly_name"]
        state = l.get("state", "")
        if state == "on":
            bri = l.get("brightness")
            if bri is not None:
                try:
                    pct = int(round(int(bri) / 255 * 100))
                    state_str = f"an {pct}%"
                except (TypeError, ValueError):
                    state_str = "an"
            else:
                state_str = "an"
        elif state == "off":
            state_str = "aus"
        else:
            state_str = state or "?"
        parts.append(f"- {eid} ({name}) — {state_str}")
    return "\n".join(parts)


def build_client_from_config(config: dict) -> HomeAssistantClient:
    """Factory: read URL from config, token from env."""
    return HomeAssistantClient(
        base_url=config.get("home_assistant_url", ""),
        token=os.getenv("HOMEASSISTANT_TOKEN", ""),
        entities=config.get("home_assistant_entities", []),
    )
