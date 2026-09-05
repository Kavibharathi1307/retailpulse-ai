"use strict";

// Dashboard: loads all dashboard data in parallel from the existing APIs and
// renders KPIs, inventory health, store performance, attention centre and
// product performance. No fake numbers: every value comes from the backend.

const SEVERITY_RANK = { CRITICAL: 4, HIGH: 3, MEDIUM: 2, LOW: 1 };
const TREND_RANK = { UP: 3, STABLE: 2, DOWN: 1 };
const MAX_ATTENTION_VISIBLE = 20;
const MAX_PRODUCTS_VISIBLE = 12;

async function prefer(url) {
  try {
    return await getJSON(url);
  } catch (_) {
    return null;
  }
}

function pillElement(label, className) {
  const pill = document.createElement("span");
  pill.className = `pill ${className}`;
  pill.textContent = label;
  return pill;
}

function trendBadge(value) {
  const config = {
    UP: ["Up", "trend-ok"],
    DOWN: ["Down", "trend-danger"],
    STABLE: ["Stable", "trend-neutral"],
    UNKNOWN: ["Unknown", "trend-neutral"],
  }[String(value == null ? "" : value).toUpperCase()];
  if (!config) {
    return pillElement(String(value == null ? "" : value), "trend-neutral");
  }
  return pillElement(config[0], config[1]);
}

function riskBadgeForProduct(productId, stockoutByProduct) {
  const worst = stockoutByProduct.get(productId) || 0;
  const label = { 4: "Critical", 3: "High", 2: "Medium" }[worst] || "Ok";
  const cls = worst === 4 ? "risk-critical" : worst === 3 ? "risk-high" : worst === 2 ? "risk-medium" : "risk-ok";
  return pillElement(label, cls);
}

function stateNote(text, kind) {
  const note = document.createElement("p");
  note.className = `state-note ${kind || "state-warn"}`;
  note.textContent = text;
  return note;
}

// --- Status pills ---------------------------------------------------------

function renderStatus(health) {
  const backend = document.getElementById("status-backend");
  const gemini = document.getElementById("status-gemini");

  if (health && health.status === "ok") {
    backend.className = "status-pill is-online";
    backend.innerHTML = '<span class="dot dot-green" aria-hidden="true"></span>Backend \u00b7 Online';
  } else {
    backend.className = "status-pill is-offline";
    backend.innerHTML = '<span class="dot dot-red" aria-hidden="true"></span>Backend \u00b7 Offline';
  }

  if (health && health.gemini_configured) {
    gemini.className = "status-pill is-online";
    gemini.innerHTML = '<span class="dot dot-green" aria-hidden="true"></span>Gemini \u00b7 Configured';
  } else {
    gemini.className = "status-pill is-idle";
    gemini.innerHTML = '<span class="dot dot-amber" aria-hidden="true"></span>Gemini \u00b7 Not configured';
  }
}

// --- KPI cards ------------------------------------------------------------

function renderKpis(seriesItems, inventory, stockout, attention, summary) {
  const latestEl = document.getElementById("kpi-latest-sales");
  const latestDateEl = document.getElementById("kpi-latest-sales-date");
  const revenueEl = document.getElementById("kpi-revenue");
  const stockEl = document.getElementById("kpi-stock");
  const riskEl = document.getElementById("kpi-risk");
  const attentionEl = document.getElementById("kpi-attention");
  const noteEl = document.getElementById("kpi-note");

  if (Array.isArray(seriesItems) && seriesItems.length > 0) {
    const days = seriesItems;
    const last = days[days.length - 1];
    latestEl.textContent = formatNumber(last.units);
    latestDateEl.textContent = `Sales on ${formatDateLabel(last.date)}`;
    const totalRevenue = days.reduce((sum, day) => sum + Number(day.revenue), 0);
    revenueEl.textContent = formatMoney(totalRevenue);
  } else {
    latestEl.textContent = "\u2014";
    latestDateEl.textContent = "No sales history available";
    revenueEl.textContent = "\u2014";
  }

  if (inventory && Array.isArray(inventory.items)) {
    const totalStock = inventory.items.reduce((sum, row) => sum + Number(row.current_stock || 0), 0);
    stockEl.textContent = formatNumber(totalStock);
  } else {
    stockEl.textContent = "\u2014";
  }

  if (stockout && Array.isArray(stockout.items)) {
    const risks = stockout.items.filter((row) => row.status === "CRITICAL" || row.status === "HIGH").length;
    riskEl.textContent = formatNumber(risks);
  } else {
    riskEl.textContent = "\u2014";
  }

  if (attention && attention.counts) {
    attentionEl.textContent = formatNumber(attention.counts.total);
  } else {
    attentionEl.textContent = "\u2014";
  }

  if (summary && summary.first_date && summary.last_date) {
    noteEl.textContent =
      `Sales from ${formatDateLabel(summary.first_date)} to ${formatDateLabel(summary.last_date)} \u00b7 ` +
      `${formatNumber(summary.counts.sales)} records \u00b7 ${formatNumber(summary.counts.stores)} stores`;
  } else {
    noteEl.textContent = "Unable to load sales data.";
  }
}

