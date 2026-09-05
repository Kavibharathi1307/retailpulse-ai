"use strict";

// Lightweight, dependency-free SVG sales trend chart. No CDN, no build step,
// fully offline. The chart scales via viewBox; axis + tooltip text is drawn
// inside the SVG so it always stays legible.

const CHART_LAYOUT = { width: 840, height: 300, padL: 78, padR: 18, padT: 20, padB: 40 };
const SVG_NS = "http://www.w3.org/2000/svg";

let salesSeries = [];
let chartMetric = "revenue";
let chartRange = "all";
let svgElement = null;

function svgNode(name, attrs) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attrs || {})) {
    node.setAttribute(key, String(value));
  }
  return node;
}

function metricValue(point) {
  return Number(chartMetric === "units" ? point.units : point.revenue);
}

function yLabel(value) {
  if (chartMetric === "units") {
    return formatNumberCompact(value);
  }
  return "$" + formatNumberCompact(value);
}

function targetPoints() {
  let points = salesSeries;
  if (chartRange === "30") {
    points = points.slice(-30);
  } else if (chartRange === "90") {
    points = points.slice(-90);
  }
  return points;
}

function renderChart() {
  if (!svgElement) {
    return;
  }
  clearNode(svgElement);

  const { width, height, padL, padR, padT, padB } = CHART_LAYOUT;
  const points = targetPoints();

  if (points.length < 2) {
    const emptyText = svgNode("text", {
      x: width / 2,
      y: height / 2,
      "text-anchor": "middle",
    });
    emptyText.classList.add("chart-empty");
    emptyText.textContent = "Not enough sales history to chart.";
    svgElement.appendChild(emptyText);
    return;
  }

  const values = points.map(metricValue);
  const maxValue = Math.max(...values);
  const minValue = Math.min(...values);
  const span = maxValue - minValue || 1;
  const innerW = width - padL - padR;
  const innerH = height - padT - padB;

  const xAt = (index) => padL + (index / (points.length - 1)) * innerW;
  const yAt = (value) => padT + (1 - (value - minValue) / span) * innerH;

  // Gridlines + y-axis labels.
  const grid = svgNode("g", { class: "chart-grid" });
  const gridCount = 4;
  for (let i = 0; i <= gridCount; i += 1) {
    const value = minValue + (span * i) / gridCount;
    const y = yAt(value);
    grid.appendChild(svgNode("line", { x1: padL, x2: width - padR, y1: y, y2: y }));
    const label = svgNode("text", { x: padL - 10, y: y + 4 });
    label.classList.add("chart-axis");
    label.setAttribute("text-anchor", "end");
    label.textContent = yLabel(value);
    grid.appendChild(label);
  }
  svgElement.appendChild(grid);

  // X-axis date labels (up to 6, evenly spaced).
  const labels = svgNode("g", { class: "chart-ticks" });
  const tickEvery = Math.max(1, Math.floor(points.length / 6));
  for (let i = 0; i < points.length; i += tickEvery) {
    const tick = svgNode("text", { x: xAt(i), y: height - padB + 22 });
    tick.classList.add("chart-axis");
    tick.setAttribute("text-anchor", "middle");
    tick.textContent = formatShortDate(points[i].date);
    labels.appendChild(tick);
  }
  svgElement.appendChild(labels);

  // Area + line for the selected metric.
  const linePath = points
    .map((point, index) => `${index === 0 ? "M" : "L"}${xAt(index).toFixed(1)},${yAt(metricValue(point)).toFixed(1)}`)
    .join(" ");
  const areaPath =
    linePath +
    ` L${xAt(points.length - 1).toFixed(1)},${(yAt(minValue)).toFixed(1)}` +
    ` L${xAt(0).toFixed(1)},${(yAt(minValue)).toFixed(1)} Z`;

  const area = svgNode("path", { d: areaPath });
  area.classList.add("chart-area");
  const line = svgNode("path", { d: linePath });
  line.classList.add("chart-line");
  svgElement.appendChild(area);
  svgElement.appendChild(line);

  // Hover interaction.
  const overlay = svgNode("rect", {
    x: padL,
    y: padT,
    width: innerW,
    height: innerH,
    fill: "transparent",
  });
  overlay.classList.add("chart-overlay");
  const tooltip = svgNode("g", { class: "chart-tooltip" });
  tooltip.setAttribute("opacity", "0");
  svgElement.appendChild(overlay);
  svgElement.appendChild(tooltip);

  overlay.addEventListener("mousemove", (event) => {
    const bounds = svgElement.getBoundingClientRect();
    const scaleX = CHART_LAYOUT.width / (bounds.width || 1);
    const cursorX = (event.clientX - bounds.left) * scaleX;
    const ratio = (cursorX - padL) / innerW;
    const index = Math.min(
      points.length - 1,
      Math.max(0, Math.round(ratio * (points.length - 1))),
    );
    const point = points[index];
    const tx = xAt(index);
    const ty = yAt(metricValue(point));
    showTooltip(tooltip, point, tx, ty, width);
    moveCrosshair(svgElement, tx, padT, padB, ty);
  });

  overlay.addEventListener("mouseleave", () => {
    tooltip.setAttribute("opacity", "0");
    const crosshair = svgElement.querySelector(".chart-crosshair");
    if (crosshair) {
      crosshair.setAttribute("display", "none");
    }
  });

  svgElement.setAttribute(
    "aria-label",
    `${chartMetric === "units" ? "Units sold" : "Sales revenue"} over time, last ${points.length === salesSeries.length ? "full" : chartRange} days of history`,
  );
}

