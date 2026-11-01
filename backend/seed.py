"""Demo data: python -m seed  (fictional numbers)."""

from datetime import date

import db
from app import create_app
from models import Account, AllowedPlanMenu, Holding, Liability, PlannedEvent, UserProfile
from services import ingestion


def seed(app=None):
    app = app or create_app()
    with app.app_context():
        s = db.session()
        if s.query(Account).count():
            print("Database already has accounts; skipping seed.")
            return
        p = s.get(UserProfile, 1) or UserProfile(id=1)
        p.name, p.birth_date, p.target_retirement_age = "Demo", date(1988, 6, 15), 52
        p.annual_income, p.monthly_expenses_current, p.monthly_expenses_retirement = 150000, 5500, 5000
        p.monthly_contribution, p.emergency_fund_target_months = 3500, 6
        p.current_money_market_yield, p.money_market_yield_override = 0.046, True
        p.spouse_name, p.spouse_birth_date, p.spouse_annual_income = "Demo Spouse", date(1990, 2, 1), 95000
        p.social_security_monthly, p.spouse_social_security_monthly = 3100, 2300
        p.home_value = 480000
        s.merge(p)
        spec = [
            (
                "Fidelity NetBenefits 401k",
                "FIDELITY_NETBENEFITS",
                "PRE_TAX_401K",
                "SAFE_CORE",
                True,
                [
                    ("FXAIX", "Fidelity 500 Index", 520000 / 190, 190, "US_EQUITY"),
                    ("FSPSX", "Fidelity International Index", 90000 / 50, 50, "INTL_EQUITY"),
                    ("FXNAX", "Fidelity US Bond Index", 60000 / 11, 11, "BOND"),
                ],
            ),
            (
                "Nationwide 401k",
                "NATIONWIDE",
                "PRE_TAX_401K",
                "SAFE_CORE",
                True,
                [("NATIONWIDE-S-P-500-INDEX", "Nationwide S&P 500 Index Fund", 140000 / 40, 40, "US_EQUITY")],
            ),
            (
                "Fidelity Individual Brokerage",
                "FIDELITY_RETAIL",
                "TAXABLE_BROKERAGE",
                "AGGRESSIVE_SATELLITE",
                False,
                [("VGT", "Vanguard Information Technology ETF", 45000 / 600, 600, "SECTOR_ETF"), ("NVDA", "NVIDIA Corp", 20000 / 130, 130, "INDIVIDUAL_STOCK")],
            ),
            (
                "Fidelity HSA",
                "FIDELITY_RETAIL",
                "HSA",
                "MODERATE_GROWTH",
                False,
                [("FXAIX", "Fidelity 500 Index Fund", 190, 60, "US_EQUITY")],
            ),
            (
                "Cash / Money Market",
                "FIDELITY_RETAIL",
                "CASH_MMF",
                "SAFE_CORE",
                False,
                [("SPAXX", "Fidelity Government Money Market", 60000, 1, "MONEY_MARKET")],
            ),
        ]
        owners = {"Nationwide 401k": "SPOUSE", "Cash / Money Market": "JOINT"}
        for name, inst, bucket, tier, restricted, holds in spec:
            a = Account(name=name, institution=inst, tax_bucket=bucket, risk_tier=tier, is_restricted_plan=restricted, owner=owners.get(name, "SELF"))
            s.add(a)
            s.flush()
            for sym, hn, price, shares, ac in holds:
                s.add(
                    Holding(
                        account_id=a.id,
                        symbol=sym,
                        name=hn,
                        shares=shares,
                        current_price=price,
                        market_value=price * shares,
                        cost_basis_total=price * shares * 0.8,
                        asset_class=ac,
                    )
                )
            if restricted:
                for sym, hn, ac, er in [
                    ("FXAIX", "Fidelity 500 Index", "US_EQUITY", 0.00015),
                    ("FSKAX", "Fidelity Total Market Index", "US_EQUITY", 0.00015),
                    ("FCNTX", "Fidelity Contrafund", "US_EQUITY", 0.0039),
                    ("FSPSX", "Fidelity International Index", "INTL_EQUITY", 0.00035),
                    ("FXNAX", "Fidelity US Bond Index", "BOND", 0.00025),
                ]:
                    s.add(AllowedPlanMenu(account_id=a.id, ticker_or_cusip=sym, fund_name=hn, asset_class=ac, expense_ratio=er))
        s.add_all(
            [
                Liability(
                    name="Home mortgage",
                    kind="MORTGAGE",
                    balance=310000,
                    apr=0.0325,
                    monthly_payment=1850,
                    payoff_date=date(2049, 3, 1),
                    escrow_monthly=650,
                    owner="JOINT",
                    extra_monthly_payment=300,
                    extra_payment_until="RETIREMENT",
                ),
                Liability(name="Car loan", kind="AUTO", balance=18000, apr=0.059, monthly_payment=520),
                Liability(name="Rewards card", kind="CARD", balance=2400, apr=0.2299, monthly_payment=150),
                PlannedEvent(name="Two new cars", kind="PURCHASE", amount=70000, start_year=date.today().year + 3, repeat_every_years=10, owner="JOINT"),
                PlannedEvent(name="Roof replacement", kind="PURCHASE", amount=18000, start_year=date.today().year + 8),
            ]
        )
        s.flush()
        ingestion.snapshot_net_worth(s)
        s.commit()
        print("Seeded demo data.")


if __name__ == "__main__":
    seed()
