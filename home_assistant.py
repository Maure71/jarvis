"""
Home Assistant client for Jarvis (Level C — read + light control).

Talks to a Home Assistant instance (typically via Nabu Casa Cloud) using
a Long-Lived Access Token. Exposes async helpers:

- get_dashboard_status()  -> compact dict/string snapshot of all curated
                             entities, used both at startup (system prompt)
                             and on demand via [ACTION:HOME].
- get_entity(entity_id)   -> raw state dict for a single entity.
- search_entities(query)  -> keyword filter over the curated entity list,
                             returns a list of (entity_id, friendly_name,
                             state) tuples.
- call_service(domain, service, entity_id, **kwargs)
                          -> call an HA service (e.g. light/turn_on).
                             Only the 'light' domain is used by Jarvis.

The token is read from the HOMEASSISTANT_TOKEN environment variable. The
base URL and the curated entity list live in config.json. If either is
missing, the helpers degrade gracefully: get_dashboard_status() returns
"" so the system prompt simply omits the block, and get_entity() returns
an {"error": ...} dict.

LEVEL C: read access to curated entities + write access to light.* only.
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


    # Entities that are always fetched, regardless of config.json.
    # This avoids requiring a manual config update when new sensors are added.
WALLBOX_ENTITIES = [
    "sensor.myenergi_zappi_links_status",
    "select.myenergi_zappi_links_charge_mode",
    "sensor.myenergi_zappi_links_charge_added_session",
    "sensor.myenergi_zappi_links_energy_used_today",
    "sensor.myenergi_zappi_links_green_energy_today",
    "sensor.myenergi_zappi_rechts_status",
    "select.myenergi_zappi_rechts_charge_mode",
    "sensor.myenergi_zappi_rechts_charge_added_session",
    "sensor.myenergi_zappi_rechts_energy_used_today",
    "sensor.myenergi_zappi_rechts_green_energy_today",
]

NETATMO_ENTITIES = [
    "sensor.temperatur_draussen_temperatur",
    "sensor.temperatur_draussen_luftfeuchtigkeit",
    "sensor.thermometer_innen_temperatur",
    "sensor.thermometer_innen_luftfeuchtigkeit",
    "sensor.innen_schlafzimmer_temperatur",
    "sensor.innen_schlafzimmer_luftfeuchtigkeit",
    "sensor.innen_kinderzimmer_temperatur",
    "sensor.innen_kinderzimmer_luftfeuchtigkeit",
    "sensor.windmesser_windgeschwindigkeit",
]

AUTO_ENTITIES = WALLBOX_ENTITIES + NETATMO_ENTITIES


class HomeAssistantClient:
    """Thin async client for the HA REST API."""

    def __init__(self, base_url: str, token: str, entities: list[str]):
        self.base_url = base_url.rstrip("/")
        self.token = token
        # Merge config entities with always-on entities (deduplicated).
        merged = list(entities)
        for eid in AUTO_ENTITIES:
            if eid not in merged:
                merged.append(eid)
        self.entities = merged
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

    async def _post(self, path: str, payload: dict) -> Any:
        url = f"{self.base_url}{path}"
        resp = await _client().post(url, headers=self._headers, json=payload)
        resp.raise_for_status()
        return resp.json()

    async def call_service(
        self, domain: str, service: str, entity_id: str, **kwargs
    ) -> dict | list:
        """Call a Home Assistant service.

        Example: call_service("light", "turn_on", "light.kuche", brightness=200)
        Returns the HA response (list of changed states) or {"error": ...}.
        """
        if not self.configured:
            return {"error": "Home Assistant nicht konfiguriert"}
        try:
            payload: dict[str, Any] = {"entity_id": entity_id}
            payload.update(kwargs)
            return await self._post(f"/api/services/{domain}/{service}", payload)
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP {e.response.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    async def is_anyone_home(self, person_ids: list[str]) -> bool:
        """Return True if at least one person entity has state 'home'."""
        if not self.configured:
            return True  # Fail safe: assume someone is home
        results = await asyncio.gather(
            *(self.get_entity(pid) for pid in person_ids),
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, dict) and r.get("state") == "home":
                return True
        return False

    async def get_open_windows(
        self, sensor_ids: list[str]
    ) -> list[tuple[str, str]]:
        """Return list of (entity_id, friendly_name) for sensors that are 'on' (= open)."""
        if not self.configured:
            return []
        results = await asyncio.gather(
            *(self.get_entity(sid) for sid in sensor_ids),
            return_exceptions=True,
        )
        open_sensors: list[tuple[str, str]] = []
        for r in results:
            if isinstance(r, dict) and r.get("state") == "on":
                eid = r.get("entity_id", "")
                fn = r.get("attributes", {}).get("friendly_name", eid)
                open_sensors.append((eid, fn))
        return open_sensors

    async def send_notification(
        self, service_target: str, message: str, title: str = "Jarvis"
    ) -> dict | list:
        """Send a push notification via HA notify service.

        Example: send_notification("mobile_app_iphone_maure", "Fenster offen!")
        """
        if not self.configured:
            return {"error": "Home Assistant nicht konfiguriert"}
        try:
            return await self._post(
                f"/api/services/notify/{service_target}",
                {"message": message, "title": title},
            )
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP {e.response.status_code}"}
        except Exception as e:
            return {"error": str(e)}

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

        # Wallbox links (myenergi Zappi)
        wb_left = []
        if v := val("sensor.myenergi_zappi_links_status"):
            wb_left.append(f"Status {v}")
        if v := val("select.myenergi_zappi_links_charge_mode"):
            wb_left.append(f"Modus {v}")
        if v := val("sensor.myenergi_zappi_links_charge_added_session", " kWh"):
            wb_left.append(f"Session {v}")
        if v := val("sensor.myenergi_zappi_links_energy_used_today", " kWh"):
            wb_left.append(f"heute {v}")
        if v := val("sensor.myenergi_zappi_links_green_energy_today", " kWh"):
            wb_left.append(f"davon Solar {v}")
        if wb_left:
            lines.append("Wallbox links: " + ", ".join(wb_left))

        # Wallbox rechts (myenergi Zappi)
        wb_right = []
        if v := val("sensor.myenergi_zappi_rechts_status"):
            wb_right.append(f"Status {v}")
        if v := val("select.myenergi_zappi_rechts_charge_mode"):
            wb_right.append(f"Modus {v}")
        if v := val("sensor.myenergi_zappi_rechts_charge_added_session", " kWh"):
            wb_right.append(f"Session {v}")
        if v := val("sensor.myenergi_zappi_rechts_energy_used_today", " kWh"):
            wb_right.append(f"heute {v}")
        if v := val("sensor.myenergi_zappi_rechts_green_energy_today", " kWh"):
            wb_right.append(f"davon Solar {v}")
        if wb_right:
            lines.append("Wallbox rechts: " + ", ".join(wb_right))

        # Klima — Außen
        climate_parts = []
        # Netatmo Außenmodul bevorzugen, Fallback auf Arbeitszimmer-Sensor
        outdoor_temp = val("sensor.temperatur_draussen_temperatur", "°C") or val("sensor.arbeitszimmer_oben_aussen_temperatur", "°C")
        if outdoor_temp:
            climate_parts.append(f"Außen {outdoor_temp}")
        outdoor_hum = val("sensor.temperatur_draussen_luftfeuchtigkeit", "%") or val("sensor.arbeitszimmer_oben_aussen_luftfeuchtigkeit", "%")
        if outdoor_hum:
            climate_parts.append(f"Luftfeuchte {outdoor_hum}")
        # Netatmo Windmesser bevorzugen, Fallback auf HomematicIP
        wind = val("sensor.windmesser_windgeschwindigkeit", " km/h") or val("sensor.homematic_ip_wettersensor_pro_windspeed", " km/h")
        if wind:
            climate_parts.append(f"Wind {wind}")
        raining = by_id.get("binary_sensor.homematic_ip_wettersensor_pro_raining", {}).get("state")
        if raining == "on":
            climate_parts.append("regnet gerade")
        if v := val("sensor.homematic_ip_wettersensor_pro_today_rain", " mm"):
            climate_parts.append(f"Regen heute {v}")
        if climate_parts:
            lines.append("Klima außen: " + ", ".join(climate_parts))

        # Klima — Innenräume (Netatmo)
        indoor_parts = []
        if v := val("sensor.thermometer_innen_temperatur", "°C"):
            indoor_parts.append(f"Wohnzimmer {v}")
        if v := val("sensor.thermometer_innen_luftfeuchtigkeit", "%"):
            indoor_parts.append(f"({v} Feuchte)")
        if v := val("sensor.arbeitszimmer_oben_innen_wohnzimmer_kohlendioxid", " ppm"):
            indoor_parts.append(f"CO₂ {v}")
        if v := val("sensor.innen_schlafzimmer_temperatur", "°C"):
            indoor_parts.append(f"Schlafzimmer {v}")
        if v := val("sensor.innen_kinderzimmer_temperatur", "°C"):
            indoor_parts.append(f"Kinderzimmer {v}")
        if indoor_parts:
            lines.append("Klima innen: " + ", ".join(indoor_parts))

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

        # Lichter (Philips Hue) — nur eingeschaltete anzeigen
        lights_on = []
        for s in states:
            eid = s.get("entity_id", "")
            if eid.startswith("light.") and s.get("state") == "on":
                fn = s.get("attributes", {}).get("friendly_name", eid)
                br = s.get("attributes", {}).get("brightness")
                if br is not None:
                    pct = round(br / 255 * 100)
                    lights_on.append(f"{fn} ({pct}%)")
                else:
                    lights_on.append(fn)
        if lights_on:
            lines.append("Lichter an: " + ", ".join(lights_on))

        # Fenster / Tueren — nur offene anzeigen
        open_names = []
        for s in states:
            eid = s.get("entity_id", "")
            dc = s.get("attributes", {}).get("device_class", "")
            if dc in ("window", "door", "opening") and s.get("state") == "on":
                fn = s.get("attributes", {}).get("friendly_name", eid)
                open_names.append(fn)
        if open_names:
            lines.append("Fenster/Tueren offen: " + ", ".join(open_names))

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

        # ── Plausibilitätsprüfung: logische Widersprüche erkennen ──
        warnings: list[str] = []

        # Hilfsfunktion: Person-Status auslesen
        def person_state(eid: str) -> str | None:
            s = by_id.get(eid)
            if not s:
                return None
            st = s.get("state", "")
            return st if st not in ("unknown", "unavailable", "") else None

        mario_home = person_state("person.maure")
        britta_home = person_state("person.britta")

        # BMW Ladeleistung prüfen
        bmw_power_raw = by_id.get(
            "sensor.ix1_xdrive30_battery_ev_charging_power", {}
        ).get("state")
        try:
            bmw_power = float(bmw_power_raw) if bmw_power_raw not in (None, "", "unknown", "unavailable") else 0.0
        except (TypeError, ValueError):
            bmw_power = 0.0

        # Widerspruch 1: BMW lädt angeblich, aber Britta (BMW-Fahrerin) ist nicht zu Hause
        if bmw_power > 0.5 and britta_home and britta_home != "home":
            warnings.append(
                f"WIDERSPRUCH: BMW zeigt {bmw_power:.0f} W Ladeleistung, "
                f"aber person.britta meldet '{britta_home}'. "
                "Der BMW-Ladewert ist vermutlich veraltet (Connected Drive "
                "aktualisiert nicht, wenn das Auto unterwegs ist). "
                "Vertraue der Anwesenheitserkennung."
            )

        # Widerspruch 2: Wallbox zeigt 'Charging' aber kein Auto zu Hause
        wb_status_raw = by_id.get(
            "sensor.myenergi_zappi_links_status", {}
        ).get("state", "").lower()
        all_away = (
            (britta_home and britta_home != "home")
            and (mario_home and mario_home != "home")
        )
        if "charg" in wb_status_raw and all_away:
            warnings.append(
                "WIDERSPRUCH: Wallbox meldet Ladestatus, aber beide Personen "
                "sind nicht zu Hause. Wallbox-Status ist vermutlich veraltet."
            )

        # Widerspruch 3: Person als 'home' gemeldet, aber seit langer Zeit
        # kein Update → können wir hier nicht prüfen (braucht last_changed),
        # aber Jarvis bekommt den Hinweis im System-Prompt.

        if warnings:
            lines.append("")
            lines.append("⚠️ PLAUSIBILITÄTS-HINWEISE (nicht vorlesen, nur intern nutzen):")
            for w in warnings:
                lines.append(f"  - {w}")

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


def build_client_from_config(config: dict) -> HomeAssistantClient:
    """Factory: read URL from config, token from env."""
    return HomeAssistantClient(
        base_url=config.get("home_assistant_url", ""),
        token=os.getenv("HOMEASSISTANT_TOKEN", ""),
        entities=config.get("home_assistant_entities", []),
    )
