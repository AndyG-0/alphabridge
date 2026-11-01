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
UserProfile, Account, AllowedPlanMenu, Holding, Liability (debts; profile expenses exclude debt payments), IngestionLog, NetWorthSnapshot, ResearchReport, LLMConfig, NotificationConfig (fields per original blueprint).

## Modules
A. Ingestion (Fidelity/NetBenefits/Nationwide CSV, Ally/Chase bank statements as cash, pdfplumber -> Tesseract OCR / LLM vision for scanned docs -> LLM structured extraction -> `validate_parse` arithmetic checks -> user-confirmed preview (`services/doc_reader.py`), proxy-ticker mapper; institutions, defaults and export instructions live in `backend/services/institutions.py`)
B. Planner (5,000-iter Monte Carlo, bridge phase to 59.5 then full retirement to 95 (ages derived from stored birth dates); core/satellite partition; 401k menu optimizer; surplus allocator)
C. Cash optimizer (0–100 deployment score from real yield, ERP, VIX/200DMA; hold/DCA/aggressive with dollar amounts)
D. Research pipeline (quant screener -> macro/sector overlay -> EDGAR 10-K/10-Q bull/bear synthesis; portfolio-aware concentration check)

## UI
Command Center, Portfolio & Dropzone, AI Analyst & What-If Lab, Settings. Mobile bottom nav, desktop multi-column.

## Phases
1 Foundation & ingestion · 2 Quant & cash optimizer · 3 EDGAR discovery · 4 Scheduler, alerts, seed data, tests.

## Commands
- Backend: `cd backend && source .venv/bin/activate && uv pip install -r requirements.txt && pytest && flask --app app run`
- Frontend: `cd frontend && npm install && npm run dev` (proxies /api to :5000), `npm run build`
- Hot-reload dev (native, no podman): `./dev.sh` (Flask `--debug` on :5001 + Vite on :5173; scheduler off unless `ENABLE_SCHEDULER=1`)
- Git hooks: `make hooks` (commit: hygiene, ruff, gitleaks, eslint, prettier, private-data guard; push: mypy, pytest, tsc). CI re-runs them.
- Seed demo data: `python -m seed`
- Stack: `podman compose up --build` (or docker compose)

## Local dev notes
- macOS AirPlay occupies port 5000: run Flask locally with `flask --app wsgi run -p 5001`; `frontend/vite.config.ts` proxies `/api` to 5001. In containers the backend still listens on 5000 (nginx proxies to it).
- Run Flask with `ENABLE_SCHEDULER=1` only for a single worker (gunicorn is pinned to `-w 1`).
- Live market data needs no key (Yahoo fallback); set `FRED_API_KEY` for live CPI, `EDGAR_IDENTITY` for SEC requests, and an LLM key in Settings for PDF fallback and deep dives.
- Container stack serves the UI on `http://localhost:8088` (override with `FRONTEND_PORT`; 8080 is often taken). `.env` is generated from `.env.example` with random `ACCESS_TOKEN`/`APP_SECRET`. The compose file sets `OPENSSL_armcap=0` to avoid SIGILL on podman's ARM VM.

## Agent tools & routing
- Every new read endpoint needs a read-only chat tool in `backend/services/chat_tools.py`; `tests/test_chat.py::test_every_read_route_family_has_a_chat_tool` fails until the route is listed there.
- Each left-nav page is a URL (`/`, `/plan`, `/portfolio`, `/research`, `/chat/:sessionId?`, `/settings`) via react-router; navigate with `<Link>`/`useNavigate`, never state or window events. Ask-AI conversations persist server-side (`ChatSession`/`ChatMessage`).

## Backlog
Work items live in `TODO.md` (tracks E engineering, P planning, I investing, D data, U UX). Pick the lowest unblocked item, add tests, tick the box. Tax/IRS/SSA/ACA constants go in versioned data files with a source URL, never inline. Once `make check` exists (E2) run it before finishing; it mirrors CI.
