"use strict";

// Shared formatting + DOM helpers. Everything in here is small and dependency-free.

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatNumber(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) {
    return "\u2014";
  }
  return n.toLocaleString("en-US");
}

function formatMoney(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) {
    return "\u2014";
  }
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

function formatNumberCompact(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) {
    return "\u2014";
  }
  if (Math.abs(n) >= 1e6) {
    return (n / 1e6).toLocaleString("en-US", { maximumFractionDigits: 1 }) + "M";
  }
  if (Math.abs(n) >= 1e3) {
    return (n / 1e3).toLocaleString("en-US", { maximumFractionDigits: 1 }) + "k";
  }
  return n.toLocaleString("en-US");
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function formatDateLabel(iso) {
  if (!iso) {
    return "\u2014";
  }
  const parts = String(iso).split("-");
  if (parts.length !== 3) {
    return iso;
  }
  const month = Number(parts[1]);
  const day = Number(parts[2]);
  if (!(month >= 1 && month <= 12) || !(day >= 1 && day <= 31)) {
    return iso;
  }
  return `${day} ${MONTHS[month - 1]} ${parts[0]}`;
}

function formatShortDate(iso) {
  if (!iso) {
    return "\u2014";
  }
  const parts = String(iso).split("-");
  if (parts.length !== 3) {
    return iso;
  }
  const month = Number(parts[1]);
  const day = Number(parts[2]);
  if (!(month >= 1 && month <= 12) || !(day >= 1 && day <= 31)) {
    return iso;
  }
  return `${day} ${MONTHS[month - 1]}`;
}

function prettyKey(key) {
  return String(key)
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

// Severity / trend metadata used to render badges with text labels + colour dots
// (never colour alone, for accessibility).
const SEVERITY_META = {
  CRITICAL: { label: "Critical", className: "sev-critical", dot: "dot-red" },
  HIGH: { label: "High", className: "sev-high", dot: "dot-orange" },
  MEDIUM: { label: "Medium", className: "sev-medium", dot: "dot-amber" },
  LOW: { label: "Low", className: "sev-low", dot: "dot-gray" },
  NORMAL: { label: "Normal", className: "sev-ok", dot: "dot-green" },
  UP: { label: "Up", className: "sev-ok", dot: "dot-green" },
  DOWN: { label: "Down", className: "sev-danger", dot: "dot-red" },
  STABLE: { label: "Stable", className: "sev-ok", dot: "dot-green" },
  OVERSTOCK: { label: "Overstock", className: "sev-over", dot: "dot-overstock" },
  SLOW_MOVER: { label: "Slow mover", className: "sev-medium", dot: "dot-amber" },
};

function severityPill(value) {
  const key = String(value == null ? "" : value).toUpperCase();
  const meta = SEVERITY_META[key] || {
    label: String(value == null ? "" : value),
    className: "sev-neutral",
    dot: "dot-gray",
  };
  return `<span class="sev-pill ${meta.className}"><i class="dot ${meta.dot}" aria-hidden="true"></i>${escapeHtml(meta.label)}</span>`;
}

function el(tagName, className, text) {
  const node = document.createElement(tagName);
  if (className) {
    node.className = className;
  }
  if (text !== undefined) {
    node.textContent = text;
  }
  return node;
}

function clearNode(node) {
  while (node.firstChild) {
    node.removeChild(node.firstChild);
  }
}