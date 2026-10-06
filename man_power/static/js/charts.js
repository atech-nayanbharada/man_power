/* Chart.js integration. Pages embed data with Django's json_script as #chart-data
   and mark canvases with data-chart="<name>". Null values (not calculated) are left as gaps. */
(function () {
  "use strict";
  if (!window.Chart) return;
  const dataEl = document.getElementById("chart-data");
  if (!dataEl) return;
  const data = JSON.parse(dataEl.textContent || "{}") || {};

  const C = {
    blue: "#1f4e79", lightBlue: "#5b9bd5", green: "#198754", amber: "#f0ad00", teal: "#0e7c86",
    orange: "#fd7e14", red: "#dc3545", gray: "#8a96a3", purple: "#6f42c1", paleBlue: "#9dc3e6",
    track: "#e3e7ee",
  };
  const STATUS_COLOR = { LESS: C.red, SUFFICIENT: C.green, HIGHER: C.amber };
  const RAG_COLOR = { success: C.green, amber: C.amber, danger: C.red, secondary: C.gray };
  Chart.defaults.font.family = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";
  Chart.defaults.color = "#5f6b7a";
  Chart.defaults.maintainAspectRatio = false;
  Chart.defaults.plugins.legend.position = "bottom";

  const fmt = (v) => (typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : v);
  const pctAxis = { beginAtZero: true, ticks: { callback: (v) => `${v}%` } };
  const utilColor = (u) => (u === null ? C.gray : u > 100 ? C.red : u > 90 ? C.orange : u >= 70 ? C.green : C.amber);
  const probColor = (v) => (v === null ? C.gray : v >= 80 ? C.green : v >= 50 ? C.amber : C.red);
  const alpha = (hex, a) => hex + Math.round(a * 255).toString(16).padStart(2, "0");

  const builders = {
    /* ---------------- Operations dashboard ---------------- */
    currentVsRequired: () => {
      const sets = [
        { label: "Current FTE", data: data.current, backgroundColor: C.gray },
        { label: "Required FTE (today)", data: data.required, backgroundColor: C.blue },
      ];
      if (data.has_projection) {
        sets.push({ label: "Required FTE (end of horizon)", data: data.required_horizon, backgroundColor: C.teal });
      }
      return { type: "bar", data: { labels: data.labels, datasets: sets },
        options: { scales: { y: { beginAtZero: true, title: { display: true, text: "FTE" } } } } };
    },
    currentVsP90: () => ({
      type: "bar",
      data: { labels: data.labels, datasets: [
        { label: "Current FTE", data: data.current, backgroundColor: C.gray },
        { label: "P90 FTE", data: data.p90, backgroundColor: C.purple },
      ] },
      options: { scales: { y: { beginAtZero: true, title: { display: true, text: "FTE" } } } },
    }),
    utilization: () => ({
      type: "bar",
      data: { labels: data.labels, datasets: [{
        label: "Utilization %", data: data.utilization, backgroundColor: data.utilization.map(utilColor),
      }] },
      options: { plugins: { legend: { display: false },
        tooltip: { callbacks: { label: (ctx) => `Utilization: ${fmt(ctx.raw)}%` } } }, scales: { y: pctAxis } },
    }),
    statusDistribution: () => ({
      type: "doughnut",
      data: { labels: data.status.labels, datasets: [{ data: data.status.values,
        backgroundColor: [C.red, C.green, C.amber], borderWidth: 2 }] },
      options: { cutout: "60%" },
    }),
    functionGap: () => ({
      type: "bar",
      data: { labels: data.function_gap.labels, datasets: [{
        label: "FTE Gap (Current - Required)", data: data.function_gap.values,
        backgroundColor: data.function_gap.values.map((v) => (v < 0 ? C.red : C.green)),
      }] },
      options: { indexAxis: "y", plugins: { legend: { display: false } },
        scales: { x: { title: { display: true, text: "FTE (negative = shortage)" } } } },
    }),
    sufficiency: () => ({
      type: "bar",
      data: { labels: data.labels, datasets: [{
        label: "Sufficiency %", data: data.sufficiency, backgroundColor: data.sufficiency.map(probColor),
      }] },
      options: { plugins: { legend: { display: false } }, scales: { y: { ...pctAxis, max: 100 } } },
    }),
    percentileComparison: () => ({
      type: "bar",
      data: { labels: data.labels, datasets: [
        { label: "P50", data: data.p50, backgroundColor: C.paleBlue },
        { label: "P80", data: data.p80, backgroundColor: C.lightBlue },
        { label: "P90", data: data.p90, backgroundColor: C.blue },
        { label: "P95", data: data.p95, backgroundColor: C.purple },
        { type: "line", label: "Current FTE", data: data.current, borderColor: C.red,
          backgroundColor: C.red, pointRadius: 4, showLine: false },
      ] },
      options: { scales: { y: { beginAtZero: true, title: { display: true, text: "FTE" } } } },
    }),

    /* ---------------- Forecast result ---------------- */
    histogram: () => {
      const h = data.histogram || { labels: [], counts: [] };
      const current = data.current_fte;
      const colors = h.labels.map((l) => (parseFloat(l.split("-").pop()) <= current ? C.green : C.red));
      return {
        type: "bar",
        data: { labels: h.labels, datasets: [{ label: "Simulations", data: h.counts, backgroundColor: colors,
          barPercentage: 1.0, categoryPercentage: 1.0 }] },
        options: {
          plugins: { legend: { display: false },
            title: { display: true, text: `Required FTE distribution (green = within current ${current} FTE)` } },
          scales: { x: { title: { display: true, text: "Required FTE range" }, ticks: { maxRotation: 60 } },
            y: { beginAtZero: true, title: { display: true, text: "Count" } } },
        },
      };
    },
    percentiles: () => ({
      type: "bar",
      data: { labels: data.percentiles.labels, datasets: [
        { label: "Required FTE", data: data.percentiles.values,
          backgroundColor: [C.gray, C.paleBlue, C.lightBlue, C.blue, C.purple, C.red] },
        { type: "line", label: "Current FTE", data: data.percentiles.labels.map(() => data.current_fte),
          borderColor: C.green, borderDash: [6, 4], pointRadius: 0, fill: false },
      ] },
      options: { plugins: { title: { display: true, text: "Calculated vs percentile requirement" } },
        scales: { y: { beginAtZero: true } } },
    }),
    projection: () => {
      const p = data.projection;
      const sets = [
        { type: "bar", label: "FTE Needed", data: p.needed, order: 3,
          backgroundColor: p.status.map((s) => alpha(STATUS_COLOR[s], 0.33)),
          borderColor: p.status.map((s) => STATUS_COLOR[s]), borderWidth: 1 },
        { type: "line", label: "Required FTE", data: p.required, borderColor: C.blue, backgroundColor: C.blue,
          tension: 0.25, pointRadius: 3, order: 1 },
        { type: "line", label: "Current FTE", data: p.current, borderColor: C.gray, borderDash: [6, 4],
          pointRadius: 0, fill: false, order: 0 },
      ];
      if (p.p90) {
        sets.push({ type: "line", label: "P90 FTE", data: p.p90, borderColor: C.purple, backgroundColor: C.purple,
          tension: 0.25, pointRadius: 2, order: 2 });
      }
      return {
        type: "bar",
        data: { labels: p.labels, datasets: sets },
        options: {
          interaction: { mode: "index", intersect: false },
          plugins: {
            title: { display: true, text: "Projected FTE requirement vs current FTE (bar colour = status)" },
            tooltip: { callbacks: { afterBody: (items) => {
              const i = items[0].dataIndex;
              const util = p.utilization[i];
              const lines = [`Status: ${{ LESS: "Less", SUFFICIENT: "Sufficient", HIGHER: "Higher" }[p.status[i]]} Manpower`];
              if (util !== null) lines.push(`Utilization: ${fmt(util)}%`);
              if (p.sufficiency && p.sufficiency[i] !== null) lines.push(`Sufficiency: ${fmt(p.sufficiency[i])}%`);
              return lines;
            } } },
          },
          scales: { y: { beginAtZero: true, title: { display: true, text: "FTE" } },
            x: { ticks: { maxRotation: 60, autoSkip: true } } },
        },
      };
    },

    /* ---------------- Scenario comparison ---------------- */
    scenarioFte: () => {
      const sets = [
        { label: "Required FTE", data: data.required, backgroundColor: C.blue },
        { label: "Operational FTE", data: data.operational, backgroundColor: C.lightBlue },
      ];
      if (data.has_monte_carlo) sets.push({ label: "P90 FTE", data: data.p90, backgroundColor: C.purple });
      if (data.has_projection) sets.push({ label: "Required FTE at horizon", data: data.horizon_required, backgroundColor: C.teal });
      sets.push({ label: "Current / Proposed FTE", data: data.current, backgroundColor: C.gray });
      return { type: "bar", data: { labels: data.labels, datasets: sets },
        options: { scales: { y: { beginAtZero: true } } } };
    },
    scenarioSufficiency: () => ({
      type: "bar",
      data: { labels: data.labels, datasets: [{ label: "Sufficiency %", data: data.sufficiency,
        backgroundColor: (data.sufficiency || []).map(probColor) }] },
      options: { plugins: { legend: { display: false } }, scales: { y: { ...pctAxis, max: 100 } } },
    }),
    scenarioUtilization: () => ({
      type: "bar",
      data: { labels: data.labels, datasets: [{ label: "Utilization %", data: data.utilization,
        backgroundColor: (data.utilization || []).map(utilColor) }] },
      options: { plugins: { legend: { display: false } }, scales: { y: pctAxis } },
    }),

    /* ---------------- Executive dashboard ---------------- */
    healthGauge: () => {
      const score = data.health.score;
      return {
        type: "doughnut",
        data: { labels: ["Score", ""], datasets: [{ data: [score, 100 - score],
          backgroundColor: [RAG_COLOR[data.health.rag] || C.blue, C.track], borderWidth: 0 }] },
        options: { rotation: -90, circumference: 180, cutout: "72%",
          plugins: { legend: { display: false }, tooltip: { enabled: false } } },
      };
    },
    execTrajectory: () => {
      const t = data.trajectory;
      return {
        type: "line",
        data: { labels: t.labels, datasets: [
          { label: "Safe staffing needed", data: t.needed, borderColor: C.purple,
            backgroundColor: alpha(C.purple, 0.12), fill: "+1", tension: 0.25, pointRadius: 3 },
          { label: "Current workforce", data: t.current, borderColor: C.gray, borderDash: [6, 4],
            pointRadius: 0, fill: false },
          { label: "Required (average workload)", data: t.required, borderColor: C.blue, tension: 0.25,
            pointRadius: 2, fill: false },
        ] },
        options: {
          interaction: { mode: "index", intersect: false },
          plugins: { tooltip: { callbacks: { afterBody: (items) => {
            const i = items[0].dataIndex;
            const gap = t.needed[i] - t.current[i];
            return gap > 0 ? `Gap: ${fmt(gap)} FTE to hire` : `Headroom: ${fmt(-gap)} FTE`;
          } } } },
          scales: { y: { beginAtZero: false, title: { display: true, text: "FTE" } },
            x: { ticks: { maxRotation: 45, autoSkip: true } } },
        },
      };
    },
    execFteStatus: () => ({
      type: "doughnut",
      data: { labels: data.fte_status.labels, datasets: [{ data: data.fte_status.values,
        backgroundColor: [C.red, C.green, C.amber], borderWidth: 2 }] },
      options: { cutout: "58%", plugins: { tooltip: { callbacks: {
        label: (ctx) => {
          const total = ctx.dataset.data.reduce((a, b) => a + b, 0) || 1;
          return `${ctx.label}: ${fmt(ctx.raw)} FTE (${((ctx.raw / total) * 100).toFixed(0)}%)`;
        } } } } },
    }),
    execFunctions: () => {
      const f = data.functions;
      return {
        type: "bar",
        data: { labels: f.labels, datasets: [
          { label: "Current FTE", data: f.current, backgroundColor: C.gray },
          { label: "Required FTE today", data: f.required, backgroundColor: C.blue },
          { label: "Safe staffing at outlook end", data: f.needed_horizon, backgroundColor: C.purple },
        ] },
        options: { scales: { y: { beginAtZero: true, title: { display: true, text: "FTE" } } } },
      };
    },
    execRiskMatrix: () => {
      const m = data.risk_matrix;
      const points = m.points;
      const shadeZones = {
        id: "zones",
        beforeDraw(chart) {
          const { ctx, chartArea, scales } = chart;
          if (!chartArea) return;
          ctx.save();
          const x90 = scales.x.getPixelForValue(m.util_upper);
          const x100 = scales.x.getPixelForValue(100);
          ctx.fillStyle = alpha(C.orange, 0.06);
          ctx.fillRect(x90, chartArea.top, x100 - x90, chartArea.bottom - chartArea.top);
          ctx.fillStyle = alpha(C.red, 0.07);
          ctx.fillRect(x100, chartArea.top, chartArea.right - x100, chartArea.bottom - chartArea.top);
          ctx.restore();
        },
      };
      return {
        type: "bubble",
        data: { datasets: [{
          label: "Processes",
          data: points.map((p) => ({ x: p.x, y: p.y, r: p.r })),
          backgroundColor: points.map((p) => alpha(STATUS_COLOR[p.status], 0.55)),
          borderColor: points.map((p) => STATUS_COLOR[p.status]),
        }] },
        options: {
          plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx) => {
            const p = points[ctx.dataIndex];
            const runway = p.y > m.horizon ? "no shortage within outlook" : (p.y === 0 ? "short now" : `short in ${p.y} month(s)`);
            return `${p.label}: utilization ${fmt(p.x)}%, ${runway}, ${fmt(p.fte)} FTE`;
          } } } },
          scales: {
            x: { min: 0, suggestedMax: 150, title: { display: true, text: "Utilization today (%)" },
              ticks: { callback: (v) => `${v}%` } },
            y: { min: -1, max: m.horizon + 2, reverse: false, title: { display: true, text: "Months until shortage" },
              ticks: { stepSize: Math.max(1, Math.round(m.horizon / 6)),
                callback: (v) => (v > m.horizon ? "None" : v < 0 ? "" : v) } },
          },
        },
        plugins: [shadeZones],
      };
    },
    execHiringPlan: () => {
      const h = data.hiring_plan;
      return {
        type: "bar",
        data: { labels: h.labels, datasets: [
          { type: "bar", label: "New hires in period", data: h.new_hires, backgroundColor: C.orange },
          { type: "line", label: "Cumulative net hires", data: h.cumulative, borderColor: C.red,
            backgroundColor: C.red, tension: 0.2, pointRadius: 4 },
        ] },
        options: { scales: { y: { beginAtZero: true, ticks: { precision: 0 }, title: { display: true, text: "FTE" } } } },
      };
    },
  };

  document.querySelectorAll("canvas[data-chart]").forEach((canvas) => {
    const builder = builders[canvas.dataset.chart];
    if (!builder) return;
    try { new Chart(canvas, builder()); } catch (e) { console.error("Chart error", canvas.dataset.chart, e); }
  });
})();
