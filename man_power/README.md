# Manpower Capacity Planning and Monte Carlo Forecasting System

A Django web application that tells you whether each process has **Less**, **Sufficient** or **Higher** manpower
**today** and **in the future**, and rolls the results up into a **CEO-level Executive Dashboard**.

* **Monte Carlo** (optional) measures how much risk day-to-day variability adds (P90 FTE, sufficiency probability).
* **Growth forecast** (optional) projects volume growth and recalculates manpower month by month.
* **Executive Dashboard** shows the organisation-wide health score, hiring need and budget, risks,
  redeployment moves and the headcount outlook.

---

## 1. Local setup

```bash
cd manpower_forecasting
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # Linux / macOS
pip install -r requirements.txt
python manage.py migrate
python manage.py setup_roles
python manage.py createsuperuser
python manage.py load_sample_data      # optional demo data
python manage.py runserver
```

Open http://127.0.0.1:8000/ and log in. The Executive Dashboard is at http://127.0.0.1:8000/executive/.

**Upgrading:** copy the new files over the old project and run `python manage.py migrate`.
The executive dashboard adds **no database changes**; it is calculated from existing forecasts.

**Demo users** (`load_sample_data`, password `Demo@12345`): `admin_user`, `analyst_user`, `analyst2_user`,
`approver_user`, `viewer_user`.

**Tests:** `python manage.py test forecasting` runs 113 tests, including 21 for the executive dashboard.

---

## 2. Executive Dashboard

Menu: **Overview -> Executive Dashboard**. It is available to all roles; Viewers see approved forecasts only.

### Controls
| Control | Purpose |
|---|---|
| Function | Whole organisation or one function |
| Outlook | 3 / 6 / 12 / 18 / 24 months |
| Annual cost per FTE | Fully loaded cost used for all budget figures (default in settings) |
| Approved only | Use only approved forecasts (recommended for board reporting) |
| Export Excel / Print-PDF | A board-ready workbook, or a print-optimised page |

### Sections
| Section | What the CEO learns |
|---|---|
| **Capacity Health Score (0-100)** | One number with a red/amber/green rating and three pillars |
| **The Bottom Line** | Net hires now, net hires by the outlook date, redeployable FTE, capacity above the safe level, all with annual cost |
| **KPI strip** | Workforce, requirement, utilization vs target, processes short now and short later |
| **Key Insights** | Plain-English findings generated from the data |
| **Headcount Outlook** | Safe staffing needed vs current workforce, month by month |
| **Where Our People Sit** | Current FTE split by Less / Sufficient / Higher status |
| **Function Scorecard** | Status rating, utilization, hire now, redeployable and hire-by-horizon per function, with drill-down |
| **Top Risks & Actions** | Short now (red), short in future (orange), high utilization (amber), each with a recommended action |
| **Risk Matrix** | Utilization vs months until shortage; bubble size = FTE |
| **Quarterly Hiring Plan** | New and cumulative net hires and annual cost per quarter |
| **Redeployment Opportunities** | Specific "move N FTE from X to Y" suggestions (same function first) |

### Calculation logic
| Measure | Formula |
|---|---|
| Safe staffing | ceil(P90 FTE) with Monte Carlo, otherwise ceil(required FTE) |
| Hire now | Sum of (safe staffing - current FTE) for processes below safe staffing |
| Redeployable | Whole people above safe staffing in Higher Manpower processes |
| Net hires | max(0, hire now - redeployable) |
| Hires by outlook | Same, using each process's projected safe staffing at the outlook month |
| Budget | Net hires x annual cost per FTE |
| Capacity above safe level | Sum of (current FTE - safe staffing) where positive, x cost per FTE |
| Organisation utilization | Total required FTE / total current FTE |
| **Health Score** | 40% Coverage + 30% Efficiency + 30% Resilience |
| Coverage | % of processes not short today |
| Efficiency | 100 - 2 x \|utilization - target (80%)\| |
| Resilience | Average Monte Carlo sufficiency %; if no Monte Carlo data, % of processes neither short nor at high-utilization risk |
| Rating | 75+ Healthy, 50-74 Needs attention, below 50 At risk |

### Settings (`settings.FORECASTING`)
```python
"EXEC_COST_PER_FTE": 600000,      # default annual cost per FTE
"EXEC_CURRENCY": "₹",             # ₹ shows Lakh / Crore; other symbols show K / M
"EXEC_HORIZON_MONTHS": 12,        # default outlook
"EXEC_TARGET_UTILIZATION": 80,    # organisation target
```

---

## 3. Forecast logic (unchanged)

| Step | Formula |
|------|---------|
| Productive minutes / FTE / day | Hours x 60 x (1 - Contingency% / 100) |
| Daily volume | Volume / working days in the period |
| Required FTE | Daily volume x minutes per item / productive minutes |
| Utilization | Required FTE / Current FTE x 100 |
| Growth | Volume(m) = Volume x (1 + Growth%) ^ periods elapsed |

**Status rules:** 1) Current FTE = 0 -> Less, 2) Current < Required -> Less, 3) Monte Carlo sufficiency < 80% -> Less (only when Monte Carlo is on),
4) Utilization < 70% -> Higher, 5) otherwise Sufficient (+ High Utilization Risk above 90%).

## 4. Maker-checker
Every new, edited, recalculated or uploaded forecast is Pending until it is approved. Approvers can never approve their own forecast, and rejection requires a comment.

## 5. PostgreSQL / production
Set `DB_ENGINE=postgresql` and the `DB_*` variables, then `pip install "psycopg[binary]"` and `python manage.py migrate`.
For production, set `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False` and `DJANGO_ALLOWED_HOSTS`, then run `python manage.py collectstatic`.
