"""Loads and validates ``table.yaml``.

The loader is strict on purpose. A typo in a fact-type key would otherwise silently fall
through to the default half-life, and a scorer quietly using the wrong decay constant is
exactly the kind of failure this project exists to make impossible elsewhere.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from memory_staleness.ids import sha256_file
from memory_staleness.types import FactType, Frozen

TABLE_PATH = Path(__file__).parent / "table.yaml"
SCHEMA = "memory-staleness/volatility@1"


class UnknownFactTypeError(ValueError):
    """Raised when ``table.yaml`` names a fact type that :class:`FactType` does not define.

    Unrecoverable rather than warn-and-continue: a table that references a type the code
    cannot represent means the table and the code have drifted, and every score produced
    afterward would be computed against an assumption nobody checked.
    """


class VolatilityEntry(Frozen):
    """One row of the table."""

    fact_type: FactType
    half_life_days: float | None
    basis: str

    @property
    def immutable(self) -> bool:
        """True when this kind of fact does not decay with time at all."""
        return self.half_life_days is None


class VolatilityTable(Frozen):
    """The whole table, plus the digest of the file it came from.

    ``source_sha256`` is carried so a run manifest can record *which* volatility assumptions
    produced a set of scores. Changing a half-life changes every score in the audit, so a
    result that does not name its table is not reproducible.
    """

    entries: tuple[VolatilityEntry, ...]
    default_half_life_days: float
    default_basis: str
    source_sha256: str

    def entry_for(self, fact_type: FactType) -> VolatilityEntry:
        """Return the row for ``fact_type``, falling back to the documented default."""
        for entry in self.entries:
            if entry.fact_type is fact_type:
                return entry
        return VolatilityEntry(
            fact_type=fact_type,
            half_life_days=self.default_half_life_days,
            basis=self.default_basis,
        )

    def half_life(self, fact_type: FactType) -> float | None:
        """Half-life in days for ``fact_type``; None when the type does not decay."""
        return self.entry_for(fact_type).half_life_days


def load_table(path: Path | str = TABLE_PATH) -> VolatilityTable:
    """Parse and validate the volatility table at ``path``."""
    path = Path(path)
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))

    schema = raw.get("schema")
    if schema != SCHEMA:
        raise ValueError(f"{path}: expected schema {SCHEMA!r}, found {schema!r}")

    defaults = raw.get("defaults") or {}
    entries: list[VolatilityEntry] = []
    for key, value in (raw.get("fact_types") or {}).items():
        try:
            fact_type = FactType(key)
        except ValueError as exc:
            known = ", ".join(sorted(member.value for member in FactType))
            raise UnknownFactTypeError(
                f"{path}: fact type {key!r} is not defined in FactType. "
                f"Add it to the enum or fix the key. Known types: {known}"
            ) from exc
        entries.append(
            VolatilityEntry(
                fact_type=fact_type,
                half_life_days=value.get("half_life_days"),
                basis=value.get("basis", ""),
            )
        )

    return VolatilityTable(
        entries=tuple(sorted(entries, key=lambda e: e.fact_type.value)),
        default_half_life_days=float(defaults.get("half_life_days", 180)),
        default_basis=defaults.get("basis", ""),
        source_sha256=sha256_file(path),
    )


__all__ = [
    "SCHEMA",
    "TABLE_PATH",
    "UnknownFactTypeError",
    "VolatilityEntry",
    "VolatilityTable",
    "load_table",
]
