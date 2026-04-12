#!/usr/bin/env python3
"""Einmalig ausfuehren: Fuegt fehlende Wallbox-Entitaeten zur config.json hinzu."""

import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.json")

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

with open(CONFIG_PATH, "r") as f:
    config = json.load(f)

entities = config.get("home_assistant_entities", [])
added = []
for eid in WALLBOX_ENTITIES:
    if eid not in entities:
        entities.append(eid)
        added.append(eid)

config["home_assistant_entities"] = entities

with open(CONFIG_PATH, "w") as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
    f.write("\n")

if added:
    print(f"{len(added)} Wallbox-Entitaeten hinzugefuegt:")
    for eid in added:
        print(f"  + {eid}")
else:
    print("Alle Wallbox-Entitaeten waren bereits vorhanden.")
