/* Global UI behaviour: sidebar, confirmation modal, loading overlay, dependent dropdown,
   capacity preview, volume + AHT growth preview, Monte Carlo toggle, scenario formset,
   progress-bar widths and print. */
(function () {
  "use strict";

  /* ---------- Sidebar ---------- */
  const sidebar = document.getElementById("sidebar");
  document.querySelectorAll("[data-sidebar-toggle]").forEach((btn) =>
    btn.addEventListener("click", () => sidebar && sidebar.classList.toggle("show")));
  document.querySelectorAll("[data-sidebar-close]").forEach((el) =>
    el.addEventListener("click", () => sidebar && sidebar.classList.remove("show")));

  /* ---------- Progress bars (width from data attribute, no inline CSS in templates) ---------- */
  document.querySelectorAll("[data-width]").forEach((bar) => {
    const w = Math.max(0, Math.min(100, parseFloat(bar.dataset.width) || 0));
    requestAnimationFrame(() => { bar.style.width = `${w}%`; });
  });

  /* ---------- Print ---------- */
  document.querySelectorAll("[data-print]").forEach((btn) => btn.addEventListener("click", () => {
    document.querySelectorAll("details.methodology").forEach((d) => { d.open = true; });
    window.print();
  }));

  /* ---------- Loading overlay ---------- */
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
      const text = toggle && toggle.checked && form.dataset.mcLoadingText
        ? form.dataset.mcLoadingText : form.dataset.loadingText;
      showLoading(text);
      form.querySelectorAll("button[type=submit]").forEach((b) => { b.disabled = true; });
    });
  });

  /* ---------- Monte Carlo on/off toggle ---------- */
  document.querySelectorAll("[data-mc-toggle]").forEach((toggle) => {
    const scope = toggle.closest("form") || document;
    const apply = () => {
      const on = toggle.checked;
      scope.querySelectorAll("[data-mc-fields]").forEach((el) => el.classList.toggle("d-none", !on));
      scope.querySelectorAll("[data-mc-off-note]").forEach((el) => el.classList.toggle("d-none", on));
      scope.querySelectorAll("[data-submit-label]").forEach((el) => {
        el.textContent = on ? el.dataset.mcLabel : el.dataset.detLabel;
      });
    };
    toggle.addEventListener("change", apply);
    apply();
  });

  /* ---------- Confirmation modal ---------- */
  const modalEl = document.getElementById("confirmModal");
  if (modalEl && window.bootstrap) {
    const modal = new bootstrap.Modal(modalEl);
    const form = document.getElementById("confirmModalForm");
    const btn = document.getElementById("confirmModalButton");
    let useLoading = false;
    document.querySelectorAll("[data-confirm-url]").forEach((trigger) => {
      trigger.addEventListener("click", () => {
        form.action = trigger.dataset.confirmUrl;
        document.getElementById("confirmModalTitle").textContent = trigger.dataset.confirmTitle || "Please confirm";
        document.getElementById("confirmModalBody").textContent = trigger.dataset.confirmMessage || "Are you sure?";
        btn.textContent = trigger.dataset.confirmButton || "Confirm";
        btn.className = "btn " + (trigger.dataset.confirmClass || "btn-danger");
        btn.disabled = false;
        useLoading = trigger.dataset.loading === "true";
        modal.show();
      });
    });
    form.addEventListener("submit", () => {
      btn.disabled = true;
      if (useLoading) { modal.hide(); showLoading("Calculating..."); }
    });
  }

  /* ---------- Function -> Process dependent dropdown ---------- */
  const fnSelect = document.querySelector("[data-function-select]");
  const procSelect = document.querySelector("[data-process-select]");
  const freqSelect = document.querySelector("[data-frequency-select]");
  if (fnSelect && procSelect) {
    fnSelect.addEventListener("change", async () => {
      procSelect.innerHTML = '<option value="">Loading...</option>';
      if (!fnSelect.value) { procSelect.innerHTML = '<option value="">Select process</option>'; return; }
      try {
        const url = `${procSelect.dataset.url}?function=${encodeURIComponent(fnSelect.value)}`;
        const res = await fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } });
        const data = await res.json();
        procSelect.innerHTML = '<option value="">Select process</option>';
        data.results.forEach((p) => {
          const opt = document.createElement("option");
          opt.value = p.id; opt.textContent = p.name; opt.dataset.frequency = p.default_frequency;
          procSelect.appendChild(opt);
        });
        if (!data.results.length) procSelect.innerHTML = '<option value="">No active processes</option>';
      } catch (e) {
        procSelect.innerHTML = '<option value="">Unable to load processes</option>';
      }
    });
    procSelect.addEventListener("change", () => {
      const opt = procSelect.selectedOptions[0];
      if (freqSelect && opt && opt.dataset.frequency) freqSelect.value = opt.dataset.frequency;
    });
  }

  /* ---------- Productive capacity live preview ---------- */
  const byId = (id) => document.getElementById(id);
  const preview = document.querySelector("[data-capacity-preview]");
  const hoursInput = byId("id_working_hours_per_day");
  const contInput = byId("id_contingency_percentage");
  function updatePreview() {
    if (!preview || !hoursInput || !contInput) return;
    const h = parseFloat(hoursInput.value);
    const c = parseFloat(contInput.value);
    const minEl = preview.querySelector("[data-preview-minutes]");
    const hrEl = preview.querySelector("[data-preview-hours]");
    if (isNaN(h) || isNaN(c) || h <= 0 || c < 0 || c >= 100) { minEl.textContent = "-"; hrEl.textContent = "-"; return; }
    const productive = h * 60 * (1 - c / 100);
    minEl.textContent = productive.toFixed(2);
    hrEl.textContent = (productive / 60).toFixed(2);
  }
  [hoursInput, contInput].forEach((el) => el && el.addEventListener("input", updatePreview));
  updatePreview();

  /* ---------- Volume growth + AHT change live preview (same compounding rules as the server) ---------- */
  const growthPreview = document.querySelector("[data-growth-preview]");
  const MONTHS_PER_PERIOD = { MONTHLY: 1, QUARTERLY: 3, HALF_YEARLY: 6, YEARLY: 12 };
  const UNIT_TO_MIN = { SECONDS: 1 / 60, MINUTES: 1, HOURS: 60 };
  function periodsElapsed(period, months, daysWeek, daysMonth) {
    if (period === "DAILY") return months * daysMonth;
    if (period === "WEEKLY") return Math.floor((months * daysMonth) / daysWeek);
    return Math.floor(months / (MONTHS_PER_PERIOD[period] || 1));
  }
  const val = (id) => (byId(id) || {}).value;
  const pctChange = (f) => `${f >= 1 ? "+" : ""}${((f - 1) * 100).toFixed(1)}%`;
  function updateGrowthPreview() {
    if (!growthPreview) return;
    const text = growthPreview.querySelector("[data-growth-text]");
    const volRate = parseFloat(val("id_growth_rate_percentage")) || 0;
    const ahtRate = parseFloat(val("id_aht_change_percentage")) || 0;
    const horizon = parseInt(val("id_forecast_horizon_months"), 10);
    const daysWeek = parseInt(val("id_working_days_per_week"), 10) || 5;
    const daysMonth = parseInt(val("id_working_days_per_month"), 10) || 22;
    if (volRate === 0 && ahtRate === 0) {
      text.textContent = "No volume growth or AHT change entered: the future projection will not be calculated.";
      return;
    }
    if (isNaN(horizon) || horizon < 1) { text.textContent = "Enter a forecast horizon in months."; return; }
    const vf = Math.pow(1 + volRate / 100, periodsElapsed(val("id_growth_period"), horizon, daysWeek, daysMonth));
    const af = Math.pow(1 + ahtRate / 100, periodsElapsed(val("id_aht_change_period"), horizon, daysWeek, daysMonth));
    const parts = [];
    const volume = parseFloat(val("id_volume"));
    if (volRate !== 0) {
      let s = `volume ×${vf.toFixed(2)} (${pctChange(vf)})`;
      if (!isNaN(volume) && volume > 0) s += ` ${volume.toLocaleString()} → ${(volume * vf).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
      parts.push(s);
    }
    if (ahtRate !== 0) {
      let s = `AHT ×${af.toFixed(2)} (${pctChange(af)})`;
      const aht = parseFloat(val("id_avg_processing_time"));
      const unit = UNIT_TO_MIN[val("id_time_unit")] || 1;
      if (!isNaN(aht) && aht > 0) s += ` ${(aht * unit).toFixed(2)} → ${(aht * unit * af).toFixed(2)} min`;
      parts.push(s);
    }
    const wf = vf * af;
    text.textContent = `After ${horizon} months: ${parts.join("; ")}. Total workload ×${wf.toFixed(2)} (${pctChange(wf)}). Current FTE stays fixed in the projection.`;
  }
  ["id_growth_rate_percentage", "id_growth_period", "id_aht_change_percentage", "id_aht_change_period",
    "id_forecast_horizon_months", "id_volume", "id_avg_processing_time", "id_time_unit",
    "id_working_days_per_week", "id_working_days_per_month"].forEach((id) => {
    const el = byId(id);
    if (el) { el.addEventListener("input", updateGrowthPreview); el.addEventListener("change", updateGrowthPreview); }
  });
  updateGrowthPreview();

  /* ---------- Scenario base reload ---------- */
  const baseSelect = document.querySelector("[data-reload-param]");
  if (baseSelect) {
    baseSelect.addEventListener("change", () => {
      if (baseSelect.value) window.location.search = `?${baseSelect.dataset.reloadParam}=${baseSelect.value}`;
    });
  }

  /* ---------- Scenario formset add / remove ---------- */
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
    addBtn.addEventListener("click", () => {
      if (container.querySelectorAll(".scenario-form").length >= maxForms) return;
      container.appendChild(tpl.content.cloneNode(true));
      renumber();
    });
    container.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-remove-scenario]");
      if (btn) { btn.closest(".scenario-form").remove(); renumber(); }
    });
    renumber();
  }
})();
