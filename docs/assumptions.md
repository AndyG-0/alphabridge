# Model assumptions

Every number the planner assumes, where it lives, and how to change it. The live list (with defaults, current values and sources) is
`GET /api/planner/assumptions` and the Assumptions card on the Retirement Plan page. Edits are stored in `assumption_override` and applied to
`services/quant_engine.py` before each run; clearing an edit restores the default.

| Group | Keys | Default source |
|---|---|---|
| Returns and volatility | `ret.<CLASS>`, `vol.<CLASS>` | Project capital-market assumptions, long-run nominal. Not forecasts. |
| Inflation | `inflation` | Project assumption (2.5%). |
| Correlations | `corr.equity`, `corr.other` | Project assumption (0.8 and 0.2). |
| Fees | `fee.expense_ratio` | Used by the fee-drag calculator only; not subtracted from engine returns. |
| Taxes, Social Security, ACA, RMD, contribution limits, estate | versioned files in `backend/data/` | Each file carries `source_url`, `retrieved_on` and, where unconfirmed, `verified: false`. |

Plan health (0-100) combines success vs target (55), bridge funding (25) and spending headroom (20); each part states what it measured.
"Save this run" stores the headline metrics and the assumptions in force; the next view shows what changed since.

Unverified figures: `healthcare.json` (Part D, Medigap) and `estate.json` (read from secondary sources citing the IRS) are flagged `verified: false`.
