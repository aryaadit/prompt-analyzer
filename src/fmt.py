"""Small formatting helpers shared by the diagnosis and the receipt page."""


def money(value):
    """Dollars, always two decimals; anything under one cent is "<$0.01". None means no public price."""
    if value is None:
        return 'no public price'
    if 0 < value < 0.01:
        return '<$0.01'
    return '$%s' % format(value, ',.2f')


def money_column(values):
    """A formatter for one table column. A true zero is "$0.00" and nothing else is, so no row hides a real amount.

    When every non-zero value is at least one cent, rows have two decimals. Otherwise rows have four, so small
    amounts stay readable, and anything under $0.0001 reads "<$0.0001".
    """
    small = any(0 < v < 0.01 for v in values)

    def one(value):
        if not value:
            return '$0.00'
        if not small:
            return money(value)
        return '<$0.0001' if value < 0.0001 else '$%s' % format(value, ',.4f')
    return one


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
