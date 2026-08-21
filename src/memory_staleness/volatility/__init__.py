"""Fact-type volatility: how fast a given kind of fact goes stale."""

from memory_staleness.volatility.loader import (
    VolatilityEntry,
    VolatilityTable,
    load_table,
)

__all__ = ["VolatilityEntry", "VolatilityTable", "load_table"]
