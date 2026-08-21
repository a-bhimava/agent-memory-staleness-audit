"""Known-answer validation over synthetic stores with planted staleness.

"Golden" here does not mean snapshot comparison. There are no stored expected-output files.
It means the corpus is generated with its own ground truth attached, so the assertions are
against a designed answer rather than against whatever the code produced last time. A
snapshot test locks in bugs; this locks in intent.
"""

from __future__ import annotations

from collections import Counter

import pytest

from memory_staleness.scoring import score_store
from memory_staleness.synth import generate_store
from memory_staleness.synth.generate import CaseKind
from memory_staleness.types import Verdict


def _verdicts(store):
    scored = score_store(store.entries, as_of=store.as_of)
    return {s.memory_id: s for s in scored}


def test_every_planted_case_gets_its_expected_verdict(store):
    """The headline claim. 100% on a corpus whose answers are known by construction is the
    floor, not an achievement — if this ever fails, the scorer is broken, not merely weak."""
    scored = _verdicts(store)
    wrong = [
        (
            case.entry.memory_id,
            case.kind.value,
            case.expected.value,
            scored[case.entry.memory_id].verdict.value,
        )
        for case in store.cases
        if scored[case.entry.memory_id].verdict is not case.expected
    ]
    assert not wrong, f"{len(wrong)} of {len(store.cases)} planted cases mis-verdicted: {wrong[:5]}"


def test_the_corpus_is_balanced_enough_to_be_meaningful(store):
    """An imbalanced corpus lets a scorer that flags everything post a good-looking number."""
    counts = Counter(case.kind for case in store.cases)
    for kind in CaseKind:
        assert counts[kind] > 0, f"{kind.value} is unrepresented; specificity would go untested"


def test_silent_supersession_is_caught_without_any_contradiction(store):
    """The flagship case, and the entire reason this project exists.

    A newer entry asserts the same subject+predicate with an *identical* object. Nothing
    disagrees, so contradiction-based invalidation in Zep or Mem0 has nothing to fire on.
    """
    scored = _verdicts(store)
    cases = [c for c in store.cases if c.kind is CaseKind.STALE_SUPERSEDED_SILENT]
    assert cases, "the flagship case must be present in the corpus"
    for case in cases:
        result = scored[case.entry.memory_id]
        assert result.verdict is Verdict.REVERIFY
        assert result.supersession is not None
        assert result.supersession.contradicts is False, (
            "this case must remain non-contradicting; if the generator starts producing a "
            "visible disagreement here, the test no longer proves anything a contradiction "
            "detector could not also do"
        )


def test_contradicting_supersession_is_reported_separately(store):
    """Caught too, but flagged as contradicting so no credit is claimed for the easy case."""
    scored = _verdicts(store)
    cases = [c for c in store.cases if c.kind is CaseKind.STALE_SUPERSEDED_CONTRADICTING]
    for case in cases:
        result = scored[case.entry.memory_id]
        assert result.supersession is not None
        assert result.supersession.contradicts is True


def test_abandoned_memories_are_forgotten_not_reverified(store):
    """The second branch. If retrieval frequency were multiplied into the score, this
    verdict would be unreachable — see the module docstring in scoring/score.py."""
    scored = _verdicts(store)
    cases = [c for c in store.cases if c.kind is CaseKind.ABANDONED]
    assert cases
    for case in cases:
        result = scored[case.entry.memory_id]
        assert result.verdict is Verdict.FORGET
        assert result.score >= 0.5, "should be plainly stale; it is only the exposure that differs"
        assert result.retrieval_component == 0.0


@pytest.mark.parametrize("n_per_kind", [1, 3, 12])
def test_accuracy_holds_at_different_corpus_sizes(n_per_kind: int):
    """Guards against an accuracy that depends on a particular corpus size."""
    store = generate_store(n_per_kind=n_per_kind)
    scored = _verdicts(store)
    assert all(scored[c.entry.memory_id].verdict is c.expected for c in store.cases)


@pytest.mark.parametrize("seed", [1729, 7, 424242])
def test_accuracy_holds_across_seeds(seed: int):
    """And against an accuracy that depends on one lucky draw."""
    store = generate_store(n_per_kind=4, seed=seed)
    scored = _verdicts(store)
    assert all(scored[c.entry.memory_id].verdict is c.expected for c in store.cases)


def test_generation_is_byte_stable_for_a_fixed_seed():
    """A generator that reads the wall clock produces a different corpus every run and
    destroys cross-run comparability."""
    from memory_staleness.ids import content_id

    assert content_id(generate_store(n_per_kind=4).cases) == content_id(
        generate_store(n_per_kind=4).cases
    )
