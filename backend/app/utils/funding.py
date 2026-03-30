def normalize_funding_rate(rate: float, side: str) -> float:
    """
    Normalize funding rate based on position side.
    For long positions, a positive rate means paying (cost), so we negate it.
    For short positions, a positive rate means receiving (profit).
    """
    if side == "long":
        return -rate
    elif side == "short":
        return rate
    else:
        raise ValueError(f"Invalid side: {side}. Must be 'long' or 'short'.")


def calc_spread(short_price: float, long_price: float) -> float:
    """
    Calculate spread percentage between short and long prices.
    Returns the percentage difference: (short - long) / long * 100
    """
    if long_price == 0:
        return 0.0
    return (short_price - long_price) / long_price * 100


def calc_funding_diff(long_rate: float, short_rate: float) -> float:
    """
    Calculate the funding rate difference (annualized or per-period).
    Positive means net cost, negative means net profit.
    long_rate: funding rate on the long exchange (already normalized)
    short_rate: funding rate on the short exchange (already normalized)
    """
    return long_rate - short_rate
