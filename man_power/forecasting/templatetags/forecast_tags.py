from decimal import ROUND_CEILING, Decimal, InvalidOperation

from django import template

register = template.Library()


def _dec(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


@register.filter
def num(value, places=2):
    if value is None or value == "":
        return "-"
    d = _dec(value)
    return value if d is None else f"{d:,.{int(places)}f}"


@register.filter
def fte(value):
    """Required headcount in whole people, rounded UP (2.45 -> 3)."""
    if value is None or value == "":
        return "-"
    d = _dec(value)
    if d is None:
        return value
    return f"{int(d.quantize(Decimal('1'), rounding=ROUND_CEILING)):,}"


@register.filter
def fte_dec(value):
    """FTE exactly as entered, without trailing zeros: 3, 2.5, 0.75."""
    if value is None or value == "":
        return "-"
    d = _dec(value)
    if d is None:
        return value
    text = f"{d.quantize(Decimal('0.01')):f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


@register.filter
def days(value):
    return fte_dec(value)


@register.filter
def pct(value, places=2):
    if value is None or value == "":
        return "N/A"
    return f"{num(value, places)}%"


@register.filter
def signed(value, places=2):
    if value is None or value == "":
        return "-"
    d = Decimal(str(value))
    return f"+{num(d, places)}" if d > 0 else num(d, places)


@register.filter
def signed_fte(value):
    if value is None or value == "":
        return "-"
    d = Decimal(str(value))
    return f"+{fte_dec(d)}" if d > 0 else fte_dec(d)


@register.filter
def gap_css(value):
    if value is None:
        return "text-muted"
    d = Decimal(str(value))
    if d < 0:
        return "text-danger"
    if d > 0:
        return "text-success"
    return "text-muted"


@register.simple_tag(takes_context=True)
def query_transform(context, **kwargs):
    params = context["request"].GET.copy()
    for k, v in kwargs.items():
        if v is None:
            params.pop(k, None)
        else:
            params[k] = v
    return params.urlencode()
