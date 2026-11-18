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

## 2026-11-17 — No installer: a taskbar shortcut instead (Phase 4)

The brief's Phase 4 (PyInstaller one-dir build, Inno Setup installer, tray icon, single instance, bundled yt-dlp.exe and ffmpeg, keyring-only secrets, %APPDATA% data, sandbox testing) was dropped at the user's direction: "I don't want a proper package installer, just an icon and startup script". It now matches the user's Dashboard project. A shortcut runs the project's own `.venv\Scripts\pythonw.exe -m web.shell` with no console, a `.vbs` serves the Startup folder, and the window carries the Resolve icon and its own AppUserModelID. The app still runs from the repo, with its data in `data/`, its fonts from Google Fonts, and yt-dlp from the venv.

## 2026-11-17 — The panel becomes a black dashboard with a flow chart

The control-room mimic panel, with its sage ground, Archivo, and full-screen drawing, is replaced. The user found it hard on the eye and hard to navigate. They rejected two serif directions and a star-atlas metaphor, then chose a sleek dashboard. It takes its colours and finish from a star-atlas reference board, moved to a black ground.

- **Navigation:** a top bar lists every section, and the Learning OS name returns home from anywhere.
- **The flow stays:** a clickable "How it flows" chart heads the home page, because it explains how the system works. Red marks a stage waiting on you; mint marks running work.
- **Type:** Geist with Geist Mono for labels and counts (user's option C, kept despite Geist being a common face).
- **Section pages keep their markup** and restyle through the shared tokens, so their behaviour and tests are unchanged.
- **Fonts load from Google Fonts for now.** They must be vendored before the offline Windows build (Phase 4).

## 2026-11-17 — Reel Inbox is storage plus a summary (Phase 3)

The brief asked for referent extraction and a one-card review with Explore, Later and Drop, ranking, auto-archiving and work-mode triggers. All of that was built and then replaced at the user's direction. Reel Inbox is now storage plus a summary.

- **Processing writes a summary, not a referent.** Each reel gets two or three plain sentences on what it says, naming the specific things it mentions. This reverses the brief's "do not summarize". The `extract(url)` seam now returns `{summary}`, and an empty summary is a `no_summary` failure.
- **The Inbox is a list.** Every reel that has not been dropped, newest first, with your note and its summary. Pending and failed reels are listed too, with their state, so nothing captured is invisible. Each has Open reel (default browser, http(s) only) and Drop. Dropped reels stay in the store.
- **Removed:** Explore, Later, the learned note, ranking, the three-showing auto-archive, the `surfacings` table, work mode, break, the surfacing-moment setting, the context re-rank, and the Explore → learning-os hook (it was triggered by Explore). Phase 5's explore-rate stats lose their subject; what to measure instead is open.
- **Own store, own file.** `%APPDATA%\LearningOSeel_inbox.db` holds `captures` and `extractions`, created with `create_all` and not with learning-os's Alembic chain, so the package lifts out unchanged. It is the source of truth; Supabase is only a mailbox that rows are deleted from once stored locally.
- **One retry without an extra column.** A first failure is recorded as `status=pending` plus a `fail_reason`. The next run tries it once more, and a second failure moves it to `failed`.
- **Keys.** The phone uses the publishable key, which RLS limits to inserting an Instagram or YouTube link. The laptop uses the secret key, stored in Windows Credential Manager through `keyring`. `CaptureSource` (`pull`, `ack`) is the seam a Telegram bot would replace.
- **The LEARNING-OS name on the plate is the way home:** it closes whatever surface is open.

## 2026-11-14 — Every captured reel is assumed actionable; no labelling

Only reels worth following up get captured in the first place, so neither the eval nor the app checks whether a reel deserves action. The extractor's job is to turn each reel into a referent and a next step. The eval reports only the referent-found rate and failure reasons: the label column is gone, and no grounding or search checks were added. On the first eval (9 Instagram reels, no cookies) 9 of 9 produced a referent after one retry of an Ollama out-of-memory error, so Phase 3 is a go.

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
