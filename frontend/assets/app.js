"use strict";

const statusBadge = document.getElementById("engine-status");

function formatNumber(value) {
  return Number(value).toLocaleString("en-US");
}

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

async function refreshDataStatus() {
  const targets = {
    stores: document.getElementById("data-stores"),
    products: document.getElementById("data-products"),
    sales: document.getElementById("data-sales"),
    inventory: document.getElementById("data-inventory"),
  };

  let summary;
  try {
    const response = await fetch("/api/data/summary");
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    summary = await response.json();
  } catch (err) {
    Object.values(targets).forEach((el) => {
      el.textContent = "unavailable";
    });
    return;
  }

  targets.stores.textContent = formatNumber(summary.counts.stores);
  targets.products.textContent = formatNumber(summary.counts.products);
  targets.sales.textContent = formatNumber(summary.counts.sales);
  targets.inventory.textContent = formatNumber(summary.counts.inventory);

  const rangeElement = document.getElementById("data-range");
  rangeElement.textContent = summary.first_date && summary.last_date
    ? `Sales history from ${summary.first_date} to ${summary.last_date}.`
    : "No sales history available.";

  await refreshSalesPreview();
}

async function refreshSalesPreview() {
  const tbody = document.getElementById("sales-preview");
  try {
    const response = await fetch("/api/sales?limit=8");
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    if (data.items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" class="placeholder-body">No sales records.</td></tr>`;
      return;
    }
    tbody.innerHTML = "";
    for (const sale of data.items) {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>${sale.sale_date}</td>
        <td>${escapeHtml(sale.store_name)}</td>
        <td>${escapeHtml(sale.product_name)}</td>
        <td>${formatNumber(sale.quantity_sold)}</td>
        <td>${Number(sale.revenue).toFixed(2)}</td>`;
      tbody.appendChild(row);
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" class="placeholder-body">Sales preview unavailable.</td></tr>`;
  }
}

async function refreshAnalyticsStatus() {
  const targets = {
    stockout: document.getElementById("analytics-stockout"),
    overstock: document.getElementById("analytics-overstock"),
    slow: document.getElementById("analytics-slow"),
    anomalies: document.getElementById("analytics-anomalies"),
  };

  try {
    const response = await fetch("/api/analytics/attention-summary?limit=1");
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    const counts = data.counts;
    targets.stockout.textContent = formatNumber(counts.stock_out_risks);
    targets.overstock.textContent = formatNumber(counts.overstock);
    targets.slow.textContent = formatNumber(counts.slow_movers);
    targets.anomalies.textContent = formatNumber(
      counts.sales_spikes + counts.sales_drops,
    );

    const rangeElement = document.getElementById("analytics-range");
    rangeElement.textContent = data.analysis_date
      ? `Deterministic insights computed as of ${data.analysis_date} (no AI used).`
      : "Analytics unavailable.";
  } catch (err) {
    Object.values(targets).forEach((el) => {
      el.textContent = "unavailable";
    });
    document.getElementById("analytics-range").textContent =
      "Analytics engine unreachable.";
  }
}

async function refreshCopilot() {
  const form = document.getElementById("copilot-form");
  const input = document.getElementById("copilot-question");
  const askButton = document.getElementById("copilot-ask");
  const statusEl = document.getElementById("copilot-status");
  const resultEl = document.getElementById("copilot-result");

  function addListItem(container, text) {
    const li = document.createElement("li");
    li.textContent = text;
    container.appendChild(li);
  }

  async function ask(question) {
    const trimmed = (question || "").trim();
    if (!trimmed) {
      return;
    }
    input.value = trimmed;
    askButton.disabled = true;
    statusEl.textContent = "Thinking\u2026 (gathering evidence and reasoning)";
    resultEl.hidden = true;

    try {
      const response = await fetch("/api/copilot/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error((data.detail && data.detail.message) || `HTTP ${response.status}`);
      }
      renderAnswer(data);
    } catch (err) {
      statusEl.textContent = `Request failed: ${err.message}`;
    } finally {
      askButton.disabled = false;
    }
  }

  function renderAnswer(data) {
    const meta = document.getElementById("copilot-meta");
    const answer = document.getElementById("copilot-answer");
    const evidenceUl = document.getElementById("copilot-evidence");
    const assumptionsUl = document.getElementById("copilot-assumptions");

    const aiLabel = data.ai_status === "AVAILABLE"
      ? "Gemini grounded answer"
      : data.ai_status === "NOT_CONFIGURED" || data.ai_status === "UNAVAILABLE"
        ? "Gemini unavailable \u00b7 deterministic summary"
        : "No AI needed";
    const groundedLabel = data.grounded ? "grounded in evidence" : "engine-only";
    meta.textContent =
      `Intent: ${data.intent} \u00b7 Data as of: ${data.analysis_date || "n/a"} ` +
      `\u00b7 Status: ${data.data_status} \u00b7 ${aiLabel} (${groundedLabel})`;

    answer.textContent = data.answer || "";
    answer.classList.toggle("copilot-unavailable", data.ai_status !== "AVAILABLE");

    evidenceUl.innerHTML = "";
    for (const record of data.evidence || []) {
      addListItem(
        evidenceUl,
        `${record.type}${record.store_name ? " \u00b7 " + record.store_name : ""}` +
          `${record.product_name ? " \u00b7 " + record.product_name : ""}` +
          `${record.metric ? " \u00b7 " + record.metric + " = " + record.value : ""}` +
          `${record.threshold ? " \u00b7 threshold " + record.threshold : ""}`,
      );
    }
    if (!data.evidence || data.evidence.length === 0) {
      addListItem(evidenceUl, "No matching evidence in the retail data.");
    }

    assumptionsUl.innerHTML = "";
    for (const assumption of data.assumptions || []) {
      addListItem(assumptionsUl, assumption);
    }

    statusEl.textContent =
      data.error && data.error.message
        ? `Gemini status: ${data.ai_status} (${data.error.message})`
        : `Gemini status: ${data.ai_status}`;
    resultEl.hidden = false;
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    ask(input.value);
  });

  document.getElementById("copilot-suggestions").addEventListener("click", (event) => {
    const chip = event.target.closest(".suggestion-chip");
    if (chip) {
      ask(chip.dataset.question);
    }
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

refreshEngineStatus();
refreshDataStatus();
refreshAnalyticsStatus();
refreshCopilot();