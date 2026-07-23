# learning-os

A local-first system that turns what you read into a structured account of what you know, then uses that account to decide what to learn and what to build next.

Everything that reasons runs on your machine. Concept extraction, identity adjudication, idea generation, feasibility scoring, and execution planning all call a local [Ollama](https://ollama.com) model. Embeddings are local. Storage is a SQLite file and a ChromaDB directory next to it. No document, note, concept, skill, or goal leaves the machine — with one clearly marked exception, web search for reading recommendations.

Status: **backend complete, no UI yet.** Every stage below is implemented, tested, and running against real data. The interface is a CLI.

---

## The pipeline

```
ingest a paper or note
    │
    ├─ parse (Docling for PDFs) and target the sections worth reading
    ├─ extract candidate concepts with a local model
    │
    ▼
identity resolution ─────────────────────────────┐
    retrieve nearest neighbours from the vector store
    adjudicate match / new / uncertain with a model + confidence
    │                                            │
    ├─ high-confidence match  → reinforce the existing concept
    ├─ high-confidence new    → insert and embed it
    └─ anything uncertain     → MERGE QUEUE ─────┘ (human decides)
    │
    ▼
knowledge base of concepts
    │
    ├──► goals ──► gaps (present / weak / missing)
    │                │
    │                └──► web search per gap ──► dedup ──► relevance filter
    │                          └─► reading recommendations
    │
    └──► sample held concepts
             └──► generate project ideas
                      │
                      ▼
                 APPROVAL GATE (human decides)
                      │
                      ├──► feasibility scoring against your skills
                      │        └─► skill_match_pct + missing_skills
                      │
                      └──► execution planning
                               └─► ordered learn / build milestones
```

Three points in that flow stop and wait for a person. They are not confirmations — they are the mechanism.

---

## The idea worth stealing

Most "second brain" tools store what you read as tags or free text, which makes *"what do I already know?"* an unanswerable question. Here, a concept is an identity-resolved entity.

Every extracted candidate is checked against its nearest neighbours in the vector store, then adjudicated by a model that returns a decision **and a confidence**. Three routes:

| Decision | Confidence | Outcome |
|---|---|---|
| `match` | ≥ 0.85 | Reinforce the existing concept |
| `new` | ≥ 0.65 | Insert it and embed it |
| anything else | below threshold | Queue it for a human |

The system never asserts into persistent state when it is uncertain. That single rule is what makes every downstream stage — gaps, feasibility, planning — mean something, and it is why the merge queue exists. Every adjudication is logged with the model's decision, confidence, reasoning, and the human's eventual resolution, so the thresholds can be tuned against real disagreement data later.

---

## Architecture

A Python package per stage. No framework, no service layer, no dependency injection container — functions that take a `session` and return values, plus [LangGraph](https://langchain-ai.github.io/langgraph/) `StateGraph`s where a stage is genuinely a pipeline.

| Package | Responsibility |
|---|---|
| `storage/` | SQLAlchemy 2.0 models, engine/session factories, ChromaDB collection setup |
| `ingestion/` | `ingest_paper()` — a 6-node graph; `ingest_note()` — a 4-node graph sharing the tail nodes |
| `resolution/` | `resolve_candidate()`, the shared identity subroutine; the merge-queue review loop |
| `goals/` | Seeded goals with concept requirements; `concept_gaps()` present/weak/missing classifier |
| `recommend/` | `recommend_goal()` — a 5-node graph: gaps → rank → search → dedup → relevance filter |
| `skills/` | Interactive skills entry |
| `opportunities/` | Idea generation (3-node graph), approval loop, feasibility scoring, execution planning |

Two conventions hold throughout, and both exist for reasons that cost something to learn:

**Loops are not graphs.** Anything that walks rows and commits per row is a plain loop — the review gates, scoring, planning. A `StateGraph` is used only where the stage is a true pipeline. A node that blocks on `input()` is hard to test and hard to resume.

**Every model call is injectable.** Each stage takes a `*_fn` parameter (`match_fn`, `generate_fn`, `plan_fn`, `adjudicate_fn`, `input_fn`) defaulting to the real implementation. The entire suite runs without a model except for a handful of deliberate live round-trips.

### Batch work is resumable

Every batch stage selects only rows it has not yet handled — `skill_match_pct IS NULL`, `execution_plan IS NULL`, `status = 'generated'` — and commits after each row. Interrupting a run mid-way loses nothing, and re-running continues where it stopped. This matters more than it sounds: a single model call takes 60-90 seconds, so a full run is measured in minutes.

---

## Data model

One SQLite database, seven tables, migrated with Alembic.

| Table | Holds |
|---|---|
| `concepts` | The knowledge base. Name, category, confidence, source, embedding id |
| `merge_queue` | Candidates awaiting human judgment |
| `adjudication_log` | Every model decision with confidence, reasoning, and human resolution |
| `skills` | What you can actually do. **The one table only you may write to** |
| `goals` | What you are trying to learn, with concept requirement phrases |
| `content_log` | What has been ingested, so recommendations never suggest it again |
| `opportunities` | Generated ideas, their status, feasibility score, missing skills, execution plan |

Vector storage is a single ChromaDB collection, `concepts`, in cosine space using `all-MiniLM-L6-v2`.

List-shaped fields are JSON in TEXT columns. There are no child tables anywhere — deliberately.

---

## Setup

**Prerequisites**

- Python 3.11
- [uv](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com) running locally, with `qwen2.5:7b` pulled

```bash
ollama pull qwen2.5:7b
```

**Install and migrate**

```bash
uv sync
uv run alembic upgrade head
```

That creates `data/learning_os.db`. The ChromaDB directory at `data/chroma` is created on first use.

**Environment**

Copy `.env.example` to `.env` and fill it in. One key is required, and only for reading recommendations:

- `TAVILY_API_KEY` — [Tavily](https://tavily.com) web search. Every other stage works fully offline.

**Verify**

```bash
uv run pytest
```

218 tests. A handful make real Ollama and Tavily calls and take 60-90 seconds each, so the full suite runs about ten minutes. There is no marker separating them yet.

---

## Usage

> **Note:** `cli.py` is intentionally untracked, so a fresh clone has **no entry point**. All logic lives in the importable modules listed above — that is the real API, and the CLI is a thin `argparse` shim over it. The commands below describe the author's local shim; reproduce it, or call the functions directly.

### Getting started

```bash
uv run python cli.py seed-goals    # five goals, 14 requirement phrases each; idempotent
uv run python cli.py add-skills    # interactive; only you know your skills
```

Skills entry offers three coarse proficiency bands rather than a 0-100 scale, on the grounds that self-assessment cannot honestly distinguish 72 from 78.

### Ingesting

**There is no `ingest` subcommand.** Ingestion is currently reachable only in Python:

```python
from ingestion.papers import ingest_paper
from ingestion.notes import ingest_note
from storage.db import get_engine, get_session
from storage.vectors import get_chroma_client, get_concepts_collection

engine = get_engine("data/learning_os.db")
collection = get_concepts_collection(get_chroma_client("data/chroma"))

with get_session(engine) as session:
    ingest_paper(session, collection, "https://arxiv.org/abs/1706.03762")
```

Then resolve whatever the model was unsure about:

```bash
uv run python cli.py list-queue
uv run python cli.py review-queue   # [1-N] merge  [n] new  [d] dismiss  [s] skip  [q] quit
```

Each entry renders with a live top-5 neighbour query against the current knowledge base, so you see real similarity scores while deciding. Quitting mid-review is safe.

### Finding what to read

```bash
uv run python cli.py recommend llm-internals --top 3
```

Computes gaps for the goal, ranks them by nearest-neighbour similarity — closest-to-what-you-know first — searches each, drops anything already ingested, and filters the rest for relevance with a model.

### Finding what to build

```bash
uv run python cli.py generate-ideas --sample 5 --count 3   # generate, then review inline
uv run python cli.py review-ideas                          # [a]pprove [r]eject [s]kip [q]uit
uv run python cli.py score-opportunities                   # skill_match_pct + missing_skills
uv run python cli.py plan-opportunities                    # ordered learn/build milestones
uv run python cli.py show-plan 11
```

Each stage runs only on rows the previous stage approved, so the expensive work happens only on ideas you chose.

### Full command list

`list-concepts` · `list-queue` · `review-queue` · `seed-goals` · `add-skills` · `recommend` · `generate-ideas` · `review-ideas` · `score-opportunities` · `plan-opportunities` · `show-plan`

---

## Things learned the hard way

Recorded because each cost real debugging and each generalizes.

**A JSON schema that permits a degenerate answer will eventually get one.** Three separate instances:

- A top-level `{"type": "array"}` schema is satisfied by `[]`, and a constrained decoder will emit `]` immediately as the shortest legal completion. Idea generation returned **zero** ideas on every run until the array was wrapped in an object with a required key.
- A field typed `["string", "null"]` is satisfied by the literal string `"null"`, which the model duly returned. Schema-valid, and the type was lying.
- An empty milestone list would satisfy `execution_plan IS NOT NULL`, making a failed generation read as "planned" forever after. It raises instead.

**Treat the model's reply as a lookup table, never as the list you iterate.** Feasibility scoring walks the *stored* requirements and looks each one up in the model's answer, so a requirement the model omits still counts as missing and one it invents is ignored. Execution planning walks the *stored* missing skills and generates a blunt fallback milestone for any the model skipped — which it does: on real data the model produced learning steps for skills already held and omitted the one that was actually missing.

**Embedding similarity is not a synonym matcher.** Measured against the real skills table, `containerization` → Docker scored 0.577 and `deep learning frameworks` returned *Scikit-Learn*, not PyTorch. For half of realistic cases the nearest neighbour is the wrong entity, so no threshold recovers it. Skill names are vendor nouns that nobody wrote to be retrievable. Goal requirement phrases work at 0.70 only because they were hand-written for that purpose, under a convention that every acronym appears with its expansion.

---

## Current state

Real data in the author's database: 15 concepts from one ingested paper, 1 pending queue entry, 12 skills, 5 goals, and 12 opportunities of which 3 are approved, scored, and planned.

Known gaps, in rough priority order:

- **No UI.** The three human gates are keyboard loops in a terminal. A desktop app is the next build.
- **`qwen2.5:7b` everywhere.** The design specifies `qwen2.5:14b` for idea generation, feasibility, and planning. It was never installed, so every quality judgment is confounded by model size.
- **Prompt adherence is inconsistent** in three places: the notes extraction engagement rule, `required_skills` compliance, and learn-milestone targeting. Same class of problem, not yet attacked deliberately.
- **Nothing is recomputed.** Learning a new skill does not improve any existing opportunity's score, and no plan is ever revised.
- **Thresholds are unmeasured.** `k=5`, 0.85, 0.65, and 0.70 were all chosen by feel. The `adjudication_log` is accumulating the model-versus-human pairs needed to settle them.
- **`skills.last_used` has no writer** and is NULL on every row. Either something populates it or the column should go.
