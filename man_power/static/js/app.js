/* Global UI: sidebar, modal, loading overlay, dependent dropdown, Monte Carlo toggle, scenario formset,
   Calculate AHT button (contingency not deducted) and live previews (capacity, required FTE, growth). */
(function () {
  "use strict";

  const sidebar = document.getElementById("sidebar");
  document.querySelectorAll("[data-sidebar-toggle]").forEach((b) => b.addEventListener("click", () => sidebar && sidebar.classList.toggle("show")));
  document.querySelectorAll("[data-sidebar-close]").forEach((b) => b.addEventListener("click", () => sidebar && sidebar.classList.remove("show")));
  document.querySelectorAll("[data-width]").forEach((bar) => {
    const w = Math.max(0, Math.min(100, parseFloat(bar.dataset.width) || 0));
    requestAnimationFrame(() => { bar.style.width = `${w}%`; });
  });
  document.querySelectorAll("[data-print]").forEach((b) => b.addEventListener("click", () => window.print()));

  const overlay = document.getElementById("loadingOverlay");
  function showLoading(text) {
    if (!overlay) return;
    const label = document.getElementById("loadingText");
    if (label && text) label.textContent = text;
    overlay.classList.remove("d-none");
  }
  window.addEventListener("pageshow", () => overlay && overlay.classList.add("d-none"));
  document.querySelectorAll("form[data-loading-form]").forEach((form) => {
    form.addEventListener("submit", () => {
      const toggle = form.querySelector("[data-mc-toggle]");
      showLoading(toggle && toggle.checked && form.dataset.mcLoadingText ? form.dataset.mcLoadingText : form.dataset.loadingText);
      form.querySelectorAll("button[type=submit]").forEach((b) => { b.disabled = true; });
    });
  });

  document.querySelectorAll("[data-mc-toggle]").forEach((toggle) => {
    const scope = toggle.closest("form") || document;
    const apply = () => {
      const on = toggle.checked;
      scope.querySelectorAll("[data-mc-fields]").forEach((el) => el.classList.toggle("d-none", !on));
      scope.querySelectorAll("[data-mc-off-note]").forEach((el) => el.classList.toggle("d-none", on));
      scope.querySelectorAll("[data-submit-label]").forEach((el) => { el.textContent = on ? el.dataset.mcLabel : el.dataset.detLabel; });
    };
    toggle.addEventListener("change", apply);
    apply();
  });

  const modalEl = document.getElementById("confirmModal");
  if (modalEl && window.bootstrap) {
    const modal = new bootstrap.Modal(modalEl);
    const form = document.getElementById("confirmModalForm");
    const btn = document.getElementById("confirmModalButton");
    let useLoading = false;
    document.querySelectorAll("[data-confirm-url]").forEach((t) => t.addEventListener("click", () => {
      form.action = t.dataset.confirmUrl;
      document.getElementById("confirmModalTitle").textContent = t.dataset.confirmTitle || "Please confirm";
      document.getElementById("confirmModalBody").textContent = t.dataset.confirmMessage || "Are you sure?";
      btn.textContent = t.dataset.confirmButton || "Confirm";
      btn.className = "btn " + (t.dataset.confirmClass || "btn-danger");
      btn.disabled = false;
      useLoading = t.dataset.loading === "true";
      modal.show();
    }));
    form.addEventListener("submit", () => { btn.disabled = true; if (useLoading) { modal.hide(); showLoading("Calculating..."); } });
  }

  /* ---------- Shared helpers (same rules as the server) ---------- */
  const byId = (id) => document.getElementById(id);
  const val = (id) => (byId(id) || {}).value;
  const num = (id) => parseFloat(val(id));
  const fmt = (v, d = 2) => v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
  const trim = (v) => String(Math.round(v * 100) / 100);
  const PERIOD_DAYS = { DAILY: () => 1, WEEKLY: (wk) => wk, MONTHLY: (wk, mo) => mo,
    QUARTERLY: (wk, mo) => mo * 3, HALF_YEARLY: (wk, mo) => mo * 6, YEARLY: (wk, mo) => mo * 12 };
  const MONTHS_PER_PERIOD = { MONTHLY: 1, QUARTERLY: 3, HALF_YEARLY: 6, YEARLY: 12 };
  const daysWeek = () => { const v = num("id_working_days_per_week"); return isNaN(v) || v <= 0 ? 5 : v; };
  const daysMonth = () => { const v = num("id_working_days_per_month"); return isNaN(v) || v <= 0 ? 22 : v; };
  const periodDays = () => (PERIOD_DAYS[val("id_frequency")] || PERIOD_DAYS.DAILY)(daysWeek(), daysMonth());
  function productiveMinutes() {
    const h = num("id_working_hours_per_day"), c = num("id_contingency_percentage");
    if (isNaN(h) || isNaN(c) || h <= 0 || c < 0 || c >= 100) return NaN;
    return h * 60 * (1 - c / 100);
  }
  function periodsElapsed(period, months) {
    if (period === "DAILY") return Math.floor(months * daysMonth());
    if (period === "WEEKLY") return Math.floor((months * daysMonth()) / daysWeek());
    return Math.floor(months / (MONTHS_PER_PERIOD[period] || 1));
  }

  /* ---------- Function -> Process dropdown ---------- */
  const fnSelect = document.querySelector("[data-function-select]");
  const procSelect = document.querySelector("[data-process-select]");
  const freqSelect = document.querySelector("[data-frequency-select]");
  if (fnSelect && procSelect) {
    fnSelect.addEventListener("change", async () => {
      procSelect.innerHTML = '<option value="">Loading...</option>';
      if (!fnSelect.value) { procSelect.innerHTML = '<option value="">Select process</option>'; return; }
      try {
        const res = await fetch(`${procSelect.dataset.url}?function=${encodeURIComponent(fnSelect.value)}`);
        const data = await res.json();
        procSelect.innerHTML = '<option value="">Select process</option>';
        data.results.forEach((p) => {
          const opt = document.createElement("option");
          opt.value = p.id; opt.textContent = p.name; opt.dataset.frequency = p.default_frequency;
          procSelect.appendChild(opt);
        });
      } catch (e) { procSelect.innerHTML = '<option value="">Unable to load processes</option>'; }
    });
    procSelect.addEventListener("change", () => {
      const opt = procSelect.selectedOptions[0];
      if (freqSelect && opt && opt.dataset.frequency) freqSelect.value = opt.dataset.frequency;
      updateAll();
    });
  }

  /* ---------- AHT field + Calculate AHT button ----------
     AHT = Current FTE x Working hours per day x Working days in the period x 60 / Volume (contingency not deducted) */
  const ahtInput = document.querySelector("[data-aht-input]");
  const ahtBtn = document.querySelector("[data-aht-calc]");
  const ahtBadge = document.querySelector("[data-aht-badge]");
  const ahtResult = document.querySelector("[data-aht-result]");
  const ahtFormula = document.querySelector("[data-aht-formula]");
  const ahtWarning = document.querySelector("[data-aht-warning]");
  const ahtStale = document.querySelector("[data-aht-stale]");
  const ahtError = document.querySelector("[data-aht-error]");
  let ahtMode = ahtInput ? (ahtInput.dataset.calculated === "true" ? "calculated" : (ahtInput.value ? "entered" : "")) : "";
  let calcSignature = "";
  const signature = () => ["id_frequency", "id_volume", "id_current_fte", "id_working_hours_per_day",
    "id_working_days_per_week", "id_working_days_per_month"].map(val).join("|");

  function capacityAht() {
    const volume = num("id_volume"), fte = num("id_current_fte"), hrs = num("id_working_hours_per_day"), days = periodDays();
    if (isNaN(volume) || volume <= 0) return { error: "Enter a Volume greater than zero first." };
    if (isNaN(fte) || fte < 0) return { error: "Enter Current FTE first." };
    if (fte === 0) return { error: "Current FTE is 0, so there is no team time to calculate AHT from. Type the measured AHT." };
    if (isNaN(hrs) || hrs <= 0 || hrs > 24) return { error: "Check Working Hours Per Day in Working Capacity." };
    const hours = fte * hrs * days;
    return { aht: (hours * 60) / volume, hours, fte, hrs, days, volume };
  }
  function formulaText(r) {
    return `AHT = ${trim(r.fte)} FTE × ${trim(r.hrs)} h × ${trim(r.days)} days = ${fmt(r.hours)} team hours`
      + ` × 60 ÷ ${fmt(r.volume)} items = ${fmt(r.aht)} min per item (contingency not deducted)`
      + (r.aht >= 60 ? ` (${fmt(r.aht / 60)} hours)` : "");
  }
  function renderAht() {
    if (!ahtInput) return;
    ahtBadge.textContent = ahtMode === "calculated" ? "Calculated" : "Entered";
    ahtBadge.className = `badge ms-1 border ${ahtMode === "calculated" ? "bg-warning-subtle text-warning-emphasis" : "bg-success-subtle text-success-emphasis"}${ahtMode ? "" : " d-none"}`;
    ahtInput.classList.toggle("bg-warning-subtle", ahtMode === "calculated");
    ahtWarning.classList.toggle("d-none", ahtMode !== "calculated");
    ahtStale.classList.toggle("d-none", !(ahtMode === "calculated" && calcSignature && calcSignature !== signature()));
    ahtResult.classList.toggle("d-none", ahtMode !== "calculated");
  }
  if (ahtInput && ahtBtn) {
    ahtBtn.addEventListener("click", () => {
      const r = capacityAht();
      ahtError.classList.toggle("d-none", !r.error);
      if (r.error) { ahtError.textContent = r.error; return; }
      ahtInput.value = String(Math.round(r.aht * 10000) / 10000);
      ahtMode = "calculated";
      calcSignature = signature();
      ahtFormula.textContent = formulaText(r);
      renderAht();
      updateAll();
    });
    ahtInput.addEventListener("input", () => {
      ahtMode = ahtInput.value ? "entered" : "";
      calcSignature = "";
      ahtError.classList.add("d-none");
      renderAht();
      updateAll();
    });
    if (ahtMode === "calculated") {
      const r = capacityAht();
      if (!r.error) { calcSignature = signature(); ahtFormula.textContent = formulaText(r); }
    }
    renderAht();
  }

  /* ---------- Capacity preview ---------- */
  const preview = document.querySelector("[data-capacity-preview]");
  function updatePreview() {
    if (!preview) return;
    const p = productiveMinutes(), h = num("id_working_hours_per_day"), wk = daysWeek();
    preview.querySelector("[data-preview-minutes]").textContent = isNaN(p) ? "-" : fmt(p);
    preview.querySelector("[data-preview-hours]").textContent = isNaN(p) ? "-" : fmt(p / 60);
    preview.querySelector("[data-preview-week]").textContent = isNaN(h) ? "-" : `${trim(wk)} days × ${trim(h)} h = ${fmt(wk * h, 1)}`;
    const suggested = (wk * 52) / 12;
    preview.querySelector("[data-preview-month-hint]").textContent = Math.abs(suggested - daysMonth()) > 0.5
      ? ` · Tip: ${trim(wk)} days a week ≈ ${fmt(suggested)} working days per month` : "";
  }

  /* ---------- Required FTE preview ---------- */
  const bePreview = document.querySelector("[data-breakeven-preview]");
  function updateBreakeven() {
    if (!bePreview) return;
    const text = bePreview.querySelector("[data-breakeven-text]");
    const volume = num("id_volume"), fte = num("id_current_fte"), aht = num("id_avg_processing_time"), prod = productiveMinutes();
    bePreview.classList.remove("is-short");
    if ([volume, fte, prod, aht].some(isNaN) || volume <= 0 || aht <= 0) {
      text.textContent = "Required FTE is calculated once AHT is available (type it or click Calculate AHT).";
      return;
    }
    const daily = volume / periodDays();
    const work = (daily * aht) / prod;
    const required = Math.ceil(Math.round(work * 1e6) / 1e6);
    const util = fte > 0 ? (work / fte) * 100 : NaN;
    text.textContent = `Daily volume ${fmt(daily)} × AHT ${fmt(aht)} min ÷ ${fmt(prod)} min = ${fmt(work)} FTE of work → `
      + `Required FTE ${required} (you have ${trim(fte)})` + (isNaN(util) ? "." : `, utilization ${fmt(util, 1)}%.`);
    if (fte < work - 1e-9) bePreview.classList.add("is-short");
  }

  /* ---------- Growth preview ---------- */
  const growthPreview = document.querySelector("[data-growth-preview]");
  function updateGrowthPreview() {
    if (!growthPreview) return;
    const text = growthPreview.querySelector("[data-growth-text]");
    const volRate = num("id_growth_rate_percentage") || 0, ahtRate = num("id_aht_change_percentage") || 0;
    const horizon = parseInt(val("id_forecast_horizon_months"), 10);
    if (volRate === 0 && ahtRate === 0) { text.textContent = "No volume growth or AHT change entered: the future projection will not be calculated."; return; }
    if (isNaN(horizon) || horizon < 1) { text.textContent = "Enter a forecast horizon in months."; return; }
    const vf = Math.pow(1 + volRate / 100, periodsElapsed(val("id_growth_period"), horizon));
    const af = Math.pow(1 + ahtRate / 100, periodsElapsed(val("id_aht_change_period"), horizon));
    text.textContent = `After ${horizon} months: volume ${vf.toFixed(2)}x, AHT ${af.toFixed(2)}x; workload ${(vf * af).toFixed(2)}x today. Current FTE stays fixed.`;
  }

  function updateAll() { updatePreview(); updateBreakeven(); updateGrowthPreview(); if (ahtInput) renderAht(); }
  ["id_volume", "id_current_fte", "id_frequency", "id_working_hours_per_day", "id_working_days_per_week",
    "id_working_days_per_month", "id_contingency_percentage", "id_growth_rate_percentage", "id_growth_period",
    "id_aht_change_percentage", "id_aht_change_period", "id_forecast_horizon_months"].forEach((id) => {
    const el = byId(id);
    if (el) { el.addEventListener("input", updateAll); el.addEventListener("change", updateAll); }
  });
  updateAll();

  /* ---------- Scenario page ---------- */
  const baseSelect = document.querySelector("[data-reload-param]");
  if (baseSelect) baseSelect.addEventListener("change", () => { if (baseSelect.value) window.location.search = `?${baseSelect.dataset.reloadParam}=${baseSelect.value}`; });
  const container = document.getElementById("scenarioForms");
  const addBtn = document.getElementById("addScenario");
  const tpl = document.getElementById("scenarioTemplate");
  if (container && addBtn && tpl) {
    const total = document.getElementById("id_sc-TOTAL_FORMS");
    const maxForms = parseInt(container.dataset.maxForms || "4", 10);
    const renumber = () => {
      const forms = container.querySelectorAll(".scenario-form");
      forms.forEach((card, idx) => {
        card.querySelectorAll("input, select, textarea, label").forEach((el) => {
          ["name", "id", "for"].forEach((attr) => {
            const v = el.getAttribute(attr);
            if (v) el.setAttribute(attr, v.replace(/sc-(\d+|__prefix__)-/, `sc-${idx}-`));
          });
        });
        const title = card.querySelector(".card-header .fw-semibold");
        if (title) title.textContent = `Scenario ${idx + 1}`;
      });
      total.value = forms.length;
      addBtn.disabled = forms.length >= maxForms;
    };
    addBtn.addEventListener("click", () => { if (container.querySelectorAll(".scenario-form").length < maxForms) { container.appendChild(tpl.content.cloneNode(true)); renumber(); } });
    container.addEventListener("click", (e) => { const b = e.target.closest("[data-remove-scenario]"); if (b) { b.closest(".scenario-form").remove(); renumber(); } });
    renumber();
  }
})();
