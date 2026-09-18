"""Load the planning catalog from CSV files into the orchestrator's data dict.

Every file is validated as it is read: missing files/columns, unparseable
numbers, negative quantities, and dangling foreign-key references all raise
:class:`CatalogError` (with file name and 1-based row number) instead of
surfacing later as an unhandled 500 deep in the planning pipeline.
"""
from __future__ import annotations

import csv
import hashlib
import os
from typing import Any

# The catalog is exactly these five files. The inputs hash (P1-3) covers the
# same set, sorted by filename, so any byte-level change is detected.
CATALOG_FILES = ("demand.csv", "inventory.csv", "sku_suppliers.csv", "skus.csv", "suppliers.csv")


class CatalogError(Exception):
    """A typed catalog validation failure: which file, which row, what is wrong."""

    def __init__(self, *, file: str, row: int | None, message: str):
        self.file = file
        self.row = row
        self.message = message
        super().__init__(f"{file}:{row if row is not None else '?'}: {message}")

    def to_dict(self) -> dict[str, Any]:
        return {"file": self.file, "row": self.row, "message": self.message}


def hash_catalog_files(data_dir: str) -> str:
    """SHA-256 over the raw bytes of the five catalog CSVs, sorted by filename."""
    digest = hashlib.sha256()
    for name in sorted(CATALOG_FILES):
        path = os.path.join(data_dir, name)
        try:
            with open(path, "rb") as f:
                digest.update(f.read())
        except OSError as exc:
            raise CatalogError(file=name, row=None, message=f"cannot read file: {exc}") from exc
    return digest.hexdigest()


def _read(data_dir: str, name: str, required_columns: list[str]) -> list[dict[str, str]]:
    path = os.path.join(data_dir, name)
    try:
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise CatalogError(file=name, row=1, message="missing header row")
            missing = [c for c in required_columns if c not in reader.fieldnames]
            if missing:
                raise CatalogError(
                    file=name, row=1, message=f"missing columns: {', '.join(missing)}"
                )
            return list(reader)
    except FileNotFoundError as exc:
        raise CatalogError(file=name, row=None, message="required file is missing") from exc
    except OSError as exc:
        raise CatalogError(file=name, row=None, message=f"cannot read file: {exc}") from exc


def _float(
    raw: str, *, file: str, row: int, column: str, minimum: float | None = None
) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise CatalogError(
            file=file, row=row, message=f"column {column!r} is not a number: {raw!r}"
        ) from exc
    if minimum is not None and value < minimum:
        raise CatalogError(
            file=file,
            row=row,
            message=f"column {column!r} must be >= {minimum:g}, got {value:g}",
        )
    return value


def _check_ref(
    value: str, known: set[str], *, file: str, row: int, column: str, target: str
) -> None:
    if value not in known:
        raise CatalogError(
            file=file,
            row=row,
            message=f"column {column!r} references unknown {target}: {value!r}",
        )


def load_data(data_dir: str) -> dict[str, Any]:
    sku_rows = _read(data_dir, "skus.csv", ["sku_id", "unit_cost", "lead_time_days"])
    skus: dict[str, dict[str, Any]] = {}
    for i, r in enumerate(sku_rows, start=2):
        if not r["sku_id"]:
            raise CatalogError(file="skus.csv", row=i, message="sku_id must not be empty")
        skus[r["sku_id"]] = {
            **r,
            "unit_cost": _float(r["unit_cost"], file="skus.csv", row=i,
                               column="unit_cost", minimum=0.0),
            "lead_time_days": _float(r["lead_time_days"], file="skus.csv", row=i,
                                     column="lead_time_days", minimum=0.0),
        }

    supplier_rows = _read(
        data_dir, "suppliers.csv", ["supplier_id", "approved", "reliability"]
    )
    suppliers: dict[str, dict[str, Any]] = {}
    for i, r in enumerate(supplier_rows, start=2):
        if not r["supplier_id"]:
            raise CatalogError(
                file="suppliers.csv", row=i, message="supplier_id must not be empty"
            )
        reliability = _float(r["reliability"], file="suppliers.csv", row=i,
                             column="reliability", minimum=0.0)
        if reliability > 1.0:
            raise CatalogError(
                file="suppliers.csv", row=i,
                message=f"column 'reliability' must be <= 1, got {reliability:g}",
            )
        suppliers[r["supplier_id"]] = {
            **r,
            "approved": (r["approved"] or "").strip().lower() in ("1", "true", "yes"),
            "reliability": reliability,
        }

    link_rows = _read(
        data_dir, "sku_suppliers.csv", ["sku_id", "supplier_id", "unit_cost", "lead_time_days"]
    )
    sku_suppliers: dict[str, list[dict]] = {}
    for i, r in enumerate(link_rows, start=2):
        _check_ref(r["sku_id"], set(skus), file="sku_suppliers.csv", row=i,
                   column="sku_id", target="sku")
        _check_ref(r["supplier_id"], set(suppliers), file="sku_suppliers.csv", row=i,
                   column="supplier_id", target="supplier")
        sku_suppliers.setdefault(r["sku_id"], []).append(
            {
                "supplier_id": r["supplier_id"],
                "unit_cost": _float(r["unit_cost"], file="sku_suppliers.csv", row=i,
                                    column="unit_cost", minimum=0.0),
                "lead_time_days": _float(r["lead_time_days"], file="sku_suppliers.csv",
                                         row=i, column="lead_time_days", minimum=0.0),
                "reliability": suppliers[r["supplier_id"]]["reliability"],
            }
        )

    inventory: dict[str, dict[str, Any]] = {}
    for i, r in enumerate(
        _read(data_dir, "inventory.csv", ["sku_id", "location", "on_hand", "on_order"]),
        start=2,
    ):
        _check_ref(r["sku_id"], set(skus), file="inventory.csv", row=i,
                   column="sku_id", target="sku")
        inventory[r["sku_id"]] = {
            "location": r["location"],
            "on_hand": _float(r["on_hand"], file="inventory.csv", row=i,
                              column="on_hand", minimum=0.0),
            "on_order": _float(r["on_order"], file="inventory.csv", row=i,
                               column="on_order", minimum=0.0),
        }

    demand_history: dict[str, list[float]] = {sku_id: [] for sku_id in skus}
    for i, r in enumerate(
        _read(data_dir, "demand.csv", ["sku_id", "qty"]), start=2
    ):
        _check_ref(r["sku_id"], set(skus), file="demand.csv", row=i,
                   column="sku_id", target="sku")
        demand_history[r["sku_id"]].append(
            _float(r["qty"], file="demand.csv", row=i, column="qty", minimum=0.0)
        )

    return {
        "skus": skus,
        "suppliers": suppliers,
        "sku_suppliers": sku_suppliers,
        "inventory": inventory,
        "demand_history": demand_history,
    }
