"""Command-line entry point: ``run`` / ``export`` / ``verify``, in that order.

Deliberately built on ``argparse`` rather than a CLI framework. This is an audit tool, and
its dependency list is a claim about how much of it a reader has to trust — a colour-printing
library has no business being in the trust boundary of something that produces evidence.

The three verbs are the pipeline. ``run`` scores and writes raw artifacts; ``export`` builds a
checked bundle; ``verify`` re-derives that bundle and reports per-claim. They are separate
commands rather than one because the separation is the point: an exporter that also verifies
itself is not a verification.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from memory_staleness import __version__
from memory_staleness.ids import DEFAULT_SEED
from memory_staleness.io.jsonl import read_entries, write_scores
from memory_staleness.report.export import ExportError, export_bundle
from memory_staleness.report.manifest import build_manifest
from memory_staleness.report.verify import verify_bundle
from memory_staleness.scoring import REVERIFY_THRESHOLD, SUPERSESSION_WEIGHT, score_store
from memory_staleness.synth import generate_store
from memory_staleness.synth.generate import REFERENCE_NOW
from memory_staleness.volatility import load_table

DEFAULT_RUN_DIR = Path("audits/latest")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="staleness-audit",
        description="Score agent memories for silent staleness.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="score a memory store and write raw artifacts")
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--synthetic",
        action="store_true",
        help="score a generated known-answer corpus (no API calls, no credentials, no network)",
    )
    source.add_argument(
        "--from-export",
        type=Path,
        metavar="PATH",
        help="score a JSONL export of an existing memory store",
    )
    run.add_argument(
        "--n-per-kind", type=int, default=6, help="synthetic corpus size per case kind"
    )
    run.add_argument("--seed", type=int, default=DEFAULT_SEED)
    run.add_argument(
        "--as-of",
        type=dt.datetime.fromisoformat,
        default=None,
        help="ISO-8601 instant to age memories against. Defaults to the generator's "
        "fixed clock for synthetic runs and to now for real exports.",
    )
    run.add_argument("--out", type=Path, default=DEFAULT_RUN_DIR)
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan and exit without scoring or writing anything",
    )

    export = sub.add_parser("export", help="build a checked, hash-listed bundle from a run")
    export.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    export.add_argument("--out", type=Path, default=Path("audits/exported"))

    verify = sub.add_parser("verify", help="re-derive an exported bundle and report per claim")
    verify.add_argument("bundle", type=Path)
    verify.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero if any claim fails (use this in CI)",
    )
    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    table = load_table()

    if args.synthetic:
        as_of = args.as_of or REFERENCE_NOW
        kind, corpus = "synthetic", {"n_per_kind": args.n_per_kind}
    else:
        as_of = args.as_of or dt.datetime.now(dt.UTC)
        kind, corpus = "export", {"n_per_kind": 0}

    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=dt.UTC)

    if args.dry_run:
        print(f"plan: kind={kind} as_of={as_of.isoformat()} seed={args.seed} corpus={corpus}")
        print(f"      volatility table {table.source_sha256}")
        print(f"      would write to {args.out}")
        return 0

    if args.synthetic:
        store = generate_store(n_per_kind=args.n_per_kind, seed=args.seed, as_of=as_of)
        entries = store.entries
    else:
        entries = read_entries(args.from_export)

    scores = score_store(entries, as_of=as_of, table=table)
    manifest = build_manifest(
        scores,
        kind=kind,
        as_of=as_of,
        seed=args.seed,
        corpus=corpus,
        volatility_sha256=table.source_sha256,
        reverify_threshold=REVERIFY_THRESHOLD,
        supersession_weight=SUPERSESSION_WEIGHT,
    )

    args.out.mkdir(parents=True, exist_ok=True)
    write_scores(args.out / "scores.jsonl", scores)
    (args.out / "manifest.json").write_text(
        json.dumps(manifest.model_dump_public(), indent=2, default=str) + "\n", encoding="utf-8"
    )

    counts = manifest.counts
    print(f"scored {counts.total} memories  (run {manifest.run_id})")
    print(f"  reverify      {counts.reverify:4}   stale and still retrieved")
    print(f"  forget        {counts.forget:4}   stale and never retrieved")
    print(f"  fresh         {counts.fresh:4}")
    print(f"  cannot assess {counts.cannot_assess:4}   no provenance to work from")
    print(f"wrote {args.out}")
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    from memory_staleness.report.manifest import Manifest

    raw = json.loads((args.run_dir / "manifest.json").read_text(encoding="utf-8"))
    raw["schema_"] = raw.pop("schema")
    raw["platform_"] = raw.pop("platform")
    manifest = Manifest.model_validate(raw)
    scores = tuple(read_scores(args.run_dir / "scores.jsonl"))

    try:
        digests = export_bundle(args.out, manifest=manifest, scores=scores)
    except ExportError as exc:
        print(f"export refused: {exc}", file=sys.stderr)
        return 2
    print(f"exported {len(digests)} files to {args.out}")
    for name in sorted(digests):
        print(f"  {name}")
    return 0


def read_scores(path: Path):
    """Read scores back from a run directory."""
    from memory_staleness.types import StalenessScore

    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield StalenessScore.model_validate_json(line)


def _cmd_verify(args: argparse.Namespace) -> int:
    report = verify_bundle(args.bundle)
    print(report.format())
    if args.strict and not report.ok:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "export":
        return _cmd_export(args)
    if args.command == "verify":
        return _cmd_verify(args)
    raise SystemExit(f"unknown command {args.command!r}. Try run, export, or verify.")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
