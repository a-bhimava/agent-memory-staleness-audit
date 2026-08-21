"""The exporter's three pre-write rules, and the determinism they protect."""

from __future__ import annotations

import datetime as dt

import pytest

from memory_staleness.ids import DEFAULT_SEED
from memory_staleness.report.export import (
    BundleWriter,
    ExportError,
    check_headline_support,
    export_bundle,
    lint_synthetic_bundle,
    scan_for_secrets,
)
from memory_staleness.report.manifest import build_manifest
from memory_staleness.report.verify import verify_bundle
from memory_staleness.scoring import REVERIFY_THRESHOLD, SUPERSESSION_WEIGHT, score_store


@pytest.fixture
def bundle(tmp_path, store, table):
    scores = score_store(store.entries, as_of=store.as_of, table=table)
    manifest = build_manifest(
        scores,
        kind="synthetic",
        as_of=store.as_of,
        seed=DEFAULT_SEED,
        corpus={"n_per_kind": 6},
        volatility_sha256=table.source_sha256,
        reverify_threshold=REVERIFY_THRESHOLD,
        supersession_weight=SUPERSESSION_WEIGHT,
        created_at=dt.datetime(2026, 8, 21, tzinfo=dt.UTC),
    )
    out = tmp_path / "bundle"
    export_bundle(out, manifest=manifest, scores=scores)
    return out, manifest, scores


def test_a_bundle_verifies_against_itself(bundle):
    out, _, _ = bundle
    report = verify_bundle(out)
    assert report.ok, report.format()


def test_export_is_byte_identical_when_repeated(tmp_path, store, table):
    """Determinism gate. A run_id derived from a timestamp would defeat this, which is why
    build_manifest content-addresses everything except created_at."""
    scores = score_store(store.entries, as_of=store.as_of, table=table)
    made = []
    for name in ("a", "b"):
        manifest = build_manifest(
            scores,
            kind="synthetic",
            as_of=store.as_of,
            seed=DEFAULT_SEED,
            corpus={"n_per_kind": 6},
            volatility_sha256=table.source_sha256,
            reverify_threshold=REVERIFY_THRESHOLD,
            supersession_weight=SUPERSESSION_WEIGHT,
            created_at=dt.datetime(2026, 8, 21, tzinfo=dt.UTC),
        )
        out = tmp_path / name
        export_bundle(out, manifest=manifest, scores=scores)
        made.append(out)
    for name in ("manifest.json", "summary.json", "scores.json", "SHA256SUMS"):
        assert (made[0] / name).read_bytes() == (made[1] / name).read_bytes()


def test_rule_1_rejects_a_summary_the_scores_do_not_support(store, table):
    scores = score_store(store.entries, as_of=store.as_of, table=table)
    lying = {"headline": ["all clear"], "counts": {"total": 9999}}
    with pytest.raises(ExportError, match="must not disagree"):
        check_headline_support(lying, scores)


def test_rule_1_rejects_an_empty_headline(store, table):
    scores = score_store(store.entries, as_of=store.as_of, table=table)
    with pytest.raises(ExportError, match="nothing to say"):
        check_headline_support({"headline": [], "counts": {}}, scores)


@pytest.mark.parametrize("phrase", ["Mem0", "outperforms Zep", "state-of-the-art"])
def test_rule_2_blocks_vendor_claims_in_a_synthetic_bundle(phrase: str):
    """A run over planted fixtures measures the harness against its own generator. The
    exporter refuses to let that be phrased as a result about anyone else's product."""
    writer = BundleWriter()
    writer.add_text("report.md", f"This harness {phrase} on our corpus.")
    with pytest.raises(ExportError, match="vendor-claim phrase"):
        lint_synthetic_bundle(writer, kind="synthetic")


def test_rule_2_does_not_apply_to_a_real_export_run():
    """The rule is about what a synthetic corpus can support, not about censorship."""
    writer = BundleWriter()
    writer.add_text("report.md", "Audited a Mem0 export.")
    lint_synthetic_bundle(writer, kind="export")


def test_rule_2_covers_every_buffered_file_not_just_the_summary():
    """Checking the whole buffered bundle means a file added by a future exporter is covered
    without that exporter knowing the rule exists."""
    writer = BundleWriter()
    writer.add_json("summary.json", {"headline": ["clean"]})
    writer.add_json("some_future_file.json", {"note": "beats Mem0"})
    with pytest.raises(ExportError, match="some_future_file"):
        lint_synthetic_bundle(writer, kind="synthetic")


@pytest.mark.parametrize("needle", ["sk-abc123", "AKIAIOSFODNN7", "ghp_xxxx", "-----BEGIN"])
def test_rule_3_blocks_secrets(needle: str):
    writer = BundleWriter()
    writer.add_text("notes.txt", f"token {needle} here")
    with pytest.raises(ExportError, match="refusing to write"):
        scan_for_secrets(writer)


def test_checks_run_before_anything_reaches_disk(tmp_path, store, table):
    """The buffering is the point: a refused export must leave no partial bundle behind."""
    scores = score_store(store.entries, as_of=store.as_of, table=table)
    manifest = build_manifest(
        scores,
        kind="synthetic",
        as_of=store.as_of,
        seed=DEFAULT_SEED,
        corpus={"n_per_kind": 6},
        volatility_sha256=table.source_sha256,
        reverify_threshold=REVERIFY_THRESHOLD,
        supersession_weight=SUPERSESSION_WEIGHT,
    )
    broken = manifest.model_copy(update={"counts": manifest.counts.model_copy(update={"total": 1})})
    out = tmp_path / "never"
    with pytest.raises(ExportError):
        export_bundle(out, manifest=broken, scores=scores)
    assert not out.exists() or not any(out.iterdir())


def test_verify_detects_a_tampered_file(bundle):
    """Re-deriving, not re-diffing: the point is catching a bundle whose numbers do not
    follow from its own evidence."""
    out, _, _ = bundle
    scores_path = out / "scores.json"
    scores_path.write_text(scores_path.read_text().replace("reverify", "fresh", 1))
    report = verify_bundle(out)
    assert not report.ok
    assert any("SHA-256" in f.claim or "re-derive" in f.claim for f in report.failures)
