# Manpower Capacity Planning and Monte Carlo Forecasting System

A Django web application that tells you whether a process has **Less**, **Sufficient** or **Higher** manpower
**today**, and, when a growth % is entered, **when in the future** it will need more manpower.

* **Monte Carlo** is optional. It measures how much risk day-to-day variability adds (P90 FTE, sufficiency probability).
* **Growth forecast** is optional. It projects volume growth per day, week, month, quarter, half-year or year,
  then recalculates manpower for every month of the forecast horizon.

---

## 1. Local setup (Windows / Linux / macOS)

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

Open http://127.0.0.1:8000/ and log in.

### Upgrading from the previous version

Copy the new files over the old project, then run:

```bash
python manage.py migrate
```

Migration `0003_manpowerforecast_growth_projection` adds the growth fields. All existing forecasts get
**Growth = 0%**, so no projection is created and their results stay the same. To add a projection to an
existing forecast, edit it and enter a growth %.

### Demo users (`load_sample_data`, password `Demo@12345`)

| Username       | Role     |
|----------------|----------|
| admin_user     | Admin    |
| analyst_user   | Analyst  |
| analyst2_user  | Analyst  |
| approver_user  | Approver |
| viewer_user    | Viewer   |

### Run tests

```bash
python manage.py test forecasting
```

There are 92 tests, including 18 for the growth projection.

---

## 2. Growth forecast: inputs

| Field | Meaning | Default |
|---|---|---|
| Volume Growth (%) | Change in volume per growth period. Negative = decline. 0 = no projection | 0 |
| Growth Per | Daily, Weekly, Monthly, Quarterly, Half-Yearly or Yearly | Monthly |
| Forecast Horizon (Months) | How far ahead to project, 1-60 months | 12 |

## 3. Growth forecast: logic

Growth is compounded and applied in steps, once per growth period:

```
Projected volume (month m) = Current volume x (1 + Growth% / 100) ^ periods_elapsed(m)
```

| Growth Per | periods_elapsed(m) | Example: month 6 |
|---|---|---|
| Daily | m x working days per month | 6 x 22 = 132 |
| Weekly | floor(m x days per month / days per week) | floor(132 / 5) = 26 |
| Monthly | m | 6 |
| Quarterly | floor(m / 3) | 2 |
| Half-Yearly | floor(m / 6) | 1 |
| Yearly | floor(m / 12) | 0 |

For **each month from 0 (today) to the horizon**, the system reruns the full calculation with the projected volume:
deterministic FTE, Monte Carlo (if on, using the same seed every month), and the status rules. **Current FTE stays fixed.**

| Output | Meaning |
|---|---|
| Sufficient Until | Last month in which current FTE is still enough |
| More Manpower Needed From | First month with **Less Manpower** (month 0 = already short today) |
| Required FTE at horizon | Calculated FTE at the last month |
| FTE Needed at horizon | ceil(P90) if Monte Carlo is on, otherwise ceil(Required FTE) |
| Additional FTE | FTE Needed minus Current FTE |
| Manpower Plan | Each month in which the FTE needed increases, with the total and the additional FTE |

**Example:** 2,200 invoices a month, 10 minutes each, 3 FTE, 5% monthly growth, Monte Carlo off.
Required FTE is 2.45 x 1.05^m: 2.98 at month 4, which is still sufficient, and **3.13 at month 5, the first month with Less Manpower**.
By month 12 the requirement is 4.40 FTE, so 5 FTE are needed (2 more). The manpower plan is: 4 FTE from month 5 and 5 FTE from month 11.

With Monte Carlo on, the shortfall usually comes **earlier**, because the "sufficiency below 80%" rule
triggers before the average requirement exceeds current FTE.

Growth settings that would multiply volume by more than 1,000x within the horizon are rejected
(`GROWTH_MAX_FACTOR` in settings).

## 4. Where the growth forecast appears

| Screen | What you see |
|---|---|
| Add/Edit Forecast | Section 4, "Future Growth Forecast", with a live preview (e.g. "After 12 months volume will be 1.80x today") |
| Result / Detail | Summary sentence, 4 KPI cards, a projection chart (bars coloured by status, with lines for Required, P90 and Current FTE), the manpower plan, and a month-by-month table with the first short month highlighted |
| Dashboard | A "Future Shortage Risk" alert and card, an "Additional FTE at Horizon" card, a Future Outlook column, and a "Required FTE at horizon" bar on the FTE chart |
| History / Reports | A **Future outlook** filter (Short in future / Short now / Sufficient through horizon / No growth projection) and an outlook badge |
| Scenario Comparison | An "Ongoing growth %" override per scenario, plus rows for Shortfall From, Required FTE at Horizon, FTE Needed and Status at Horizon |
| Excel upload | New columns: Growth Percentage, Growth Period, Forecast Horizon Months. Templates without these columns still upload |
| Excel report | A "Growth Projection" column group and a month-by-month "Growth Projection" sheet. The single-forecast export includes a projection sheet |

---

## 5. Today's status rules (unchanged)

1. Current FTE = 0 -> Less Manpower
2. Current FTE < Required FTE -> Less Manpower
3. Sufficiency probability < 80% -> Less Manpower *(only when Monte Carlo is on)*
4. Utilization < 70% -> Higher Manpower
5. Otherwise -> Sufficient Manpower (+ High Utilization Risk when utilization > 90%)

The same rules are applied to every projected month.

## 6. Settings (`settings.FORECASTING`)

```python
"SUFFICIENCY_THRESHOLD": 80, "UTILIZATION_LOWER": 70, "UTILIZATION_UPPER": 90,
"MONTE_CARLO_DEFAULT": True, "HORIZON_DEFAULT": 12, "HORIZON_MAX": 60, "GROWTH_MAX_FACTOR": 1000,
```

## 7. Maker-checker

Every new, edited, recalculated or uploaded forecast is **Pending Approval**. Approvers can never approve their own forecast,
and rejection requires a comment. Changing the growth inputs recalculates the forecast and resets it to Pending.

## 8. PostgreSQL / production

Set `DB_ENGINE=postgresql` and `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, then run
`pip install "psycopg[binary]"` and `python manage.py migrate`. For production, set `DJANGO_SECRET_KEY`,
`DJANGO_DEBUG=False` and `DJANGO_ALLOWED_HOSTS`, then run `python manage.py collectstatic`.
