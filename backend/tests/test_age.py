from datetime import date

from services.age import age_on


def test_birthday_boundary():
    b = date(1990, 6, 15)
    assert 34.99 < age_on(b, date(2025, 6, 14)) < 35.0
    assert 35.0 <= age_on(b, date(2025, 6, 15)) < 35.01


def test_leap_day_birth():
    assert 24.99 < age_on(date(2000, 2, 29), date(2025, 2, 28)) < 25.01


def test_future_birth_clamped():
    assert age_on(date(2030, 1, 1), date(2025, 1, 1)) == 0.0
