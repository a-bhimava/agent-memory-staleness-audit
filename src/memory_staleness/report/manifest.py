"""The run manifest: everything needed to reproduce a set of scores.

A score with no manifest is an anecdote. The manifest names the seed, the clock, the corpus
parameters, and — critically — the SHA-256 of the volatility table, because changing one
half-life changes every score in the audit.
"""

from __future__ import annotations

import datetime as dt
import platform
import sys
from collections import Counter

from memory_staleness.ids import content_id
from memory_staleness.types import Frozen, StalenessScore, Verdict

SCHEMA = "memory-staleness/manifest@1"


class Counts(Frozen):
    """Verdict distribution for one audit."""

    total: int
    reverify: int
    forget: int
    fresh: int
    cannot_assess: int

    @classmethod
    def from_scores(cls, scores: tuple[StalenessScore, ...]) -> Counts:
        tally = Counter(s.verdict for s in scores)
        return cls(
            total=len(scores),
            reverify=tally[Verdict.REVERIFY],
            forget=tally[Verdict.FORGET],
            fresh=tally[Verdict.FRESH],
            cannot_assess=tally[Verdict.CANNOT_ASSESS],
        )


class Manifest(Frozen):
    """Provenance for one audit run."""

    schema_: str = SCHEMA
    run_id: str
    created_at: dt.datetime
    kind: str
    """'synthetic' or 'export'. Chosen at construction, never sniffed afterwards — a run that
    guesses its own nature can misdescribe itself in the published bundle."""

    as_of: dt.datetime
    seed: int
    corpus: dict[str, int]
    volatility_sha256: str
    reverify_threshold: float
    supersession_weight: float
    tool_version: str
    python_version: str
    platform_: str
    counts: Counts

    def model_dump_public(self) -> dict:
        """Serialization shape with the trailing-underscore fields spelled properly."""
        data = self.model_dump()
        data["schema"] = data.pop("schema_")
        data["platform"] = data.pop("platform_")
        return data


def build_manifest(
    scores: tuple[StalenessScore, ...],
    *,
    kind: str,
    as_of: dt.datetime,
    seed: int,
    corpus: dict[str, int],
    volatility_sha256: str,
    reverify_threshold: float,
    supersession_weight: float,
    created_at: dt.datetime | None = None,
) -> Manifest:
    """Assemble a manifest.

    ``run_id`` is content-addressed over everything that determines the result *except*
    ``created_at``, so re-running the same audit twice yields the same run_id. That is what
    makes the determinism gate in CI meaningful — a timestamp-derived id would differ on
    every run and the gate would prove nothing.
    """
    from memory_staleness import __version__

    identity = {
        "kind": kind,
        "as_of": as_of,
        "seed": seed,
        "corpus": corpus,
        "volatility_sha256": volatility_sha256,
        "reverify_threshold": reverify_threshold,
        "supersession_weight": supersession_weight,
        "scores": [s.model_dump() for s in scores],
    }
    return Manifest(
        run_id=content_id(identity),
        created_at=created_at or dt.datetime.now(dt.UTC),
        kind=kind,
        as_of=as_of,
        seed=seed,
        corpus=corpus,
        volatility_sha256=volatility_sha256,
        reverify_threshold=reverify_threshold,
        supersession_weight=supersession_weight,
        tool_version=__version__,
        python_version=sys.version.split()[0],
        platform_=platform.platform(),
        counts=Counts.from_scores(scores),
    )


__all__ = ["SCHEMA", "Counts", "Manifest", "build_manifest"]
