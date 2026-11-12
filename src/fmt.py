"""Small formatting helpers shared by the diagnosis and the receipt page."""


def money(value):
    """Dollars: two decimals, or four for amounts under a cent. None means no public price."""
    if value is None:
        return 'no public price'
    return '$%s' % format(value, ',.4f' if 0 < abs(value) < 0.01 else ',.2f')


def count(value):
    """A whole number with thousands separators."""
    return format(int(round(value)), ',')


def percent(share):
    """A share (0 to 1) as a percent: 12.3%, or 0.4% for small ones."""
    value = 100 * share
    return '%.1f%%' % value if value < 10 else '%.0f%%' % value


def minutes(value):
    """Minutes as plain words: 'under a minute', '18 minutes', '2.5 hours'."""
    if value is None:
        return 'an unknown number of minutes'
    if value < 1:
        return 'under a minute'
    if value < 90:
        return '%d minutes' % round(value)
    return '%.1f hours' % (value / 60)
