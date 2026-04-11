"""
Home Assistant read-only client for Jarvis.

Talks to a Home Assistant instance (typically via Nabu Casa Cloud) using
a Long-Lived Access Token. Exposes three async helpers:

- get_dashboard_status()  -> compact dict/string snapshot of all curated
                             entities, used both at startup (system prompt)
                             and on demand via [ACTION:HOME].
- get_entity(entity_id)   -> raw state dict for a single entity.
- search_entities(query)  -> keyword filter over the curated entity list,
                             returns a list of (entity_id, friendly_name,
                             state) tuples.

The token is read from the HOMEASSISTANT_TOKEN environment variable. The
base URL and the curated entity list live in config.json. If either is
missing, the helpers degrade gracefully: get_dashboard_status() returns
"" so the system prompt simply omits the block, and get_entity() returns
an {"error": ...} dict.

LEVEL B (read-only): no services are called, no state is ever changed.
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

        # Energie
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


def build_client_from_config(config: dict) -> HomeAssistantClient:
    """Factory: read URL from config, token from env."""
    return HomeAssistantClient(
        base_url=config.get("home_assistant_url", ""),
        token=os.getenv("HOMEASSISTANT_TOKEN", ""),
        entities=config.get("home_assistant_entities", []),
    )
