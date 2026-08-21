"""Re-derives a bundle rather than re-diffing it.

Re-exporting and diffing proves the exporter is *deterministic*. Re-deriving proves it is
*correct* — that the numbers in the bundle are the numbers the evidence supports, and not the
numbers a bug produced consistently. Only the second one catches a scorer that is reliably
wrong.
"""

from __future__ import annotations

import json
from pathlib import Path

from memory_staleness.ids import sha256_file
from memory_staleness.types import Frozen


class VerifyFinding(Frozen):
    claim: str
    ok: bool
    detail: str = ""


class VerifyReport(Frozen):
    run_id: str
    findings: tuple[VerifyFinding, ...]

    @property
    def ok(self) -> bool:
        return all(f.ok for f in self.findings)

    @property
    def failures(self) -> tuple[VerifyFinding, ...]:
        return tuple(f for f in self.findings if not f.ok)

    def format(self) -> str:
        lines = [f"run {self.run_id}"]
        for finding in self.findings:
            lines.append(f"  [{'ok  ' if finding.ok else 'FAIL'}] {finding.claim}")
            if finding.detail:
                lines.append(f"         {finding.detail}")
        lines.append(f"  {'PASS' if self.ok else 'FAIL'}: {len(self.failures)} failing claim(s)")
        return "\n".join(lines)


def verify_bundle(bundle_dir: Path) -> VerifyReport:
    """Check a bundle against itself and against a fresh re-derivation of its scores."""
    bundle_dir = Path(bundle_dir)
    findings: list[VerifyFinding] = []

    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    scores = json.loads((bundle_dir / "scores.json").read_text(encoding="utf-8"))
    summary = json.loads((bundle_dir / "summary.json").read_text(encoding="utf-8"))

    # 1. Published checksums match the files actually on disk.
    recorded = {}
    for line in (bundle_dir / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, name = line.split("  ", 1)
            recorded[name] = f"sha256:{digest}"
    mismatched = [
        name for name, digest in recorded.items() if sha256_file(bundle_dir / name) != digest
    ]
    findings.append(
        VerifyFinding(
            claim="every file matches its published SHA-256",
            ok=not mismatched,
            detail="" if not mismatched else f"mismatched: {mismatched}",
        )
    )

    # 2. Counts in the summary are the counts in the scores.
    tally = {
        "total": len(scores),
        "reverify": sum(1 for s in scores if s["verdict"] == "reverify"),
        "forget": sum(1 for s in scores if s["verdict"] == "forget"),
        "fresh": sum(1 for s in scores if s["verdict"] == "fresh"),
        "cannot_assess": sum(1 for s in scores if s["verdict"] == "cannot_assess"),
    }
    disagreements = {
        k: (summary["counts"].get(k), v) for k, v in tally.items() if summary["counts"].get(k) != v
    }
    findings.append(
        VerifyFinding(
            claim="summary counts re-derive from the scores",
            ok=not disagreements,
            detail="" if not disagreements else f"claimed vs derived: {disagreements}",
        )
    )

    # 3. Manifest counts agree with the same tally.
    manifest_counts = {k: v for k, v in manifest["counts"].items()}
    findings.append(
        VerifyFinding(
            claim="manifest counts re-derive from the scores",
            ok=manifest_counts == tally,
            detail="" if manifest_counts == tally else f"{manifest_counts} != {tally}",
        )
    )

    # 4. Every score carries at least one stated reason.
    unreasoned = [s["memory_id"] for s in scores if not s.get("reasons")]
    findings.append(
        VerifyFinding(
            claim="every finding states its reasoning",
            ok=not unreasoned,
            detail="" if not unreasoned else f"{len(unreasoned)} without reasons",
        )
    )

    # 5. A synthetic bundle does not name a vendor.
    from memory_staleness.report.export import VENDOR_CLAIM_PHRASES

    offending: list[str] = []
    if manifest.get("kind") == "synthetic":
        for path in sorted(bundle_dir.glob("*")):
            lowered = path.read_text(encoding="utf-8", errors="replace").lower()
            offending += [f"{path.name}:{p}" for p in VENDOR_CLAIM_PHRASES if p in lowered]
    findings.append(
        VerifyFinding(
            claim="a synthetic bundle makes no claim about any real memory store",
            ok=not offending,
            detail="" if not offending else f"found: {offending[:5]}",
        )
    )

    return VerifyReport(run_id=manifest["run_id"], findings=tuple(findings))


__all__ = ["VerifyFinding", "VerifyReport", "verify_bundle"]
