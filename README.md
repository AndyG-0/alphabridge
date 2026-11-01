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

## Exports, backups and MCP
- **Reports:** `GET /api/export/report.csv` and `report.pdf`; full JSON export `GET /api/export/json`, restore with `POST /api/export/import` (`{"confirm": true, "data": ...}`, replaces everything). API keys and other credentials are never exported.
- **Encrypted backup:** set `BACKUP_DEST` to `local` (`BACKUP_PATH`), `webdav` (`WEBDAV_URL`, `WEBDAV_USER`, `WEBDAV_PASSWORD`) or `s3` (`S3_BUCKET`, optional `S3_PREFIX`, `S3_ENDPOINT`; AWS credentials from the usual boto3 environment). A nightly job writes a Fernet-encrypted JSON export (key derived from `APP_SECRET`; keep that secret, or the backups cannot be read). Run one now with `POST /api/export/backup`.
- **Share link:** `POST /api/export/share {"days": 7}` returns a signed token (max 30 days) that unlocks only `/api/share/<token>/report.csv|pdf`. Rotating `APP_SECRET` revokes all links.
- **MCP server (read-only):** `cd backend && python mcp_server.py` serves every read-only planning tool over stdio (Claude Desktop config: command `python`, args `["mcp_server.py"]`, cwd `backend`). `python mcp_server.py --http` serves streamable HTTP at `http://127.0.0.1:5002/mcp` (`MCP_HOST`/`MCP_PORT`) and requires `Authorization: Bearer <ACCESS_TOKEN>`. Each tool takes its arguments as an `args` object.

## License
MIT, see `LICENSE`.
