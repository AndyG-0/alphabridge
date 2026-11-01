"""Stock splits and spin-offs applied to holdings. Splits change share count and price, never value or basis; spin-offs move cost basis."""

from models import Holding


def split(h: Holding, ratio: float) -> dict:
    """ratio = new shares per old share (2 for a 2-for-1 split, 0.1 for a 1-for-10 reverse split)."""
    if not ratio or ratio <= 0:
        raise ValueError("split ratio must be positive")
    h.shares *= ratio
    h.current_price = h.current_price / ratio if h.current_price else h.current_price
    return {
        "symbol": h.symbol,
        "ratio": ratio,
        "shares": h.shares,
        "price": h.current_price,
        "market_value": h.market_value,
        "cost_basis_total": h.cost_basis_total,
    }


def allocate_spinoff_basis(parent_basis: float, child_fraction: float) -> tuple[float, float]:
    """Split a parent's cost basis between parent and spun-off child by the fraction the company allocates to the child (Form 8937)."""
    if not 0 < child_fraction < 1:
        raise ValueError("basis fraction must be between 0 and 1 (exclusive)")
    child = parent_basis * child_fraction
    return parent_basis - child, child


def spinoff(s, parent: Holding, child_symbol: str, child_shares: float, child_fraction: float, child_price: float = 0.0, child_name: str = "") -> dict:
    """Create (or add to) the child holding in the parent's account and move `child_fraction` of the parent's basis to it.
    The child's value is its shares x price; the parent's value is left as imported until the next statement refreshes it."""
    if child_shares <= 0:
        raise ValueError("spin-off shares must be positive")
    sym = child_symbol.strip().upper()
    if not sym or sym == parent.symbol:
        raise ValueError("spin-off needs a different symbol")
    parent_basis, child_basis = allocate_spinoff_basis(parent.cost_basis_total, child_fraction)
    child = s.query(Holding).filter(Holding.account_id == parent.account_id, Holding.symbol == sym).first()
    if child is None:
        child = Holding(
            account_id=parent.account_id, symbol=sym, name=child_name or sym, asset_class=parent.asset_class, shares=0, cost_basis_total=0, market_value=0
        )
        s.add(child)
    child.shares += child_shares
    child.cost_basis_total += child_basis
    if child_price:
        child.current_price = child_price
        child.market_value = child.shares * child_price
    parent.cost_basis_total = parent_basis
    return {
        "parent": parent.symbol,
        "parent_basis": parent_basis,
        "child": sym,
        "child_shares": child.shares,
        "child_basis": child.cost_basis_total,
        "child_value": child.market_value,
    }
