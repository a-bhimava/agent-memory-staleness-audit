"""The single serialization boundary.

Every read and write of a JSONL artifact goes through this module. One boundary means one
place where encoding decisions live, rather than a subtly different ``json.dumps`` call at
each call site that drifts apart over time.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path

from memory_staleness.ids import portable_json
from memory_staleness.types import MemoryEntry, StalenessScore


def write_entries(path: Path, entries: Iterable[MemoryEntry]) -> int:
    """Write memories as JSONL. Returns the count written."""
    return _write(path, (e.model_dump(by_alias=True) for e in entries))


def write_scores(path: Path, scores: Iterable[StalenessScore]) -> int:
    """Write scores as JSONL. Returns the count written."""
    return _write(path, (s.model_dump() for s in scores))


def _write(path: Path, rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(portable_json(row) + "\n")
            count += 1
    return count


def read_entries(path: Path | str) -> tuple[MemoryEntry, ...]:
    """Read a JSONL export of memories.

    Line numbers are reported on failure because a 40,000-line export with one malformed row
    is otherwise a very long afternoon.
    """
    entries: list[MemoryEntry] = []
    with Path(path).open(encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                entries.append(MemoryEntry.model_validate_json(line))
            except Exception as exc:
                raise ValueError(f"{path}:{lineno}: not a valid memory entry: {exc}") from exc
    return tuple(entries)


def iter_jsonl(path: Path | str) -> Iterator[dict]:
    """Yield raw rows, for adapters that need to inspect before validating."""
    import json

    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


__all__ = ["iter_jsonl", "read_entries", "write_entries", "write_scores"]
