from django import template

register = template.Library()

@register.filter
def percentual(etapa, total):
    """Calcula porcentagem de conclusão."""
    try:
        return round((int(etapa) / int(total)) * 100, 0)
    except ZeroDivisionError:
        return 0
