# AlphaBridge backlog

Agent-ready work items. One item ≈ one session ≈ one PR.

## How to pick up a task
1. Take the lowest-numbered unchecked item whose `Depends` are all checked (Track E first).
2. Honor the core laws in `CLAUDE.md`: all math in Python, LLM narrates only; tax/IRS/SSA/ACA constants live in versioned data files with a source URL, never inline in logic.
3. Add tests with the change (unit, plus property/golden tests for numeric code). Don't lower a coverage threshold; ratchet it up.
4. Once E2 lands, run `make check` before finishing (it is exactly what CI runs). Until then: `cd backend && pytest && ruff check .` and `cd frontend && npm run build`.
5. Tick the box and note the PR/commit. Keep the item's `Touch` list honest.

Task format: **ID Title** — scope · *Acceptance* · *Touch* · *Depends* · *Notes*

Baseline (2026-10-30): 12 backend test files, ruff `E,F,I,B` only, no frontend tests/linter, no CI, no coverage measurement, nothing committed.

---

## Track E — Engineering foundation (do first)

- [x] **E1 Initial commit + repo hygiene** — first commit on `main`, keep secrets and personal data out.
  - *Acceptance:* `.env`, `data/`, real statements (`samples/`, `*.csv`, `*.pdf`) are gitignored and tests use only synthetic fixtures in `backend/tests/fixtures.py`; `.gitattributes`, `.editorconfig` added; stray `backend/sqlite:` dir and `frontend/tsconfig.tsbuildinfo` removed/ignored; LICENSE decision recorded; `git status` clean after a fresh `make setup`.
  - *Touch:* `.gitignore`, `.gitattributes`, `.editorconfig`, `backend/tests/fixtures.py`
  - *Depends:* —
- [x] **E2 One-command local checks** — `Makefile` with `setup dev test lint fmt typecheck cov audit check ci`.
  - *Acceptance:* `make check` runs backend + frontend lint, format check, typecheck, tests with coverage, build; identical to CI; works offline after `make setup`; documented in README.
  - *Touch:* `Makefile`, `README.md`, `dev.sh`
  - *Depends:* E1
- [x] **E3 Backend quality gates** — dev deps, `pyproject.toml` config, stricter lint/type/coverage.
  - *Acceptance:* `requirements.txt` (runtime) vs `requirements-dev.txt` (pytest, pytest-cov, pytest-xdist, hypothesis, freezegun, responses, mypy, ruff, bandit, pip-audit, vulture); ruff adds `UP,S,SIM,C4,PT,RET,RUF,DTZ,PERF,N` (+ `ruff format --check`), staged with per-file ignores rather than blanket disables; mypy strict on `services/` then `routes/`; pytest `--strict-markers -W error`; coverage `--fail-under` set to current baseline and documented ratchet to 85% overall / 95% pure-math modules; `ruff.toml` merged into `pyproject.toml`.
  - *Touch:* `backend/pyproject.toml`, `backend/requirements*.txt`, `backend/ruff.toml`, `backend/Dockerfile`
  - *Depends:* E1
- [x] **E4 Frontend quality gates** — tests, lint, format, dead-code, bundle budget.
  - *Acceptance:* Vitest + React Testing Library + MSW with at least one test per page rendering against mocked `/api`; ESLint (typescript-eslint, react-hooks, jsx-a11y); Prettier; `knip`; `npm audit --omit=dev`; size-limit budget; `noUncheckedIndexedAccess`; scripts `lint format:check test test:cov typecheck`.
  - *Touch:* `frontend/package.json`, `frontend/tsconfig.json`, `frontend/eslint.config.js`, `frontend/src/**/*.test.tsx`
  - *Depends:* E1
- [ ] **E5 E2E + accessibility** — Playwright smoke per page on seeded data.
  - *Acceptance:* runs against `python -m seed` data; one smoke test each for Dashboard, Portfolio/Dropzone, Retirement Plan, Research Lab, Chat, Settings; `@axe-core/playwright` has zero serious violations; desktop + mobile (bottom nav) projects; traces/screenshots on failure; `make e2e`.
  - *Touch:* `frontend/e2e/`, `frontend/playwright.config.ts`, `Makefile`
  - *Depends:* E2, E4
- [x] **E6 Backend coverage backfill** — test the untested/thin modules.
  - *Acceptance:* tests for `market_data` (mock yfinance/FRED/requests, cache hit/expiry, Yahoo fallback), `scheduler`, `notifier` (Discord + SMTP fallback), `llm_router` (mock LiteLLM), `crypto` (round-trip, wrong key), `settings_routes` (API keys never returned in plaintext), auth (bearer `ACCESS_TOKEN` missing/invalid/valid, constant-time compare), `validate_parse`, `doc_reader`; a route-contract test asserting every route has a test and returns a schema-valid body; no real network in the suite (socket blocked via pytest plugin).
  - *Touch:* `backend/tests/`
  - *Depends:* E3
- [x] **E7 Property-based + golden numeric tests** — enforce core law #1.
  - *Acceptance:* Hypothesis tests: `amortize`/`monthly_schedule` (balance never negative, total paid ≥ principal), `ss_factor` monotonic, allocations sum to input, weights sum to 1, MC success rate monotone in spend and in starting balance; seeded golden-file test for Monte Carlo percentiles and `deployment_score`; a test proving `chat_tools` output sent to the LLM is Python-computed JSON only.
  - *Touch:* `backend/tests/test_properties.py`, `backend/tests/golden/`
  - *Depends:* E3
- [x] **E8 DB/migration tests** — prove Alembic and the Postgres swap.
  - *Acceptance:* upgrade empty→head, downgrade round-trip, `alembic check` shows no model/migration drift; suite also passes against Postgres (env-selected `DATABASE_URL`, container in CI).
  - *Touch:* `backend/tests/test_migrations.py`, `backend/alembic/`, `backend/db.py`
  - *Depends:* E3
