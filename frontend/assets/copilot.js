"use strict";

// Copilot: hero question input + structured, evidence-first answer rendering.
// All Gemini output is treated as untrusted text and rendered via textContent.
// No innerHTML is used with dynamic content anywhere in this module.

const COPILOT_SKIP_EVIDENCE_KEYS = new Set([
  "type",
  "category",
  "severity",
  "store_id",
  "product_id",
  "analysis_date",
  "data_status",
  "explanation",
  "threshold",
  "metric",
  "value",
]);

function addListItem(container, text) {
  const li = document.createElement("li");
  li.textContent = text;
  container.appendChild(li);
}

function pillElement(label, className) {
  const pill = document.createElement("span");
  pill.className = `pill ${className}`;
  pill.textContent = label;
  return pill;
}

function severityBadge(value) {
  const meta = {
    CRITICAL: { label: "Critical", className: "sev-critical", dot: "dot-red" },
    HIGH: { label: "High", className: "sev-high", dot: "dot-orange" },
    MEDIUM: { label: "Medium", className: "sev-medium", dot: "dot-amber" },
    LOW: { label: "Low", className: "sev-low", dot: "dot-gray" },
    NORMAL: { label: "Normal", className: "sev-ok", dot: "dot-green" },
  }[String(value == null ? "" : value).toUpperCase()];
  if (!meta) {
    return pillElement(String(value == null ? "" : value), "sev-neutral");
  }
  const badge = document.createElement("span");
  badge.className = `sev-pill ${meta.className}`;
  const dot = document.createElement("i");
  dot.className = `dot ${meta.dot}`;
  dot.setAttribute("aria-hidden", "true");
  badge.appendChild(dot);
  badge.appendChild(document.createTextNode(meta.label));
  return badge;
}

function evidenceValueLabel(key, recordValue) {
  if (recordValue === null || recordValue === undefined || recordValue === "") {
    return "\u2014";
  }
  const lower = String(key).toLowerCase();
  if (typeof recordValue === "number") {
    if (lower.includes("date")) {
      return String(recordValue);
    }
    if (lower.includes("revenue")) {
      return formatMoney(recordValue);
    }
    if (lower === "change_pct" || lower.includes("change") && lower.includes("pct")) {
      return `${Number(recordValue.toFixed ? recordValue.toFixed(1) : recordValue)}%`;
    }
    if (lower.includes("average_daily")) {
      return `${Number(recordValue.toFixed ? recordValue.toFixed(2) : recordValue)}/day`;
    }
    if (lower.includes("days") || lower.includes("stock_cover") || lower.includes("daily_sales")) {
      return `${Number(recordValue.toFixed ? recordValue.toFixed(1) : recordValue)} days`;
    }
    return formatNumber(recordValue);
  }
  if (typeof recordValue === "boolean") {
    return recordValue ? "Yes" : "No";
  }
  if (String(recordValue).match(/^\d{4}-\d{2}-\d{2}$/)) {
    return formatDateLabel(String(recordValue));
  }
  return String(recordValue);
}

function evidenceCard(record) {
  const card = document.createElement("article");
  card.className = "evidence-card";

  const head = document.createElement("div");
  head.className = "evidence-head";
  head.appendChild(pillElement(record.type || "EVIDENCE", "type-pill"));
  if (record.category) {
    head.appendChild(pillElement(record.category, "category-pill"));
  }
  if (record.severity) {
    head.appendChild(severityBadge(record.severity));
  }
  card.appendChild(head);

  const title = document.createElement("div");
  title.className = "evidence-title";
  const titleParts = [];
  if (record.product_name) {
    titleParts.push(record.product_name);
  }
  if (record.store_name) {
    titleParts.push(record.store_name);
  }
  title.textContent = titleParts.join(" \u00b7 ") || "Store / product";
  card.appendChild(title);

  const grid = document.createElement("dl");
  grid.className = "evidence-grid";

  function addRow(label, valueText) {
    if (valueText === null || valueText === undefined || valueText === "\u2014") {
      return;
    }
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = valueText;
    grid.appendChild(dt);
    grid.appendChild(dd);
  }

  if (record.metric && record.value !== undefined && record.value !== null) {
    const metricLabel = prettyKey(record.metric);
    addRow(metricLabel, evidenceValueLabel(record.metric, record.value));
  }
  if (record.threshold) {
    addRow("Threshold", String(record.threshold));
  }

  for (const [key, value] of Object.entries(record)) {
    if (COPILOT_SKIP_EVIDENCE_KEYS.has(key)) {
      continue;
    }
    addRow(prettyKey(key), evidenceValueLabel(key, value));
  }

  card.appendChild(grid);
  return card;
}

