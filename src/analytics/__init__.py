"""Deterministic retail analytics engine (Milestone 3).

Pure, rule-based analytics over the committed retail dataset. No AI, no external
services -- every insight is derived from raw numbers with documented formulas
and carries the evidence used to make it.
"""

from src.analytics.config import AnalyticsConfig, DEFAULT_CONFIG
from src.analytics.engine import (
    attention_summary,
    overstock,
    product_performance,
    sales_anomalies,
    slow_movers,
    stockout_risks,
    store_performance,
)
from src.analytics.recommendations import recommendations

__all__ = [
    "AnalyticsConfig",
    "DEFAULT_CONFIG",
    "attention_summary",
    "overstock",
    "product_performance",
    "recommendations",
    "sales_anomalies",
    "slow_movers",
    "stockout_risks",
    "store_performance",
]