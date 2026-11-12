"""Small formatting helpers shared by the diagnosis and the receipt page."""


def money(value):
    """Dollars, always two decimals; anything under one cent is "<$0.01". None means no public price."""
    if value is None:
        return 'no public price'
    if 0 < value < 0.01:
        return '<$0.01'
    return '$%s' % format(value, ',.2f')


def money_column(values):
    """A formatter for one table column: every row gets the same number of decimals.

    Two decimals when every non-zero value is at least one cent; four otherwise, so small rows
    stay readable and "$0.0100" never sits next to "$0.12" with a different number of decimals.
    """
    decimals = 2 if all(v >= 0.01 for v in values if v) else 4
    return lambda value: '$%s' % format(value, ',.%df' % decimals)


def count(value):
    """A whole number with thousands separators."""
    return format(int(round(value)), ',')


def percent(share):
    """A share (0 to 1) as a percent: 12%, 4.5%, "<0.1%" for tiny ones, "0%" for none."""
    value = 100 * share
    if value <= 0:
        return '0%'
    if value < 0.1:
        return '<0.1%'
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


def short_tokens(value):
    """Tokens for an axis label: 950, 12k, 1.2M."""
    if value >= 1_000_000:
        return ('%.1fM' % (value / 1e6)).replace('.0M', 'M')
    if value >= 1000:
        return ('%.1fk' % (value / 1e3)).replace('.0k', 'k')
    return '%d' % value
