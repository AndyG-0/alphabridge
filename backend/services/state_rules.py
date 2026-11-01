"""State health-coverage rules (Medicaid expansion, community engagement). Data lives in data/state_rules.json."""

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "state_rules.json"


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(DATA_FILE.read_text())


def codes() -> list[str]:
    return sorted(_data()["states"])


def retrieved_on() -> date:
    return date.fromisoformat(_data()["retrieved_on"])


def engagement() -> dict:
    return _data()["community_engagement"]


def rules_for(state: str | None) -> dict:
    """Rules for a two-letter state code. Unknown codes get the expansion-state default, flagged `known: False`."""
    data = _data()
    code = (state or "").upper()
    if code in data["states"]:
        return {**data["states"][code], "state": code, "known": True}
    return {**data["default"], "state": code, "known": False}
