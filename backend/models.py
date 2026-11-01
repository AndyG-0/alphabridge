from datetime import UTC, date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from services.age import age_on


def utcnow():
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class UserProfile(Base):
    __tablename__ = "user_profile"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="Me")
    birth_date: Mapped[date] = mapped_column(Date, default=lambda: date.today().replace(year=date.today().year - 35, month=1, day=1))
    target_retirement_age: Mapped[float] = mapped_column(Float, default=50)
    annual_income: Mapped[float] = mapped_column(Float, default=0)
    monthly_expenses_current: Mapped[float] = mapped_column(Float, default=0)
    monthly_expenses_retirement: Mapped[float] = mapped_column(Float, default=0)
    emergency_fund_target_months: Mapped[float] = mapped_column(Float, default=6)
    current_money_market_yield: Mapped[float] = mapped_column(Float, default=0.045)  # decimal
    money_market_yield_override: Mapped[bool] = mapped_column(Boolean, default=False)
    tax_filing_status: Mapped[str] = mapped_column(String(40), default="SINGLE")
    effective_tax_rate: Mapped[float] = mapped_column(Float, default=0.15)
    monthly_contribution: Mapped[float] = mapped_column(Float, default=0)
    risk_appetite: Mapped[float] = mapped_column(Float, default=0.3)  # share of surplus to speculative sleeve
    sector_concentration_limit: Mapped[float] = mapped_column(Float, default=0.30)
    employer_symbol: Mapped[str] = mapped_column(String(20), default="")  # employer's stock ticker, for X-Ray concentration
    spouse_name: Mapped[str] = mapped_column(String(120), default="")
    spouse_birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # None = no spouse
    spouse_annual_income: Mapped[float] = mapped_column(Float, default=0)
    social_security_monthly: Mapped[float] = mapped_column(Float, default=0)  # primary, at 67, today's dollars
    spouse_social_security_monthly: Mapped[float] = mapped_column(Float, default=0)  # spouse, at their 67, today's dollars
    spouse_target_retirement_age: Mapped[float] = mapped_column(Float, default=0)  # 0 = retire together with the primary
    spouse_take_home_monthly: Mapped[float] = mapped_column(Float, default=0)  # 0 = derive from income x (1 - tax)
    target_success_rate: Mapped[float] = mapped_column(Float, default=0.85)  # confidence for earliest age / sustainable spend
    ss_claim_age: Mapped[float] = mapped_column(Float, default=67)
    spouse_ss_claim_age: Mapped[float] = mapped_column(Float, default=67)
    # health care, all today's dollars; pre-retirement health costs are inside current expenses
    state: Mapped[str] = mapped_column(String(2), default="AZ")  # drives Medicaid expansion rules (data/state_rules.json)
    meets_community_engagement: Mapped[bool] = mapped_column(Boolean, default=False)  # will do 80 hrs/mo (Medicaid 2027+)
    aca_benchmark_premium_monthly: Mapped[float] = mapped_column(Float, default=0)  # household benchmark silver; 0 = estimate from ages
    dental_vision_monthly: Mapped[float] = mapped_column(Float, default=50)  # per person
    health_oop_annual: Mapped[float] = mapped_column(Float, default=2500)  # per person under 65
    medicare_monthly_per_person: Mapped[float] = mapped_column(Float, default=450)  # Part B + Medigap + Part D
    health_inflation: Mapped[float] = mapped_column(Float, default=0.05)
    home_value: Mapped[float] = mapped_column(Float, default=0)
    home_upkeep_pct: Mapped[float] = mapped_column(Float, default=0.01)
    ltc_annual: Mapped[float] = mapped_column(Float, default=100000)  # per person
    ltc_years: Mapped[float] = mapped_column(Float, default=2)  # 0 = ignore long-term care
    ltc_start_age: Mapped[float] = mapped_column(Float, default=85)
    guardrails_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    spending_model: Mapped[dict] = mapped_column(JSON, default=dict)  # services/spending.py SpendingModel; {} = flat spending
    target_allocation: Mapped[dict] = mapped_column(JSON, default=dict)  # {asset_class: weight} summing to 1; {} = none set (performance, rebalancing)
    accounts = relationship("Account", back_populates="user", cascade="all, delete-orphan")

    @property
    def current_age(self) -> float:
        return age_on(self.birth_date)

    @property
    def spouse_age(self) -> float:  # 0 = no spouse
        return age_on(self.spouse_birth_date) if self.spouse_birth_date else 0.0

    def to_dict(self) -> dict:
        d = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        d["birth_date"] = self.birth_date.isoformat() if self.birth_date else None
        d["spouse_birth_date"] = self.spouse_birth_date.isoformat() if self.spouse_birth_date else None
        return d | {"current_age": round(self.current_age, 2), "spouse_age": round(self.spouse_age, 2)}


