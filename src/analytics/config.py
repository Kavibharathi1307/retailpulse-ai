"""Central configuration of the deterministic analytics engine (Milestone 3).

All thresholds live here so they can be tuned in one place. Every default is
documented; the engine reads them through a frozen :class:`AnalyticsConfig`.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AnalyticsConfig:
    # --- analysis periods --------------------------------------------------
    # Window (days) of sales history used to estimate daily demand for
    # inventory-based analytics (stock-out risk, overstock, slow movers).
    demand_window_days: int = 28
    # Window (days) used for product/store performance comparisons.
    performance_period_days: int = 28
    # Window (days) scanned for sales anomalies, ending at the analysis date.
    anomaly_scan_days: int = 90
    # Recent window (days) compared against the baseline for anomalies.
    anomaly_recent_days: int = 7
    # Baseline window (days) immediately preceding the recent window.
    anomaly_baseline_days: int = 28

    # --- stock-out risk ----------------------------------------------------
    # days_of_stock = current_stock / average_daily_sales.
    # Risk categories:
    #   CRITICAL when days_of_stock <= stockout_critical_days
    #   HIGH     when days_of_stock <= stockout_high_days
    #   MEDIUM   when days_of_stock <= stockout_medium_days
    #   LOW      otherwise
    stockout_critical_days: float = 7.0
    stockout_high_days: float = 14.0
    stockout_medium_days: float = 30.0

    # --- overstock ---------------------------------------------------------
    # stock_cover_days = current_stock / average_daily_sales.
    # A store/product is OVERSTOCK when cover >= overstock_cover_days.
    overstock_cover_days: float = 60.0

    # --- slow movers -------------------------------------------------------
    # A store/product is a SLOW_MOVER when average_daily_sales <= threshold
    # AND it was observed selling on at least slow_mover_min_sales_days distinct
    # days within the demand window (avoids false positives from thin history).
    slow_mover_daily_units: float = 0.5
    slow_mover_min_sales_days: int = 5

    # --- sales anomalies ---------------------------------------------------
    # change_pct = (recent_daily_rate - baseline_daily_rate) / baseline_daily_rate.
    #   SPIKE when change_pct >= spike_threshold_pct
    #   DROP  when change_pct <= -drop_threshold_pct
    # A candidate event must also satisfy:
    #   baseline window total units >= min_baseline_units   (volume safeguard)
    #   |recent - baseline| total units >= min_anomaly_change_units
    #   (applies in both directions, preventing tiny fluctuations from being
    #    reported as business-changing anomalies)
    spike_threshold_pct: float = 100.0
    drop_threshold_pct: float = 50.0
    min_baseline_units: float = 30.0
    min_anomaly_change_units: float = 10.0

    # --- trend -------------------------------------------------------------
    # Trend direction within a period uses the first vs second half of the
    # period average daily rate. |difference| below this % => STABLE.
    trend_change_threshold_pct: float = 10.0

    # --- data sufficiency --------------------------------------------------
    # Minimum number of days in a window before an average is trusted.
    min_history_days: int = 7


DEFAULT_CONFIG = AnalyticsConfig()