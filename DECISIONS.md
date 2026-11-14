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

## 2026-11-14 — Reel Inbox extractor (Phase 2 spike)

- **`extract(url)` is the seam.** `reel_inbox.extractor.Extractor` is a protocol: one method that returns the six specified fields or raises `ExtractionFailed(reason)`. The pipeline behind it is yt-dlp → captions, else faster-whisper (`small`, CPU int8, downloaded on first use to `%APPDATA%\LearningOS\models`) → optional frame OCR (rapidocr) → one `qwen3:8b` call with a JSON schema and thinking off.
- **One Instagram page request per reel.** Media is downloaded from the info already fetched. Audio and video are separate streams, because joining them would need ffmpeg and YouTube often offers no combined file.
- **Shared links are canonicalized.** Every query parameter except YouTube's `v` is dropped: they are tracking, they can identify the sharer, and they are never needed to fetch.
- **Cookies: Firefox, then Chrome, then a `cookies.txt`.** On this machine only a cookies file can work. Chrome and Edge refuse ("Could not copy Chrome cookie database"), and the leftover Firefox profile holds no Instagram cookies.
- **YouTube media now needs a JS runtime (deno).** Without one, YouTube media downloads return 403. Shorts with captions are unaffected, and Instagram never needs it. Packaging has to ship deno next to yt-dlp.exe, or accept captions-only YouTube.

## 2026-11-14 — Panel: the wide drawing folds onto two rows

Eight stages in one row produced a 1240×420 drawing that could never be drawn larger than 1:1. That meant 11px labels and an empty lower window. The main line now runs on two rows joined by a return run from Concept Store to Ideas, with Goals and Skills on side branches. The drawing is fitted to the window in both directions, so at 1280×672 (1920×1080 at 150% scaling) it draws at about 1.4× and labels read at about 16px. The mimic-panel world, palette and type are unchanged. The window also opens no larger than the screen's work area: it used to open 820 tall on a 672-tall work area.

## 2026-11-14 — Panel files are served with `Cache-Control: no-cache`

The webview cached `app.js` and the stage modules, so an updated panel kept running its old code until the cache was cleared. Revalidating costs one local 304 per file, which matters once the app is installed and updated in place (Phase 4).

## 2026-11-14 — Panel: one surface load at a time

Opening a stage cancels any surface load still in flight, and the body is cleared to a loading line before the new request starts. A slow endpoint (`/goals` takes about 0.9s) previously painted its rows under whichever stage had been opened since, and the previous stage's rows stayed visible under the new title until the response arrived.