- [x] **E9 Security hardening + checks** — scanners and app-level controls.
  - *Acceptance:* `bandit`, `pip-audit`, `npm audit`, `gitleaks`, `hadolint`, `trivy` wired into `make audit`; containers run non-root; nginx sends CSP, `X-Content-Type-Options`, `frame-ancestors`; CORS restricted; rate limit on auth failures; upload size/type limits and PDF-bomb guard; path-traversal and SQLi tests on ingestion; logs redact tokens/account numbers; `docs/security.md` threat model.
  - *Touch:* `backend/app.py`, `frontend/nginx.conf`, both Dockerfiles, `docs/security.md`, `backend/tests/test_security.py`
  - *Depends:* E3
- [x] **E10 Pre-commit** — local hooks mirror CI.
  - *Acceptance:* `.pre-commit-config.yaml` with ruff, ruff-format, mypy, eslint, prettier, gitleaks, actionlint, check-yaml/toml/json, large-file guard; `make hooks`; hooks run in <30s on a typical diff.
  - *Touch:* `.pre-commit-config.yaml`, `Makefile`
  - *Depends:* E3, E4
- [x] **E11 GitHub Actions** — CI, security, release, dependency automation.
  - *Acceptance:* `.github/workflows/ci.yml` (backend matrix py3.12/3.13 with uv cache; frontend node LTS; migrations on SQLite + Postgres service; e2e; docker build + compose smoke hitting `/api/health`; concurrency cancel; `permissions: contents: read`; actions pinned by SHA); `security.yml` (CodeQL python+js, gitleaks, pip-audit, npm audit, trivy, dependency-review on PRs, weekly cron); `release.yml` (tag → multi-arch GHCR images, SBOM, provenance); `dependabot.yml` (pip, npm, docker, actions, grouped weekly); `CODEOWNERS`, PR + issue templates; `actionlint` clean; local run via `act` documented.
  - *Touch:* `.github/**`
  - *Depends:* E2 (E5/E8/E9 jobs added as those land)
- [x] **E12 Observability & ops** — health, logs, backups.
  - *Acceptance:* `/api/health` and `/api/ready` (DB, scheduler, last market-data refresh); JSON logs with request IDs; Docker `HEALTHCHECK`; WAL-safe SQLite backup/restore script with a restore test; scheduler job-status endpoint + Settings panel.
  - *Touch:* `backend/app.py`, `backend/services/scheduler.py`, `scripts/backup.py`, Dockerfiles, `docker-compose.yml`
  - *Depends:* E3
- [ ] **E13 Docs + typed API client** — README, ADRs, OpenAPI.
  - *Acceptance:* README (quickstart, architecture, ingestion→plan data flow); `CONTRIBUTING.md`; `docs/adr/`; `docs/assumptions.md` listing every modeling assumption; OpenAPI generated from Pydantic schemas and a generated TS client replaces hand-written `frontend/src/api/client.ts` with a CI drift check.
  - *Touch:* `README.md`, `docs/`, `backend/schemas.py`, `frontend/src/api/`
  - *Depends:* E2, E4

---

## Track P — Planning engine (deterministic Python)

Tax and threshold data: `backend/data/tax_tables/<year>.json` with `source_url` and `retrieved_on`; a test fails when the newest table is more than a year old. Verify figures against IRS / SSA / HHS / CMS, not blogs or vendor pages.

- [x] **P1 Federal + state tax engine** — replace flat tax-rate assumptions. (Done: `services/tax.py`, 2026 IRS/CMS tables, `GET /api/tax/estimate` + chat tool, taxable-SS in household MAGI. Left for P2: wire engine rates into planner/household gross-ups, HoH status, state brackets beyond no-tax states + AZ.)
  - *Acceptance:* ordinary brackets, standard deduction, LTCG/qualified-dividend stacking, NIIT, state income tax (configurable, incl. no-tax states), taxable portion of Social Security, IRMAA tiers; filing status single/MFJ; known-answer tests from IRS worked examples; property tests (tax monotone in income, never negative, marginal ≤ top rate).
  - *Touch:* `backend/services/tax.py`, `backend/data/tax_tables/`, `backend/tests/test_tax.py`
  - *Depends:* E3, E7
- [x] **P2 Withdrawal-sequencing optimizer** — which account to draw each year. (Done: `services/withdrawals.py` with taxable-first / proportional / bracket-fill / target-MAGI strategies priced through `tax.total_tax` and the ACA schedule, ACA constants moved to `data/aca/2026.json`, `aca.subsidy_schedule`/`target_magi`, `GET /api/planner/withdrawals` + chat tool, Retirement Plan card. Left: replacing the flat `effective_tax_rate` gross-up inside `household.build_flows`/the Monte Carlo with engine rates; `household` still counts only taxable SS in ACA MAGI, whereas the new engine counts all SS per IRC 36B; HoH status.)
  - *Acceptance:* strategies (taxable→pretax→Roth, proportional, bracket-filling, target-MAGI); target-MAGI mode uses the ACA subsidy schedule for the plan year (extends `services/aca.py` beyond the cliff, respecting current law); year-by-year table of taxes/MAGI/balances; lifetime-tax comparison across strategies; wired into the planner and Retirement Plan page.
  - *Touch:* `backend/services/withdrawals.py`, `backend/services/aca.py`, `backend/services/planner.py`, `frontend/src/pages/RetirementPlan.tsx`
  - *Depends:* P1
- [x] **P3 Roth conversion explorer / ladder** — conversion amounts per year. (Done: `services/roth.py` runs fill-bracket / ACA-MAGI / first-IRMAA-tier ladders through the P2 simulator and tax/ACA code, 5-year seasoning ledger with locked converted dollars under 59½, bridge check, lifetime-cost / ending-wealth / first-RMD comparison vs no conversion, `GET /api/planner/roth` + chat tool, Retirement Plan card with per-year bars. Left: conversions are chosen greedily year by year (no look-ahead reserve for the bridge, so a long ladder can drain taxable savings sooner); Roth contribution basis vs earnings is not modeled (existing Roth treated as seasoned); IRMAA mode ignores tax-exempt interest; the chart is inline bars, not a Recharts chart.)
  - *Acceptance:* 5-year seasoning tracker per conversion; modes: fill bracket, stay under ACA MAGI target, stay under IRMAA; bridge-fund coverage check (taxable balance covers living costs + conversion tax during seasoning); lifetime-tax and ending-wealth comparison vs no-conversion; RMD-reduction effect; UI table + chart.
  - *Touch:* `backend/services/roth.py`, `backend/routes/planner_routes.py`, frontend page
  - *Depends:* P1, P2
