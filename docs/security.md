# Security model

AlphaBridge holds a household's complete financial picture. It is built for one trusted household on a home-lab network, not for the open internet. This page lists what is protected, what is deliberately not, and which test or check enforces each control.

## Assets
Account balances and holdings, liabilities, birth dates, uploaded statements, LLM/Discord/SMTP credentials, the `ACCESS_TOKEN` and `APP_SECRET`.

## Trust boundaries
| Boundary | Assumption |
|---|---|
| Browser <-> nginx | Served over a network you control. **Put TLS in front (reverse proxy / Tailscale / Caddy) before exposing beyond the LAN**; the app itself speaks plain HTTP. |
| nginx <-> Flask | Private compose network. nginx forwards the client address; Flask trusts exactly one proxy hop when `TRUST_PROXY=1`. |
| App <-> LLM provider | Only the numbers needed for narrative leave the box, as structured JSON computed in Python. Statement images/text go to the provider only when the vision/LLM fallback is used. |
| App <-> data sources | Outbound only (Yahoo, FRED, SEC EDGAR). No inbound webhooks. |

## Controls
| Threat | Control | Enforced by |
|---|---|---|
| Unauthenticated API access | Shared bearer `ACCESS_TOKEN`, constant-time compare; every `/api/*` route except `/api/health` | `tests/test_route_contract.py`, `tests/test_auth_and_crypto.py` |
| Token brute force | 10 failures / 60 s per client address -> HTTP 429 (tunable: `AUTH_MAX_FAILURES`, `AUTH_WINDOW_SECONDS`) | `tests/test_security.py` |
| Secrets at rest | UI-entered API keys / webhook / SMTP password are Fernet-encrypted with a key derived from `APP_SECRET`; never returned by the API (only `*_set` booleans) | `tests/test_settings.py`, `tests/test_auth_and_crypto.py` |
| Secrets in logs | Redaction filter on app and werkzeug loggers: bearer tokens, `key=`/`token=`/`password=` values, Discord webhook tokens, `sk-` keys, account numbers (last 4 kept) | `tests/test_security.py::test_redact*` |
| Cross-origin reads | CORS **off** unless `CORS_ORIGINS` lists origins; UI and API share one origin | `tests/test_security.py::test_cors_*` |
| Clickjacking / sniffing / XSS | API: `X-Content-Type-Options`, `X-Frame-Options: DENY`, `CSP default-src 'none'`, `no-store`. UI (nginx): strict CSP (`script-src 'self'`, `frame-ancestors 'none'`), `Permissions-Policy`, COOP | `tests/test_security.py`, `frontend/nginx.conf` |
| Malicious uploads | 20 MB cap (HTTP 413); extension allowlist + magic-byte check (HTTP 415); PDFs over 60 pages rejected; images over 100 MP rejected (Pillow bomb guard); uploads are parsed in memory and never written to disk under a user-supplied name | `tests/test_security.py` |
| Path traversal | Filenames are reduced to a safe basename before logging/storage | `tests/test_security.py::test_safe_filename`, `::test_traversal_*` |
| SQL injection | SQLAlchemy ORM with bound parameters only; hostile strings round-trip as data; enum-like fields allowlisted | `tests/test_security.py::test_sql_injection_*` |
| Container breakout / privilege | Both images run non-root; compose sets `read_only`, `cap_drop: [ALL]`, `no-new-privileges`; only `/app/data` is writable | `docker-compose.yml`, `hadolint`, `trivy` |
| Vulnerable dependencies | `pip-audit`, `npm audit`, Dependabot, Trivy (CI + weekly), CodeQL, `dependency-review` on PRs | `.github/workflows/security.yml`, `make audit` |
| Leaked credentials in git | `gitleaks` in pre-commit and CI; `.env`, `data/`, statements/CSV/PDF files ignored; tests use synthetic fixtures | `.pre-commit-config.yaml` |
| LLM doing arithmetic / being steered by data | The model gets structured JSON only and has read-only tools; all math runs in Python (core law #1); statement text is treated as data (extraction output is re-validated by `validate_parse` and confirmed by the user before any write) | `tests/test_properties.py`, `tests/test_validate_parse_and_llm.py` |

## Known gaps (accepted for now)
- Single shared token, no per-user identity or revocation. Multi-user hardening is tracked as U6.
- The token lives in browser `localStorage`; an XSS would expose it. The strict CSP is the mitigation.
- The auth rate limiter is in-process and per client address; behind a proxy that does not set `X-Forwarded-For` every client looks identical. gunicorn is pinned to one worker so the counters are consistent.
- No TLS termination or HSTS in the bundled nginx (add at your reverse proxy).
- The SQLite file is not encrypted at rest; use disk encryption on the host.
- Uploaded statements are sent to the configured LLM provider when the vision/LLM fallback runs. Choose a provider whose data terms you accept, or use a local model (Ollama).

## Reporting
Open a private security advisory on the repository.

## Operations
- `/api/health` (liveness) and `/api/ready` (DB, scheduler, last market-data refresh; 503 when degraded) are intentionally unauthenticated and return no data beyond status. `/api/scheduler/status` requires the token.
- Every response carries `X-Request-ID` (client-supplied values are accepted only if they match alphanumerics and hyphens (truncated to 64 characters)); log lines are redacted before emission.
- Back up with `python backend/scripts/backup.py backup` (SQLite online-backup API, WAL-safe, integrity-checked, 14 kept). Restore with `restore FILE --force` while the app is stopped; the previous DB is kept as `.pre-restore`.
