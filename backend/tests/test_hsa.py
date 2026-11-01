from datetime import date

import services.hsa as hsa
from models import Account, Holding
from services import ingestion, planner
from services.institutions import attrs_for_name


def _acct(bucket, value, asset_class="US_EQUITY", owner="SELF"):
    a = Account(name=bucket, tax_bucket=bucket, owner=owner)
    a.holdings = [Holding(symbol="X", market_value=value, asset_class=asset_class)]
    return a


def test_hsa_name_inference_beats_cash_rule():
    assert attrs_for_name("Fidelity HSA")["tax_bucket"] == "HSA"
    assert attrs_for_name("Health Savings Account")["tax_bucket"] == "HSA"
    assert attrs_for_name("Ally Savings")["tax_bucket"] == "CASH_MMF"


def test_hsa_excluded_from_bridge_and_pretax_pools():
    taxable, pretax, pretax_sp, _, _ = planner._pools([_acct("TAXABLE_BROKERAGE", 100), _acct("HSA", 50_000)])
    assert (taxable, pretax, pretax_sp) == (100, 0, 0)
    assert planner.hsa_balance([_acct("TAXABLE_BROKERAGE", 100), _acct("HSA", 50_000)]) == 50_000


def test_hsa_cash_is_not_deployable_but_counts_in_net_worth(client):
    from db import session_scope

    with session_scope() as s:
        s.add(_acct("HSA", 1_000, "MONEY_MARKET"))
        s.commit()
        assert ingestion.cash_total(s) == 0
        t = ingestion.bucket_totals(s)
        assert t["dry_powder"] == 0 and t["satellite"] == 1_000


def test_limits_lookup():
    assert hsa.annual_limit(2026, family=False, age=40) == 4_400
    assert hsa.annual_limit(2026, family=True, age=40) == 8_750
    assert hsa.annual_limit(2026, family=False, age=55) == 5_400
    assert hsa.annual_limit(2030, family=False, age=40) == 4_400  # latest known year


def test_limits_table_has_source_and_is_fresh():
    assert hsa._data()["source_url"].startswith("https://www.irs.gov/")
    assert (date.today() - hsa.retrieved_on()).days < 366
