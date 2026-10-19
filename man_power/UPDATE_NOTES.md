# Update v3: decimal Current FTE and Volume + AHT button (contingency not deducted)

Apply on top of `manpower_forecasting_auto_total_time.zip`.
This pack already includes everything from `aht_button_update_v2.zip`; you do not need the earlier packs.

## Step 1 - copy the files in this ZIP over your project (same paths)

| File | Change |
|---|---|
| forecasting/forms.py | Current FTE and Volume accept decimals; AHT field + calculated AHT; Proposed FTE (scenarios) accepts decimals |
| forecasting/services/calculations.py | Calculate AHT does not deduct contingency |
| forecasting/services/forecast_service.py | AHT entered / calculated |
| forecasting/services/explain.py | Calculation table shows Current FTE and gap with decimals |
| templates/forecasting/forecast_form.html | AHT field + Calculate AHT button |
| templates/partials/_calc_steps.html, _forecast_summary.html | Wording; Current FTE and gap with decimals |
| static/js/app.js | Calculate AHT button |
| forecasting/tests/helpers.py, test_aht_button.py, test_decimal_fte.py | Tests |
| apply_decimal_fte.py | Patch script for the remaining small edits (Step 2) |

## Step 2 - run the patch script from the project root (folder with manage.py)

    python apply_decimal_fte.py

It edits, and lists every change it makes:
* models.py - FTE gap keeps decimals (2.5 - 3 = -0.5)
* status.py, projection.py - messages show Current FTE as entered ("2.5 FTE")
* dashboard_service.py, excel_service.py - totals, report columns and the upload template accept decimal FTE
* views.py - Calculate AHT message wording; scenario default "Proposed FTE"
* forecast_tags.py - new `fte_dec` filter; all templates show Current FTE with decimals
* deletes the old forecasting/tests/test_auto_total_time.py

It is safe to run twice. If any edit is not found it prints the line so you can change it by hand.

## Step 3 - test

    python manage.py test forecasting

No database change: Current FTE and Volume were already stored with 2 decimal places.
Required FTE, P90 FTE and hiring numbers stay whole people (rounded up).