- [x] **P4 Early-access rules** — penalty-free availability before 59½. (Done: Rule of 55, SEPP amortization/annuitization/RMD via Notice 2022-6 mortality rates, Uniform Lifetime table option, rate cap, penalty cost, exceptions list, per-account tags, rollover advice, Roth basis→conversions(5-yr)→earnings ordering with route and chat tools, SEPP comparison in the UI. Left: the mortality qx table was read from a summarized page and cross-checked against the Single Life Table (ages 0–100) rather than the primary regulation; Joint and Last Survivor table not tabulated; no Roth-ordering UI.)
  - *Acceptance:* Rule of 55 (separation year ≥ age 55 in year of separation, current-employer plan only); 72(t) SEPP calculator (amortization, annuitization, RMD methods; rate choice; modification-risk warning); 10% penalty exceptions list; Roth contribution-basis vs conversion vs earnings ordering; per-account "accessible at age X" tags shown in UI.
  - *Touch:* `backend/services/early_access.py`, `backend/models.py` (+ migration), frontend
  - *Depends:* P1
- [x] **P5 Social Security optimizer** — claiming strategy for one or two earners. (Done: `services/social_security.py` + `data/social_security.json` (2026 bend points, wage base and earnings-test amounts verified on ssa.gov via search results; statutory claiming factors), PIA from AIME, FRA by birth year, claim-age grid 62–70, spousal top-up, survivor benefit, break-even ages, Gompertz longevity-weighted household NPV across all claim pairs, haircut toggle, earnings-test function, `household.ss_factor` now delegates (identical results, tested), `GET /api/planner/social-security` + chat tool, Retirement Plan card. Left: the earnings test is a tested function but is not yet applied to planned wages inside the plan; AIME entry/statement import (the profile's amount is treated as the PIA); COLA is zero because everything is in real dollars; ssa.gov blocks automated fetches, so the COLA percentage and FRA table were not read from the page directly; no child/divorced-spouse benefits.)
  - *Acceptance:* PIA from entered AIME or statement figures; claim-age grid 62–70 per person; spousal + survivor benefits; break-even ages; longevity-weighted NPV; COLA; earnings test; benefit-cut haircut toggle (e.g. −20% after a chosen year); replaces `household.ss_factor` call sites without changing results for existing tests.
  - *Touch:* `backend/services/social_security.py`, `backend/services/household.py`, frontend
  - *Depends:* P1
- [x] **P6 RMDs and QCDs** — required distributions. (Done: `services/rmd.py` + `data/rmd_tables.json` (IRS Pub 590-B Tables I and III, SECURE 2.0 start ages, QCD limits from Notice 2025-67), per-person projection with QCD offset, inherited 10-year / stretch schedule, forced-bracket and IRMAA warning, `GET /api/rmd` and `/api/rmd/inherited` + chat tools, Retirement Plan card. Left: Table II joint-life divisor is not tabulated (flagged, Uniform table used); RMDs are not yet fed into the P2 withdrawal simulator.)
  - *Acceptance:* RMD start age by birth year (SECURE 2.0), Uniform Lifetime Table, spouse-beneficiary table when applicable, inherited-account 10-year rule, QCD offset; forced-bracket warnings feed P3.
  - *Touch:* `backend/services/rmd.py`, `backend/data/`, tests
  - *Depends:* P1
- [x] **P7 Withdrawal-strategy library + safe-spend solver** — compare policies under Monte Carlo. (Done: fixed-real, % of portfolio, Guyton-Klinger (incl. the no-cuts-in-last-15-years rule), ratcheting, floor-and-ceiling, VPW and cash-bucket policies on shared seeded real-return paths; bisection solver for max initial spend at 90% and 95% success; p10/p50/p90 spend bands and worst-year spend; route, chat tool, panel. Left: success means the spending floor was met every year, with a 50% floor for the flexible policies (a stated choice, and results are sensitive to it); one pooled portfolio with a single lognormal return, so no asset-class glide path, taxes are a flat gross-up, and it does not replace `simulate_fire`; policy parameters (GK band, ratchet trigger, ceiling) are fixed defaults, not user inputs.)
  - *Acceptance:* fixed-real (4% style), % of portfolio, Guyton-Klinger guardrails, ratcheting, floor-and-ceiling, VPW, bucket; solver returns max initial spend for a target success rate (90/95%) for the user's horizon; outputs spend-flex bands, not a single number; deterministic with a seed.
  - *Touch:* `backend/services/withdrawal_strategies.py`, `backend/services/planner.py`
  - *Depends:* E7
- [x] **P8 Sequence-of-returns stress tests** — beyond a single normal-return MC. (Done: `data/historical_returns.json` (Damodaran/NYU Stern 1928–2025 S&P 500, 10-yr bond, T-bill, CPI; spot-checked 1928/1931/2008 stock returns); replays of 1929/1966/1973/2000/2008 starts (windows without a full horizon are flagged incomplete, never a pass), all rolling windows, block bootstrap, Student-t fat tails, two-state regime model, success vs first-5-year return, cash-bucket comparison, every method labelled; route, chat tool, panel. Left: regime parameters are illustrative, not fitted; stocks/bonds only (no international, small-cap or TIPS series), annual rebalancing, no fees or taxes; rolling windows overlap; the bucket test shows the bucket does not improve overall success on these paths, which is reported as is; the 1928–2025 sample is US-only.)
  - *Acceptance:* historical-start backtests (1929, 1966, 1973, 2000, 2008) from cached public data; block bootstrap; regime-switching/fat-tail option; chart of success vs first-5-year returns; cash-bucket mitigation test; clearly labels each method and its assumptions.
  - *Touch:* `backend/services/stress.py`, `backend/data/`, frontend
  - *Depends:* E7
- [x] **P9 Healthcare + long-term care** — pre- and post-Medicare costs. (Done: `services/healthcare.py` + `data/healthcare.json`; Medicare Part B/D + Medigap with IRMAA via `tax.irmaa` (also added to the plan's Medicare line in `household.build_flows` using the current-year MAGI estimate); pre-65 ACA net premium by age via `aca.premium`; HSA accumulate/spend using `hsa.annual_limit`; LTC expected-value (probability x cost) and stress (certain) outlays, and `LTC` is now a valid `PlannedEvent` kind (priced as a purchase); `health_adj` still the only place health inflation is applied; route `/api/planner/healthcare`, chat tool, panel. Left: Part D (38.99) came from secondary web sources and Medigap (150/mo) is an unsourced illustrative figure, both flagged `verified:false`; IRMAA uses current-year MAGI, not the real two-year look-back; the profile's flat `medicare_monthly_per_person` is still the base and the new Part B/D/Medigap build-up is shown beside it, not substituted; HSA projection is a standalone panel input, not yet drawn from the account balances inside the Monte Carlo; the LTC expected/stress helper does not auto-create the PlannedEvent.)
  - *Acceptance:* pre-65 premiums by age with subsidy via P2/ACA; Medicare Part B/D with IRMAA via P1; Medigap; HSA accumulate/spend; LTC event (probability × cost, or stress case) as a `PlannedEvent` kind; health inflation separate from general (`household.health_adj`).
  - *Touch:* `backend/services/healthcare.py`, `backend/services/household.py`, `backend/models.py`
  - *Depends:* P1, P2
- [x] **P10 Spending model** — categories, smile, events. (Done: `services/spending.py` + `data/spending_model.json`; per-profile `spending_model` (migration d0e1f2a3b4c5) with category shares, per-category real inflation and go-go/slow-go/no-go smile, feeding `household.build_flows` (default model reproduces the old flat numbers, tested); event templates for college/wedding/home purchase/car/downsizing with a create-from-template route; real/nominal projection; routes, chat tools, panel. Left: the smile multipliers, category shares and template amounts are illustrative project defaults, flagged unverified in the data file; the real/nominal toggle covers the spending projection only, not every output; category shares are not editable in the UI (API only); health care keeps its own inflation and is not a category; no category-level education inflation tied to the college template.)
  - *Acceptance:* categories with their own inflation (healthcare, housing, education); spending "smile" phases; event templates (college, wedding, home purchase, car, downsizing); real/nominal toggle across all outputs.
  - *Touch:* `backend/services/household.py`, `backend/schemas.py`, frontend
  - *Depends:* E7
- [x] **P11 Income streams** (cash-balance pensions done: `Pension` model, `services/pension.py`, statement import) — non-portfolio cash flow with tax treatment. (Done: `services/income_streams.py` adds PlannedEvent kinds ANNUITY (exclusion-ratio approximation), PARTTIME (end date via repeat_until_year), RENTAL (depreciation shelters rent), EQUITY (RSU/ESPP/NSO as ordinary income), INHERIT (untaxed) and BIZSALE (long-term gain on price minus basis); new `planned_event.basis` column (migration e1f2a3b4c5d6); each year's streams are taxed as the incremental `tax.total_tax` over pension income already that year, the net flows into `household.build_flows` income (and so the Monte Carlo) and the taxable part into the MAGI estimate for ACA/IRMAA; route `/api/planner/income-streams`, chat tool, event-form kinds and basis field. Left: ISO/AMT, payroll and self-employment tax, rental passive-loss limits and depreciation recapture on sale, installment sales, inherited-IRA 10-year rule, annuity life-contingent exclusion ratio (fixed 20-year horizon used), and the streams are stacked on pension income only, not on wages or withdrawals; no dedicated UI panel beyond the event list.)
  - *Acceptance:* pension, annuity/SPIA, part-time income with end date, rental (cash flow, depreciation, sale), RSU/ESPP/ISO/NSO vesting and tax, inheritance, business sale; each taxed via P1; included in Monte Carlo flows.
  - *Touch:* `backend/models.py` (+ migration), `backend/services/household.py`
  - *Depends:* P1
- [x] **P12 Real estate and net worth** — home as an asset and a lever. (Done: `services/real_estate.py` + `data/real_estate.json`; home value, mortgage balance and equity by year at an editable appreciation rate; `liabilities.paydown_vs_invest` surfaced per debt in a new Home and debt panel; downsizing what-if with selling costs, the section 121 exclusion ($250k single / $500k joint, from the data file with the IRS source), incremental LTCG tax through P1, cash freed and upkeep change; relocation cost-of-living comparison (index ratio plus flat state-tax difference); route `/api/planner/real-estate`, chat tool, panel. Left: appreciation (3%) and selling cost (6%) are unsourced project defaults; cost basis defaults to the sale price (so no gain) unless supplied; no depreciation recapture or two-year ownership/use test; the downsize and relocation are what-if outputs, not yet applied to the Monte Carlo as events; net worth history already lives on the Dashboard and is not re-derived here.)
  - *Acceptance:* home value/equity tracking; surface `liabilities.paydown_vs_invest` in the UI; downsizing and relocation scenario; cost-of-living comparison input.
  - *Touch:* `backend/services/liabilities.py`, frontend
  - *Depends:* P10
- [x] **P13 Savings and accumulation** — contribution limits and FI variants. (Done: 2026 limits from `data/contribution_limits.json` incl. 50+ and 60–63 catch-ups, Roth IRA and IRA-deduction phase-outs, Roth catch-up wage flag; match-capture check; waterfall match → HSA → Roth/IRA (backdoor above the limit) → 401(k) → mega-backdoor → taxable; backdoor/mega-backdoor checklist with pro-rata warning; Lean/FI/Fat/Barista/Coast numbers and years-to-FI sensitivity; route, chat tool, panel. Left: only 2026 limits are tabulated and later years reuse them; match terms, HSA eligibility and pre-tax IRA balance are query inputs, not stored profile fields; SIMPLE/415(c) limits are tabulated but not in the waterfall; no per-year limit history.)
  - *Acceptance:* per-year limits (401k/IRA/HSA, catch-up, super catch-up) from data tables; employer-match capture check; backdoor/mega-backdoor Roth checklist; savings waterfall (match → HSA → Roth/IRA → 401k → taxable); FI number, Coast, Barista, Fat variants; years-to-FI sensitivity.
  - *Touch:* `backend/services/savings.py`, `backend/data/`, frontend
  - *Depends:* P1
- [x] **P14 Scenario and what-if engine** — saved, comparable scenarios. (Done: `Scenario` model + migration, presets (retire at N, spend ±10%, −30% year-1 shock via `FireInputs.first_year_shock`, SS cut, spouse death, job loss), side-by-side compare vs base, tornado of input sensitivities, seeded bisection solver for max spend / required savings / earliest age at the target success rate; routes, four chat tools, ScenarioCard. Left: SS-cut factor 0.77 is illustrative; spouse death is a rough stand-in until P15; the year-1 shock is not applied inside the earliest-age rebuild; overrides limited to whitelisted fields; tornado is a text list, not a chart.)
  - *Acceptance:* named scenarios persisted; side-by-side diff; presets (retire at N, spend ±10%, −30% market in year 1, SS cut, spouse death, job loss); tornado chart of most sensitive inputs; reverse solver (max spend / required savings / earliest retirement age for a target success).
  - *Touch:* `backend/models.py` (+ migration), `backend/routes/planner_routes.py`, frontend What-If Lab
  - *Depends:* P1, P7
- [x] **P15 Survivor and estate planning** — if one spouse dies. (Done: `services/survivor.py` + `data/estate.json`; survivor SS from P5 rules, same-income MFJ vs single tax (widow's penalty), estate-exposure flag OK/WATCH/OVER with portability, beneficiary/re-titling checklist, term-life and disability gaps; `GET /api/planner/survivor`, chat tool, card. Left: the 2026 $15M exclusion is `verified: false` (secondary sources citing Rev. Proc. 2025-32, not read on irs.gov); beneficiaries are not stored so the audit is a checklist; state estate taxes not modeled; death is modeled as a static year-0 snapshot, not threaded through the Monte Carlo; survivor spend ratio 0.75 and insurance defaults are assumptions.)
  - *Acceptance:* death-of-spouse scenario (single-filer brackets, survivor SS, account re-titling); beneficiary audit checklist; estate-tax exposure flag; term-life/disability gap estimate.
  - *Touch:* `backend/services/survivor.py`, frontend
  - *Depends:* P1, P5, P14
- [x] **P16 Assumptions panel + plan health** — transparency about the model. (Done: `services/assumptions.py`, `assumption_override` and `run_snapshot` tables + migration; returns, volatility, inflation and correlations editable with default, range and source and applied to the engine; fee-drag calculator; plan-health score with explained parts; diff of results and assumptions vs the last saved run; routes, three chat tools, card, `docs/assumptions.md`. Left: tax rates and brackets are not editable here (they come from versioned data files and the profile); the expense-ratio assumption feeds only the fee-drag calculator, not engine returns; the health score has no concentration or cash-buffer part; E13 is not done, so the doc is hand-written.)
  - *Acceptance:* every assumption (returns, vol, correlations, inflation, fees, taxes) editable with default and source; fee-drag calculator; plan health score with explanations; diff of results since last run.
  - *Touch:* `backend/services/assumptions.py`, `backend/models.py`, frontend
  - *Depends:* E13

---

## Track I — Investing and portfolio analytics

- [x] **I1 Portfolio X-Ray** — look-through exposure. (Done: `services/xray.py` look-through by asset class, sector, region and market-cap tier, fund overlap matrix, top underlying names, HHI, employer-stock concentration (`UserProfile.employer_symbol`), coverage report with Unclassified buckets; `market_data.get_fund_lookthrough` cached 7d with 1h retry on failure (also fixes `get_etf_holdings` caching a failure for a week); `GET /api/portfolio/xray`, `get_xray` chat tool, X-Ray card on Portfolio. Left: region and market-cap tier for funds come from a small approximate static table (`data/xray_fund_fallback.json`, `verified: false`) because yfinance doesn't supply them; look-through covers reported top holdings only; `research_pipeline.portfolio_exposure` still has its own sector look-through and was not migrated onto xray.)
  - *Acceptance:* exposure by asset class, sector, geography, market cap; fund overlap matrix; concentration including employer stock; cached fund-holdings fetch with graceful fallback.
  - *Touch:* `backend/services/xray.py`, `backend/services/market_data.py`, frontend
  - *Depends:* E6
- [x] **I2 Performance and benchmarks** — how the portfolio actually did. (Done: `services/performance.py` — TWR by chaining snapshot sub-periods with recorded `CashFlow`s (new table, `POST/GET/DELETE /api/cashflows`), MWR as XIRR via SciPy brentq, comparison with SPY and with a static blend of the `target_allocation` (new `UserProfile` JSON field, validated; class proxies in `data/benchmarks.json`), fee drag from plan-menu or `data/fund_fees.json` expense ratios (flagged unverified, source URL included) through `assumptions.fee_drag`, and a monthly income calendar (money markets monthly, others assumed quarterly on trailing yield). Migration `e7f8a9b0c1d2`; `GET /api/performance`, `get_performance` chat tool, Performance card on Portfolio. Left: no UI editor for `target_allocation` yet (API only); benchmarks are price-only so they understate total return by the dividend yield; the quarterly pay-month assumption is a placeholder because yfinance gives no pay dates.)
  - *Acceptance:* TWR and MWR, vs benchmark and vs target allocation, fee drag, dividend/income calendar; tested against hand-computed examples.
  - *Touch:* `backend/services/performance.py`, `backend/models.py`
  - *Depends:* D3
- [x] **I3 Rebalancing + asset location** — drift and trades. (Done: `services/rebalance.py` — drift vs `UserProfile.target_allocation` with a threshold (default 5 points) and a daily `daily_checks` alert through the notifier; self-funding trade list where every sell/buy pair sits in one account, 401(k) buys limited to `AllowedPlanMenu` (cheapest expense ratio), tax-advantaged accounts used first and taxable sells ordered lowest-gain first, realized gains priced with `tax.ltcg_tax` stacked on ordinary income; unfillable remainders are reported as `unresolved` (direct new money there); asset-location suggestions from `data/asset_location.json` with an estimated annual tax drag; `GET /api/rebalance`, `get_rebalance_plan` chat tool, Rebalance card with a target-allocation editor. Property test: trades net to zero per account and never raise drift. Left: gains use average cost and assume long-term until I4 lots land; no `planner.py` hook; no wash-sale check on the suggested buys.)
  - *Acceptance:* target allocation, drift alerts, trade list that respects 401(k) menus (`AllowedPlanMenu`) and minimizes realized gains in taxable; asset-location suggestions.
  - *Touch:* `backend/services/rebalance.py`, `backend/services/planner.py`
  - *Depends:* P1
- [x] **I4 Tax lots + tax-loss harvesting** — lot-level tracking. (Done: `TaxLot` model (migration `f8a9b0c1d2e3`); Fidelity-style lot export parser (`ingestion.parse_lots`, per-row errors, idempotent per-account replace) at `POST /api/tax-lots/import`, and `/api/ingest` now refuses lot files instead of reading them as positions; `services/tax_lots.py` — holding period (more than 365 days = long), wash-sale conflicts within ±30 days across every household account (taxable, IRA, 401(k), spouse) using substantially-identical groups in `data/substantially_identical.json`, loss-harvest candidates with per-lot estimated federal savings (marginal ordinary rate for short-term, LTCG rate for long-term via `tax.py`), wash-blocked losses listed separately, 0% LTCG gain-harvest headroom, short-term lots about to turn long-term, and specific-lot sale suggestions (losses first, then lowest tax per dollar); rules and the $3,000 offset limit in `data/tax_lot_rules.json` with IRS sources; `GET /api/tax-lots[/list|/sell]`, `get_tax_lot_report` and `suggest_lot_sale` chat tools, Tax-lots card. Left: federal only; this year's already-realized gains and loss carryforwards are unknown, so savings are per-lot estimates; fund groups are a conservative planning list, not IRS guidance; `rebalance.py` still sells at holding-level average cost rather than picking lots.)
  - *Acceptance:* lot ingestion (Fidelity lot export); wash-sale detection across taxable, IRA and spouse accounts; harvest candidates with estimated tax savings; 0% LTCG gain-harvesting hints; specific-lot sell suggestions.
  - *Touch:* `backend/models.py` (+ migration), `backend/services/ingestion.py`, `backend/services/tax_lots.py`
  - *Depends:* P1, D2
- [x] **I5 Risk analytics** — surface and test what `quant_engine` computes. (Done: `services/risk.py` — annualized volatility, max drawdown, 1-day historical VaR/CVaR (fraction and dollars), beta vs SPY, correlation matrix, per-holding risk contribution (w·Σw / wᵀΣw, hedges can go negative), and stress tests of the actual holdings against 2000–02, 2008, 2022 and 1973–74 using `data/risk_scenarios.json` (Damodaran annual returns by stocks/bonds/bills, with sector and single-stock sensitivity multipliers); holdings with no price history use their proxy ticker or the class proxy and are listed in coverage; golden test in `tests/golden/risk_two_asset.json` computed independently with the stdlib; `GET /api/portfolio/risk`, `get_risk_report` chat tool, Risk card. Left: current weights are held constant over the price window, stress uses calendar-year returns (intra-year drawdowns were deeper), sensitivities are assumptions.)
  - *Acceptance:* volatility, max drawdown, VaR/CVaR, beta, correlation matrix, risk contribution, historical stress scenarios (2008, 2022, dot-com) on actual holdings; UI panel; golden tests.
  - *Touch:* `backend/services/quant_engine.py`, frontend
  - *Depends:* E7
- [x] **I6 Cash engine upgrades** — beyond the deployment score. (Done: `services/ladder.py` — equal-rung T-bill/CD ladder with maturities, blended yield and interest (yields interpolated between the 3-month bill and 10-year note unless entered), after-tax T-bill vs money-market comparison using the state flat rate and an optional Treasury share of the fund (T-bill interest is state-exempt), I-bond annual cap/lock-up/penalty and rate check (rate is user-entered, never stored), emergency fund and bridge reserve (first N retirement years of draws from the `withdrawals.py` TAXABLE_FIRST simulation), DCA schedule; rules and sources in `data/cash_rules.json`; `services/cash_plan.py` ties them to the profile; `GET /api/planner/cash/plan|backtest`, `POST|DELETE /api/planner/cash/dca` (new `UserProfile.dca_plan`, migration `a9b0c1d2e3f4`) with a daily reminder per due tranche; `get_cash_plan` and `get_cash_backtest` chat tools; Cash-plan card on the Dashboard; `services/cash_backtest.py` and generated `docs/cash_backtest.md` (a test fails if the doc is stale). Left: the backtest uses a reduced score (real yield plus prior-year return) because annual data has no VIX, P/E or 200-day average, so it does not validate the full live score; the ladder uses one filing-status marginal rate and no CD/I-bond rate feed.)
  - *Acceptance:* T-bill/CD/I-bond ladder planner; MMF vs T-bill state-tax advantage; emergency and bridge-fund sizing tied to P2; DCA reminders; backtest of the deployment score vs buy-and-hold with results documented.
  - *Touch:* `backend/services/cash_optimizer.py`, `backend/services/ladder.py`
  - *Depends:* P1, P2
- [x] **I7 Research pipeline upgrades** — rigor and cost control. (Done: `quant_engine.dcf_grid` and `research_extras.dcf_sensitivity` — deterministic growth × discount grid (cells with discount ≤ terminal growth are blank), `GET /api/research/dcf/<sym>`, grid on the symbol detail; Form 4 insider signal (`market_data.insider_transactions`) and a 13F signal; watchlist with buy-below/upside alerts and thesis tracker with invalidation criteria (`WatchlistItem`/`ThesisRecord`, migration `b0c1d2e3f4a5`), daily alert job, Watchlist & theses card on Research; per-report cache keyed by (symbol, input hash), per-run token budget (`LLMConfig.token_budget`, 429 when exceeded, input trimmed to fit) and `verify_narrative_numbers` flagging numbers in the LLM text that are not in the input JSON; rules in `data/research_rules.json`; chat tools `get_dcf_sensitivity`, `get_insider_activity`, `get_watchlist`, `get_theses`. Left: 13F is a stub (`tracked_managers` empty, no live edgartools fetch, tested with fake data); Form 4 column mapping unverified against live data; unverified numbers are flagged in the stored report but not shown in the UI or blocked; token budget is estimated at 4 chars/token; cache keys on the exact payload hash.)
  - *Acceptance:* deterministic DCF with sensitivity grid; insider/13F signals via edgartools; watchlist and valuation alerts; thesis tracker with invalidation criteria; per-report cache and token budget; automated check that every number in LLM narrative appears in the input JSON.
  - *Touch:* `backend/services/research_pipeline.py`, `backend/services/quant_engine.py`, `backend/tests/test_research.py`
  - *Depends:* E6, E7

---

## Track D — Data in and out

- [x] **D1 More importers** — Schwab, Vanguard, E*TRADE, Robinhood, IBKR, Empower, Monarch/YNAB/Mint CSV, OFX/QFX/QIF, generic mapper, SimpleFIN Bridge. (Done: Schwab/E*TRADE/Vanguard layouts detected in `ingestion.detect_layout` (aliases extended, Schwab account from the title line, "Cash & Cash Investments" read as cash), `services/importers/ibkr.py` (Open Positions, FX converted), `services/importers/ofx.py` (OFX v1/v2 positions + cash, QIF net cash flagged low-confidence), `services/importers/mapper.py` + `ImportTemplate` (migration `c1d2e3f4a5b6`, `GET/POST/DELETE /api/ingest/templates`, `template_id`/`mapping` on `/api/ingest`); all fill `checks` via `validate_parse`; fixtures in `tests/fixtures_data/` (a `fixtures/` dir would collide with `fixtures.py`); institutions + name rules added. SimpleFIN Bridge in `services/simplefin.py` (setup-token claim, Fernet-encrypted access URL in `SimpleFinConfig`, migration `d2e3f4a5b6c7`, `/api/simplefin*`, daily `simplefin_sync` job; one cash-class holding per account). Left: SimpleFIN is tested against mocked responses only, balances only (no transactions/holdings), skips negative and non-USD accounts; layouts are built from published column names, not checked against live exports, and the Robinhood/Empower/Mint/YNAB/Monarch formats have no dedicated parser (Robinhood and Empower go through the generic path or the mapper; Monarch/YNAB/Mint are transaction exports, handled by the D4 spending parser); no frontend UI for the mapper/templates yet (API only); `.ofx` Vanguard/E*TRADE files untested against real exports.)
  - *Acceptance:* each importer has anonymized golden fixtures under `backend/tests/fixtures/` and a `validate_parse` arithmetic check; export instructions added to `services/institutions.py`; generic CSV mapper with saved templates.
  - *Touch:* `backend/services/ingestion.py`, `backend/services/institutions.py`, `backend/tests/fixtures/`
  - *Depends:* E6
- [x] **D2 Ingestion robustness** — safe re-imports. (Done against the existing parsers; D1's new importers are still open. `apply_parse` is idempotent via an order-independent rows hash (an unchanged account is skipped and not re-logged); `IngestionLog` keeps `batch_id`, `content_hash` and a pre-import copy so `POST /api/ingest/<id>/undo` restores the whole upload (removing accounts it created; only the newest live import per account is undoable); per-row `row_errors` (non-numeric, negative, shares×price mismatch) on imports and on `dry_run=1` previews; `services/corporate_actions.py` splits/reverse splits and spin-off basis allocation via `POST /api/holdings/<id>/split|spinoff`; CSV `Currency` column converted to USD with cached FX (`market_data.fx_rate`), native currency/rate kept on `Holding`; Import history card with Undo on Portfolio. Left: PDF/LLM-read statements don't carry currency or row errors; splits/spin-offs are manual (no automatic detection from statement diffs).)
  - *Acceptance:* idempotent re-import (dedupe), undo import, per-row errors in preview, split/spinoff adjustments, multi-currency, `IngestionLog` audit view in UI.
  - *Touch:* `backend/services/ingestion.py`, `backend/routes/portfolio_routes.py`, frontend
  - *Depends:* D1
- [x] **D3 Net-worth history** — snapshots and plan-vs-actual. (Done: `services/networth.py` — series, asset/liability `breakdown` on `NetWorthSnapshot` (migration `c5d6e7f8a9b0`), milestones incl. the FI number (25x retirement spend, a marker only), monthly plan-vs-actual drift projected from the first snapshot at the holdings' expected return plus monthly savings; `snapshot_net_worth` is now one row per UTC day; daily `net_worth_snapshot` scheduler job; `GET /api/networth/summary`, `get_net_worth_summary` chat tool, Net-worth card on the Dashboard. Left: drift baseline is the first snapshot, not a saved plan, so back-filled history isn't compared against what the plan said at the time.)
  - *Acceptance:* scheduled `NetWorthSnapshot`; time-series chart; asset/liability breakdown; milestones; monthly plan-vs-actual drift.
  - *Touch:* `backend/services/scheduler.py`, frontend Dashboard
  - *Depends:* E6
- [x] **D4 Spending actuals** — budgeting-lite. (Done: `services/transactions.py` (Chase/Monarch signed, Mint, YNAB, debit/credit CSVs; rules from `data/transaction_rules.json` + user rules; LLM suggestions never applied until confirmed; measured vs plan monthly spend, partial month excluded, lifestyle-creep flag), `Transaction`/`CategoryRule` (migration `e3f4a5b6c7d8`), `/api/spending/*` incl. opt-in `apply-to-plan`, chat tool `get_spending_actuals`, Spending card on Portfolio. Left: `transaction_rules.json` has no `source_url` (keyword rules are heuristics, `verified: false`); no UI for editing rules or the mapper/templates; transfers are matched by keyword only.)
  - *Acceptance:* import bank transactions; categorize via rules with LLM suggestions that require human confirm; measured spend vs plan assumption; lifestyle-creep flag; optionally feed measured spend into the planner.
  - *Touch:* `backend/services/transactions.py`, `backend/models.py` (+ migration)
  - *Depends:* D1
- [x] **D5 Exports and backups** — own your data. (Done: `services/export.py` + `routes/export_routes.py`: CSV and dependency-free text PDF plan report, full JSON export/import with round-trip test (credentials and caches excluded), Fernet-encrypted backup to local path / WebDAV / S3 via env config with a nightly `backup` job, HMAC-signed read-only share links (max 30 days) limited to `/api/share/<token>/report.csv|pdf`, Data card in Settings. Left: S3 untested (no mocked client test); share links cannot be revoked individually (rotate `APP_SECRET`); the PDF is plain text, no charts; import replaces everything and is not merge-aware; backup destination is env-only, not a Settings form.)
  - *Acceptance:* PDF and CSV plan report; full JSON export/import round-trip test; scheduled encrypted backup to local path/S3/WebDAV; read-only token-scoped share link.
  - *Touch:* `backend/services/export.py`, `backend/routes/settings_routes.py`
  - *Depends:* E12
- [x] **D6 MCP server** — read-only planning tools for external agents. (Done: `backend/mcp_server.py` exposes every `chat_tools` read-only tool (plan health, scenarios, holdings, etc.) over stdio or streamable HTTP with constant-time bearer auth, refuses to start HTTP without a token; `mcp` pinned `>=2,<3` (2.x moved `FastMCP` to `MCPServer`); tests in `tests/test_mcp_server.py`; README section. Left: each tool takes its arguments as a single `args` object rather than its native schema; no per-tool scoping or rate limit.)
  - *Acceptance:* uses the existing `mcp` dependency; tools: plan summary, scenarios, holdings; bearer-auth; contract tests; documented in README.
  - *Touch:* `backend/mcp_server.py`
  - *Depends:* E6

---

## Track U — UX and product

- [ ] **U1 shadcn/ui adoption** — spec says shadcn, code has a hand-rolled `ui.tsx`.
  - *Acceptance:* migrate components incrementally; light/dark; keyboard navigation; axe clean (E5).
  - *Touch:* `frontend/src/components/`
  - *Depends:* E4
- [ ] **U2 Onboarding wizard** — household → accounts → upload → goals → first plan.
  - *Acceptance:* resumable steps; data-completeness meter explaining which inputs improve accuracy; component + e2e tests.
  - *Touch:* `frontend/src/pages/`, `backend/routes/`
  - *Depends:* E5
- [ ] **U3 Charts** — fan chart, tax/withdrawal stack, bracket and ACA-cliff visualizer, cash-flow Sankey, scenario compare.
  - *Acceptance:* follows the `dataviz` skill; renders empty/NaN/loading states; light/dark; tested.
  - *Touch:* `frontend/src/components/charts/`
  - *Depends:* E4, P2
- [ ] **U4 Action center** — prioritized to-do feed.
  - *Acceptance:* items for match capture, conversion amount, rebalance, harvest, stale statement, year-end checklist; snooze/done; Discord/SMTP notification hooks.
  - *Touch:* `backend/services/actions.py`, `backend/services/notifier.py`, frontend
  - *Depends:* P3, I3, I4
- [ ] **U5 AI analyst improvements** — grounded, non-arithmetic assistant.
  - *Acceptance:* chat tools cover new engines; answers cite JSON fields used; refuses to compute (test with adversarial prompts and a mocked LLM); "not financial advice" and assumptions disclosure; per-scenario memory; Ollama via LiteLLM; prompt versioning tests.
  - *Touch:* `backend/services/chat_tools.py`, `backend/services/llm_router.py`
  - *Depends:* E7
- [ ] **U6 PWA, privacy, multi-user** — polish and isolation.
  - *Acceptance:* offline shell, mobile polish, privacy mode (mask balances), i18n-ready strings; per-user data-scoping tests; optional passkey/OIDC login in place of the shared token.
  - *Touch:* `frontend/public/sw.js`, `backend/app.py`, `backend/models.py`
  - *Depends:* E9

---

## Suggested order
E1 → E2 → E3 → E4 → E10 → E11 → E6/E7/E8 → P1 → P2/P3/P4 → P5/P6 → P7/P8 → I1/I3/I4 → D1/D2 → rest by value. E5, E9, E12, E13 can run alongside feature work.

## Research notes (verify before implementing)
- Competitors reviewed: Boldin/NewRetirement (Roth explorer, SS explorer), ProjectionLab, Empower, MaxiFi (SS), Ghostfolio/Actual/Firefly III (self-hosted). Most comparison pages are vendor-authored; treat claims skeptically.
- Search results disagreed on the ACA subsidy cliff figure and whether enhanced subsidies are in force. P2/P9 must read current-year law from official sources into a tax table, and the plan must show which year's rules it used.
- Sources: <https://www.boldin.com/retirement/newretirement-vs-best-retirement-planning/> · <https://robberger.com/?p=5431> · <https://q3adv.com/services/roth-conversion/for-early-retirees/> · <https://wealthvieu.com/fire-withdrawal-strategies> · <https://selfhostyourself.com/alternative-to/quicken>