// --- Inventory health -----------------------------------------------------

function renderInventoryHealth(stockout, overstock, slow, inventory) {
  const stockoutEl = document.getElementById("analytics-stockout");
  const overstockEl = document.getElementById("health-overstock");
  const slowEl = document.getElementById("health-slow");
  const flaggedEl = document.getElementById("health-flagged");
  const okEl = document.getElementById("health-ok");

  const risky = new Set();
  let riskCount = 0;
  if (stockout && Array.isArray(stockout.items)) {
    for (const row of stockout.items) {
      if (row.status === "CRITICAL" || row.status === "HIGH") {
        riskCount += 1;
        risky.add(`${row.store_id}:${row.product_id}`);
      }
    }
  }
  let overCount = 0;
  if (overstock && Array.isArray(overstock.items)) {
    for (const row of overstock.items) {
      if (row.status === "OVERSTOCK") {
        overCount += 1;
        risky.add(`${row.store_id}:${row.product_id}`);
      }
    }
  }
  let slowCount = 0;
  if (slow && Array.isArray(slow.items)) {
    for (const row of slow.items) {
      if (row.status === "SLOW_MOVER") {
        slowCount += 1;
        risky.add(`${row.store_id}:${row.product_id}`);
      }
    }
  }
  const totalPositions = inventory && inventory.total ? inventory.total : risky.size;
  const healthy = Math.max(0, totalPositions - risky.size);

  stockoutEl.textContent = formatNumber(riskCount);
  overstockEl.textContent = formatNumber(overCount);
  slowEl.textContent = formatNumber(slowCount);
  flaggedEl.textContent = formatNumber(risky.size);
  okEl.textContent = formatNumber(healthy);

  const bar = document.getElementById("health-bar");
  const riskSeg = bar.querySelector(".health-risk");
  const okSeg = bar.querySelector(".health-ok");
  const flaggedPct = totalPositions > 0 ? (risky.size / totalPositions) * 100 : 0;
  riskSeg.style.width = `${flaggedPct.toFixed(1)}%`;
  okSeg.style.width = `${(100 - flaggedPct).toFixed(1)}%`;
}

// --- Store performance ----------------------------------------------------

function renderStores(stores, stockout) {
  const list = document.getElementById("store-list");
  clearNode(list);

  if (!stores || !Array.isArray(stores.items)) {
    list.appendChild(stateNote("Unable to load store performance."));
    return;
  }
  if (stores.items.length === 0) {
    list.appendChild(stateNote("No store data available."));
    return;
  }

  const riskByStore = new Map();
  if (stockout && Array.isArray(stockout.items)) {
    for (const row of stockout.items) {
      if (row.status === "CRITICAL" || row.status === "HIGH") {
        riskByStore.set(row.store_id, (riskByStore.get(row.store_id) || 0) + 1);
      }
    }
  }

  for (const store of stores.items) {
    const card = document.createElement("article");
    card.className = "store-card";

    const name = document.createElement("h4");
    name.className = "store-name";
    name.textContent = store.store_name;
    card.appendChild(name);

    const meta = document.createElement("div");
    meta.className = "store-meta";
    meta.appendChild(pillElement(formatMoney(store.revenue), "store-revenue"));
    meta.appendChild(trendBadge(store.trend));
    card.appendChild(meta);

    const stats = document.createElement("div");
    stats.className = "store-stats";
    const units = document.createElement("span");
    units.innerHTML = `<b>${formatNumber(store.units_sold)}</b> units`;
    const risk = riskByStore.get(store.store_id) || 0;
    const riskText = document.createElement("span");
    riskText.className = risk > 0 ? "risk-text-danger" : "risk-text-ok";
    riskText.innerHTML = risk > 0 ? `<b>${formatNumber(risk)}</b> stock-out ${risk === 1 ? "flag" : "flags"}` : "No stock-out flags";
    stats.appendChild(units);
    stats.appendChild(riskText);
    card.appendChild(stats);

    list.appendChild(card);
  }
}

