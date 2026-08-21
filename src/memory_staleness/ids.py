"""Canonical serialization, content addressing, and seed derivation.

Three invariants live here, and each is enforced by a test in ``tests/unit/test_ids.py``
rather than by convention:

1. ``canonical_json`` is injective enough to hash. Two objects that differ in any way a
   reader would call meaningful must produce different bytes. Floats are written as
   IEEE-754 hex so that ``0.1 + 0.2`` and ``0.30000000000000004`` never collide through
   decimal rounding.
2. ``portable_json`` is what goes on the wire, and it is *not* the hash format. A browser
   or a notebook should read a staleness score as ``0.82``, not as ``0x1.a3d70a3d70a3dp-1``.
   The split is deliberate: hashing stays lossless while the published bundle stays legible.
3. ``derive_seed`` is hierarchical. A global RNG means adding memory #226 to a fixture set
   shifts the draws for memories 1-225 and nothing is comparable across runs any more.

The default seed is 1729 throughout the project.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from collections.abc import Mapping, Sequence, Set
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

DEFAULT_SEED = 1729
"""Every fixture generator and sampler in this package defaults to this seed.

Chosen to be memorable rather than meaningful; the point is that it is *written down*, so a
reader can regenerate a fixture set and get the same bytes.
"""

_SEP = b"\x1f"
"""ASCII unit separator.

Used between seed-derivation parts because it cannot appear in any identifier this package
generates, so ``("ab", "c")`` and ``("a", "bc")`` cannot collide.
"""


def _encode(obj: Any, *, float_as_hex: bool) -> Any:
    """Recursively rewrite ``obj`` into JSON-encodable primitives.

    ``float_as_hex`` selects between the hash format and the wire format. Everything else
    is shared, which is the point — the two formats must not drift apart in how they order
    keys or normalize containers, only in how they spell a float.
    """
    # bool before int: bool is a subclass of int and would otherwise serialize as 0/1.
    if isinstance(obj, bool):
        return obj
    # Enum before str: StrEnum members are str instances and would serialize by identity
    # rather than by value on some paths.
    if isinstance(obj, Enum):
        return _encode(obj.value, float_as_hex=float_as_hex)
    if obj is None or isinstance(obj, int | str):
        return obj
    if isinstance(obj, float):
        if not math.isfinite(obj):
            # Not left to json.dumps: floats may be formatted to strings before they reach
            # the encoder, and NaN would then serialize as the literal "nan" — a garbage
            # value that looks like data.
            raise ValueError(f"non-finite float cannot be serialized canonically: {obj!r}")
        # Normalize signed zero so -0.0 and 0.0 hash identically.
        obj = obj + 0.0 if obj else 0.0
        return obj.hex() if float_as_hex else obj
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, dt.datetime):
        # Normalized to UTC and spelled exactly one way. Two datetimes naming the same instant
        # in different offsets must hash identically, or a store exporting "+05:30" and one
        # exporting "Z" would produce different ids for the same memory. A naive datetime is
        # rejected rather than assumed UTC: guessing a timezone inside a hash function is how
        # an off-by-hours error becomes permanent.
        if obj.tzinfo is None:
            raise ValueError(f"naive datetime cannot be serialized canonically: {obj!r}")
        return obj.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")
    if isinstance(obj, dt.date):
        return obj.isoformat()
    if isinstance(obj, Path):
        return obj.as_posix()
    if isinstance(obj, Mapping):
        return {str(k): _encode(v, float_as_hex=float_as_hex) for k, v in sorted(obj.items())}
    if isinstance(obj, Set):
        return sorted(_encode(v, float_as_hex=float_as_hex) for v in obj)
    if isinstance(obj, Sequence) and not isinstance(obj, str | bytes):
        return [_encode(v, float_as_hex=float_as_hex) for v in obj]
    if hasattr(obj, "model_dump"):  # pydantic v2
        return _encode(obj.model_dump(), float_as_hex=float_as_hex)
    raise TypeError(f"cannot canonically serialize {type(obj).__name__}: {obj!r}")


def canonical_json(obj: Any) -> str:
    """Return the hash-stable JSON encoding of ``obj``.

    Floats become IEEE-754 hex strings. Use this for anything whose bytes feed a digest;
    use :func:`portable_json` for anything a human or a browser will read.
    """
    return json.dumps(
        _encode(obj, float_as_hex=True),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def portable_json(obj: Any, *, indent: int | None = None) -> str:
    """Return the wire encoding of ``obj``: identical to :func:`canonical_json` but with
    ordinary JSON numbers, so published artifacts stay readable."""
    return json.dumps(
        _encode(obj, float_as_hex=False),
        sort_keys=True,
        separators=(",", ":") if indent is None else None,
        ensure_ascii=False,
        allow_nan=False,
        indent=indent,
    )


def content_id(obj: Any) -> str:
    """Return ``blake2b128:<hex>`` for ``obj``.

    blake2b at 128 bits is used for internal identity because this package creates a great
    many small ids and speed matters more than collision margin at that size. Anything a
    *skeptic* checks uses :func:`sha256_file` instead — see its docstring.
    """
    digest = hashlib.blake2b(canonical_json(obj).encode("utf-8"), digest_size=16)
    return f"blake2b128:{digest.hexdigest()}"


def sha256_bytes(payload: bytes) -> str:
    """Return ``sha256:<hex>`` for ``payload``."""
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def sha256_file(path: Path | str) -> str:
    """Return ``sha256:<hex>`` for the contents of ``path``.

    Published checksums are SHA-256 rather than blake2b for one reason: ``shasum -a 256 -c``
    exists on every machine a skeptic might use, and a checksum nobody can verify in one
    paste is a checksum on trust.
    """
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def derive_seed(run_seed: int, *parts: str | int) -> int:
    """Derive a stable child seed from ``run_seed`` and ``parts``.

    Returns a 63-bit non-negative int, which is safe for both ``random.Random`` and
    ``numpy.random.default_rng``. Keyed on the full path — e.g.
    ``derive_seed(1729, memory_id, "planted_stale")`` — so that generating one memory never
    consumes randomness that another memory depends on.
    """
    digest = hashlib.blake2b(digest_size=8)
    digest.update(str(run_seed).encode("utf-8"))
    for part in parts:
        digest.update(_SEP)
        digest.update(str(part).encode("utf-8"))
    return int.from_bytes(digest.digest(), "big") & ((1 << 63) - 1)


__all__ = [
    "DEFAULT_SEED",
    "canonical_json",
    "content_id",
    "derive_seed",
    "portable_json",
    "sha256_bytes",
    "sha256_file",
]