class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profile.id"), default=1)
    name: Mapped[str] = mapped_column(String(160))
    institution: Mapped[str] = mapped_column(String(40), default="OTHER")
    tax_bucket: Mapped[str] = mapped_column(String(40), default="TAXABLE_BROKERAGE")
    risk_tier: Mapped[str] = mapped_column(String(40), default="MODERATE_GROWTH")
    is_restricted_plan: Mapped[bool] = mapped_column(Boolean, default=False)
    owner: Mapped[str] = mapped_column(String(10), default="SELF")  # SELF | SPOUSE | JOINT
    is_current_employer_plan: Mapped[bool] = mapped_column(Boolean, default=False)  # Rule of 55 applies to the current employer's plan only
    user = relationship("UserProfile", back_populates="accounts")
    holdings = relationship("Holding", back_populates="account", cascade="all, delete-orphan")
    plan_menu = relationship("AllowedPlanMenu", back_populates="account", cascade="all, delete-orphan")


class AllowedPlanMenu(Base):
    __tablename__ = "allowed_plan_menu"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    ticker_or_cusip: Mapped[str] = mapped_column(String(40))
    fund_name: Mapped[str] = mapped_column(String(200), default="")
    asset_class: Mapped[str] = mapped_column(String(40), default="US_EQUITY")
    expense_ratio: Mapped[float] = mapped_column(Float, default=0.0)  # decimal, 0.0005 = 5bp
    benchmark_proxy_ticker: Mapped[str | None] = mapped_column(String(20), nullable=True)
    account = relationship("Account", back_populates="plan_menu")


class Holding(Base):
    __tablename__ = "holding"
    __table_args__ = (UniqueConstraint("account_id", "symbol", name="uq_holding_account_symbol"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    symbol: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200), default="")
    shares: Mapped[float] = mapped_column(Float, default=0)
    cost_basis_total: Mapped[float] = mapped_column(Float, default=0)
    current_price: Mapped[float] = mapped_column(Float, default=0)
    market_value: Mapped[float] = mapped_column(Float, default=0)
    asset_class: Mapped[str] = mapped_column(String(40), default="US_EQUITY")
    proxy_ticker: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    currency: Mapped[str] = mapped_column(String(3), default="USD")  # statement currency; amounts are stored in USD
    fx_rate: Mapped[float] = mapped_column(Float, default=1.0)  # USD per unit of `currency` at import
    account = relationship("Account", back_populates="holdings")


class TaxLot(Base):
    """One purchase lot (from a lot-level cost-basis export). Needed for holding periods, wash-sale windows and choosing which lot to sell."""

    __tablename__ = "tax_lot"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    symbol: Mapped[str] = mapped_column(String(40))
    acquired: Mapped[date] = mapped_column(Date)
    shares: Mapped[float] = mapped_column(Float)
    cost_basis_total: Mapped[float] = mapped_column(Float, default=0)
    current_value: Mapped[float] = mapped_column(Float, default=0)  # from the export; refreshed from the holding's price when one exists
    source: Mapped[str] = mapped_column(String(40), default="fidelity_lots")


class IngestionLog(Base):
    __tablename__ = "ingestion_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(300))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"), nullable=True)
    parser: Mapped[str] = mapped_column(String(40), default="")
    rows_parsed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="OK")
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    content_hash: Mapped[str] = mapped_column(String(64), default="")  # hash of the imported rows (idempotency + audit)
    batch_id: Mapped[str] = mapped_column(String(32), default="")  # one upload can touch several accounts
    before: Mapped[list | None] = mapped_column(JSON, nullable=True)  # the account's holdings before this import (for undo)
    created_account: Mapped[bool] = mapped_column(Boolean, default=False)  # import created the account, so undo removes it
    undone_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class NetWorthSnapshot(Base):
    __tablename__ = "net_worth_snapshot"
    id: Mapped[int] = mapped_column(primary_key=True)
    taken_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    total: Mapped[float] = mapped_column(Float, default=0)
    safe_core: Mapped[float] = mapped_column(Float, default=0)
    satellite: Mapped[float] = mapped_column(Float, default=0)
    dry_powder: Mapped[float] = mapped_column(Float, default=0)
    liabilities: Mapped[float] = mapped_column(Float, default=0)
    breakdown: Mapped[dict] = mapped_column(JSON, default=dict)  # {"assets": {tax_bucket: $}, "liabilities": {kind: $}}


