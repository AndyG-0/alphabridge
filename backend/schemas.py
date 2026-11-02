from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from services import spending, state_rules


class OnboardingIn(BaseModel):
    step: Literal["household", "accounts", "upload", "goals", "plan"] | None = None  # resume point
    skip: Literal["household", "accounts", "upload", "goals", "plan"] | None = None  # mark a step skipped
    completed: bool | None = None
    dismissed: bool | None = None


class ProfileIn(BaseModel):
    name: str | None = None
    birth_date: date | None = None
    target_retirement_age: float | None = Field(None, ge=0, le=100)
    annual_income: float | None = Field(None, ge=0)
    employer_match_rate: float | None = Field(None, ge=0, le=5)
    employer_match_cap_pct: float | None = Field(None, ge=0, le=1)
    monthly_expenses_current: float | None = Field(None, ge=0)
    monthly_expenses_retirement: float | None = Field(None, ge=0)
    emergency_fund_target_months: float | None = Field(None, ge=0, le=60)
    current_money_market_yield: float | None = Field(None, ge=0, le=0.25)
    money_market_yield_override: bool | None = None
    tax_filing_status: Literal["SINGLE", "MFJ"] | None = None
    effective_tax_rate: float | None = Field(None, ge=0, le=0.6)
    monthly_contribution: float | None = Field(None, ge=0)
    risk_appetite: float | None = Field(None, ge=0, le=1)
    sector_concentration_limit: float | None = Field(None, ge=0.05, le=1)
    employer_symbol: str | None = Field(None, max_length=20, pattern=r"^[A-Za-z0-9.\-]*$")
    spouse_name: str | None = Field(None, max_length=120)
    spouse_birth_date: date | None = None
    spouse_annual_income: float | None = Field(None, ge=0)
    social_security_monthly: float | None = Field(None, ge=0)
    spouse_social_security_monthly: float | None = Field(None, ge=0)
    spouse_target_retirement_age: float | None = Field(None, ge=0, le=100)
    spouse_take_home_monthly: float | None = Field(None, ge=0)
    target_success_rate: float | None = Field(None, ge=0.5, le=0.99)
    ss_claim_age: float | None = Field(None, ge=62, le=70)
    spouse_ss_claim_age: float | None = Field(None, ge=62, le=70)
    state: str | None = Field(None, min_length=2, max_length=2)
    meets_community_engagement: bool | None = None
    aca_benchmark_premium_monthly: float | None = Field(None, ge=0)
    dental_vision_monthly: float | None = Field(None, ge=0)
    health_oop_annual: float | None = Field(None, ge=0)
    medicare_monthly_per_person: float | None = Field(None, ge=0)
    health_inflation: float | None = Field(None, ge=0, le=0.15)
    home_value: float | None = Field(None, ge=0)
    home_upkeep_pct: float | None = Field(None, ge=0, le=0.1)
    ltc_annual: float | None = Field(None, ge=0)
    ltc_years: float | None = Field(None, ge=0, le=15)
    spending_model: dict | None = None
    ltc_start_age: float | None = Field(None, ge=50, le=100)
    guardrails_enabled: bool | None = None
    target_allocation: dict[str, float] | None = None

    @field_validator("target_allocation")
    @classmethod
    def _valid_target(cls, v: dict[str, float] | None):
        if not v:
            return v
        from services.quant_engine import ASSET_ASSUMPTIONS

        bad = [k for k in v if k not in ASSET_ASSUMPTIONS]
        if bad:
            raise ValueError(f"unknown asset class: {', '.join(bad)}")
        if any(w < 0 for w in v.values()) or abs(sum(v.values()) - 1) > 0.01:
            raise ValueError("target weights must be non-negative and sum to 1")
        return v

    @field_validator("state")
    @classmethod
    def _known_state(cls, v: str | None):
        if v is None:
            return v
        if v.upper() not in state_rules.codes():
            raise ValueError("unknown state code")
        return v.upper()

    @field_validator("spending_model")
    @classmethod
    def _spending_model(cls, v: dict | None):
        return None if v is None else spending.SpendingModel.model_validate(v).model_dump(exclude_defaults=True)

    @field_validator("birth_date", "spouse_birth_date")
    @classmethod
    def _plausible_birth(cls, v: date | None):
        if v is not None and not 0 <= (date.today() - v).days / 365.2425 <= 100:
            raise ValueError("birth date must be in the past and within 100 years")
        return v


