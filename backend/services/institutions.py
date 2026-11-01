"""Institution registry: single source of truth for account defaults, name inference and
"where to get your documents" help. Adding a bank = one entry here (plus a parser only if its
export isn't a generic positions/balance CSV)."""

INSTITUTIONS: list[dict] = [
    {
        "id": "FIDELITY_RETAIL",
        "label": "Fidelity",
        "kind": "brokerage",
        "login_url": "https://digital.fidelity.com/",
        "docs": [
            {
                "what": "Positions (brokerage, Roth IRA, HSA, cash)",
                "steps": [
                    "Log in and open Accounts & Trade > Portfolio.",
                    "Choose the Positions tab.",
                    "Click the download icon (top right of the table) and pick Download.",
                    "Upload the CSV; every account in the file is split out automatically.",
                ],
                "formats": ["CSV"],
            }
        ],
    },
    {
        "id": "FIDELITY_NETBENEFITS",
        "label": "Fidelity NetBenefits (401k)",
        "kind": "retirement_plan",
        "login_url": "https://nb.fidelity.com/",
        "docs": [
            {
                "what": "401(k) balances by fund",
                "steps": [
                    "Log in and open your plan, then Investments / Portfolio Summary.",
                    "Use the download/export option on the holdings table, or save the Statements PDF.",
                    "Upload to the plan's account; unknown plan funds will ask for a proxy ticker.",
                ],
                "formats": ["CSV", "PDF"],
            }
        ],
    },
    {
        "id": "NATIONWIDE",
        "label": "Nationwide (retirement plan)",
        "kind": "retirement_plan",
        "login_url": "https://www.nationwide.com/",
        "docs": [
            {
                "what": "Plan balances by fund",
                "steps": [
                    "Log in to your retirement plan account and open Account Balance / Investments.",
                    "Export the balances (CSV) or download the quarterly statement PDF.",
                    "Nationwide files have no account column: choose the target account before uploading.",
                ],
                "formats": ["CSV", "PDF"],
            },
            {
                "what": "Cash-balance pension (Account Balance statement)",
                "steps": [
                    "Open the plan's Account Balance statement and use Print Statement > Save as PDF.",
                    "Upload it as-is: it is imported as a pension (balance plus pay and interest credits), not as holdings.",
                    "Each spouse's statement is matched by the name printed on it; if it can't tell, choose the owner before uploading.",
                ],
                "formats": ["PDF"],
            },
        ],
    },
    {
        "id": "ALLY",
        "label": "Ally (Invest & Bank)",
        "kind": "brokerage",
        "login_url": "https://www.ally.com/",
        "docs": [
            {
                "what": "Monthly statements (Invest brokerage, savings, checking)",
                "steps": ["Log in and open Documents > Statements for the account.", "Download the monthly statement PDF and upload it."],
                "formats": ["PDF"],
            }
        ],
    },
    {
        "id": "CHASE",
        "label": "Chase (checking / savings)",
        "kind": "bank",
        "login_url": "https://www.chase.com/",
        "docs": [
            {
                "what": "Account activity with running balance (checking, savings)",
                "steps": [
                    "Log in, open the account, then Download account activity.",
                    "Choose CSV and a recent date range; the latest balance is used.",
                    "Statement PDFs (Statements & documents) also work but go through the AI fallback.",
                ],
                "formats": ["CSV", "PDF"],
            }
        ],
    },
    {
        "id": "COMPUTERSHARE",
        "label": "Computershare (company stock)",
        "kind": "brokerage",
        "login_url": "https://www.computershare.com/",
        "docs": [
            {
                "what": "Balance letter for directly held shares (DRIP / transfer agent)",
                "steps": [
                    "Log in to Investor Center and open the holding, then Documents / Balance letter.",
                    "Save or print the letter as PDF (a screenshot or photo also works).",
                    "Scanned or image-only letters are read with OCR / the AI vision fallback and shown for confirmation.",
                ],
                "formats": ["PDF", "PNG", "JPG"],
            }
        ],
    },
    {
        "id": "OTHER",
        "label": "Other",
        "kind": "other",
        "login_url": None,
        "docs": [
            {
                "what": "Any CSV with a name/symbol column and a value/balance column, or a PDF statement",
                "steps": [
                    "Export positions or balances from your provider.",
                    "Upload it; PDFs and photos without a known layout are read by OCR / the AI fallback and shown for confirmation.",
                ],
                "formats": ["CSV", "PDF", "PNG", "JPG"],
            }
        ],
    },
]

_CASH = dict(tax_bucket="CASH_MMF", risk_tier="CASH")
_HSA = dict(tax_bucket="HSA", risk_tier="MODERATE_GROWTH")
_PLAN = dict(tax_bucket="PRE_TAX_401K", risk_tier="SAFE_CORE", is_restricted_plan=True)

# Ordered; first rule with a matching keyword wins. Matched against the lower-cased account name.
NAME_RULES: list[tuple[tuple[str, ...], dict]] = [
    (("hsa", "health savings"), dict(institution="FIDELITY_RETAIL", **_HSA)),  # before the "savings"/"cash" rule
    (("chase",), dict(institution="CHASE", **_CASH)),
    (("ally bank", "savings", "cash", "money market"), dict(institution="ALLY", **_CASH)),
    (("ally",), dict(institution="ALLY", tax_bucket="TAXABLE_BROKERAGE", risk_tier="AGGRESSIVE_SATELLITE")),
    (("nationwide",), dict(institution="NATIONWIDE", **_PLAN)),
    (("netbenefits", "401", "403"), dict(institution="FIDELITY_NETBENEFITS", **_PLAN)),
    (("computershare", "shareowner", "equiniti"), dict(institution="COMPUTERSHARE", tax_bucket="TAXABLE_BROKERAGE", risk_tier="AGGRESSIVE_SATELLITE")),
    (("roth",), dict(institution="FIDELITY_RETAIL", tax_bucket="ROTH", risk_tier="MODERATE_GROWTH")),
]
DEFAULT_ATTRS = dict(institution="FIDELITY_RETAIL", tax_bucket="TAXABLE_BROKERAGE", risk_tier="AGGRESSIVE_SATELLITE")


def attrs_for_name(name: str) -> dict:
    n = name.lower()
    for keywords, attrs in NAME_RULES:
        if any(k in n for k in keywords):
            return dict(attrs)
    return dict(DEFAULT_ATTRS)


# Where to get debt statements (not tied to a lender: layouts vary, so CSV is read by header and PDFs by the AI fallback).
LIABILITY_DOCS: list[dict] = [
    {
        "what": "Mortgage",
        "steps": [
            "Open your servicer's Statements / Documents page and download the latest monthly statement PDF.",
            "Statements that itemise principal, interest and escrow import the escrow separately.",
        ],
    },
    {"what": "Auto, student and personal loans", "steps": ["Download the latest statement PDF, or the loan summary CSV if offered."]},
    {
        "what": "Credit cards",
        "steps": [
            "Download the latest monthly statement PDF; the statement balance and purchase APR are used.",
            "The minimum payment is recorded; raise it in the debt list if you pay more.",
        ],
    },
    {"what": "CSV format", "steps": ["Any CSV with a name column and a balance column; optional APR, payment, escrow and type columns."]},
]
