// The goals view. The concept store answers "what do I hold?"; this answers
// "what do I hold against what I said I wanted?" — and now turns the shortfall
// into something to read.
import { el } from "./dom.js";
import { meter } from "./meter.js";

const body = document.getElementById("surface-body");
const count = document.getElementById("surface-count");

const LEGEND = "SENDS THESE GAP PHRASES TO TAVILY"
  + " · THE ONLY REQUEST THAT LEAVES THIS MACHINE";

function tally(goal) {
  return `${goal.present.length} PRESENT · ${goal.weak.length} WEAK`
    + ` · ${goal.missing.length} MISSING`;
}

function requirementRow(requirement, score, threshold) {
  const row = el("li", "goals__requirement");
  row.appendChild(el("p", "goals__requirement-name", requirement));
  // The tick is earned: 0.70 is exactly what decides missing from matched.
  row.appendChild(meter(score ?? null, threshold, "similarity"));
  return row;
}

// Absent, not empty. A bucket with nothing in it is not drawn at all — no
// "0 present", no reassurance. The Unlit Rule, inside a surface.
function bucket(legend, requirements, scores, threshold) {
  if (!requirements.length) return null;
  const wrap = el("div", "goals__bucket");
  wrap.appendChild(el("p", "gate__legend", legend));
  const list = el("ul", "goals__requirements");
  for (const requirement of requirements) {
    list.appendChild(requirementRow(requirement, scores[requirement], threshold));
  }
  wrap.appendChild(list);
  return wrap;
}

function host(url) {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    // A malformed URL is the web's problem, not a reason to drop the row.
    return url;
  }
}

function resultRow(result) {
  const row = el("li", "recs__result");
  const link = el("a", "recs__link", result.title || result.url);
  link.href = result.url;
  link.target = "_blank";
  link.rel = "noreferrer noopener";
  row.appendChild(link);
  row.appendChild(el("p", "recs__host", host(result.url)));
  if (result.snippet) row.appendChild(el("p", "recs__snippet", result.snippet));
  return row;
}

// Three states, the same trichotomy the CLI renderer draws. The middle one
// must render: a gap that was searched and found nothing new is not the same
// as a gap nobody has searched, and this row is what distinguishes them.
function recommendationBlock(recommendation) {
  const wrap = el("div", "recs__gap");
  wrap.appendChild(el(
    "p", "gate__legend",
    `${recommendation.gap.toUpperCase()} · ${recommendation.gap_score.toFixed(2)}`,
  ));

  if (recommendation.error) {
    wrap.appendChild(el("p", "recs__error", recommendation.error));
    return wrap;
  }
  if (!recommendation.results.length) {
    wrap.appendChild(el(
      "p", "recs__empty", "NOTHING NEW · ALREADY INGESTED OR FILTERED OUT",
    ));
    return wrap;
  }

  const list = el("ul", "recs__results");
  for (const result of recommendation.results) {
    list.appendChild(resultRow(result));
  }
  wrap.appendChild(list);
  return wrap;
}

function toRead(recommendations) {
  return recommendations.reduce((total, r) => total + r.results.length, 0);
}

// The first screen that matters for a new user. Without a goal there are no
// gaps, no recommendations, and nothing to generate ideas against, so this is
// a call to action rather than a notice that something is missing.
function createForm(onDone) {
  const wrap = el("div", "goals__create");
  wrap.appendChild(el("p", "gate__legend", "NEW GOAL"));

  const description = document.createElement("input");
  description.className = "goals__input";
  description.placeholder = "What do you want to be able to do?";

  const category = document.createElement("input");
  category.className = "goals__input";
  category.placeholder = "Short name, e.g. diffusion";

  const button = el("button", "gate__button", "CREATE");
  button.type = "button";
  button.addEventListener("click", async () => {
    if (!description.value.trim()) return;
    button.disabled = true;
    const response = await fetch("/goals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        description: description.value,
        category: category.value,
        priority: 1,
      }),
    });
    if (!response.ok) {
      const problem = await response.json();
      wrap.appendChild(el("p", "recs__error", problem.detail));
      button.disabled = false;
      return;
    }
    await fetch("/jobs/draft-requirements", { method: "POST" });
    onDone();
  });

  wrap.append(description, category, button);
  return wrap;
}