class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    institution: str = Field("OTHER", max_length=40)
    tax_bucket: str = Field("TAXABLE_BROKERAGE", pattern="^(TAXABLE_BROKERAGE|ROTH|PRE_TAX_401K|HSA|CASH_MMF)$")
    risk_tier: str = Field("MODERATE_GROWTH", pattern="^(SAFE_CORE|MODERATE_GROWTH|AGGRESSIVE_SATELLITE|CASH)$")
    is_restricted_plan: bool = False
    owner: str = Field("SELF", pattern="^(SELF|SPOUSE|JOINT)$")
    is_current_employer_plan: bool = False


class PlanMenuItemIn(BaseModel):
    ticker_or_cusip: str
    fund_name: str = ""
    asset_class: str = "US_EQUITY"
    expense_ratio: float = Field(0.0, ge=0, le=0.1)
    benchmark_proxy_ticker: str | None = None


class ProxyMapIn(BaseModel):
    holding_id: int
    proxy_ticker: str


class LLMConfigIn(BaseModel):
    provider: str | None = None
    fast_model: str | None = None
    reasoning_model: str | None = None
    api_key: str | None = None
    api_base: str | None = None
    token_budget: int | None = Field(default=None, ge=0, le=5_000_000)


class NotificationConfigIn(BaseModel):
    discord_webhook: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_to: str | None = None


class LiabilityIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    kind: str = Field("OTHER", pattern="^(MORTGAGE|AUTO|CARD|STUDENT|HELOC|OTHER)$")
    balance: float = Field(0.0, ge=0)
    apr: float = Field(0.0, ge=0, le=0.6)
    monthly_payment: float = Field(0.0, ge=0)
    payoff_date: date | None = None
    owner: str = Field("SELF", pattern="^(SELF|SPOUSE|JOINT)$")
    escrow_monthly: float = Field(0.0, ge=0)
    extra_monthly_payment: float = Field(0.0, ge=0)
    extra_payment_until: str = Field("RETIREMENT", pattern="^(RETIREMENT|PAYOFF)$")


class PlannedEventIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    kind: str = Field("PURCHASE", pattern="^(PURCHASE|INFLOW|PENSION|LTC|ANNUITY|PARTTIME|RENTAL|EQUITY|INHERIT|BIZSALE)$")
    amount: float = Field(gt=0)
    start_year: int = Field(ge=2000, le=2150)
    repeat_every_years: int = Field(0, ge=0, le=50)
    repeat_until_year: int | None = Field(None, ge=2000, le=2150)
    owner: str = Field("JOINT", pattern="^(SELF|SPOUSE|JOINT)$")
    financed: bool = False
    down_payment: float = Field(0.0, ge=0)
    loan_apr: float = Field(0.0, ge=0, le=0.4)
    loan_term_months: int = Field(60, ge=1, le=480)
    is_home_sale: bool = False
    basis: float = Field(0.0, ge=0)


class PensionIn(BaseModel):
    """Editable assumptions; balance and credits come from the imported statement."""

    start_age: float | None = Field(None, ge=50, le=80)
    payout: str | None = Field(None, pattern="^(ANNUITY|LUMP_SUM)$")
    interest_credit_rate: float | None = Field(None, ge=0, le=0.15)
    pay_credit_pct: float | None = Field(None, ge=0, le=0.5)
    covered_pay_annual: float | None = Field(None, ge=0)


COVERAGE_CATEGORIES = "^(PRE_MEDICARE|MEDICARE_ADVANTAGE|MEDIGAP|DRUG|OTHER)$"


