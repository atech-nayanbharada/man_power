"""
Step-by-step "How the numbers are calculated" breakdown for the Result page.
Shows whether AHT was entered or calculated with Calculate AHT, then every step to FTE.
"""
from .calculations import FREQUENCY_DAYS_TEXT, ceil_decimal, fmt, to_decimal, working_days_in_period


def _n(value, places=2):
    if value is None:
        return "-"
    return f"{to_decimal(value):,.{places}f}"


def calculation_steps(f):
    wk, mo = to_decimal(f.working_days_per_week), to_decimal(f.working_days_per_month)
    period_days = working_days_in_period(f.frequency, wk, mo)
    total_h = to_decimal(f.total_time_spent_hours)
    aht = to_decimal(f.processing_time_minutes)
    hours = to_decimal(f.working_hours_per_day)
    cont = to_decimal(f.contingency_percentage)
    prod = to_decimal(f.productive_minutes_per_fte)
    daily = to_decimal(f.daily_volume)
    workload = to_decimal(f.workload_minutes)
    req = to_decimal(f.required_fte)
    people = int(ceil_decimal(req))
    current = to_decimal(f.current_fte)
    current_txt = fmt(current)
    freq = f.get_frequency_display()
    days_text = FREQUENCY_DAYS_TEXT[f.frequency].format(wk=fmt(wk), mo=fmt(mo))

    if f.aht_is_calculated:
        available = f.available_time_hours
        steps = [
            {"group": "Average handling time (AHT)", "label": "Team time available in the period",
             "formula": f"{current_txt} FTE x {_n(hours)} h x {fmt(period_days)} days (contingency not deducted)",
             "result": f"{_n(available)} hours"},
            {"group": "", "label": "AHT (calculated with Calculate AHT)", "key": True, "warn": True,
             "formula": f"{_n(available)} h x 60 / {_n(f.volume)} items", "result": f"{_n(aht)} min per item"},
        ]
    else:
        steps = [
            {"group": "Average handling time (AHT)", "label": "AHT (entered)", "key": True,
             "formula": "Entered by user (measured time per item)", "result": f"{_n(aht)} min per item"},
            {"group": "", "label": "Implied total time spent",
             "formula": f"{_n(aht)} min x {_n(f.volume)} items / 60", "result": f"{_n(total_h)} hours"},
        ]
    gap = current - people
    steps += [
        {"group": "Working capacity", "label": "Working week",
         "formula": f"{fmt(wk)} days x {_n(hours)} hours", "result": f"{_n(wk * hours)} hours per person"},
        {"group": "", "label": "Productive time per person per day",
         "formula": f"{_n(hours)} h x 60 x (1 - {_n(cont)}% contingency)", "result": f"{_n(prod)} min"},
        {"group": "Workload", "label": f"Working days in the {freq.lower()} period",
         "formula": days_text, "result": f"{fmt(period_days)} days"},
        {"group": "", "label": "Daily volume", "formula": f"{_n(f.volume)} / {fmt(period_days)} days",
         "result": f"{_n(daily)} items"},
        {"group": "", "label": "Daily workload", "formula": f"{_n(daily)} items x {_n(aht)} min",
         "result": f"{_n(workload)} min"},
        {"group": "Manpower", "label": "Workload in FTE",
         "formula": f"{_n(workload)} min / {_n(prod)} min per person", "result": f"{_n(req)} FTE of work"},
        {"group": "", "label": "Required FTE (whole people)", "key": True,
         "formula": f"{_n(req)} rounded up", "result": f"{people} FTE"},
        {"group": "", "label": "Current FTE", "formula": "Entered", "result": f"{current_txt} FTE"},
        {"group": "", "label": "Gap", "formula": f"{current_txt} - {people}",
         "result": ("+" if gap > 0 else "") + f"{fmt(gap)} FTE"},
    ]
    if f.utilization_percentage is not None:
        steps.append({"group": "", "label": "Utilization", "formula": f"{_n(req)} / {current_txt} x 100",
                      "result": f"{_n(f.utilization_percentage)}%"})
    if f.breakeven_aht_minutes is not None:
        steps.append({"group": "", "label": "Break-even AHT",
                      "formula": f"{current_txt} FTE x {_n(prod)} min / {_n(daily)} items",
                      "result": f"{_n(f.breakeven_aht_minutes)} min ({_n(f.aht_headroom_percentage)}% vs AHT)"})
    return steps
