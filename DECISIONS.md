# Decisions

Major design decisions, newest first. Each entry says what was decided and why.

## 2026-11-14 — Reel Inbox project, Phase 0 outcomes

The Reel Inbox work runs in five gated phases on `feat/reel-inbox`, with one commit per phase: stabilize + UI, extractor spike (go/no-go), inbox/queue/review, Windows packaging, stats.

- **The extractor uses local Ollama `qwen3:8b`.** Every other model call in the repo is already local, so this needs no cloud key. It sits behind an `extract(url) -> JSON` interface so another model can be swapped in.
- **Reel Inbox is a self-contained package** with its own tables. It hands an explored referent to the existing identity resolution (`resolution.adjudicate.resolve_candidate`) through a new `source_type`, without changing resolution internals. The hook is proposed before it is built.
- **The panel stays hand-written vanilla JS + SVG.** It was never generated with Lovable, so there is no Lovable structure to preserve.
- **Packaging targets Windows 10/11 x64 only.** The ~2 GB one-dir bundle (torch, docling, opencv) is accepted. Ollama is detected on first run, with a link and pull command, and is never bundled or silently installed.
- **The `worktree-conversational-orchestration` branch stays unmerged** and untouched by this work.
- **`cli.py` stays untracked.** Its dead `seed-goals` command was removed so it imports again.

## 2026-11-14 — Panel: the wide drawing folds onto two rows

Eight stages in one row produced a 1240×420 drawing that could never be drawn larger than 1:1. That meant 11px labels and an empty lower window. The main line now runs on two rows joined by a return run from Concept Store to Ideas, with Goals and Skills on side branches. The drawing is fitted to the window in both directions, so at 1280×672 (1920×1080 at 150% scaling) it draws at about 1.4× and labels read at about 16px. The mimic-panel world, palette and type are unchanged. The window also opens no larger than the screen's work area: it used to open 820 tall on a 672-tall work area.

## 2026-11-14 — Panel files are served with `Cache-Control: no-cache`

The webview cached `app.js` and the stage modules, so an updated panel kept running its old code until the cache was cleared. Revalidating costs one local 304 per file, which matters once the app is installed and updated in place (Phase 4).

## 2026-11-14 — Panel: one surface load at a time

Opening a stage cancels any surface load still in flight, and the body is cleared to a loading line before the new request starts. A slow endpoint (`/goals` takes about 0.9s) previously painted its rows under whichever stage had been opened since, and the previous stage's rows stayed visible under the new title until the response arrived.
