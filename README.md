# AlphaBridge

Self-hosted AI financial planner, early-retirement and equity-research engine for a home-lab Docker/podman environment. Single user (multi-tenant ready).

**Not financial advice.** AlphaBridge is a planning aid. Tax and benefit constants are versioned data files with sources; verify them before relying on any output. All demo and test data is fictional.

## Principles
- **Deterministic math vs. probabilistic AI:** Monte Carlo, DCF, indicators and statistics run in Python; the LLM only narrates structured results.
- **Core & Satellite:** 401(k)s are the safe core; brokerage and excess cash form the growth satellite.
- **Cash vs. market engine:** scores whether idle cash stays in a money market or gets deployed.

## Stack
Flask 3 + gunicorn, APScheduler, SQLite (WAL) via SQLAlchemy 2 + Alembic, LiteLLM, React 19 + TypeScript + Vite + Tailwind + Recharts, PWA, docker-compose.

## Quickstart
```bash
cp .env.example .env        # set ACCESS_TOKEN and APP_SECRET to long random strings
podman compose up --build   # or: docker compose up --build  -> http://localhost:8088
```

Native development (hot reload): `./dev.sh` (Flask on :5001, Vite on :5173). Demo data: `cd backend && python -m seed`.

Checks: `make check` (mirrors CI). See `SPEC.md`, `TODO.md` and `docs/` for design, backlog and the threat model.

## Your data
Statements and CSV/PDF exports are gitignored. Your database lives in `data/` and API keys are stored Fernet-encrypted. Nothing leaves your machine except calls to the market-data and LLM providers you configure.

## License
MIT, see `LICENSE`.