function moveCrosshair(svg, tx, padT, padB, ty) {
  let crosshair = svg.querySelector(".chart-crosshair");
  if (!crosshair) {
    crosshair = svgNode("g", { class: "chart-crosshair" });
    crosshair.appendChild(svgNode("line", { y1: padT, y2: CHART_LAYOUT.height - padB, class: "chart-crosshair-line" }));
    crosshair.appendChild(svgNode("circle", { r: 4, class: "chart-crosshair-dot" }));
    svg.appendChild(crosshair);
  }
  const line = crosshair.querySelector("line");
  const dot = crosshair.querySelector("circle");
  line.setAttribute("x1", tx);
  line.setAttribute("x2", tx);
  dot.setAttribute("cx", tx);
  dot.setAttribute("cy", ty);
  crosshair.setAttribute("display", "block");
}

function showTooltip(tooltip, point, tx, ty, width) {
  const boxes = [
    [formatDateLabel(point.date), "tooltip-title"],
    [chartMetric === "units" ? `Units: ${formatNumber(metricValue(point))}` : `Revenue: ${formatMoney(metricValue(point))}`, "tooltip-value"],
  ];
  const rows = boxes.map(([text, className]) => ({ text, className }));
  const title = rows[0];
  const valueRow = rows[1];

  const titleText = svgNode("text", { x: 0, y: 0, class: "chart-tooltip-title" });
  titleText.textContent = title.text;
  const valueText = svgNode("text", { x: 0, y: 16, class: "chart-tooltip-value" });
  valueText.textContent = valueRow.text;

  const rect = svgNode("rect", { width: 168, height: 30, rx: 6 });
  rect.classList.add("chart-tooltip-bg");

  clearNode(tooltip);
  tooltip.appendChild(rect);
  tooltip.appendChild(titleText);
  tooltip.appendChild(valueText);

  let dx = tx - 84;
  dx = Math.max(CHART_LAYOUT.padL, Math.min(width - CHART_LAYOUT.padR - 168, dx));
  const dy = Math.max(CHART_LAYOUT.padT + 2, ty - 46);
  tooltip.setAttribute("transform", `translate(${dx.toFixed(1)}, ${dy.toFixed(1)})`);
  tooltip.setAttribute("opacity", "1");
}

function initSalesChart(element) {
  svgElement = element;
}

function setSalesSeries(series) {
  salesSeries = series || [];
  renderChart();
}

function updateSalesChart(metric, range) {
  chartMetric = metric || chartMetric;
  chartRange = range || chartRange;
  renderChart();
}