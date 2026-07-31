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

function goalBlock(goal, similarity, confidence, running, onStarted) {
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

  body.replaceChildren();
  count.textContent = goals.length ? `${goals.length} GOALS` : "";

  if (!goals.length) {
    body.appendChild(el(
      "p",
      "surface__empty",
      "No goals seeded. Nothing here has anything to measure against.",
    ));
    return;
  }

  for (const goal of goals) {
    body.appendChild(goalBlock(goal, similarity, confidence, busy, onStarted));
  }
}