class CoverageOptionIn(BaseModel):
    """A user-defined coverage alternative; prices are keyed by year, e.g. {"2027": 125.54}."""

    name: str = Field(min_length=1, max_length=160)
    carrier: str = Field("", max_length=120)
    plan_code: str = Field("", max_length=60)
    category: str = Field("PRE_MEDICARE", pattern=COVERAGE_CATEGORIES)
    premium_by_year: dict[str, float] = {}
    premium_period: str = Field("MONTHLY", pattern="^(MONTHLY|ANNUAL)$")
    premium_basis: str = Field("PER_PERSON", pattern="^(PER_PERSON|PER_HOUSEHOLD)$")
    deductible: float = Field(0, ge=0)
    oop_max: float = Field(0, ge=0)
    eligibility_min_age: float = Field(0, ge=0, le=120)
    eligibility_max_age: float | None = Field(None, ge=0, le=120)
    requires_medicare_parts: str = Field("", pattern="^(A|B|A,B)?$")
    requires_part_b_premium: bool = False
    includes_drugs: bool = False
    drug_option_id: int | None = None
    owner: str = Field("BOTH", pattern="^(SELF|SPOUSE|BOTH)$")
    cost_sharing_note: str = Field("", max_length=2000)
    source_note: str = Field("", max_length=2000)
    verified: bool = False
    active: bool = True
    sort_order: int = 0

    @field_validator("premium_by_year")
    @classmethod
    def _prices(cls, v: dict[str, float]) -> dict[str, float]:
        for k, x in v.items():
            if not k.isdigit() or not 2000 <= int(k) <= 2100:
                raise ValueError(f"year key {k!r} must be a four-digit year")
            if x < 0:
                raise ValueError("premiums must be >= 0")
        return v

    @model_validator(mode="after")
    def _ages(self):
        if self.eligibility_max_age is not None and self.eligibility_max_age <= self.eligibility_min_age:
            raise ValueError("eligibility_max_age must exceed eligibility_min_age")
        return self


class CoverageChoiceIn(BaseModel):
    """Which option each person uses instead of ACA / flat Medicare; null clears the choice."""

    SELF: int | None = None
    SPOUSE: int | None = None


class ConfirmedRow(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    name: str = ""
    shares: float = Field(0, ge=0)
    price: float = Field(0, ge=0)
    market_value: float = Field(gt=0)
    asset_class: str = "US_EQUITY"
    account_name: str | None = Field(None, max_length=120)


class ConfirmedIngest(BaseModel):
    """Rows the user reviewed in the OCR/AI preview, re-posted to be written."""

    rows: list[ConfirmedRow] = Field(min_length=1, max_length=500)
    source: str = "vision"


class ChatMessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class ChatSessionPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    scenario: str | None = Field(default=None, max_length=80)
    memory: str | None = Field(default=None, max_length=4000)


SCENARIO_FIELDS = {
    "target_retirement_age", "spouse_target_retirement_age", "monthly_expenses_retirement", "monthly_contribution", "social_security_monthly",
    "spouse_social_security_monthly", "ss_claim_age", "spouse_ss_claim_age", "annual_income", "spouse_annual_income", "spouse_age",
    "health_inflation", "effective_tax_rate", "target_success_rate", "ltc_annual", "ltc_years",
}  # fmt: skip


class ScenarioIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    overrides: dict[str, float] = Field(default_factory=dict)
    shock: float = Field(0.0, ge=-0.9, le=0.5)

    @field_validator("overrides")
    @classmethod
    def _known_fields(cls, v):
        bad = sorted(set(v) - SCENARIO_FIELDS)
        if bad:
            raise ValueError(f"unsupported override fields: {bad}")
        return v


class SpendingGoalIn(BaseModel):
    """A recurring retirement cost on top of the base budget; amount is today's dollars a year."""

    name: str = Field(min_length=1, max_length=120)
    category: str = Field("other", min_length=1, max_length=40)
    annual_amount: float = Field(ge=0, le=10_000_000)
    start_basis: str = Field("YEARS_AFTER_RETIREMENT", pattern="^(AGE|YEARS_AFTER_RETIREMENT)$")
    start_value: float = Field(0, ge=0, le=120)
    end_basis: str = Field("YEARS_AFTER_RETIREMENT", pattern="^(AGE|YEARS_AFTER_RETIREMENT)$")
    end_value: float | None = Field(None, ge=0, le=120)
    owner: str = Field("SELF", pattern="^(SELF|SPOUSE|JOINT)$")
    real_inflation: float = Field(0.0, ge=-0.15, le=0.15)
    smile_applies: bool = True
    enabled: bool = True
    note: str = Field("", max_length=2000)
    sort_order: int = 0

    @model_validator(mode="after")
    def _window(self):
        if self.end_value is not None and self.end_basis == self.start_basis and self.end_value <= self.start_value:
            raise ValueError("end must be after start")
        return self
