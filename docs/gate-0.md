# Gate 0 — agent-memory-staleness-audit

**Run:** 2026-08-21 · **Passes:** 2 independent research passes · **Verdict:** **BUILD**

Gate 0 is the pre-code novelty check this project had to survive before a line was written.
It exists because a predecessor project in the same portfolio was retired at exactly this
gate — all four of its modules turned out to be commodity, and two were methodologically
unsound. **A Gate 0 that cannot kill a project is theatre.** This one has killed five.

---

## 1. Name availability

| Check | Result |
|---|---|
| PyPI `agent-memory-staleness-audit` | 404, checked 2026-08-21 |
| GitHub repositories named `agent-memory-staleness-audit` | 0 matches, checked 2026-08-21 |
| Semantic collisions | None. "Staleness audit" is not an owned term of art in this space. |

Name availability on PyPI is not by itself sufficient — a name can be *semantically* owned
while the package index is free, which is what retired the predecessor project.

---

## 2. Incumbents

| Tool | Stars | Covers | Does NOT cover |
|---|---|---|---|
| [Zep / Graphiti](https://github.com/getzep/graphiti) | ~30.1k | Genuine bi-temporal edge invalidation: four timestamps per edge (`t_created`, `t_expired`, `t_valid`, `t_invalid`); superseded facts marked, not deleted | **Fires only when a contradicting fact arrives.** A memory that is stale with nothing disagreeing is invisible to it. |
| [Mem0](https://github.com/mem0ai/mem0) | ~63.7k | Memory decay (search-time re-ranking), eviction, tier lifetimes, supersession-on-contradiction | Its own 2026 report concedes: *"Decay handles low-relevance memories, but staleness in high-relevance memories is a harder, open problem."* |
| [MemGuard](https://github.com/ac12644/MemGuard) | 3 | The closest match that exists: adapters for Mem0/Zep/Letta/LangMem, a composite trust score using source reliability + volatility-weighted freshness + retrieval frequency, auto-quarantine below 30% | **No benchmark. No evaluation of any kind.** Also does network source re-validation, which this project deliberately does not. |
| [memwatch](https://github.com/kresnapandu/memwatch) | 32 | Ebbinghaus decay + category TTLs (employment 180d, location 365d, objective 3650d) + access boosts | Created and last pushed the same day, 1 commit. Benchmarks listed "coming soon" and never came. |
| [TOKI](https://arxiv.org/abs/2606.06240) | — | Bitemporal operator algebra for contradiction resolution in agent memory (HKUST, 2026-06-04) | Contradiction resolution, again. |

**The pattern across all of them: everything detects *contradiction* — two facts that
disagree.** Staleness with no contradiction present is the documented open case.

---

## 3. The surviving gap

Score memory entries for staleness using provenance age, hand-authored fact-type volatility,
and **supersession that does not require a contradiction** — then evaluate that scoring
against a public benchmark with published incumbent baselines. Every incumbent either needs a
disagreement to fire on (Zep, Mem0, TOKI) or has never been evaluated at all (MemGuard,
memwatch). Being the first to put a number on this, against a benchmark someone else
published, is the contribution; the scoring heuristics themselves are not novel and are not
claimed to be.

---

## 4. Claim status

| Claim | Status | Source |
|---|---|---|
| STALE benchmark exists: 400 scenarios → 1,200 queries, contexts to 150K tokens, best model 55.2% | ✅ VERIFIED | [arXiv 2605.06527](https://arxiv.org/abs/2605.06527) — Chao, Bai, Sheng, Li & Sun, 2026-05-07 |
| STALE evaluated Mem0, Zep, LightMem, LiCoMemory, A-mem on implicit conflict; most below 10%, LightMem 17.8% | ✅ VERIFIED | Same paper. Its conclusion: *"adding an external memory module does not automatically improve implicit-conflict resolution."* |
| STALE is published by "Tandemly Research" | ❌ **DO NOT CITE — misattributed** | The authors are at **Wuhan University / CUHK / HKUST**. `tandemly.ai/research/stale-agent-memory-validity` appears in search indexes but returns HTTP 403 and is at best a secondary write-up. This project's spec carried the wrong attribution until 2026-08-21. |
| "Mem0 scores 29% on contradiction tasks" | ⚠️ **VERIFY / heavily caveat** | True only of the [MnemeBrain](https://mnemebrain.github.io/mnemebrain-benchmark/) benchmark — on which **MnemeBrain's own product scored 100%** and RAG scored 0%. A vendor benchmark grading itself. Defensible substitute: Mem0 at **18.0%** on MemoryAgentBench FactConsolidation. |
| Mem0 concedes high-relevance staleness is open | ✅ VERIFIED | Mem0, *State of AI Agent Memory 2026* |
| TOKI, arXiv 2606.06240, bitemporal operator algebra | ✅ VERIFIED | Ziming Wang, HKUST, 2026-06-04, 43pp |
| MnemeBrain 48-task belief-dynamics benchmark exists | ✅ VERIFIED but vendor-run | v0.1.0a1, run 2026-03-08, deterministic scoring, no LLM judge |

---

## 5. Kill criteria

Written before the code, not after. Any of these retires the project:

1. **A benchmarked incumbent appears.** If Mem0, Zep, or MemGuard publishes STALE results on
   implicit conflict that a provenance-and-volatility scorer cannot approach, the contribution
   is gone — the gap was never the heuristic, it was that nobody had measured.
2. **The scorer cannot beat the trivial baseline.** If age-alone scores the same as
   age × volatility × supersession on STALE, the volatility table is decoration and this is a
   clock with extra steps.
3. **False-staleness rate makes it unusable.** If specificity on durable facts is poor enough
   that a reviewer would learn to ignore the output, the tool is worse than nothing: it costs
   review time and buys none. The `must_not_fire` controls exist to catch this early.
4. **Provenance is not there to work with.** If real-world exports from Mem0 and Zep turn out
   to lack per-entry write timestamps often enough that most entries return `CANNOT_ASSESS`,
   the approach does not apply to deployed stores, whatever it scores on a synthetic corpus.

> On (4): the tool is designed to *report* that state rather than mask it. A store that is
> mostly `CANNOT_ASSESS` is itself a finding about upstream provenance capture — but it would
> be a finding about a different project than this one.
