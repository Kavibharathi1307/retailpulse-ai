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

    # --- demand forecast ---------------------------------------------------
    # Short-term demand outlook (explainable, Milestone 7). The recent window
    # daily rate is assumed to continue over the forecast horizon:
    #   forecast_units = recent_daily_rate * horizon_days
    # The preceding baseline window only positions the trend; it never changes
    # the forecast numbers.
    forecast_recent_days: int = 7
    forecast_baseline_days: int = 28
    # A forecast needs a fully covered recent window; below it is
    # INSUFFICIENT_DATA (no numbers are fabricated).
    forecast_min_recent_days: int = 7
    # The baseline window may be partial: at least this many covered days keeps
    # the trend meaningful (SUFFICIENT_DATA); a thinner but non-zero baseline is
    # reported as LIMITED_DATA.
    forecast_min_baseline_days: int = 14
    # |recent - baseline| daily rate change at or above this % => UP/DOWN;
    # smaller movements are STABLE (tiny fluctuations are noise).
    forecast_trend_threshold_pct: float = 15.0
    # Inventory vs expected demand buffer: current_stock >= forecast_units *
    # (1 + buffer/100) => SUFFICIENT; below forecast_units => AT_RISK; in
    # between => WATCH.
    forecast_inventory_buffer_pct: float = 25.0
    # Horizons (days) accepted by the API. Any other horizon is rejected with
    # HTTP 400. The engine itself accepts any positive horizon.
    forecast_valid_horizons: tuple = (7, 14, 30)

    # --- trend -------------------------------------------------------------
    # Trend direction within a period uses the first vs second half of the
    # period average daily rate. |difference| below this % => STABLE.
    trend_change_threshold_pct: float = 10.0

    # --- data sufficiency --------------------------------------------------
    # Minimum number of days in a window before an average is trusted.
    min_history_days: int = 7


DEFAULT_CONFIG = AnalyticsConfig()