// --- Attention centre -----------------------------------------------------

function attentionMeta(item) {
  const parts = [];
  if (item.metric && item.observed_value !== undefined && item.observed_value !== null) {
    const suffix =
      item.metric.includes("days") || item.metric.includes("cover") ? " days" : "";
    parts.push(`${prettyKey(item.metric)}: ${Number(item.observed_value.toFixed ? item.observed_value.toFixed(1) : item.observed_value)}${suffix}`);
  }
  if (item.threshold) {
    parts.push(`Threshold: ${item.threshold}`);
  }
  return parts.join(" \u00b7 ");
}

function attentionItem(item) {
  const node = document.createElement("article");
  node.className = `attention-item attention-${String(item.severity).toLowerCase()}`;

  const card = document.createElement("div");
  card.className = "attention-card";

  const head = document.createElement("div");
  head.className = "attention-head";
  head.appendChild(severityBadge(item.severity));
  head.appendChild(pillElement(item.issue_type || "ISSUE", "issue-pill"));
  card.appendChild(head);

  const title = document.createElement("div");
  title.className = "attention-title";
  title.textContent = [item.product_name, item.store_name].filter(Boolean).join(" \u00b7 ") || "Unknown item";
  card.appendChild(title);

  const meta = document.createElement("p");
  meta.className = "attention-meta";
  meta.textContent = attentionMeta(item);
  card.appendChild(meta);

  if (item.explanation) {
    const explanation = document.createElement("p");
    explanation.className = "attention-explanation";
    explanation.textContent = item.explanation;
    card.appendChild(explanation);
  }

  const details = document.createElement("details");
  details.className = "evidence-details";
  const summary = document.createElement("summary");
  summary.textContent = "View evidence";
  details.appendChild(summary);
  const dl = document.createElement("dl");
  dl.className = "evidence-grid";
  const evidenceMap = item.evidence && typeof item.evidence === "object" ? item.evidence : {};
  for (const [key, value] of Object.entries(evidenceMap)) {
    const dt = document.createElement("dt");
    dt.textContent = prettyKey(key);
    const dd = document.createElement("dd");
    dd.textContent = evidenceValueLabel(key, value);
    dl.appendChild(dt);
    dl.appendChild(dd);
  }
  if (!dl.childElementCount) {
    const emptyNote = document.createElement("dd");
    emptyNote.textContent = "No numeric evidence available.";
    dl.appendChild(emptyNote);
  }
  details.appendChild(dl);
  card.appendChild(details);

  node.appendChild(card);
  return node;
}

const severityBadge = (value) => {
  const meta = {
    CRITICAL: { label: "Critical", className: "sev-critical", dot: "dot-red" },
    HIGH: { label: "High", className: "sev-high", dot: "dot-orange" },
    MEDIUM: { label: "Medium", className: "sev-medium", dot: "dot-amber" },
    LOW: { label: "Low", className: "sev-low", dot: "dot-gray" },
  }[String(value == null ? "" : value).toUpperCase()];
  const badge = document.createElement("span");
  badge.className = `sev-pill ${meta ? meta.className : "sev-neutral"}`;
  const dot = document.createElement("i");
  dot.className = `dot ${meta ? meta.dot : "dot-gray"}`;
  dot.setAttribute("aria-hidden", "true");
  badge.appendChild(dot);
  badge.appendChild(document.createTextNode(meta ? meta.label : String(value == null ? "" : value)));
  return badge;
};