function initCopilot() {
  const form = document.getElementById("copilot-form");
  const input = document.getElementById("copilot-question");
  const askButton = document.getElementById("copilot-ask");
  const statusEl = document.getElementById("copilot-status");
  const resultEl = document.getElementById("copilot-result");
  const answer = document.getElementById("copilot-answer");
  const groundedPill = document.getElementById("copilot-grounded");
  const evidenceBox = document.getElementById("copilot-evidence");
  const assumptionsList = document.getElementById("copilot-assumptions");
  const dataStatusEl = document.getElementById("copilot-data-status");
  const aiStatusEl = document.getElementById("copilot-ai-status");

  function renderDataStatus(data) {
    const status = data.data_status || "UNSUPPORTED";
    const config = {
      SUFFICIENT: ["SUFFICIENT", "Sufficient evidence in the retail data.", "data-ok"],
      INSUFFICIENT_DATA: ["INSUFFICIENT DATA", "Not enough retail data to determine this answer.", "data-warn"],
      UNSUPPORTED: ["UNSUPPORTED", "Question is outside the available retail data.", "data-neutral"],
    }[status] || [status, "", "data-neutral"];

    clearNode(dataStatusEl);
    dataStatusEl.appendChild(pillElement(config[0], config[2]));
    const note = document.createElement("span");
    note.className = "status-note";
    note.textContent = config[1];
    dataStatusEl.appendChild(note);
  }

  function renderAiStatus(data) {
    const ai = data.ai_status;
    const config = {
      AVAILABLE: ["GEMINI ANSWER", "Answered by Gemini, grounded in engine evidence.", "data-ok"],
      NOT_CONFIGURED: ["DETERMINISTIC ENGINE", "Gemini is not configured; the deterministic engine answered.", "data-neutral"],
      UNAVAILABLE: ["DETERMINISTIC ENGINE", `Gemini unavailable (${data.error && data.error.message ? data.error.message : "temporary issue"}); the deterministic engine answered.`, "data-warn"],
      SKIPPED: ["ENGINE ANSWER", "No AI needed; the deterministic engine answered with the available data.", "data-neutral"],
    }[ai] || [ai, "", "data-neutral"];

    clearNode(aiStatusEl);
    aiStatusEl.appendChild(pillElement(config[0], config[2]));
    const note = document.createElement("span");
    note.className = "status-note";
    note.textContent = config[1];
    aiStatusEl.appendChild(note);
  }

  function renderAnswer(data) {
    answer.textContent = data.answer;
    if (!data.answer) {
      answer.textContent = "\u2014";
    }
    answer.classList.toggle("copilot-unavailable", data.ai_status !== "AVAILABLE");

    const grounded = Boolean(data.grounded) && (data.evidence || []).length > 0;
    groundedPill.hidden = !grounded;
    if (grounded) {
      groundedPill.setAttribute("aria-label", "This answer is grounded in the retail evidence shown below.");
    }

    clearNode(evidenceBox);
    for (const record of data.evidence || []) {
      evidenceBox.appendChild(evidenceCard(record));
    }
    if (!data.evidence || data.evidence.length === 0) {
      evidenceBox.appendChild(
        Object.assign(document.createElement("p"), { className: "state-note", textContent: "No matching evidence in the retail data." }),
      );
    }

    clearNode(assumptionsList);
    for (const assumption of data.assumptions || []) {
      addListItem(assumptionsList, assumption);
    }

    renderDataStatus(data);
    renderAiStatus(data);
    resultEl.hidden = false;
  }

  async function ask(question) {
    const trimmed = (question || "").trim();
    if (!trimmed) {
      return;
    }
    input.value = trimmed;
    askButton.disabled = true;
    statusEl.textContent = "Gathering evidence and reasoning\u2026";
    resultEl.hidden = true;

    try {
      const data = await postJSON("/api/copilot/query", { question: trimmed });
      renderAnswer(data);
      statusEl.textContent = "";
    } catch (err) {
      statusEl.textContent = `Unable to reach the copilot: ${err.message}.`;
    } finally {
      askButton.disabled = false;
    }
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