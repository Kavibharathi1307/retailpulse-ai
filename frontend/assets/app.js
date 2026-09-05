"use strict";

// Application entry point. Scripts at the end of <body> guarantee the DOM is
// ready, so we can boot immediately.

function boot() {
  initSalesChart(document.getElementById("sales-chart"));
  initOutlookChart(document.getElementById("outlook-chart"));
  initCopilot();
  bootDashboard();
  wireTrendControls();
  wireProductControls();
  wireAttentionControls();
  wireOutlookControls();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}