function evidenceValueLabel(key, value) {
  if (value === null || value === undefined || value === "") {
    return "\u2014";
  }
  const lower = String(key).toLowerCase();
  if (typeof value === "number") {
    if (lower.includes("revenue")) {
      return formatMoney(value);
    }
    if (lower.includes("average_daily")) {
      return `${Number(value.toFixed ? value.toFixed(2) : value)}/day`;
    }
    if (lower.includes("days") || lower.includes("cover")) {
      return `${Number(value.toFixed ? value.toFixed(1) : value)} days`;
    }
    return formatNumber(value);
  }
  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  return String(value);
}

function renderAttention(attention) {
  const list = document.getElementById("attention-list");
  const countEl = document.getElementById("attention-count");
  if (!attention || !Array.isArray(attention.items)) {
    clearNode(list);
    list.appendChild(stateNote("Unable to load attention items."));
    countEl.textContent = "0";
    renderAttentionFilter(list, attention);
    return;
  }
  countEl.textContent = formatNumber(attention.items.length);
  renderAttentionFilter(list, attention);
}

let currentAttention = [];
let attentionSeverityFilter = "all";

function renderAttentionFilter(list, attention) {
  currentAttention = attention && Array.isArray(attention.items) ? attention.items : [];
  applyAttentionFilter();
}

function applyAttentionFilter() {
  const list = document.getElementById("attention-list");
  clearNode(list);
  const filter = attentionSeverityFilter;
  const items = filter === "all" ? currentAttention : currentAttention.filter((i) => i.severity === filter);
  if (items.length === 0) {
    list.appendChild(stateNote(filter === "all" ? "No items need attention." : "No items at this severity."));
    return;
  }
  const visible = items.slice(0, MAX_ATTENTION_VISIBLE);
  for (const item of visible) {
    list.appendChild(attentionItem(item));
  }
  if (items.length > MAX_ATTENTION_VISIBLE) {
    list.appendChild(stateNote(`Showing ${MAX_ATTENTION_VISIBLE} of ${formatNumber(items.length)} items.`));
  }
}

// --- Recommended actions --------------------------------------------------

const MAX_RECOMMENDATIONS_VISIBLE = 12;

function recommendationTypeLabel(type) {
  return {
    REPLENISH: "Replenish",
    REDUCE_INVENTORY: "Reduce inventory",
    REVIEW_SLOW_MOVER: "Review slow mover",
    INVESTIGATE_SALES_DROP: "Investigate drop",
    MONITOR_DEMAND: "Monitor demand",
  }[type] || prettyKey(type);
}

