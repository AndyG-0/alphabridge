from datetime import date


def age_on(birth: date, today: date | None = None) -> float:
    """Age in fractional years on `today` (default: current date)."""
    return max(((today or date.today()) - birth).days / 365.2425, 0.0)
