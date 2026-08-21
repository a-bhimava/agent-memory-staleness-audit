"""Generates memory sets whose correct answer is known by construction.

This is the known-answer layer. Every entry is planted with a label saying what the auditor
*should* conclude, so a test can assert sensitivity and specificity without a human ever
labelling anything.

The generator is built around one rule: **the control entries matter as much as the planted
stale ones.** A staleness auditor that flags everything scores perfectly on recall and is
useless. Half of what this produces is deliberately fresh, deliberately immutable, or
deliberately unassessable, and a test that only checks the catches is not a test.
"""

from __future__ import annotations

import datetime as dt
import random
from enum import StrEnum

from memory_staleness.ids import DEFAULT_SEED, derive_seed
from memory_staleness.types import FactType, Frozen, MemoryEntry, Provenance, Verdict

REFERENCE_NOW = dt.datetime(2026, 8, 21, 12, 0, 0, tzinfo=dt.UTC)
"""Fixed clock for generated stores.

Hardcoded rather than ``datetime.now()`` so a fixture generated today and one generated next
year are byte-identical. A generator that reads the wall clock produces a different corpus on
every run and destroys cross-run comparability — the same reason seeds are derived
hierarchically in :mod:`memory_staleness.ids`.
"""


class CaseKind(StrEnum):
    """Why an entry was planted, i.e. which behaviour it is there to test."""

    STALE_AGED = "stale_aged"
    """Old, volatile, still retrieved. Should be REVERIFY on age alone."""

    STALE_SUPERSEDED_SILENT = "stale_superseded_silent"
    """A newer entry exists for the same subject+predicate and does NOT contradict it.

    The flagship case. Contradiction-based invalidation in Zep and Mem0 cannot see this one.
    """

    STALE_SUPERSEDED_CONTRADICTING = "stale_superseded_contradicting"
    """Superseded and visibly contradicting. A contradiction detector would also catch it —
    included so the two can be reported separately and no credit is claimed for the easy case."""

    ABANDONED = "abandoned"
    """Old, volatile, never retrieved. Should be FORGET, not REVERIFY."""

    CONTROL_FRESH = "control_fresh"
    """Recently written. Must NOT fire."""

    CONTROL_IMMUTABLE = "control_immutable"
    """Ancient but of a non-decaying type — a date of birth. Must NOT fire.

    This is the specificity test that a naive age-only scorer fails.
    """

    CONTROL_NO_PROVENANCE = "control_no_provenance"
    """No write timestamp. Must return CANNOT_ASSESS, never a guess in either direction."""


_EXPECTED: dict[CaseKind, Verdict] = {
    CaseKind.STALE_AGED: Verdict.REVERIFY,
    CaseKind.STALE_SUPERSEDED_SILENT: Verdict.REVERIFY,
    CaseKind.STALE_SUPERSEDED_CONTRADICTING: Verdict.REVERIFY,
    CaseKind.ABANDONED: Verdict.FORGET,
    CaseKind.CONTROL_FRESH: Verdict.FRESH,
    CaseKind.CONTROL_IMMUTABLE: Verdict.FRESH,
    CaseKind.CONTROL_NO_PROVENANCE: Verdict.CANNOT_ASSESS,
}


class PlantedCase(Frozen):
    """One entry plus the verdict the auditor is expected to reach for it."""

    entry: MemoryEntry
    kind: CaseKind
    expected: Verdict
    note: str = ""


class SyntheticStore(Frozen):
    """A generated corpus and its ground truth."""

    cases: tuple[PlantedCase, ...]
    as_of: dt.datetime
    seed: int

    @property
    def entries(self) -> tuple[MemoryEntry, ...]:
        """Just the memories, as an adapter would hand them over."""
        return tuple(case.entry for case in self.cases)

    def expected_for(self, memory_id: str) -> Verdict:
        """Ground-truth verdict for one memory id."""
        for case in self.cases:
            if case.entry.memory_id == memory_id:
                return case.expected
        raise KeyError(memory_id)


_SUBJECTS = (
    "alice",
    "bob",
    "cara",
    "dan",
    "erin",
    "frank",
    "gita",
    "hana",
    "ivan",
    "jo",
    "kemi",
    "luis",
    "mei",
    "nina",
    "omar",
    "priya",
)
_EMPLOYERS = ("Acme", "Globex", "Initech", "Umbrella", "Soylent", "Hooli", "Vehement", "Massive")
_CITIES = ("Boston", "Austin", "Pittsburgh", "Denver", "Seattle", "Chicago", "Atlanta", "Portland")
_PROJECTS = ("Zeus", "Atlas", "Kestrel", "Lantern", "Mosaic", "Nimbus", "Onyx", "Pyxis")


def _pick(rng: random.Random, options: tuple[str, ...]) -> str:
    return options[rng.randrange(len(options))]


