"""The frozen record types every other module reads and writes.

Four invariants live here, and each is enforced by a test in ``tests/unit/test_types.py``
rather than by convention:

1. **Every record is immutable, recursively.** A staleness score that can be edited after
   the fact is not evidence. ``Frozen`` gives shallow immutability; :class:`FrozenDict`
   closes the hole that a plain ``dict`` field would otherwise leave open.
2. **Derived quantities are properties, never stored fields.** ``age_days`` is computed
   from ``written_at`` and the audit's ``as_of``. Storing it would let a record carry an
   age that disagrees with its own timestamp — the bug class this whole tool exists to
   detect, reintroduced in the tool itself.
3. **Provenance is nullable and its absence is load-bearing.** ``source is None`` must
   produce :attr:`Verdict.CANNOT_ASSESS`, never a guess. An auditor that invents a
   confidence for a memory it cannot trace is worse than no auditor.
4. **Time is timezone-aware UTC everywhere.** A naive datetime in a staleness calculation
   is an off-by-hours error waiting for a daylight-saving boundary.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator, Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import core_schema


class FrozenDict(Mapping[str, Any]):
    """An immutable mapping that pydantic will accept in place of ``dict``.

    Exists because ``model_config = ConfigDict(frozen=True)`` freezes *attribute assignment*
    on the model, not the objects the attributes point at. Without this, ``entry.extra["x"]
    = 1`` silently mutates a record that the rest of the codebase treats as evidence.
    """

    __slots__ = ("_data",)

    def __init__(self, data: Mapping[str, Any] | None = None) -> None:
        object.__setattr__(self, "_data", dict(data or {}))

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"FrozenDict({self._data!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FrozenDict):
            return self._data == other._data
        if isinstance(other, Mapping):
            return self._data == dict(other)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(tuple(sorted(self._data.items(), key=lambda kv: kv[0])))

    def model_dump(self) -> dict[str, Any]:
        """Present as a plain dict for serialization. Named to match pydantic so
        ``ids._encode`` needs no special case."""
        return dict(self._data)

    @classmethod
    def __get_pydantic_core_schema__(cls, source: Any, handler: Any) -> core_schema.CoreSchema:
        del source, handler
        return core_schema.no_info_plain_validator_function(
            cls._validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda v: dict(v), return_schema=core_schema.dict_schema()
            ),
        )

    @classmethod
    def _validate(cls, value: Any) -> FrozenDict:
        if isinstance(value, FrozenDict):
            return value
        if isinstance(value, Mapping):
            return cls(value)
        raise TypeError(f"expected a mapping, got {type(value).__name__}")


class Frozen(BaseModel):
    """Base for every record in this package."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class FactType(StrEnum):
    """The kind of fact a memory asserts.

    This is the axis volatility is defined over, and it is the load-bearing choice in the
    whole tool: a job title and a birthday age at wildly different rates, and a scorer that
    treats them identically is just a clock. The mapping from fact type to half-life is
    human-authored in ``volatility/table.yaml`` — deliberately not model-inferred, because
    a reviewer has to be able to disagree with a specific number.
    """

    EMPLOYER = "employer"
    JOB_TITLE = "job_title"
    EMPLOYMENT_STATUS = "employment_status"
    PROJECT_STATUS = "project_status"
    RESIDENCE_CITY = "residence_city"
    STREET_ADDRESS = "street_address"
    PHONE_NUMBER = "phone_number"
    EMAIL_ADDRESS = "email_address"
    MARITAL_STATUS = "marital_status"
    ACCOUNT_BALANCE = "account_balance"
    STATED_GOAL = "stated_goal"
    TOOL_PREFERENCE = "tool_preference"
    DIETARY_RESTRICTION = "dietary_restriction"
    DATE_OF_BIRTH = "date_of_birth"
    BIRTHPLACE = "birthplace"
    IMMUTABLE_IDENTIFIER = "immutable_identifier"
    UNCLASSIFIED = "unclassified"


