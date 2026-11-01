from datetime import date, timedelta

import pytest

from schemas import ProfileIn
from services import state_rules


def test_all_states_and_dc_present():
    assert len(state_rules.codes()) == 51 and {"AZ", "DC", "TX"} <= set(state_rules.codes())


def test_arizona_and_non_expansion_states():
    az = state_rules.rules_for("az")
    assert az["medicaid_expansion"] and az["adult_limit_fpl"] == 1.38 and az["agency"] == "AHCCCS" and az["known"]
    non = {c for c in state_rules.codes() if not state_rules.rules_for(c)["medicaid_expansion"]}
    assert non == {"AL", "FL", "GA", "KS", "MS", "SC", "TN", "TX", "WI", "WY"}


def test_unknown_state_falls_back_flagged():
    r = state_rules.rules_for("ZZ")
    assert r["medicaid_expansion"] and not r["known"]


def test_data_is_less_than_a_year_old():
    assert date.today() - state_rules.retrieved_on() < timedelta(days=366), "refresh data/state_rules.json"


def test_profile_state_validated():
    assert ProfileIn(state="az").state == "AZ"
    with pytest.raises(ValueError):
        ProfileIn(state="ZZ")
