"""Onboarding wizard state and the data-completeness meter (U2).

A step is "done" when the data it asks for exists (or the user skipped it), so the wizard is resumable and never
asks twice. The completeness score is a weighted checklist computed here, never by the LLM or the browser.
"""

from typing import Any

from sqlalchemy.orm import Session

from models import Account, Holding, IngestionLog, Liability, Pension, UserProfile

STEPS = [
    ("household", "Household", "Who the plan is for: ages, filing status, income."),
    ("accounts", "Accounts", "Which accounts you have and where they are held."),
    ("upload", "Upload", "Statements or exports so holdings and balances are real."),
    ("goals", "Goals", "When you want to stop working and what you expect to spend."),
    ("plan", "First plan", "Run the simulation on what you entered."),
]
STEP_IDS = [s[0] for s in STEPS]


def _state(p: UserProfile) -> dict:
    st = dict(p.onboarding or {})
    st.setdefault("skipped", [])
    st.setdefault("completed", False)
    st.setdefault("dismissed", False)
    return st


def _done_by_data(s: Session, p: UserProfile) -> dict[str, bool]:
    return {
        "household": bool(p.annual_income) and p.name not in ("", "Me"),
        "accounts": s.query(Account).count() > 0,
        "upload": s.query(Holding).count() > 0 or s.query(IngestionLog).filter(IngestionLog.status == "OK").count() > 0,
        "goals": bool(p.monthly_expenses_retirement),
        # the plan step is done once the earlier inputs exist; running it is what the step does
        "plan": False,
    }


def _inp(key: str, label: str, weight: int, filled: bool, improves: str, where: str) -> dict[str, Any]:
    return {"key": key, "label": label, "weight": weight, "filled": bool(filled), "improves": improves, "where": where}


def completeness(s: Session, p: UserProfile) -> dict:
    """Weighted checklist of inputs; `improves` says what gets more accurate when the input is filled."""
    has_spouse = bool(p.spouse_birth_date)
    inputs = [
        _inp("income", "Annual income", 10, bool(p.annual_income), "savings capacity, taxes and Social Security-linked projections", "Household"),
        _inp(
            "expenses_retirement",
            "Retirement spending",
            15,
            bool(p.monthly_expenses_retirement),
            "every success rate and the earliest viable retirement age",
            "Goals",
        ),
        _inp("expenses_current", "Current spending", 10, bool(p.monthly_expenses_current), "how much you can save now and the emergency-fund target", "Goals"),
        _inp("accounts", "Accounts", 15, s.query(Account).count() > 0, "the starting balances the Monte Carlo simulation grows", "Accounts"),
        _inp("holdings", "Holdings", 15, s.query(Holding).count() > 0, "asset allocation, concentration and rebalancing", "Upload"),
        _inp("social_security", "Social Security estimate", 10, bool(p.social_security_monthly), "income after 62 and the bridge-phase gap", "Household"),
        _inp(
            "aca_premium",
            "Marketplace premium quote",
            5,
            bool(p.aca_benchmark_premium_monthly),
            "pre-Medicare health cost (otherwise an age-based estimate is used)",
            "Plan -> health care",
        ),
        _inp(
            "spouse",
            "Spouse details",
            5,
            (not has_spouse) or bool(p.spouse_social_security_monthly),
            "household income, survivor risk and Roth timing",
            "Household",
        ),
        _inp("liabilities", "Debts", 5, s.query(Liability).count() > 0, "payoff timing and cash-flow in the plan (skip if debt-free)", "Portfolio"),
        _inp("pension", "Pension", 5, s.query(Pension).count() > 0, "guaranteed retirement income (skip if none)", "Plan"),
        _inp("home", "Home value", 5, bool(p.home_value), "net worth and downsizing scenarios", "Plan -> real estate"),
    ]
    total = sum(i["weight"] for i in inputs)
    got = sum(i["weight"] for i in inputs if i["filled"])
    missing = sorted((i for i in inputs if not i["filled"]), key=lambda i: -i["weight"])
    return {
        "score": round(100 * got / total),
        "inputs": inputs,
        "next_best": {k: missing[0][k] for k in ("key", "label", "improves", "where")} if missing else None,
    }


def status(s: Session, p: UserProfile) -> dict:
    st = _state(p)
    data = _done_by_data(s, p)
    steps: list[dict] = []
    for sid, title, blurb in STEPS:
        skipped = sid in st["skipped"]
        steps.append(
            {
                "id": sid,
                "title": title,
                "blurb": blurb,
                "done": data[sid] or skipped or (sid == "plan" and st["completed"]),
                "skipped": skipped and not data[sid],
            }
        )
    current = st.get("step") if st.get("step") in STEP_IDS else None
    if current is None:
        current = next((x["id"] for x in steps if not x["done"]), "plan")
    # first run: nothing entered, never finished or dismissed
    fresh = not st["completed"] and not st["dismissed"] and not data["accounts"] and not data["household"]
    return {
        "current": current,
        "steps": steps,
        "completed": st["completed"],
        "dismissed": st["dismissed"],
        "show": not st["completed"] and not st["dismissed"],
        "first_run": fresh,
        "completeness": completeness(s, p),
    }


def update(s: Session, p: UserProfile, *, step=None, skip=None, completed=None, dismissed=None) -> dict:
    st = _state(p)
    if step:
        st["step"] = step
    if skip and skip not in st["skipped"]:
        st["skipped"].append(skip)
    if completed is not None:
        st["completed"] = completed
    if dismissed is not None:
        st["dismissed"] = dismissed
    p.onboarding = st  # reassign so SQLAlchemy sees the JSON change
    s.commit()
    return status(s, p)
