"""Generate the bundled demo dataset. Seeded, so output is identical every run.

12 SKUs across 3 categories, 180 days of daily demand with weekly seasonality,
a mild trend, noise, and two injected demand spikes for the risk agent to find.
"""
from __future__ import annotations

import csv
import math
import os
import random

SKUS = [
    # (sku_id, name, category, unit_cost, lead_time_days, base_daily, trend)
    ("SKU-1001", "Hex bolt M8x40, zinc", "fasteners", 0.42, 9, 120, 0.05),
    ("SKU-1002", "Hex bolt M10x50, zinc", "fasteners", 0.61, 9, 95, 0.03),
    ("SKU-1003", "Nylon lock nut M8", "fasteners", 0.18, 12, 140, 0.02),
    ("SKU-1004", "Flat washer M8", "fasteners", 0.06, 7, 220, 0.01),
    ("SKU-2001", "Temp sensor probe PT100", "sensors", 18.50, 14, 22, 0.08),
    ("SKU-2002", "Pressure transducer 0-10bar", "sensors", 64.00, 21, 8, 0.04),
    ("SKU-2003", "Proximity switch inductive", "sensors", 12.75, 11, 35, 0.06),
    ("SKU-2004", "Level float switch", "sensors", 9.20, 10, 28, 0.02),
    ("SKU-3001", "Corrugated box 400x300x200", "packaging", 1.15, 5, 310, 0.04),
    ("SKU-3002", "Stretch film 500mm", "packaging", 6.80, 6, 85, 0.03),
    ("SKU-3003", "Pallet EUR EPAL", "packaging", 14.20, 8, 60, 0.01),
    ("SKU-3004", "Bubble wrap roll 750mm", "packaging", 11.40, 6, 48, 0.02),
]

SUPPLIERS = [
    # (supplier_id, name, approved, reliability)
    ("SUP-A", "Acme Industrial Supply", True, 0.96),
    ("SUP-B", "Bharat Components Ltd", True, 0.88),
    ("SUP-C", "Continental Parts Co", True, 0.91),
    ("SUP-D", "Discount Direct Wholesale", False, 0.62),
]

DAYS = 180
SEED = 42


def _daily_demand(day: int, base: float, trend: float) -> float:
    weekly = 1.0 + 0.25 * math.sin(2 * math.pi * day / 7.0 - 1.2)
    growth = 1.0 + trend * day / 30.0
    noise = random.gauss(1.0, 0.12)
    return max(0.0, base * weekly * growth * noise)


def generate(data_dir: str) -> None:
    random.seed(SEED)
    os.makedirs(data_dir, exist_ok=True)

    with open(os.path.join(data_dir, "skus.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sku_id", "name", "category", "unit_cost", "lead_time_days"])
        for sku_id, name, cat, cost, lt, *_ in SKUS:
            w.writerow([sku_id, name, cat, f"{cost:.2f}", lt])

    with open(os.path.join(data_dir, "suppliers.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["supplier_id", "name", "approved", "reliability"])
        for sid, name, approved, rel in SUPPLIERS:
            w.writerow([sid, name, "true" if approved else "false", rel])

    with open(os.path.join(data_dir, "sku_suppliers.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sku_id", "supplier_id", "unit_cost", "lead_time_days"])
        for sku_id, _name, _cat, cost, lt, *_rest in SKUS:
            # Two offers per SKU: an approved supplier near list cost, and a
            # cheaper unapproved one the policy layer must block.
            # SKU-2002 is the exception: only the unapproved supplier offers it,
            # so the planner must block the proposal visibly.
            if sku_id != "SKU-2002":
                w.writerow([sku_id, "SUP-A", f"{cost * 1.00:.2f}", lt])
            w.writerow([sku_id, "SUP-D", f"{cost * 0.82:.2f}", lt + 6])

    with open(os.path.join(data_dir, "inventory.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sku_id", "location", "on_hand", "on_order"])
        for i, (sku_id, _n, _c, _co, lt, base, _t) in enumerate(SKUS):
            # Deliberately mixed coverage: some SKUs healthy, some thin.
            cover_factor = [1.4, 0.4, 1.1, 1.8, 0.5, 1.2, 1.0, 0.3, 1.6, 0.9, 1.3, 0.6][i]
            w.writerow([sku_id, "WH-01", int(base * lt * cover_factor), 0])

    with open(os.path.join(data_dir, "demand.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sku_id", "date", "qty"])
        for sku_id, _n, _c, _co, _lt, base, trend in SKUS:
            for day in range(DAYS):
                qty = _daily_demand(day, base, trend)
                # Injected anomalies: a spike and a drop for the risk agent.
                if sku_id == "SKU-2001" and day == DAYS - 6:
                    qty *= 4.2
                if sku_id == "SKU-3001" and day == DAYS - 12:
                    qty *= 0.15
                w.writerow([sku_id, f"2026-03-19+{day:03d}", int(round(qty))])


if __name__ == "__main__":
    generate(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data"))
    print("sample data written")
