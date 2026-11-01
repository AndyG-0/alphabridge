# AlphaBridge — AI Financial Planner, Early-Retirement & Equity Research Engine

Self-hosted, single-user (multi-tenant ready) planning platform for a home-lab Docker environment.

## Core laws
1. **Deterministic math vs. probabilistic AI.** The LLM never does arithmetic. Monte Carlo, Sharpe, correlations, DCF, indicators, MMF-vs-equity premia run in Python (NumPy/Pandas/SciPy); results go to the LLM as structured JSON for narrative only.
2. **Core & Satellite (barbell).** 401(k)s (Fidelity NetBenefits, Nationwide) = Safe Core, optimized only within the plan menu. Brokerage + excess cash = Growth Satellite across risk tiers.
3. **Cash vs. market engine.** Continuously decide whether idle cash stays in a money market (SPAXX/FDRXX/T-bills) or is deployed, using risk-free yield, ERP, drawdown and cash-buffer rules.

## Stack
Flask 3 (no FastAPI) + gunicorn, APScheduler, SQLite (WAL) via SQLAlchemy 2 + Alembic (DATABASE_URL swap -> Postgres), LiteLLM, edgartools, yfinance (cached), FRED, React 19 + TS + Vite + Tailwind + shadcn/ui + Recharts (no Next.js), PWA, Discord webhooks w/ SMTP fallback, docker-compose (backend + nginx frontend).

## Decisions
Pydantic v2 validation; Fernet-encrypted UI-entered API keys (APP_SECRET); shared bearer ACCESS_TOKEN; podman-compatible compose.

## Models
UserProfile, Account, AllowedPlanMenu, Holding, IngestionLog, NetWorthSnapshot, ResearchReport, LLMConfig, NotificationConfig (fields per original blueprint).

## Modules
A. Ingestion (Fidelity/NetBenefits/Nationwide CSV, Ally/Chase bank statements as cash, pdfplumber + LLM fallback, proxy-ticker mapper; institutions, defaults and export instructions live in `backend/services/institutions.py`)
B. Planner (5,000-iter Monte Carlo, bridge phase to 59.5 then full retirement to 95 (ages derived from stored birth dates); core/satellite partition; 401k menu optimizer; surplus allocator)
C. Cash optimizer (0–100 deployment score from real yield, ERP, VIX/200DMA; hold/DCA/aggressive with dollar amounts)
D. Research pipeline (quant screener -> macro/sector overlay -> EDGAR 10-K/10-Q bull/bear synthesis; portfolio-aware concentration check)

## UI
Command Center, Portfolio & Dropzone, AI Analyst & What-If Lab, Settings. Mobile bottom nav, desktop multi-column.

## Phases
1 Foundation & ingestion · 2 Quant & cash optimizer · 3 EDGAR discovery · 4 Scheduler, alerts, seed data, tests.