def generate_store(
    *,
    n_per_kind: int = 6,
    seed: int = DEFAULT_SEED,
    as_of: dt.datetime = REFERENCE_NOW,
) -> SyntheticStore:
    """Build a balanced corpus with ``n_per_kind`` entries of each :class:`CaseKind`.

    Balanced on purpose. An imbalanced corpus lets a degenerate scorer — one that flags
    everything, or nothing — post a respectable-looking accuracy, which is precisely the kind
    of number this project exists to distrust.
    """
    cases: list[PlantedCase] = []

    def add(
        kind: CaseKind,
        index: int,
        *,
        subject: str,
        predicate: str,
        object_: str,
        fact_type: FactType,
        days_ago: float | None,
        retrieval_count: int,
        note: str = "",
        suffix: str = "",
    ) -> MemoryEntry:
        written = None if days_ago is None else as_of - dt.timedelta(days=days_ago)
        entry = MemoryEntry(
            memory_id=f"{kind.value}-{index:03d}{suffix}",
            subject=subject,
            predicate=predicate,
            object=object_,
            fact_type=fact_type,
            provenance=Provenance(
                source=None if days_ago is None else f"conversation:{index:04d}",
                written_at=written,
            ),
            retrieval_count=retrieval_count,
            text=f"{subject} {predicate.replace('_', ' ')} {object_}",
        )
        # Supersession partners are added to the corpus but are not themselves graded — they
        # are the newer, correct entry. Grading them would double-count the same planted fact.
        if not suffix:
            cases.append(PlantedCase(entry=entry, kind=kind, expected=_EXPECTED[kind], note=note))
        else:
            cases.append(
                PlantedCase(
                    entry=entry,
                    kind=CaseKind.CONTROL_FRESH,
                    expected=Verdict.FRESH,
                    note="supersession partner: the newer, still-correct entry",
                )
            )
        return entry

    for i in range(n_per_kind):
        rng = random.Random(derive_seed(seed, "case", i))
        subject = f"{_pick(rng, _SUBJECTS)}-{i:02d}"

        add(
            CaseKind.STALE_AGED,
            i,
            subject=subject,
            predicate="works_at",
            object_=_pick(rng, _EMPLOYERS),
            fact_type=FactType.EMPLOYER,
            days_ago=1200,
            retrieval_count=8 + i,
            note="1200d against a 550d half-life, still actively retrieved",
        )

        # The flagship case: same subject+predicate, newer entry, identical object. Nothing
        # contradicts, so a contradiction detector sees nothing at all.
        silent_subject = f"silent-{subject}"
        employer = _pick(rng, _EMPLOYERS)
        add(
            CaseKind.STALE_SUPERSEDED_SILENT,
            i,
            subject=silent_subject,
            predicate="works_at",
            object_=employer,
            fact_type=FactType.EMPLOYER,
            days_ago=900,
            retrieval_count=5 + i,
            note="a newer entry asserts the same thing; no contradiction exists to detect",
        )
        add(
            CaseKind.STALE_SUPERSEDED_SILENT,
            i,
            subject=silent_subject,
            predicate="works_at",
            object_=employer,
            fact_type=FactType.EMPLOYER,
            days_ago=30,
            retrieval_count=2,
            suffix="-newer",
        )

        contra_subject = f"contra-{subject}"
        add(
            CaseKind.STALE_SUPERSEDED_CONTRADICTING,
            i,
            subject=contra_subject,
            predicate="lives_in",
            object_=_CITIES[i % len(_CITIES)],
            fact_type=FactType.RESIDENCE_CITY,
            days_ago=1500,
            retrieval_count=4 + i,
            note="visibly contradicted by a newer entry; the easy case, reported separately",
        )
        add(
            CaseKind.STALE_SUPERSEDED_CONTRADICTING,
            i,
            subject=contra_subject,
            predicate="lives_in",
            object_=_CITIES[(i + 3) % len(_CITIES)],
            fact_type=FactType.RESIDENCE_CITY,
            days_ago=20,
            retrieval_count=1,
            suffix="-newer",
        )

        add(
            CaseKind.ABANDONED,
            i,
            subject=subject,
            predicate="working_on",
            object_=_pick(rng, _PROJECTS),
            fact_type=FactType.PROJECT_STATUS,
            days_ago=600,
            retrieval_count=0,
            note="long dead and nothing reads it: forget rather than re-verify",
        )

        add(
            CaseKind.CONTROL_FRESH,
            i,
            subject=subject,
            predicate="prefers_tool",
            object_="ripgrep",
            fact_type=FactType.TOOL_PREFERENCE,
            days_ago=5,
            retrieval_count=3,
            note="must not fire",
        )

        add(
            CaseKind.CONTROL_IMMUTABLE,
            i,
            subject=subject,
            predicate="born_on",
            object_=f"19{70 + i}-0{1 + (i % 9)}-14",
            fact_type=FactType.DATE_OF_BIRTH,
            days_ago=7000,
            retrieval_count=6,
            note="ancient but non-decaying; an age-only scorer fails this",
        )

        add(
            CaseKind.CONTROL_NO_PROVENANCE,
            i,
            subject=subject,
            predicate="dietary_restriction",
            object_="vegetarian",
            fact_type=FactType.DIETARY_RESTRICTION,
            days_ago=None,
            retrieval_count=2,
            note="no write timestamp; must be an admission, not a guess",
        )

    return SyntheticStore(cases=tuple(cases), as_of=as_of, seed=seed)


__all__ = ["REFERENCE_NOW", "CaseKind", "PlantedCase", "SyntheticStore", "generate_store"]
