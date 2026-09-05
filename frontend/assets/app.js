"use strict";

// Application entry point. Scripts at the end of <body> guarantee the DOM is
// ready, so we can boot immediately.

function boot() {
  initSalesChart(document.getElementById("sales-chart"));
  initCopilot();
  bootDashboard();
  wireTrendControls();
  wireProductControls();
  wireAttentionControls();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}