class CashFlow(Base):
    """External money in (+) or out (-) of the invested portfolio; needed to separate your contributions from market returns (TWR/MWR)."""

    __tablename__ = "cash_flow"
    id: Mapped[int] = mapped_column(primary_key=True)
    on: Mapped[date] = mapped_column(Date)
    amount: Mapped[float] = mapped_column(Float)
    note: Mapped[str] = mapped_column(String(200), default="")


class Scenario(Base):
    """A named what-if: profile-field overrides plus an optional first-retirement-year market shock (services/scenarios.py)."""

    __tablename__ = "scenario"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profile.id"), default=1)
    name: Mapped[str] = mapped_column(String(160))
    overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    shock: Mapped[float] = mapped_column(Float, default=0)  # e.g. -0.30

    def to_dict(self) -> dict:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class Liability(Base):
    __tablename__ = "liability"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profile.id"), default=1)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(20), default="OTHER")  # MORTGAGE|AUTO|CARD|STUDENT|HELOC|OTHER
    balance: Mapped[float] = mapped_column(Float, default=0)
    apr: Mapped[float] = mapped_column(Float, default=0)  # decimal
    monthly_payment: Mapped[float] = mapped_column(Float, default=0)  # principal + interest
    payoff_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # None = derive from balance/apr/payment
    owner: Mapped[str] = mapped_column(String(10), default="SELF")  # SELF | SPOUSE | JOINT
    escrow_monthly: Mapped[float] = mapped_column(Float, default=0)  # taxes + insurance that outlive the loan
    extra_monthly_payment: Mapped[float] = mapped_column(Float, default=0)  # extra principal on top of monthly_payment
    extra_payment_until: Mapped[str] = mapped_column(String(12), default="RETIREMENT")  # RETIREMENT | PAYOFF

    def to_dict(self) -> dict:
        d = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        d["payoff_date"] = self.payoff_date.isoformat() if self.payoff_date else None
        return d


