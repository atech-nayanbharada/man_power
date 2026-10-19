# Manpower Capacity Planning and Monte Carlo Forecasting System

Django application that tells you whether each process has **Less**, **Sufficient** or **Higher** manpower today and
in the future, with Monte Carlo risk, volume / AHT growth forecasting and a CEO-level Executive Dashboard.

## Setup

```bash
cd manpower_forecasting
python -m venv venv
venv\Scripts\activate          # Windows   (source venv/bin/activate on Linux/macOS)
pip install -r requirements.txt
python manage.py migrate
python manage.py setup_roles
python manage.py createsuperuser
python manage.py load_sample_data      # optional demo data
python manage.py runserver
```

Demo users (password `Demo@12345`): `admin_user`, `analyst_user`, `analyst2_user`, `approver_user`, `viewer_user`.

### Upgrading an existing installation

1. Stop the server.
2. Copy all files over your project (keep `db.sqlite3` / your PostgreSQL database).
3. Delete old test files that are not in this ZIP (e.g. `forecasting/tests/test_auto_total_time.py`,
   `test_aht_button.py`, `test_decimal_fte.py`), and `apply_decimal_fte.py` if you have it.
4. `python manage.py migrate` (migrations 0001-0006; no new migration in this release).
5. Start the server again (template filters such as `fte_dec` are loaded at start-up).

Tests: `python manage.py test forecasting` (37 tests).

## Add Forecast - Process Details

| Field | Rule |
|---|---|
| Frequency | Daily / Weekly / Monthly / Quarterly / Half-Yearly / Yearly |
| Volume | Greater than 0, **decimals allowed** (e.g. 6305.5) |
| Current FTE | 0 or more, **decimals allowed** (e.g. 2.5) |
| AHT (Minutes per Item) | Type the measured AHT, **or click Calculate AHT** |

**Calculate AHT** (contingency is not deducted):

```
AHT = Current FTE x Working hours per day x Working days in the period x 60 / Volume
```

Example: Yearly, 6,305 items, 180 FTE, 8 h, 22 days a month ->
180 x 8 x 264 = 380,160 team hours x 60 / 6,305 = **3,617.70 min per item**.

Contingency is still applied when Required FTE is calculated (8 h x 85% = 408 productive minutes), so a calculated
AHT always gives utilization = 100% / (1 - contingency) (117.6% with 15%) and **Less Manpower**. The form, result
page, lists, dashboards and Excel report flag this ("Calculated AHT") because the status is then not a real
measure. Enter the measured AHT for a real Less / Sufficient / Higher status. If AHT is left blank, it is calculated
on save with the same formula. If Current FTE is 0, the measured AHT must be entered.

## Calculation (shown step by step on the Result page)

| Step | Formula |
|---|---|
| Productive minutes per FTE per day | hours x 60 x (1 - contingency) |
| Daily volume | volume / working days in the period |
| Workload in FTE | daily volume x AHT / productive minutes |
| Required FTE | workload rounded **up** to whole people |
| Gap | Current FTE (as entered, e.g. 2.5) - Required FTE |
| Utilization | workload FTE / Current FTE |

Working days per week / month accept decimals (5.5 for a Saturday half day; 23.83 days a month).
Status: Current FTE 0 or below workload = Less; Monte Carlo sufficiency < 80% = Less; utilization < 70% = Higher;
otherwise Sufficient (High Utilization Risk above 90%).

## Bulk upload

Template columns include **Current FTE** (decimals), **AHT Minutes** (optional) and **Total Time Spent Hours**
(optional alternative). If both are blank, AHT is calculated from team working hours and the row is listed after
the upload. Older templates with *Average Processing Time* + *Time Unit* still work.

## Other features

Monte Carlo (P50-P99, sufficiency), future forecast (volume growth % and AHT change % per period), scenario
comparison (Proposed FTE accepts decimals), Excel reports, Executive Dashboard, maker-checker approval and audit trail.

## PostgreSQL / production

Set `DB_ENGINE=postgresql` and the `DB_*` variables, `pip install "psycopg[binary]"`, then `python manage.py migrate`.
For production set `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=False`, `DJANGO_ALLOWED_HOSTS` and run `python manage.py collectstatic`.
