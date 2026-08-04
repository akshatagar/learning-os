// The idea archive and the generator. Every opportunity ever written, grouped
// by where it stands, plus the one control that makes more of them.
import { el } from "./dom.js";

const body = document.getElementById("surface-body");
const count = document.getElementById("surface-count");

// Pipeline order, not alphabetical: this is the road an idea travels.
const GROUPS = [
  ["generated", "GENERATED"],
  ["approved", "APPROVED"],
  ["rejected", "REJECTED"],
];

function actionButton(label, onClick) {
  const button = el("button", "gate__button", label);
  button.type = "button";
  button.addEventListener("click", onClick);
  return button;
}

async function restore(id, onChanged) {
  const response = await fetch(`/opportunities/${id}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "restore" }),
  });
  if (!response.ok) {
    const problem = await response.json();
    body.appendChild(
      el("p", "recs__error", `That did not go through: ${problem.detail}`),
    );
    return;
  }
  // The mirror of the gate's rule: a restored idea is pending again, so the
  // approval lamp has to come on while this surface is the one being read.
  await renderIdeas(onChanged);
  onChanged();
}

async function start(onChanged) {
  const response = await fetch("/jobs/generate-ideas", { method: "POST" });
  if (!response.ok) {
    const problem = await response.json();
    body.appendChild(
      el("p", "recs__error", `That did not start: ${problem.detail}`),
    );
    return;
  }
  await renderIdeas(onChanged);
  onChanged();
}

function ideaRow(idea, onChanged) {
  const row = el("li", "ideas__row");
  row.appendChild(el("p", "ideas__title", idea.title));
  if (idea.status === "rejected") {
    row.appendChild(actionButton("RESTORE", () => restore(idea.id, onChanged)));
  }
  return row;
}

function group(heading, ideas, onChanged) {
  const block = el("div", "ideas__group");
  block.appendChild(el("p", "gate__legend", `${heading}  ${ideas.length}`));
  const list = el("ul", "ideas__list");
  for (const idea of ideas) {
    list.appendChild(ideaRow(idea, onChanged));
  }
  block.appendChild(list);
  return block;
}

export async function renderIdeas(onChanged) {
  const [payload, running] = await Promise.all([
    fetch("/ideas").then((response) => response.json()),
    fetch("/jobs/running").then((response) => response.json()),
  ]);
  const { opportunities } = payload;
  // Read back from the server, not remembered locally, so a surface opened
  // during a run still knows one is going. Same rule as ingest.js.
  const busy = running.jobs.some((job) => job.kind === "generate-ideas");

  body.replaceChildren();
  count.textContent = opportunities.length
    ? `${opportunities.length} TOTAL`
    : "";

  const button = el(
    "button",
    "gate__button",
    busy ? "GENERATING…" : "RUN GENERATE",
  );
  button.type = "button";
  button.disabled = busy;
  button.addEventListener("click", () => start(onChanged));
  body.appendChild(button);

  if (!opportunities.length) {
    // The button stays: making some is the one thing you can do about this.
    body.appendChild(el("p", "surface__empty", "No ideas generated yet."));
    return;
  }

  for (const [status, heading] of GROUPS) {
    const members = opportunities.filter((idea) => idea.status === status);
    // Absent, not empty. No rejected ideas means no REJECTED heading — no
    // "0 items". The Unlit Rule inside a surface, as in concepts.js.
    if (members.length) {
      body.appendChild(group(heading, members, onChanged));
    }
  }
}
