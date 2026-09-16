"""Load the planning catalog from CSV files into the orchestrator's data dict."""
from __future__ import annotations

import csv
import os
from typing import Any


def _read(path: str) -> list[dict[str, str]]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_data(data_dir: str) -> dict[str, Any]:
    skus = {r["sku_id"]: r for r in _read(os.path.join(data_dir, "skus.csv"))}
    for s in skus.values():
        s["unit_cost"] = float(s["unit_cost"])
        s["lead_time_days"] = float(s["lead_time_days"])

    suppliers = {r["supplier_id"]: r for r in _read(os.path.join(data_dir, "suppliers.csv"))}
    for s in suppliers.values():
        s["approved"] = s["approved"].strip().lower() in ("1", "true", "yes")
        s["reliability"] = float(s["reliability"])

    sku_suppliers: dict[str, list[dict]] = {}
    for r in _read(os.path.join(data_dir, "sku_suppliers.csv")):
        sku_suppliers.setdefault(r["sku_id"], []).append(
            {
                "supplier_id": r["supplier_id"],
                "unit_cost": float(r["unit_cost"]),
                "lead_time_days": float(r["lead_time_days"]),
                "reliability": suppliers[r["supplier_id"]]["reliability"],
            }
        )

    inventory = {}
    for r in _read(os.path.join(data_dir, "inventory.csv")):
        inventory[r["sku_id"]] = {
            "location": r["location"],
            "on_hand": float(r["on_hand"]),
            "on_order": float(r["on_order"]),
        }

    demand_history: dict[str, list[float]] = {sku_id: [] for sku_id in skus}
    for r in _read(os.path.join(data_dir, "demand.csv")):
        demand_history[r["sku_id"]].append(float(r["qty"]))

    return {
        "skus": skus,
        "suppliers": suppliers,
        "sku_suppliers": sku_suppliers,
        "inventory": inventory,
        "demand_history": demand_history,
    }
