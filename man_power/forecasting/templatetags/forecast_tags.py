from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def num(value, places=2):
    """Format a number with thousands separators; '-' for empty values."""
    if value is None or value == "":
        return "-"
    try:
        return f"{Decimal(str(value)):,.{int(places)}f}"
    except (InvalidOperation, ValueError, TypeError):
        return value


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
    """Rebuild the current query string with updated params (used by pagination)."""
    params = context["request"].GET.copy()
    for k, v in kwargs.items():
        if v is None:
            params.pop(k, None)
        else:
            params[k] = v
    return params.urlencode()