function renderRecommendations(recommendations) {
  const list = document.getElementById("recommendations-list");
  const countEl = document.getElementById("recommendations-count");
  const noteEl = document.getElementById("recommendations-note");
  clearNode(list);

  if (!recommendations || !Array.isArray(recommendations.items)) {
    list.appendChild(stateNote("Unable to load recommended actions."));
    countEl.textContent = "0";
    if (noteEl) {
      noteEl.textContent = "";
    }
    return;
  }
  const items = recommendations.items;
  countEl.textContent = formatNumber(recommendations.total);
  if (noteEl) {
    const analysisDate = recommendations.analysis_date ? formatDateLabel(recommendations.analysis_date) : "";
    noteEl.textContent = analysisDate ? `Deterministic recommended actions as of ${analysisDate}.` : "";
  }
  if (items.length === 0) {
    list.appendChild(stateNote("No recommendations to show for the current filters."));
    return;
  }

  const visible = items.slice(0, MAX_RECOMMENDATIONS_VISIBLE);
  for (const rec of visible) {
    const node = document.createElement("article");
    node.className = `recommendation-item recommendation-${String(rec.priority).toLowerCase()}`;
    const card = document.createElement("div");
    card.className = "recommendation-card";

    const head = document.createElement("div");
    head.className = "recommendation-head";
    head.appendChild(severityBadge(rec.priority));
    head.appendChild(pillElement(recommendationTypeLabel(rec.type), "issue-pill"));
    if (rec.data_status) {
      head.appendChild(pillElement(prettyKey(rec.data_status), "type-pill"));
    }
    card.appendChild(head);

    const title = document.createElement("div");
    title.className = "recommendation-title";
    title.textContent = [rec.product_name, rec.store_name].filter(Boolean).join(" \u00b7 ") || "Unknown item";
    card.appendChild(title);

    if (rec.reason) {
      const reason = document.createElement("p");
      reason.className = "recommendation-reason";
      reason.textContent = rec.reason;
      card.appendChild(reason);
    }

    if (rec.action) {
      const action = document.createElement("p");
      action.className = "recommendation-action";
      action.textContent = rec.action;
      card.appendChild(action);
    }

    const details = document.createElement("details");
    details.className = "evidence-details";
    const summary = document.createElement("summary");
    summary.textContent = "View evidence";
    details.appendChild(summary);
    const dl = document.createElement("dl");
    dl.className = "evidence-grid";
    const evidenceMap = rec.evidence && typeof rec.evidence === "object" ? rec.evidence : {};
    for (const [key, value] of Object.entries(evidenceMap)) {
      const dt = document.createElement("dt");
      dt.textContent = prettyKey(key);
      const dd = document.createElement("dd");
      dd.textContent = evidenceValueLabel(key, value);
      dl.appendChild(dt);
      dl.appendChild(dd);
    }
    if (!dl.childElementCount) {
      const emptyNote = document.createElement("dd");
      emptyNote.textContent = "No numeric evidence available.";
      dl.appendChild(emptyNote);
    }
    details.appendChild(dl);
    card.appendChild(details);

    node.appendChild(card);
    list.appendChild(node);
  }
  if (items.length > MAX_RECOMMENDATIONS_VISIBLE) {
    list.appendChild(stateNote(`Showing ${MAX_RECOMMENDATIONS_VISIBLE} of ${formatNumber(items.length)} recommendations.`));
  }
}

// --- Product performance --------------------------------------------------

let productRows = [];
const productState = { key: "revenue", dir: "desc", category: "all" };

function productSortGetter(row, key) {
  if (key === "trend") {
    return TREND_RANK[row.trend] || 0;
  }
  if (key === "severity") {
    return row.severityRank || 0;
  }
  if (key === "stock") {
    return row.stock || 0;
  }
  if (key === "product_name") {
    return String(row.product_name || "").toLowerCase();
  }
  return Number(row[key]) || 0;
}

function renderProductTable() {
  const tbody = document.getElementById("product-tbody");
  const note = document.getElementById("product-note");
  clearNode(tbody);

  let rows = productRows;
  if (productState.category !== "all") {
    rows = rows.filter((row) => row.category === productState.category);
  }
  const dir = productState.dir === "asc" ? 1 : -1;
  rows = [...rows].sort((a, b) => {
    const av = productSortGetter(a, productState.key);
    const bv = productSortGetter(b, productState.key);
    if (av === bv) {
      return 0;
    }
    return av < bv ? -1 * dir : dir;
  });

  if (rows.length === 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 7;
    td.textContent = "No products match this filter.";
    td.className = "state-note";
    tr.appendChild(td);
    tbody.appendChild(tr);
    note.textContent = "";
    return;
  }

  const visible = rows.slice(0, MAX_PRODUCTS_VISIBLE);
  for (const row of visible) {
    const tr = document.createElement("tr");
    tr.appendChild(Object.assign(document.createElement("td"), { textContent: row.product_name, className: "cell-strong" }));
    tr.appendChild(Object.assign(document.createElement("td"), { textContent: row.category }));
    tr.appendChild(Object.assign(document.createElement("td"), { textContent: formatNumber(row.units_sold) }));
    tr.appendChild(Object.assign(document.createElement("td"), { textContent: formatMoney(row.revenue) }));
    const trendCell = document.createElement("td");
    trendCell.appendChild(trendBadge(row.trend));
    tr.appendChild(trendCell);
    tr.appendChild(Object.assign(document.createElement("td"), { textContent: formatNumber(row.stock) }));
    const riskCell = document.createElement("td");
    riskCell.appendChild(riskBadgeForProduct(row.product_id, productSeverityMap));
    tr.appendChild(riskCell);
    tbody.appendChild(tr);
  }

  const filteredTotal = productState.category === "all" ? productRows.length : rows.length;
  note.textContent =
    `Showing ${Math.min(visible.length, filteredTotal)} of ${formatNumber(filteredTotal)} products ` +
    `by ${prettyKey(productState.key)} (${productState.dir === "desc" ? "high to low" : "low to high"}), ` +
    `${formatDateLabel(productRows[0] ? productRows[0].analysis_date : "")} period.`;
}

