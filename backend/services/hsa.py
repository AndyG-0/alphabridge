"""HSA contribution limits. Data lives in data/hsa_limits.json (IRS Rev. Proc.)."""

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "hsa_limits.json"


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(DATA_FILE.read_text())


def retrieved_on() -> date:
    return date.fromisoformat(_data()["retrieved_on"])


def annual_limit(year: int, family: bool, age: float) -> int:
    """Max HSA contribution for `year` (latest known year if newer), incl. the age-55 catch-up."""
    d = _data()
    years = sorted(int(y) for y in d["years"])
    row = d["years"][str(min(max(year, years[0]), years[-1]))]
    base = row["family" if family else "self_only"]
    return base + (d["catch_up"] if age >= d["catch_up_age"] else 0)