class Verdict(StrEnum):
    """What the auditor concluded about one memory.

    ``REVERIFY`` and ``FORGET`` are deliberately distinct outcomes for the *same* high
    staleness score, split by whether anything still retrieves the memory. That second
    branch matters as much as the first: it makes this a principled forgetting policy, not
    only a staleness alarm.
    """

    REVERIFY = "reverify"
    """High staleness and still being retrieved — confidently wrong, in use. The dangerous case."""

    FORGET = "forget"
    """High staleness and never retrieved — safe to drop."""

    FRESH = "fresh"
    """Low staleness. Leave alone."""

    CANNOT_ASSESS = "cannot_assess"
    """No usable provenance. Not a guess, and not a pass — see invariant 3 above."""


class Provenance(Frozen):
    """Where a memory came from and when it was written."""

    source: str | None = Field(
        default=None,
        description="Opaque origin identifier, e.g. 'conversation:8821' or 'crm-sync'. "
        "None means the store did not record one, which forces CANNOT_ASSESS.",
    )
    written_at: dt.datetime | None = Field(
        default=None,
        description="When this assertion entered the store. None forces CANNOT_ASSESS.",
    )

    @field_validator("written_at")
    @classmethod
    def _require_utc(cls, value: dt.datetime | None) -> dt.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("written_at must be timezone-aware; naive datetimes are rejected")
        return value.astimezone(dt.UTC)

    @property
    def assessable(self) -> bool:
        """True when there is enough provenance to compute an age at all."""
        return self.written_at is not None


class MemoryEntry(Frozen):
    """One assertion in a memory store, normalized across adapters.

    The ``subject``/``predicate``/``object_`` triple is what makes supersession detectable:
    two entries about the same subject and predicate are candidates for one retiring the
    other, whether or not their objects contradict.
    """

    memory_id: str
    subject: str
    predicate: str
    object_: str = Field(alias="object")
    fact_type: FactType = FactType.UNCLASSIFIED
    provenance: Provenance = Provenance()
    retrieval_count: int = Field(default=0, ge=0)
    last_retrieved_at: dt.datetime | None = None
    text: str = ""
    extra: FrozenDict = Field(default_factory=FrozenDict)

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    @field_validator("last_retrieved_at")
    @classmethod
    def _require_utc(cls, value: dt.datetime | None) -> dt.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("last_retrieved_at must be timezone-aware")
        return value.astimezone(dt.UTC)

    @property
    def claim_key(self) -> tuple[str, str]:
        """The (subject, predicate) pair two entries must share to be supersession candidates."""
        return (self.subject.strip().lower(), self.predicate.strip().lower())

    def age_days(self, as_of: dt.datetime) -> float | None:
        """Age in days at ``as_of``, or None when provenance is missing.

        A property rather than a stored field on purpose — see invariant 2.
        """
        if self.provenance.written_at is None:
            return None
        return (as_of - self.provenance.written_at).total_seconds() / 86400.0


class Supersession(Frozen):
    """Evidence that a newer entry should retire an older one."""

    superseded_by: str
    """memory_id of the newer entry sharing this entry's claim_key."""

    newer_written_at: dt.datetime
    contradicts: bool
    """True when the two objects visibly disagree.

    False is the interesting case and the reason this project exists: same subject, same
    predicate, a newer entry present, and *no* visible contradiction — which is exactly
    what contradiction-based invalidation in Zep/Graphiti and Mem0 cannot catch.
    """


class StalenessScore(Frozen):
    """The auditor's finding for one memory. Every component is reported, not just the total."""

    memory_id: str
    verdict: Verdict
    score: float = Field(ge=0.0, le=1.0)
    age_days: float | None
    half_life_days: float | None
    age_component: float = Field(ge=0.0, le=1.0)
    retrieval_component: float = Field(ge=0.0, le=1.0)
    supersession: Supersession | None = None
    reasons: tuple[str, ...] = ()
    """Human-readable justification, one string per contributing signal.

    Present because a score with no explanation cannot be argued with, and the failure mode
    this tool must avoid above all others is being confidently wrong about confident
    wrongness.
    """


__all__ = [
    "FactType",
    "Frozen",
    "FrozenDict",
    "MemoryEntry",
    "Provenance",
    "StalenessScore",
    "Supersession",
    "Verdict",
]
