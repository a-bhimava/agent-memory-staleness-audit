"""Staleness scoring: age decay, supersession detection, and verdicts."""

from memory_staleness.scoring.score import (
    REVERIFY_THRESHOLD,
    SUPERSESSION_WEIGHT,
    age_component,
    find_supersessions,
    score_entry,
    score_store,
)

__all__ = [
    "REVERIFY_THRESHOLD",
    "SUPERSESSION_WEIGHT",
    "age_component",
    "find_supersessions",
    "score_entry",
    "score_store",
]
