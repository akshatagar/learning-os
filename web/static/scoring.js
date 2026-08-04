// Scoring. Never a gate — this lamp only ever says "running" — so the surface
// carries the signal the drawing cannot: the run button exists only while
// there is something for it to score.
import { el } from "./dom.js";
import { meter } from "./meter.js";

const body = document.getElementById("surface-body");
const count = document.getElementById("surface-count");

// The meter draws 0-1 and skill_match_pct is stored 0-100, so the value is
// divided on the way in and multiplied back for the numeral. No tick: nothing
// in the pipeline branches on this number.
const asPercent = (value) => `${Math.round(value * 100)}%`;

function scoredRow(row) {
  const item = el("li", "board__row");
  item.appendChild(el("p", "board__title", row.title));
  item.appendChild(
    meter(row.skill_match_pct / 100, null, "skill match", asPercent),
  );
  item.appendChild(el(
    "p",
    "board__note",
    row.missing_skills.length
      ? `MISSING: ${row.missing_skills.join(" · ")}`
      : "FULLY COVERED",
  ));
  return item;
}

function plainRow(row, note) {
  const item = el("li", "board__row");
  item.appendChild(el("p", "board__title", row.title));
  if (note) item.appendChild(el("p", "board__note", note));
  return item;
}

function group(heading, rows, build) {
  const block = el("div", "board__group");
  block.appendChild(el("p", "gate__legend", `${heading}  ${rows.length}`));
  const list = el("ul", "board__list");
  for (const row of rows) list.appendChild(build(row));
  block.appendChild(list);
  return block;
}

async function start(onChanged) {
  const response = await fetch("/jobs/score-opportunities", { method: "POST" });
  if (!response.ok) {
    const problem = await response.json();
    body.appendChild(
      el("p", "recs__error", `That did not start: ${problem.detail}`),
    );
    return;
  }
  await renderScoring(onChanged);
  onChanged();
}

export async function renderScoring(onChanged) {
  const [board, running] = await Promise.all([
    fetch("/scoring").then((response) => response.json()),
    fetch("/jobs/running").then((response) => response.json()),
  ]);
  // Read back from the server, not remembered locally, so a surface opened
  // during a run still knows one is going. Same rule as ingest.js.
  const busy = running.jobs.some((job) => job.kind === "score-opportunities");

  body.replaceChildren();
  count.textContent = board.scored.length ? `${board.scored.length} SCORED` : "";

  const total =
    board.scored.length + board.waiting.length + board.unscorable.length;
  if (!total) {
    body.appendChild(el(
      "p",
      "surface__empty",
      "Nothing approved yet. Ideas are kept at the approval gate first.",
    ));
    return;
  }

  // The button's presence is the pending signal, because this lamp never goes
  // amber. Nothing waiting means there is nothing to press, so nothing is drawn.
  if (board.waiting.length) {
    const button = el("button", "gate__button", busy ? "SCORING…" : "RUN SCORING");
    button.type = "button";
    button.disabled = busy;
    button.addEventListener("click", () => start(onChanged));
    body.appendChild(button);
  }

  // Absent, not empty, in every group below.
  if (board.scored.length) {
    body.appendChild(group("SCORED", board.scored, scoredRow));
  }
  if (board.waiting.length) {
    body.appendChild(group("WAITING", board.waiting, (row) => plainRow(row, null)));
  }
  if (board.unscorable.length) {
    body.appendChild(group(
      "CANNOT BE SCORED",
      board.unscorable,
      (row) => plainRow(row, "LISTS NO REQUIRED SKILLS"),
    ));
  }
}
