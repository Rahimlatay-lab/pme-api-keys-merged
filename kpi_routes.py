"""
KPI endpoints computed live from the ERP (stateless: nothing is stored).

  GET /v1/kpi/sales?date_from=2026-01-01&date_to=2026-03-31
  GET /v1/kpi/stock?overstock_factor=5

Rows are aggregated while streaming from the ERP, so memory stays flat. Every KPI carries its
formula, inputs and a sample of source record ids (data lineage).
"""
import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

import kpi
from erp_client import ERPError, get_erp_client
from erp_config import ERPNotConfigured, get_settings
from erp_export import ExportTooLarge, open_rows
from erp_routes import export_guard, http_error
from erp_schemas import RESOURCES

log = logging.getLogger("kpi")

router = APIRouter(prefix="/v1/kpi", tags=["kpi"])

EXCLUDED_STATUSES = {"draft", "cancel", "cancelled", "canceled", "void"}
EVIDENCE_SAMPLE = 25
MAX_RANGE_DAYS = 3660

# Edit to your business. higher_is_better=False for "bad when high" KPIs.
THRESHOLDS = {
    "growth": kpi.Threshold(Decimal("0"), Decimal("-10")),
    "stockout_rate": kpi.Threshold(Decimal("5"), Decimal("15"), higher_is_better=False),
}


async def _sales_period(client, d_from: date, d_to: date, cap: int):
    """Stream invoices for a period -> (revenue, count, customer_ids, evidence_ids, skipped)."""
    rows, stats = await open_rows(client, RESOURCES["invoices"],
                                  {"date_from": d_from, "date_to": d_to}, None, cap)
    total, count, customers, evidence = Decimal(0), 0, set(), []
    async for inv in rows:
        # defensive: re-check the range ourselves in case the ERP ignored the filter
        if not (d_from <= inv.issue_date <= d_to) or (inv.status or "").lower() in EXCLUDED_STATUSES:
            continue
        total += inv.total
        count += 1
        if inv.customer_id:
            customers.add(inv.customer_id)
        if len(evidence) < EVIDENCE_SAMPLE:
            evidence.append(inv.id)
    return total, count, customers, evidence, stats.skipped


@router.get("/sales")
async def sales_kpis(
    date_from: date,
    date_to: date,
    auth: dict = Depends(export_guard),
):
    if date_from > date_to:
        raise HTTPException(422, "date_from must be on or before date_to")
    days = (date_to - date_from).days + 1
    if days > MAX_RANGE_DAYS:
        raise HTTPException(422, f"Range too large (max {MAX_RANGE_DAYS} days)")
    prev_to = date_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=days - 1)       # same length, immediately before

    ctx = {"customer_id": auth["customer_id"], "resource": "kpi.sales"}
    try:
        cap = get_settings().max_export_rows
        client = get_erp_client()
        cur = await _sales_period(client, date_from, date_to, cap)
        prev = await _sales_period(client, prev_from, prev_to, cap)
    except (ERPError, ERPNotConfigured, ExportTooLarge) as exc:
        raise http_error(exc, ctx)

    (rev, n, cust, ev, skipped), (p_rev, p_n, p_cust, _, p_skipped) = cur, prev
    kpis = [
        kpi.revenue(rev, n, ev),
        kpi.growth(rev, p_rev, THRESHOLDS["growth"]),
        kpi.average_basket(rev, n),
        kpi.retention(p_cust, cust),
    ]
    return {
        "period": {"from": date_from, "to": date_to},
        "previous_period": {"from": prev_from, "to": prev_to},
        "kpis": [k.to_dict() for k in kpis],
        "data_quality": {"skipped_invalid_records": skipped + p_skipped},
        "not_available": {
            "gross_margin": "needs cost of goods sold (COGS) data",
            "return_rate": "needs returns data",
        },
    }


@router.get("/stock")
async def stock_kpis(
    overstock_factor: Annotated[Decimal, Query(gt=1, le=100)] = Decimal(5),
    auth: dict = Depends(export_guard),
):
    """available = on_hand - reserved. Overstock: available > overstock_factor x reorder_level."""
    ctx = {"customer_id": auth["customer_id"], "resource": "kpi.stock"}
    try:
        cfg = get_settings()
        rows, stats = await open_rows(get_erp_client(), RESOURCES["inventory"], {}, None,
                                      cfg.max_export_rows)
        total = 0
        out, over, low, value = [], [], [], Decimal(0)
        async for item in rows:
            total += 1
            available = kpi.available_stock(item.quantity_on_hand, item.quantity_reserved or 0)
            if item.unit_cost is not None and item.quantity_on_hand > 0:
                value += item.quantity_on_hand * item.unit_cost
            if available <= 0:
                out.append(item.sku)
            elif item.reorder_level and available <= item.reorder_level:
                low.append(item.sku)
            if item.reorder_level and available > overstock_factor * item.reorder_level:
                over.append(item.sku)
    except (ERPError, ERPNotConfigured, ExportTooLarge) as exc:
        raise http_error(exc, ctx)

    kpis = [
        kpi.stockout_rate(len(out), total, THRESHOLDS["stockout_rate"], out[:EVIDENCE_SAMPLE]),
        kpi.overstock_rate(len(over), total, over[:EVIDENCE_SAMPLE]),
    ]
    return {
        "kpis": [k.to_dict() for k in kpis],
        "inventory_value": str(value.quantize(Decimal("0.01"))),
        "below_reorder_level": {"count": len(low), "sku_sample": low[:EVIDENCE_SAMPLE]},
        "data_quality": {"skipped_invalid_records": stats.skipped},
        "not_available": {
            "stock_turnover": "needs COGS data (kpi.stock_turnover is ready)",
            "coverage_days": "needs daily demand (kpi.coverage_days is ready)",
        },
    }