function editor(goal, onDone) {
  const wrap = el("div", "goals__editor");
  const box = document.createElement("textarea");
  box.className = "goals__textarea";
  box.rows = Math.max(6, goal.requirements.length);
  box.value = goal.requirements.join("\n");

  const save = el("button", "gate__button", "SAVE");
  save.type = "button";
  save.addEventListener("click", async () => {
    const response = await fetch(`/goals/${goal.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        requirements: box.value.split("\n").map((line) => line.trim()),
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      wrap.appendChild(el("p", "recs__error", payload.detail));
      return;
    }
    // Warned, not blocked: the save already happened. An acronym with no
    // expansion scores 0.51-0.68 against its own concept and quietly misses.
    for (const phrase of payload.flagged) {
      wrap.appendChild(el(
        "p", "goals__warning",
        `${phrase} — add the spelled-out form or this will not match anything`,
      ));
    }
    if (!payload.flagged.length) onDone();
  });

  const remove = el("button", "gate__button", "DELETE GOAL");
  remove.type = "button";
  remove.addEventListener("click", async () => {
    await fetch(`/goals/${goal.id}`, { method: "DELETE" });
    onDone();
  });

  wrap.append(box, save, remove);
  return wrap;
}

function goalBlock(goal, similarity, confidence, running, drafting, onStarted) {
  // <details> rather than a hand-rolled toggle: each goal opens and closes on
  // its own, keyboard included, with no state to keep. Every goal's
  // requirements arrived in the same response, so expanding costs nothing.
  const block = document.createElement("details");
  block.className = "goals__goal";

  const summary = document.createElement("summary");
  summary.className = "goals__summary";
  summary.appendChild(el("p", "goals__category", goal.category.toUpperCase()));
  summary.appendChild(el("p", "goals__description", goal.description));
  summary.appendChild(el("p", "goals__tally", tally(goal)));
  // Absent when nothing has been recommended: no "0 TO READ".
  const unread = toRead(goal.recommendations);
  if (unread) summary.appendChild(el("p", "goals__tally", `${unread} TO READ`));
  block.appendChild(summary);

  // Deliberately not the Unlit Rule. A goal with no requirements is not quiet,
  // it is unfinished, and every bucket below would render empty and look
  // finished. Failure visibility wins, as it did for CANNOT BE SCORED.
  if (goal.requirements === null) {
    block.appendChild(el(
      "p", "board__note",
      drafting ? "DRAFTING REQUIREMENTS…" : "REQUIREMENTS NOT DRAFTED",
    ));
    if (!drafting) {
      const draft = el("button", "gate__button", "DRAFT");
      draft.type = "button";
      draft.addEventListener("click", async () => {
        await fetch("/jobs/draft-requirements", { method: "POST" });
        await afterChange(onStarted);
      });
      block.appendChild(draft);
    }
    return block;
  }

  const present = bucket("HELD", goal.present, goal.scores, similarity);
  if (present) block.appendChild(present);

  const weak = bucket(
    `MATCHED A CONCEPT BELOW ${confidence} CONFIDENCE`,
    goal.weak, goal.scores, similarity,
  );
  if (weak) block.appendChild(weak);

  const missing = bucket(
    `NO CONCEPT WITHIN ${similarity} SIMILARITY`,
    goal.missing, goal.scores, similarity,
  );
  if (missing) block.appendChild(missing);

  block.appendChild(editor(goal, () => afterChange(onStarted)));

  // Marked, not gated: the one request in this system that leaves the machine
  // says so in words, every time, without interrupting the click.
  block.appendChild(el("p", "recs__notice", LEGEND));
  const button = el("button", "gate__button", running ? "SEARCHING…" : "RECOMMEND");
  button.type = "button";
  button.disabled = running;
  button.addEventListener("click", () => start(goal.category, onStarted));
  block.appendChild(button);

  for (const recommendation of goal.recommendations) {
    block.appendChild(recommendationBlock(recommendation));
  }

  return block;
}

async function start(category, onStarted) {
  const response = await fetch("/recommend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ category }),
  });
  if (!response.ok) {
    const problem = await response.json();
    body.appendChild(
      el("p", "recs__error", `That did not start: ${problem.detail}`),
    );
    return;
  }
  await renderGoals(onStarted);
  onStarted();
}

// Mirrors start()'s own after-mutation shape: re-read the surface so the
// change is on screen, then tell the panel a stage may have moved.
async function afterChange(onStarted) {
  await renderGoals(onStarted);
  onStarted();
}

export async function renderGoals(onStarted) {
  const [payload, running] = await Promise.all([
    fetch("/goals").then((response) => response.json()),
    fetch("/jobs/running").then((response) => response.json()),
  ]);
  const { goals } = payload;
  const similarity = payload.similarity_threshold;
  const confidence = payload.confidence_threshold;
  // Read back from the server, not remembered locally, so a surface opened
  // during a run still knows one is going. Same rule as ingest.js.
  const busy = running.jobs.some((job) => job.kind === "recommend");
  const drafting = running.jobs.some((job) => job.kind === "draft-requirements");

  body.replaceChildren();
  count.textContent = goals.length ? `${goals.length} GOALS` : "";

  // The empty state is not a dead end: it is this form, so a fresh clone can
  // create its first goal without ever having anything to measure against.
  body.appendChild(createForm(() => afterChange(onStarted)));

  for (const goal of goals) {
    body.appendChild(
      goalBlock(goal, similarity, confidence, busy, drafting, onStarted),
    );
  }
}
