// Planning. Like scoring, never a gate. The blocked group carries the warning
// plan_all prints and a job thread swallows — without it, a row that scoring
// has not reached is simply absent here, and the surface cannot say why.
import { el } from "./dom.js";

const body = document.getElementById("surface-body");
const count = document.getElementById("surface-count");

function milestoneRow(milestone) {
  const item = el("li", "board__milestone");
  item.appendChild(el("p", "board__kind", milestone.kind.toUpperCase()));
  item.appendChild(el("p", "board__title", milestone.title));
  if (milestone.detail) {
    item.appendChild(el("p", "board__detail", milestone.detail));
  }
  return item;
}

function plannedRow(row) {
  const item = el("li", "board__row");
  item.appendChild(el("p", "board__title", row.title));
  const list = el("ol", "board__milestones");
  for (const milestone of row.execution_plan) {
    list.appendChild(milestoneRow(milestone));
  }
  item.appendChild(list);
  return item;
}

function plainRow(row) {
  const item = el("li", "board__row");
  item.appendChild(el("p", "board__title", row.title));
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
  const response = await fetch("/jobs/plan-opportunities", { method: "POST" });
  if (!response.ok) {
    const problem = await response.json();
    body.appendChild(
      el("p", "recs__error", `That did not start: ${problem.detail}`),
    );
    return;
  }
  await renderPlanning(onChanged);
  onChanged();
}

export async function renderPlanning(onChanged) {
  const [board, running] = await Promise.all([
    fetch("/planning").then((response) => response.json()),
    fetch("/jobs/running").then((response) => response.json()),
  ]);
  const busy = running.jobs.some((job) => job.kind === "plan-opportunities");

  body.replaceChildren();
  count.textContent = board.planned.length
    ? `${board.planned.length} PLANNED`
    : "";

  const total =
    board.planned.length + board.waiting.length + board.blocked.length;
  if (!total) {
    body.appendChild(el("p", "surface__empty", "Nothing scored yet."));
    return;
  }

  if (board.waiting.length) {
    const button = el(
      "button",
      "gate__button",
      busy ? "PLANNING…" : "RUN PLANNING",
    );
    button.type = "button";
    button.disabled = busy;
    button.addEventListener("click", () => start(onChanged));
    body.appendChild(button);
  }

  if (board.planned.length) {
    body.appendChild(group("PLANNED", board.planned, plannedRow));
  }
  if (board.waiting.length) {
    body.appendChild(group("WAITING", board.waiting, plainRow));
  }
  if (board.blocked.length) {
    const blocked = group("WAITING ON SCORING", board.blocked, plainRow);
    // The sentence the CLI prints. One per group, not one per row.
    blocked.appendChild(
      el("p", "board__note", "NOT SCORED YET · RUN SCORING FIRST"),
    );
    body.appendChild(blocked);
  }
}