let productSeverityMap = new Map();

function renderProducts(products, inventory, stockout) {
  const tbody = document.getElementById("product-tbody");
  const categoryFilter = document.getElementById("product-category-filter");

  if (!products || !Array.isArray(products.items)) {
    clearNode(tbody);
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 7;
    td.textContent = "Unable to load product performance.";
    td.className = "state-note";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  const stockByProduct = new Map();
  if (inventory && Array.isArray(inventory.items)) {
    for (const row of inventory.items) {
      stockByProduct.set(row.product_id, (stockByProduct.get(row.product_id) || 0) + Number(row.current_stock || 0));
    }
  }

  productSeverityMap = new Map();
  if (stockout && Array.isArray(stockout.items)) {
    for (const row of stockout.items) {
      const rank = SEVERITY_RANK[row.status] || 0;
      const current = productSeverityMap.get(row.product_id) || 0;
      if (rank > current) {
        productSeverityMap.set(row.product_id, rank);
      }
    }
  }

  const categories = new Set();
  productRows = products.items.map((row) => {
    categories.add(row.category);
    return {
      product_id: row.product_id,
      product_name: row.product_name,
      category: row.category,
      units_sold: Number(row.units_sold) || 0,
      revenue: Number(row.revenue) || 0,
      trend: row.trend,
      stock: stockByProduct.get(row.product_id) || 0,
      severityRank: productSeverityMap.get(row.product_id) || 0,
      analysis_date: row.analysis_date,
    };
  });

  clearNode(categoryFilter);
  const allOption = document.createElement("option");
  allOption.value = "all";
  allOption.textContent = "All categories";
  categoryFilter.appendChild(allOption);
  for (const category of [...categories].sort()) {
    const option = document.createElement("option");
    option.value = category;
    option.textContent = category;
    categoryFilter.appendChild(option);
  }

  renderProductTable();
}

// --- Controls -------------------------------------------------------------

function wireProductControls() {
  const categoryFilter = document.getElementById("product-category-filter");
  categoryFilter.addEventListener("change", () => {
    productState.category = categoryFilter.value;
    renderProductTable();
  });

  document.querySelectorAll("#product-table .sort-btn").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.key;
      if (productState.key === key) {
        productState.dir = productState.dir === "desc" ? "asc" : "desc";
      } else {
        productState.key = key;
        productState.dir = key === "product_name" ? "asc" : "desc";
      }
      renderProductTable();
    });
  });
}

function wireTrendControls() {
  document.querySelectorAll(".trend-panel .segmented").forEach((group) => {
    group.addEventListener("click", (event) => {
      const button = event.target.closest(".seg-btn");
      if (!button) {
        return;
      }
      group.querySelectorAll(".seg-btn").forEach((b) => b.classList.remove("is-active"));
      button.classList.add("is-active");
      const metric = button.dataset.metric;
      const range = button.dataset.range;
      updateSalesChart(metric, range);
    });
  });
}

function wireAttentionControls() {
  document.querySelectorAll(".attention-panel .filter-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      document.querySelectorAll(".attention-panel .filter-chip").forEach((c) => c.classList.remove("is-active"));
      chip.classList.add("is-active");
      attentionSeverityFilter = chip.dataset.sev;
      applyAttentionFilter();
    });
  });
}

// --- Demand outlook (Milestone 7) ------------------------------------------

let forecastHorizon = 7;
let lastSeriesItems = [];

