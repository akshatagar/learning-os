# learning-os

A local-first system that turns what you read into a structured account of what you know, then uses that account to decide what to learn and what to build next.

Everything that reasons runs on your machine: concept extraction, identity resolution, idea generation, feasibility scoring and planning all call a local [Ollama](https://ollama.com) model, and embeddings are local. Storage is a SQLite file plus a ChromaDB directory. Nothing you ingest leaves the machine, with one exception: web search for reading recommendations (Tavily).

[MIT licensed](LICENSE). ![tests](https://github.com/akshatagar/learning-os/actions/workflows/tests.yml/badge.svg)

## How it works

```
ingest a paper or note → extract candidate concepts → identity resolution
    ├─ confident match → reinforce the existing concept
    ├─ confident new   → insert and embed it
    └─ uncertain       → MERGE QUEUE (you decide)

knowledge base ─┬─► goals → gaps (present / weak / missing) → reading recommendations
                └─► sampled concepts → project ideas → APPROVAL GATE (you decide)
                                         → feasibility vs. your skills → execution plan
```

The core rule: **the system never writes to persistent state when it is uncertain.** A model adjudicates each candidate against its nearest neighbours and returns a decision with a confidence. `match` at ≥ 0.85 reinforces, `new` at ≥ 0.65 inserts, and anything else goes to a human. Every decision is logged next to the human's eventual answer, so the thresholds can later be tuned against real disagreement data.

## Setup

Requires Python 3.11, [uv](https://docs.astral.sh/uv/), and Ollama with `qwen2.5:7b` pulled.

```bash
ollama pull qwen2.5:7b
uv sync
uv run alembic upgrade head
```

Copy `.env.example` to `.env`. Only `TAVILY_API_KEY` is needed, and only for reading recommendations.

```bash
uv run pytest -m "not live"   # fast, offline; what CI runs
uv run pytest                 # also runs the live Ollama/Tavily tests (~10 min)
```

## Usage

```bash
uv run python -m web.shell    # desktop app
uv run python -m web.serve    # same panel in a browser at http://127.0.0.1:8765/
```

The panel shows every pipeline stage with its count, lit amber only where something is waiting on you. From it you can manage goals (create, draft requirements with the local model, edit, delete), generate ideas, and work through the merge queue. Both entry points bind to `127.0.0.1` only. On Windows 10 you need the Edge WebView2 runtime; Windows 11 has it.

Ingestion, skills entry, idea review, scoring and planning have no panel UI yet. `cli.py` is intentionally untracked, so a fresh clone has no command-line entry point; call the importable modules directly instead, for example:

```python
from ingestion.papers import ingest_paper
from storage.db import get_engine, get_session
from storage.vectors import get_chroma_client, get_concepts_collection

engine = get_engine("data/learning_os.db")
collection = get_concepts_collection(get_chroma_client("data/chroma"))
with get_session(engine) as session:
    ingest_paper(session, collection, "https://arxiv.org/abs/1706.03762")
```

## Architecture

One Python package per stage, with no framework or service layer: functions take a `session` and return values, and [LangGraph](https://langchain-ai.github.io/langgraph/) is used only where a stage is a true pipeline.

| Package | Responsibility |
|---|---|
| `storage/` | SQLAlchemy models, SQLite engine, ChromaDB collection |
| `ingestion/` | Paper and note ingestion graphs |
| `resolution/` | Identity resolution and the merge-queue review |
| `goals/` | Requirement drafting and gap classification |
| `recommend/` | Gaps → search → dedup → relevance filter |
| `skills/` | Skills entry |
| `opportunities/` | Idea generation, approval, feasibility scoring, planning |
| `web/` | FastAPI app, job registry, pywebview shell |

- **Loops are not graphs.** Anything that walks rows and commits per row is a plain loop; a node blocking on `input()` is hard to test and resume.
- **Every model call is injectable** (`match_fn`, `generate_fn`, `plan_fn`, …), so the suite runs without a model apart from a few `@pytest.mark.live` tests.
- **Batch work is resumable.** Each stage selects only unhandled rows and commits per row, so an interrupted run loses nothing.

Data lives in one SQLite database with seven tables (`concepts`, `merge_queue`, `adjudication_log`, `skills`, `goals`, `content_log`, `opportunities`), migrated with Alembic. List-shaped fields are JSON in TEXT columns. `skills` is the one table only you write to.

## Lessons

- **A JSON schema that permits a degenerate answer will get one.** A bare top-level array schema is satisfied by `[]`; an empty milestone list satisfies `IS NOT NULL`. Wrap, require, and raise on empties.
- **Treat the model's reply as a lookup table, not the list you iterate.** Walk your stored requirements and look each up in the answer, so omissions count as missing and inventions are ignored.
- **Embedding similarity is not a synonym matcher.** `containerization` scored 0.577 against Docker. Goal requirement phrases work only because they are hand-written to be retrievable, and every acronym is spelled out (`"KV cache key-value cache"`).

## Known gaps

- `qwen2.5:7b` is used everywhere; the design calls for 14b, so quality judgments are confounded by model size.
- Prompt adherence is inconsistent in notes extraction, `required_skills` and learn-milestone targeting.
- Nothing is recomputed: learning a skill does not update existing scores or plans.
- Thresholds (`k=5`, 0.85, 0.65, 0.70) were chosen by feel and are unmeasured.
- `skills.last_used` has no writer.
- No installer; running it means cloning the repo and using `uv`.
