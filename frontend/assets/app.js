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

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

refreshEngineStatus();
refreshDataStatus();