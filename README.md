# agent-memory-staleness-audit

[![CI](https://github.com/a-bhimava/agent-memory-staleness-audit/actions/workflows/ci.yml/badge.svg)](https://github.com/a-bhimava/agent-memory-staleness-audit/actions/workflows/ci.yml)&nbsp;[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

**Finds agent memories that have quietly gone stale — facts that were true when stored and are
silently wrong now, with nothing in the memory store to contradict them.**

## The problem

An agent stores *"Alice works at Acme."* Six months later Alice has changed jobs. Nothing in the
store contradicts the memory, it is still highly relevant to queries about Alice, so it keeps
getting retrieved — and it is now confidently wrong.

This is not the contradiction problem, and that distinction is the whole project. Every major
memory system detects **contradiction** — two entries that disagree:

- **Zep / Graphiti** maintains genuine bi-temporal edge invalidation, with four timestamps per
  edge and superseded facts marked rather than deleted. It fires **when a contradicting fact
  arrives**.
- **Mem0** ships memory decay, eviction, tier lifetimes, and supersession-on-contradiction.

Neither can catch a memory that is stale with *no contradicting entry present*, because there is
nothing to compare against. Mem0's own 2026 report concedes the point: decay handles low-relevance
memories, but *"staleness in high-relevance memories is a harder, open problem."*

The empirical picture is worse than the framing suggests. **STALE**
([arXiv 2605.06527](https://arxiv.org/abs/2605.06527) — Chao, Bai, Sheng, Li & Sun, Wuhan
University / CUHK / HKUST) evaluated Mem0, Zep, LightMem, LiCoMemory and A-mem on implicit
conflict. **Most scored below 10%.** LightMem, the best of them, reached 17.8%. The best frontier
model scored **55.2%** on the benchmark overall. The paper's conclusion is blunt: *"adding an
external memory module does not automatically improve implicit-conflict resolution."*

---

## How it works

Staleness is scored from three signals a contradiction detector never looks at.

```
Memory store  (Mem0 · Zep · a JSONL export · your own)
   │
   └── for each entry:
         │
         ├── Provenance    → source + write timestamp + fact type
         │                   no timestamp?  →  CANNOT_ASSESS, never a guess
         │
         ├── Volatility    → how fast does THIS KIND of fact change?
         │                   employer: months · address: years · date of birth: never
         │
         └── Supersession  → is there a NEWER entry with the same subject+predicate,
                             even when the two do not visibly contradict?
                                   │
                                   ▼
              staleness = age-vs-half-life  ×  volatility  ×  retrieval pressure
                                   │
      ┌────────────────────────────┼────────────────────────────┐
      ▼                            ▼                            ▼
  high + still retrieved      high + never retrieved        low score
  → REVERIFY                  → FORGET                      → FRESH
  confidently wrong,          safe to drop                  leave alone
  and in use
```

The second branch matters as much as the first. Splitting a high staleness score by whether
anything still retrieves the memory makes this a principled **forgetting policy**, not only a
staleness alarm.

### The volatility table is the load-bearing part

Trust decays by fact *type*, because a job title and a date of birth age at wildly different
rates. That mapping lives in
[`src/memory_staleness/volatility/table.yaml`](src/memory_staleness/volatility/table.yaml) as
human-authored data with a stated half-life and a rationale per type — **deliberately not
model-inferred**. A reviewer has to be able to disagree with a specific number, and a scorer that
treats every fact identically is just a clock.

---

## Running it

```bash
pip install -e '.[dev]'

# Score a generated corpus whose correct answers are known by construction.
# Zero API calls, no credentials, no network.
staleness-audit run --synthetic --n-per-kind 6

# Build a checked bundle, then re-derive it.
staleness-audit export --out audits/exported
staleness-audit verify audits/exported --strict
```

Audit your own store by exporting it to JSONL — one object per line — and pointing the CLI at
it. No store client is needed for this path; the adapters read exports, not live databases.

```bash
staleness-audit run --from-export my_memories.jsonl
```

`export` buffers every byte and checks it before writing, enforcing three rules:

1. **Every headline number must be supported by scores in the same bundle.** A summary the
   evidence does not back is a refusal, not a warning.
2. **A synthetic run may not be phrased as a claim about a real memory store.** Scoring planted
   fixtures says nothing about Mem0 or Zep, and the exporter refuses to let the bundle imply
   otherwise — the check runs over every buffered file, so a file added by a future exporter is
   covered without that exporter knowing the rule exists.
3. **No secrets** reach disk.

`verify` **re-derives** the bundle rather than re-diffing it. Re-exporting and diffing proves the
exporter is deterministic; re-deriving proves it is correct — that the numbers in the bundle are
the ones the evidence supports, and not the ones a bug produced consistently.

---

## What it will not do

- **It will not guess without provenance.** A memory with no write timestamp returns
  `CANNOT_ASSESS`. Not a pass, not a failure — an admission. An auditor that invents a confidence
  for a memory it cannot trace is worse than no auditor.
- **It will not re-validate facts against the network.** No fetching a LinkedIn page to check
  whether Alice still works at Acme. That is expensive, flaky, and is the differentiator of
  [MemGuard](https://github.com/ac12644/MemGuard); this tool scores what is already in the store.
- **It will not replace your memory system.** The adapters read; they do not write. Audit an
  existing store, do not adopt a new one.
- **False staleness is the failure mode that matters.** Flagging durable facts as expired makes
  the tool unusable faster than missing a few stale ones, so the known-answer tests assert
  specificity as hard as sensitivity — a clean control set must stay clean.

---

## Scoring against STALE

The evaluation this project is built to run, once the engine is complete:

| | |
|---|---|
| Benchmark | STALE — [arXiv 2605.06527](https://arxiv.org/abs/2605.06527), 400 scenarios → 1,200 queries |
| Published frontier-model score | 55.2% |
| Published incumbent scores on implicit conflict | Mem0, Zep, LiCoMemory, A-mem **below 10%**; LightMem 17.8% |
| Dimensions targeted | State Resolution and Implicit Policy Adaptation |
| This tool's score | **not yet run** |

Reporting against a public benchmark with published baselines is the point. A self-graded number
would prove nothing, and the incumbents' scores are already in the literature.

---

## Prior art

Named openly rather than claimed away. See [`docs/gate-0.md`](docs/gate-0.md) for the full
novelty check, including what was verified and what was found misattributed.

| Project | What it does | What it leaves open |
|---|---|---|
| [Zep / Graphiti](https://github.com/getzep/graphiti) | Bi-temporal edge invalidation, four timestamps per edge | Fires only on an arriving contradiction |
| [Mem0](https://github.com/mem0ai/mem0) | Decay, eviction, tier lifetimes, supersession-on-contradiction | Concedes high-relevance staleness is open |
| [MemGuard](https://github.com/ac12644/MemGuard) | Closest match: multi-store adapters, composite trust score, auto-quarantine | **No benchmark, no evaluation of any kind** |
| [memwatch](https://github.com/kresnapandu/memwatch) | Ebbinghaus decay + category TTLs | Single commit, abandoned; benchmarks "coming soon" and never came |
| [TOKI](https://arxiv.org/abs/2606.06240) | Bitemporal operator algebra for contradiction resolution | Contradiction, again |

The gap this occupies: **implicit supersession with no contradicting entry, scored against a
public benchmark.** MemGuard is the closest thing that exists and it has never been evaluated.

---

## Development

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'

pytest -q          # known-answer controls over synthetic memory sets
ruff check . && ruff format --check .
```

Python 3.11+. The core install has no LLM SDK and no memory-store client — scoring is arithmetic
over provenance, and a dependency list is a claim about how much of this a reader has to trust.
Store clients are optional extras (`.[mem0]`, `.[zep]`) used only by the live adapters; auditing a
JSONL export needs none of them.

---

## Documentation

- [`docs/gate-0.md`](docs/gate-0.md) — the pre-code novelty check: incumbents, the surviving gap,
  claim verification, and the criteria that would retire this project
- [`notebooks/01_quickstart.ipynb`](notebooks/01_quickstart.ipynb) [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/a-bhimava/agent-memory-staleness-audit/blob/main/notebooks/01_quickstart.ipynb)
  — runs end to end with no API key. Outputs are committed, so it reads without running

---

## Disclaimer

This tool scores heuristics over provenance metadata. **A high staleness score is a prompt to
re-verify, never a determination that a fact is false**, and a `FRESH` verdict is not a warranty
that a memory is true. Nothing here is a substitute for a system of record.

## Related work

This is one of four harnesses built on the same principle: **a model's output is not evidence
until something independent of the model can check it.** They share a house style — frozen
pydantic records, content-addressed run manifests, a buffered exporter that refuses to publish an
unsupported claim — and deliberately share no dependency, so each clones and runs on its own.

| Repository | What it does |
|---|---|
| [`rag-citation-guardrail`](https://github.com/a-bhimava/rag-citation-guardrail) | refusal correctness for RAG over regulated KYC/AML documents |
| [`agent-trace-to-evals`](https://github.com/a-bhimava/agent-trace-to-evals) | mining production agent traces into pytest regression assertions |
| [`llm-credit-decision-audit`](https://github.com/a-bhimava/llm-credit-decision-audit) | causal audit harness for AI underwriting agents, ECOA / 12 CFR §1002.9 |
| [`projectsyard`](https://github.com/a-bhimava/projectsyard) | founding-PM case study — 0-to-1 to Product Hunt Top 10 |

## License

Apache-2.0.
