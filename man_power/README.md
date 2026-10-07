# Manpower Capacity Planning and Monte Carlo Forecasting System

A Django web application that tells you whether each process has **Less**, **Sufficient** or **Higher** manpower
**today** and **in the future**, and rolls everything up into a CEO-level **Executive Dashboard**.

* **Monte Carlo** (optional): risk from day-to-day variability (P90 FTE, sufficiency probability).
* **Future forecast** (optional): projects **volume growth** and **AHT (Average Handling Time) change**, then
  recalculates manpower month by month.
* **Executive Dashboard**: health score, hiring need and budget, risks, redeployment and headcount outlook.

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

Open http://127.0.0.1:8000/. Demo users (password `Demo@12345`): `admin_user`, `analyst_user`, `analyst2_user`,
`approver_user`, `viewer_user`.

**Upgrading:** copy the new files over the old project and run `python manage.py migrate`.
Migration `0004_manpowerforecast_aht_change` adds the AHT fields. Existing forecasts get **AHT change = 0%**,
so their results do not change.

**Tests:** `python manage.py test forecasting` runs 122 tests.

---

## 2. Future forecast inputs (form section 4, all optional)

| Group | Field | Meaning | Default |
|---|---|---|---|
| Volume | Volume Growth (%) | Volume change per period. Negative = decline | 0 |
| Volume | Growth Per | Daily / Weekly / Monthly / Quarterly / Half-Yearly / Yearly | Monthly |
| Both | Forecast Horizon (Months) | How far ahead to project (1-60) | 12 |
| **AHT** | **AHT Change (%)** | Change in time per item per period. **Positive = slower** (more complexity, new checks), **negative = faster** (automation, training, learning curve) | 0 |
| **AHT** | **AHT Change Per** | How often the AHT % is applied (compounded) | Monthly |

A projection is calculated when **either** volume growth **or** AHT change is not 0.
The form shows a live preview, e.g. *"After 12 months: volume 1.80x, AHT 10.00 → 7.85 min, workload 1.41x today"*.

## 3. Forecast logic

Each driver compounds on its **own** period:

```
Volume(m)   = Volume x (1 + Volume growth% / 100) ^ periods_elapsed(volume period, m)
AHT(m)      = AHT    x (1 + AHT change%    / 100) ^ periods_elapsed(AHT period, m)
Workload(m) = Volume(m) x AHT(m)            (workload factor = volume factor x AHT factor)
```

| Period | periods_elapsed(m) |
|---|---|
| Daily | m x working days per month |
| Weekly | floor(m x days per month / days per week) |
| Monthly | m |
| Quarterly | floor(m / 3) |
| Half-Yearly | floor(m / 6) |
| Yearly | floor(m / 12) |

For every month 0..horizon the full calculation (deterministic + optional Monte Carlo + status rules) is rerun
with the projected volume and AHT. **Current FTE stays fixed.**

**Example:** 2,200 invoices a month, 10 minutes each, 3 FTE, Monte Carlo off, 12-month horizon.

| Scenario | AHT at month 12 | Required FTE at month 12 | Shortfall from | FTE needed |
|---|---|---|---|---|
| Volume +5%/month only | 10.00 min | 4.40 | Month 5 | 5 |
| Volume +5%/month, **AHT -2%/month** | 7.85 min | 3.45 | **Month 8** | 4 |
| **AHT +10%/quarter** only | 14.64 min | 3.59 | Month 9 | 4 |

The 2% monthly AHT reduction delays the shortage by 3 months and saves 1 FTE.

Settings that multiply volume, AHT or the combined workload by more than 1,000x within the horizon are rejected
(`GROWTH_MAX_FACTOR`).

### Where AHT appears
| Screen | AHT output |
|---|---|
| Result / Detail | Projection drivers line, an "AHT at horizon" card, and AHT (min) and workload-factor columns in the month-by-month table |
| Scenario Comparison | An "Ongoing AHT change %" override per scenario and an AHT-at-horizon row |
| Excel upload | `AHT Change Percentage` and `AHT Change Period` columns (older templates still work) |
| Excel report | AHT inputs, AHT at horizon, and AHT per month on the Growth Projection sheet |
| Executive Dashboard | Uses the projection automatically for hires by the outlook date, risks and hiring plan |

---

## 4. Today's status rules

1. Current FTE = 0 -> Less Manpower
2. Current FTE < Required FTE -> Less Manpower
3. Monte Carlo sufficiency < 80% -> Less Manpower (only when Monte Carlo is on)
4. Utilization < 70% -> Higher Manpower
5. Otherwise -> Sufficient Manpower (+ High Utilization Risk above 90%)

The same rules are applied to every projected month.

## 5. Executive Dashboard

Menu: **Overview -> Executive Dashboard**. It shows the Health Score (40% Coverage + 30% Efficiency + 30% Resilience),
net hires now and at the outlook date with annual cost, redeployable FTE, function scorecard, top risks, risk matrix,
quarterly hiring plan and redeployment moves. It can be exported to Excel or printed to PDF.
Settings: `EXEC_COST_PER_FTE`, `EXEC_CURRENCY`, `EXEC_HORIZON_MONTHS`, `EXEC_TARGET_UTILIZATION`.

## 6. Maker-checker

Every new, edited, recalculated or uploaded forecast is Pending until it is approved. Approvers can never approve
their own forecast, and rejection requires a comment.

## 7. PostgreSQL / production

Set `DB_ENGINE=postgresql` and the `DB_*` variables, then `pip install "psycopg[binary]"` and `python manage.py migrate`.
For production, set `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False` and `DJANGO_ALLOWED_HOSTS`, then run `python manage.py collectstatic`.