class PlannedEvent(Base):
    """A future purchase (car, roof), lump-sum inflow (inheritance, home sale) or pension. Amounts in today's dollars."""

    __tablename__ = "planned_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profile.id"), default=1)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(12), default="PURCHASE")  # PURCHASE|INFLOW|PENSION|LTC + income-stream kinds (see income_streams.py)
    amount: Mapped[float] = mapped_column(Float, default=0)  # lump sum, or monthly for PENSION
    start_year: Mapped[int] = mapped_column(Integer)
    repeat_every_years: Mapped[int] = mapped_column(Integer, default=0)  # 0 = once
    repeat_until_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    owner: Mapped[str] = mapped_column(String(10), default="JOINT")  # SELF | SPOUSE | JOINT
    financed: Mapped[bool] = mapped_column(Boolean, default=False)
    down_payment: Mapped[float] = mapped_column(Float, default=0)
    loan_apr: Mapped[float] = mapped_column(Float, default=0)
    loan_term_months: Mapped[int] = mapped_column(Integer, default=60)
    is_home_sale: Mapped[bool] = mapped_column(Boolean, default=False)  # ends home upkeep and escrow
    basis: Mapped[float] = mapped_column(Float, default=0)  # cost basis / annuity premium / annual depreciation (see services/income_streams.py)

    def to_dict(self) -> dict:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class Pension(Base):
    """Employer cash-balance plan: the balance earns interest credits and, while the owner works, pay credits.
    It is not investable, so it is kept apart from Account/Holding and feeds the planner as income."""

    __tablename__ = "pension"
    __table_args__ = (UniqueConstraint("user_id", "owner", name="uq_pension_user_owner"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profile.id"), default=1)
    owner: Mapped[str] = mapped_column(String(10), default="SELF")  # SELF | SPOUSE
    name: Mapped[str] = mapped_column(String(160), default="Pension")
    plan_balance: Mapped[float] = mapped_column(Float, default=0)
    as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    pay_credit_pct: Mapped[float] = mapped_column(Float, default=0)  # decimal, 0.07 = 7% of covered pay
    covered_pay_annual: Mapped[float] = mapped_column(Float, default=0)  # annualized from the statement's pay credits
    interest_credit_rate: Mapped[float] = mapped_column(Float, default=0.04)  # nominal annual, decimal
    start_age: Mapped[float] = mapped_column(Float, default=65)  # owner's age when benefits begin
    payout: Mapped[str] = mapped_column(String(10), default="ANNUITY")  # ANNUITY | LUMP_SUM
    ytd_interest: Mapped[float] = mapped_column(Float, default=0)
    ytd_pay_credits: Mapped[float] = mapped_column(Float, default=0)

    def to_dict(self) -> dict:
        d = {c.name: getattr(self, c.name) for c in self.__table__.columns}
        d["as_of"] = self.as_of.isoformat() if self.as_of else None
        return d


class ChatSession(Base):
    """A saved Ask-AI conversation. The server owns history so sessions can be resumed from any device."""

    __tablename__ = "chat_session"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profile.id"), default=1)
    title: Mapped[str] = mapped_column(String(160), default="New chat")
    title_source: Mapped[str] = mapped_column(String(10), default="auto")  # auto | user (a user rename is never overwritten)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.id")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "title_source": self.title_source,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class ChatMessage(Base):
    __tablename__ = "chat_message"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_session.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    tools_used: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    session = relationship("ChatSession", back_populates="messages")

    def to_dict(self) -> dict:
        return {"id": self.id, "role": self.role, "content": self.content, "tools": self.tools_used or [], "created_at": self.created_at.isoformat()}


class ResearchReport(Base):
    __tablename__ = "research_report"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    trigger_source: Mapped[str] = mapped_column(String(20), default="ON_DEMAND")
    quant_score: Mapped[float] = mapped_column(Float, default=0)
    valuation_grade: Mapped[str] = mapped_column(String(4), default="")
    growth_grade: Mapped[str] = mapped_column(String(4), default="")
    moat_grade: Mapped[str] = mapped_column(String(4), default="")
    bull_case_md: Mapped[str] = mapped_column(Text, default="")
    bear_case_md: Mapped[str] = mapped_column(Text, default="")
    sec_filing_citations_json: Mapped[list] = mapped_column(JSON, default=list)
    portfolio_fit_notes: Mapped[str] = mapped_column(Text, default="")
    recommended_action: Mapped[str] = mapped_column(String(20), default="WATCHLIST")
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)


class LLMConfig(Base):
    __tablename__ = "llm_config"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(30), default="anthropic")
    fast_model: Mapped[str] = mapped_column(String(120), default="anthropic/claude-haiku-5-5")
    reasoning_model: Mapped[str] = mapped_column(String(120), default="anthropic/claude-sonnet-5-5")
    api_key_encrypted: Mapped[str] = mapped_column(Text, default="")
    api_base: Mapped[str] = mapped_column(String(300), default="")


class NotificationConfig(Base):
    __tablename__ = "notification_config"
    id: Mapped[int] = mapped_column(primary_key=True)
    discord_webhook_encrypted: Mapped[str] = mapped_column(Text, default="")
    smtp_host: Mapped[str] = mapped_column(String(200), default="")
    smtp_port: Mapped[int] = mapped_column(Integer, default=587)
    smtp_user: Mapped[str] = mapped_column(String(200), default="")
    smtp_password_encrypted: Mapped[str] = mapped_column(Text, default="")
    smtp_to: Mapped[str] = mapped_column(String(200), default="")


class MarketCache(Base):
    """Polite cache for yfinance/FRED/EDGAR responses."""

    __tablename__ = "market_cache"
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    payload: Mapped[dict | list] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ScreenerResult(Base):
    __tablename__ = "screener_result"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    symbol: Mapped[str] = mapped_column(String(20))
    score: Mapped[float] = mapped_column(Float, default=0)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)


class AssumptionOverride(Base):
    """A user-edited model assumption (services/assumptions.py); absent key = documented default."""

    __tablename__ = "assumption_override"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[float] = mapped_column(Float)


class RunSnapshot(Base):
    """Headline plan metrics and the assumptions in force at one run, to diff against the next (services/assumptions.py)."""

    __tablename__ = "run_snapshot"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    assumptions: Mapped[dict] = mapped_column(JSON, default=dict)

    def to_dict(self) -> dict:
        return {"id": self.id, "created_at": self.created_at.isoformat(), "metrics": self.metrics, "assumptions": self.assumptions}