function inventoryOutlookBadge(value) {
  const label = {
    AT_RISK: "At risk",
    WATCH: "Watch",
    SUFFICIENT: "Sufficient",
    INSUFFICIENT_DATA: "Insufficient data",
  }[value] || String(value == null ? "" : value);
  const cls = {
    AT_RISK: "risk-critical",
    WATCH: "risk-medium",
    SUFFICIENT: "risk-ok",
    INSUFFICIENT_DATA: "trend-neutral",
  }[value] || "trend-neutral";
  return pillElement(label, cls);
}

function renderOutlookStats(summary) {
  const ids = ["outlook-rising", "outlook-falling", "outlook-at-risk", "outlook-watch", "outlook-thin"];
  const counts = summary && summary.counts ? summary.counts : null;
  if (counts) {
    const byTrend = counts.by_trend || {};
    const byOutlook = counts.by_inventory_outlook || {};
    const byStatus = counts.by_forecast_status || {};
    const values = [
      byTrend.UP || 0,
      byTrend.DOWN || 0,
      byOutlook.AT_RISK || 0,
      byOutlook.WATCH || 0,
      byStatus.INSUFFICIENT_DATA || 0,
    ];
    ids.forEach((id, index) => {
      document.getElementById(id).textContent = formatNumber(values[index]);
    });
  } else {
    ids.forEach((id) => {
      document.getElementById(id).textContent = "\u2014";
    });
  }

  const note = document.getElementById("outlook-note");
  if (summary && summary.analysis_date) {
    note.textContent =
      `Deterministic demand outlook as of ${formatDateLabel(summary.analysis_date)} \u00b7 ` +
      `${summary.method || "recent-demand rate over the forecast horizon"}.`;
  } else {
    note.textContent = "Demand outlook unavailable.";
  }

  const context = document.getElementById("outlook-chart-context");
  if (summary && summary.expected_horizon_units != null && summary.horizon_days) {
    context.textContent =
      `Expected ~${formatNumber(summary.expected_horizon_units)} units over ${summary.horizon_days} days`;
  } else {
    context.textContent = "";
  }

  document.getElementById("outlook-count").textContent =
    counts && counts.total != null ? formatNumber(counts.total) : "0";
}

function renderOutlookTable(items) {
  const tbody = document.getElementById("outlook-tbody");
  const foot = document.getElementById("outlook-foot");
  clearNode(tbody);

  if (!Array.isArray(items) || items.length === 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 7;
    td.className = "state-note";
    td.textContent = "No demand outlook available for the current dataset.";
    tr.appendChild(td);
    tbody.appendChild(tr);
    foot.textContent = "";
    return;
  }

  const MAX_OUTLOOK_VISIBLE = 20;
  const visible = items.slice(0, MAX_OUTLOOK_VISIBLE);
  for (const row of visible) {
    const tr = document.createElement("tr");
    tr.appendChild(Object.assign(document.createElement("td"), { textContent: row.product_name, className: "cell-strong" }));
    tr.appendChild(Object.assign(document.createElement("td"), { textContent: row.store_name }));
    tr.appendChild(Object.assign(document.createElement("td"), { textContent: formatNumber(row.current_stock) }));
    tr.appendChild(Object.assign(document.createElement("td"), {
      textContent: row.recent_daily_demand == null ? "\u2014" : formatNumber(row.recent_daily_demand),
    }));
    tr.appendChild(Object.assign(document.createElement("td"), {
      textContent: row.forecast_units == null ? "\u2014" : formatNumber(row.forecast_units),
    }));
    const trendCell = document.createElement("td");
    trendCell.appendChild(trendBadge(row.trend));
    tr.appendChild(trendCell);
    const outlookCell = document.createElement("td");
    outlookCell.appendChild(inventoryOutlookBadge(row.inventory_outlook));
    tr.appendChild(outlookCell);
    tbody.appendChild(tr);
  }

  foot.textContent =
    items.length > MAX_OUTLOOK_VISIBLE
      ? `Showing ${MAX_OUTLOOK_VISIBLE} of ${formatNumber(items.length)} demand outlook records.`
      : "";
}

