"""Buffered export with pre-write checks.

The exporter builds every byte in memory, runs its checks over the buffered bundle, and only
then touches the disk. Doing it in that order means a check added later automatically covers
files the exporter did not have when the check was written — the alternative, checking each
file as it is written, silently leaves new files unguarded.

Three rules are enforced before any byte lands:

1. **Every headline number must be supported.** A summary figure that no score in the bundle
   backs is a rejection, not a warning.
2. **A synthetic run may not be phrased as a claim about a real memory store.** Scoring
   planted fixtures says nothing about Mem0 or Zep, and the exporter refuses to let the
   bundle imply otherwise.
3. **No secrets.** Scanned on the buffered bytes, not the source files.
"""

from __future__ import annotations

from pathlib import Path

from memory_staleness.ids import portable_json, sha256_bytes
from memory_staleness.report.manifest import Manifest
from memory_staleness.types import StalenessScore

VENDOR_CLAIM_PHRASES = (
    "mem0",
    "zep",
    "graphiti",
    "cognee",
    "letta",
    "memgpt",
    "langmem",
    "lightmem",
    "licomemory",
    "a-mem",
    "outperforms",
    "state of the art",
    "state-of-the-art",
    "beats ",
    "sota",
)
"""Phrases a synthetic-corpus bundle may not contain.

A run over planted fixtures measures the harness against its own generator. Naming a vendor
in that bundle — or claiming to beat anything — turns a known-answer test into a competitive
benchmark result it is not. The list is deliberately blunt; a false positive costs one
rewording, a false negative costs a retraction.
"""

SECRET_NEEDLES = ("sk-", "AKIA", "ghp_", "gho_", "-----BEGIN", "api_key=", "GEMINI_API_KEY=")


class ExportError(RuntimeError):
    """Raised when a bundle fails a pre-write check.

    Unrecoverable by design: every one of these means the bundle would misrepresent the run
    if published, and there is no partial-write path that makes that acceptable.
    """


class BundleWriter:
    """Accumulates bundle bytes so checks can run before anything reaches disk."""

    def __init__(self) -> None:
        self.buffered: dict[str, bytes] = {}

    def add_json(self, name: str, payload: object) -> None:
        self.buffered[name] = (portable_json(payload, indent=2) + "\n").encode("utf-8")

    def add_text(self, name: str, text: str) -> None:
        self.buffered[name] = text.encode("utf-8")

    def flush(self, out_dir: Path) -> dict[str, str]:
        """Write every buffered file and return name -> sha256."""
        out_dir.mkdir(parents=True, exist_ok=True)
        digests: dict[str, str] = {}
        for name, payload in sorted(self.buffered.items()):
            target = out_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            digests[name] = sha256_bytes(payload)
        return digests


def check_headline_support(summary: dict, scores: tuple[StalenessScore, ...]) -> None:
    """Rule 1: refuse a summary whose counts the scores do not back."""
    if not summary.get("headline"):
        raise ExportError(
            "summary has no headline; a bundle with nothing to say is not publishable"
        )
    actual = {
        "total": len(scores),
        "reverify": sum(1 for s in scores if s.verdict.value == "reverify"),
        "forget": sum(1 for s in scores if s.verdict.value == "forget"),
        "fresh": sum(1 for s in scores if s.verdict.value == "fresh"),
        "cannot_assess": sum(1 for s in scores if s.verdict.value == "cannot_assess"),
    }
    claimed = summary.get("counts", {})
    for key, value in actual.items():
        if claimed.get(key) != value:
            raise ExportError(
                f"headline count {key!r} says {claimed.get(key)!r} but the scores in this bundle "
                f"give {value!r}. The summary and the evidence must not disagree."
            )


def lint_synthetic_bundle(writer: BundleWriter, *, kind: str) -> None:
    """Rule 2: a synthetic run describes the harness, never a vendor's memory store."""
    if kind != "synthetic":
        return
    for name, payload in writer.buffered.items():
        lowered = payload.decode("utf-8", errors="replace").lower()
        for phrase in VENDOR_CLAIM_PHRASES:
            if phrase in lowered:
                raise ExportError(
                    f"synthetic run: {name} contains the vendor-claim phrase {phrase!r}. "
                    "A run over planted fixtures measures this harness against its own "
                    "generator and says nothing about any real memory store. Reword it or "
                    "run against a real export."
                )


def scan_for_secrets(writer: BundleWriter) -> None:
    """Rule 3: nothing that looks like a credential leaves the process."""
    for name, payload in writer.buffered.items():
        text = payload.decode("utf-8", errors="replace")
        for needle in SECRET_NEEDLES:
            if needle in text:
                raise ExportError(
                    f"{name} contains something matching {needle!r}; refusing to write"
                )


def export_bundle(
    out_dir: Path,
    *,
    manifest: Manifest,
    scores: tuple[StalenessScore, ...],
) -> dict[str, str]:
    """Build, check, and write an audit bundle. Returns name -> sha256 for every file."""
    writer = BundleWriter()

    summary = {
        "run_id": manifest.run_id,
        "kind": manifest.kind,
        "counts": manifest.counts.model_dump(),
        "headline": [
            f"{manifest.counts.reverify} of {manifest.counts.total} memories are stale and "
            "still being retrieved",
            f"{manifest.counts.forget} are stale and never retrieved",
            f"{manifest.counts.cannot_assess} could not be assessed for lack of provenance",
        ],
    }

    check_headline_support(summary, scores)

    writer.add_json("manifest.json", manifest.model_dump_public())
    writer.add_json("summary.json", summary)
    writer.add_json("scores.json", [s.model_dump() for s in scores])

    lint_synthetic_bundle(writer, kind=manifest.kind)
    scan_for_secrets(writer)

    digests = writer.flush(out_dir)
    checksums = "\n".join(
        f"{digest.removeprefix('sha256:')}  {name}" for name, digest in sorted(digests.items())
    )
    (out_dir / "SHA256SUMS").write_text(checksums + "\n", encoding="utf-8")
    return digests


__all__ = [
    "SECRET_NEEDLES",
    "VENDOR_CLAIM_PHRASES",
    "BundleWriter",
    "ExportError",
    "check_headline_support",
    "export_bundle",
    "lint_synthetic_bundle",
    "scan_for_secrets",
]
