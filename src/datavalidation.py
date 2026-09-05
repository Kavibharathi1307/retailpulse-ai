"""Basic validation for the retail data layer (Milestone 2).

These functions validate raw records *before* they are trusted for analytics.
They are deliberately simple: structural integrity and reference validity, not
business analytics.
"""

from datetime import date


def validate_store(row: dict) -> list[str]:
    """Return a list of validation problems for a stores row."""
    problems = []
    if row.get("store_id") is None:
        problems.append("store_id missing")
    if not str(row.get("store_name") or "").strip():
        problems.append("store_name empty")
    if row.get("active") not in (0, 1):
        problems.append("active must be 0 or 1")
    return problems


def validate_product(row: dict) -> list[str]:
    """Return a list of validation problems for a products row."""
    problems = []
    if row.get("product_id") is None:
        problems.append("product_id missing")
    if not str(row.get("product_name") or "").strip():
        problems.append("product_name empty")
    if not str(row.get("category") or "").strip():
        problems.append("category empty")
    if not isinstance(row.get("unit_price"), (int, float)) or row.get("unit_price") < 0:
        problems.append("unit_price must be a number >= 0")
    if row.get("active") not in (0, 1):
        problems.append("active must be 0 or 1")
    return problems


def _valid_date(value) -> bool:
    try:
        date.fromisoformat(str(value))
        return True
    except ValueError:
        return False


def validate_sale(row: dict, store_ids: set, product_ids: set) -> list[str]:
    """Return a list of validation problems for a sales row."""
    problems = []
    if row.get("sale_id") is None:
        problems.append("sale_id missing")
    if not _valid_date(row.get("sale_date")):
        problems.append(f"invalid sale_date: {row.get('sale_date')!r}")
    if row.get("store_id") not in store_ids:
        problems.append(f"store_id {row.get('store_id')!r} does not exist")
    if row.get("product_id") not in product_ids:
        problems.append(f"product_id {row.get('product_id')!r} does not exist")
    if not isinstance(row.get("quantity_sold"), (int, float)) or row.get("quantity_sold") < 0:
        problems.append("quantity_sold must be a number >= 0")
    if not isinstance(row.get("revenue"), (int, float)) or row.get("revenue") < 0:
        problems.append("revenue must be a number >= 0")
    return problems


def validate_inventory(row: dict, store_ids: set, product_ids: set) -> list[str]:
    """Return a list of validation problems for an inventory row."""
    problems = []
    if row.get("inventory_id") is None:
        problems.append("inventory_id missing")
    if row.get("store_id") not in store_ids:
        problems.append(f"store_id {row.get('store_id')!r} does not exist")
    if row.get("product_id") not in product_ids:
        problems.append(f"product_id {row.get('product_id')!r} does not exist")
    if not isinstance(row.get("current_stock"), (int, float)) or row.get("current_stock") < 0:
        problems.append("current_stock must be a number >= 0")
    if not isinstance(row.get("reorder_level"), (int, float)) or row.get("reorder_level") < 0:
        problems.append("reorder_level must be a number >= 0")
    if not _valid_date(row.get("last_restock_date")):
        problems.append(f"invalid last_restock_date: {row.get('last_restock_date')!r}")
    return problems