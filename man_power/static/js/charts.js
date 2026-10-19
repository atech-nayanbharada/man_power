/* Chart.js integration: pages embed #chart-data and mark canvases with data-chart="<name>". */
(function () {
  "use strict";
  if (!window.Chart) return;
  const dataEl = document.getElementById("chart-data");
  if (!dataEl) return;
  const data = JSON.parse(dataEl.textContent || "{}") || {};
  const C = { blue: "#1f4e79", lightBlue: "#5b9bd5", green: "#198754", amber: "#f0ad00", teal: "#0e7c86",
    orange: "#fd7e14", red: "#dc3545", gray: "#8a96a3", purple: "#6f42c1", paleBlue: "#9dc3e6", track: "#e3e7ee" };
  const STATUS_COLOR = { LESS: C.red, SUFFICIENT: C.green, HIGHER: C.amber };
  const RAG_COLOR = { success: C.green, amber: C.amber, danger: C.red, secondary: C.gray };
  Chart.defaults.maintainAspectRatio = false;
  Chart.defaults.plugins.legend.position = "bottom";
  const pctAxis = { beginAtZero: true, ticks: { callback: (v) => `${v}%` } };
  const fteAxis = { beginAtZero: true, title: { display: true, text: "FTE" } };
  const utilColor = (u) => (u === null ? C.gray : u > 100 ? C.red : u > 90 ? C.orange : u >= 70 ? C.green : C.amber);
  const probColor = (v) => (v === null ? C.gray : v >= 80 ? C.green : v >= 50 ? C.amber : C.red);
  const alpha = (hex, a) => hex + Math.round(a * 255).toString(16).padStart(2, "0");

  const builders = {
    currentVsRequired: () => ({ type: "bar", data: { labels: data.labels, datasets: [
      { label: "Current FTE", data: data.current, backgroundColor: C.gray },
      { label: "Required FTE", data: data.required, backgroundColor: C.blue }] }, options: { scales: { y: fteAxis } } }),
    utilization: () => ({ type: "bar", data: { labels: data.labels, datasets: [{ label: "Utilization %", data: data.utilization,
      backgroundColor: data.utilization.map(utilColor) }] }, options: { plugins: { legend: { display: false } }, scales: { y: pctAxis } } }),
    statusDistribution: () => ({ type: "doughnut", data: { labels: data.status.labels, datasets: [{ data: data.status.values,
      backgroundColor: [C.red, C.green, C.amber] }] }, options: { cutout: "60%" } }),
    functionGap: () => ({ type: "bar", data: { labels: data.function_gap.labels, datasets: [{ label: "FTE Gap", data: data.function_gap.values,
      backgroundColor: data.function_gap.values.map((v) => (v < 0 ? C.red : C.green)) }] },
      options: { indexAxis: "y", plugins: { legend: { display: false } } } }),
    sufficiency: () => ({ type: "bar", data: { labels: data.labels, datasets: [{ label: "Sufficiency %", data: data.sufficiency,
      backgroundColor: data.sufficiency.map(probColor) }] }, options: { plugins: { legend: { display: false } }, scales: { y: { ...pctAxis, max: 100 } } } }),
    histogram: () => {
      const h = data.histogram || { labels: [], counts: [] };
      return { type: "bar", data: { labels: h.labels, datasets: [{ label: "Simulated days", data: h.counts,
        backgroundColor: h.labels.map((l) => (parseFloat(l.split("-").pop()) <= data.current_fte ? C.green : C.red)),
        barPercentage: 1, categoryPercentage: 1 }] },
        options: { plugins: { legend: { display: false }, title: { display: true, text: `Simulated workload in FTE (green = within current ${data.current_fte} FTE)` } } } };
    },
    percentiles: () => ({ type: "bar", data: { labels: data.percentiles.labels, datasets: [
      { label: "Workload FTE", data: data.percentiles.values, backgroundColor: [C.gray, C.paleBlue, C.lightBlue, C.blue, C.purple, C.red] },
      { type: "line", label: "Current FTE", data: data.percentiles.labels.map(() => data.current_fte), borderColor: C.green, borderDash: [6, 4], pointRadius: 0 }] },
      options: { scales: { y: { beginAtZero: true } } } }),
    projection: () => {
      const p = data.projection;
      return { type: "bar", data: { labels: p.labels, datasets: [
        { type: "bar", label: "FTE Needed", data: p.needed, order: 3, backgroundColor: p.status.map((s) => alpha(STATUS_COLOR[s], 0.33)), borderColor: p.status.map((s) => STATUS_COLOR[s]), borderWidth: 1 },
        { type: "line", label: "Required FTE", data: p.required, borderColor: C.blue, stepped: true, order: 1 },
        { type: "line", label: "Current FTE", data: p.current, borderColor: C.gray, borderDash: [6, 4], pointRadius: 0, order: 0 }] },
        options: { interaction: { mode: "index", intersect: false }, scales: { y: fteAxis } } };
    },
    scenarioFte: () => {
      const sets = [{ label: "Required FTE", data: data.required, backgroundColor: C.blue }];
      if (data.has_monte_carlo) sets.push({ label: "Risk-adjusted P90 FTE", data: data.p90, backgroundColor: C.purple });
      if (data.has_projection) sets.push({ label: "FTE needed at horizon", data: data.horizon_required, backgroundColor: C.teal });
      sets.push({ label: "Current / Proposed FTE", data: data.current, backgroundColor: C.gray });
      return { type: "bar", data: { labels: data.labels, datasets: sets }, options: { scales: { y: fteAxis } } };
    },
    scenarioSufficiency: () => ({ type: "bar", data: { labels: data.labels, datasets: [{ label: "Sufficiency %", data: data.sufficiency, backgroundColor: (data.sufficiency || []).map(probColor) }] },
      options: { plugins: { legend: { display: false } }, scales: { y: { ...pctAxis, max: 100 } } } }),
    scenarioUtilization: () => ({ type: "bar", data: { labels: data.labels, datasets: [{ label: "Utilization %", data: data.utilization, backgroundColor: (data.utilization || []).map(utilColor) }] },
      options: { plugins: { legend: { display: false } }, scales: { y: pctAxis } } }),
    healthGauge: () => ({ type: "doughnut", data: { datasets: [{ data: [data.health.score, 100 - data.health.score],
      backgroundColor: [RAG_COLOR[data.health.rag] || C.blue, C.track], borderWidth: 0 }] },
      options: { rotation: -90, circumference: 180, cutout: "72%", plugins: { legend: { display: false }, tooltip: { enabled: false } } } }),
    execTrajectory: () => {
      const t = data.trajectory;
      return { type: "line", data: { labels: t.labels, datasets: [
        { label: "Safe staffing needed", data: t.needed, borderColor: C.purple, backgroundColor: alpha(C.purple, 0.12), fill: "+1", stepped: true },
        { label: "Current workforce", data: t.current, borderColor: C.gray, borderDash: [6, 4], pointRadius: 0 },
        { label: "Required FTE", data: t.required, borderColor: C.blue, stepped: true }] } };
    },
    execFteStatus: () => ({ type: "doughnut", data: { labels: data.fte_status.labels, datasets: [{ data: data.fte_status.values, backgroundColor: [C.red, C.green, C.amber] }] }, options: { cutout: "58%" } }),
    execHiringPlan: () => ({ type: "bar", data: { labels: data.hiring_plan.labels, datasets: [
      { type: "bar", label: "New hires in period", data: data.hiring_plan.new_hires, backgroundColor: C.orange },
      { type: "line", label: "Cumulative net hires", data: data.hiring_plan.cumulative, borderColor: C.red }] }, options: { scales: { y: fteAxis } } }),
  };
  document.querySelectorAll("canvas[data-chart]").forEach((canvas) => {
    const b = builders[canvas.dataset.chart];
    if (b) { try { new Chart(canvas, b()); } catch (e) { console.error("Chart error", canvas.dataset.chart, e); } }
  });
})();