async function loadOutlook(seriesItems) {
  lastSeriesItems = Array.isArray(seriesItems) ? seriesItems : [];
  const horizon = forecastHorizon;
  const [summary, forecast] = await Promise.all([
    prefer(`/api/analytics/forecast-summary?horizon_days=${horizon}`),
    prefer(`/api/analytics/forecast?horizon_days=${horizon}&limit=50`),
  ]);
  renderOutlookStats(summary);
  renderOutlookTable(forecast && Array.isArray(forecast.items) ? forecast.items : []);
  setOutlookData(lastSeriesItems.slice(-28), summary || {});
}

function wireOutlookControls() {
  document.querySelectorAll(".outlook-section .segmented").forEach((group) => {
    group.addEventListener("click", (event) => {
      const button = event.target.closest(".seg-btn");
      if (!button) {
        return;
      }
      group.querySelectorAll(".seg-btn").forEach((b) => b.classList.remove("is-active"));
      button.classList.add("is-active");
      forecastHorizon = Number(button.dataset.horizon) || 7;
      loadOutlook(lastSeriesItems);
    });
  });
}

// --- Boot -----------------------------------------------------------------

function renderDatasetStrip(summary, attention, series) {
  const ids = ["data-stores", "data-products", "data-sales", "data-inventory"];
  const keys = ["stores", "products", "sales", "inventory"];
  ids.forEach((id, index) => {
    const elNode = document.getElementById(id);
    const value = summary && summary.counts ? summary.counts[keys[index]] : null;
    elNode.textContent = value === null || value === undefined ? "\u2014" : formatNumber(value);
  });
  const analysisDate =
    (attention && attention.analysis_date) ||
    (series && series.end_date) ||
    (summary && summary.last_date) ||
    null;
  document.getElementById("global-analysis-date").textContent = analysisDate ? formatDateLabel(analysisDate) : "\u2014";
}

async function bootDashboard() {
  renderStatusPlaceholders();

  const results = await Promise.all([
    prefer("/api/health"),
    prefer("/api/data/summary"),
    prefer("/api/data/sales-series"),
    prefer("/api/inventory?limit=1000"),
    prefer("/api/analytics/stock-out-risks?limit=1000"),
    prefer("/api/analytics/overstock?limit=1000"),
    prefer("/api/analytics/slow-movers?limit=1000"),
    prefer("/api/analytics/attention-summary?limit=1000"),
    prefer("/api/analytics/product-performance?limit=1000"),
    prefer("/api/analytics/store-performance?limit=1000"),
    prefer("/api/analytics/recommendations?limit=20"),
  ]);

  const [health, summary, series, inventory, stockout, overstock, slow, attention, products, stores, recommendations] = results;

  const seriesItems = Array.isArray(series && series.items)
    ? series.items.map((day) => ({
        date: day.sale_date,
        units: Number(day.units) || 0,
        revenue: Number(day.revenue) || 0,
      }))
    : [];

  renderStatus(health);
  renderKpis(seriesItems, inventory, stockout, attention, summary);
  renderInventoryHealth(stockout, overstock, slow, inventory);
  renderStores(stores, stockout);
  renderAttention(attention);
  renderProducts(products, inventory, stockout);
  renderRecommendations(recommendations);
  renderDatasetStrip(summary, attention, series);
  loadOutlook(seriesItems);

  setSalesSeries(seriesItems.length > 0 ? seriesItems : []);

  const marketNote = document.getElementById("analytics-range");
  if (attention && attention.analysis_date) {
    marketNote.textContent = `Deterministic insights computed as of ${formatDateLabel(attention.analysis_date)} \u00b7 no AI used for analytics`;
  } else {
    marketNote.textContent = "Analytics engine unreachable.";
  }
}

function renderStatusPlaceholders() {
  const backend = document.getElementById("status-backend");
  const gemini = document.getElementById("status-gemini");
  backend.innerHTML = '<span class="dot dot-neutral" aria-hidden="true"></span>Backend \u00b7 Checking&hellip;';
  gemini.innerHTML = '<span class="dot dot-neutral" aria-hidden="true"></span>Gemini \u00b7 Checking&hellip;';
}