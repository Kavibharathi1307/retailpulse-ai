"use strict";

const statusBadge = document.getElementById("engine-status");

async function refreshEngineStatus() {
  try {
    const response = await fetch("/api/health");
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    const gemini = data.gemini_configured ? "Gemini ready" : "Gemini not configured";
    statusBadge.textContent = `Backend online \u00b7 ${gemini}`;
    statusBadge.classList.remove("error");
  } catch (err) {
    statusBadge.textContent = "Backend unreachable";
    statusBadge.classList.add("error");
  }
}

refreshEngineStatus();