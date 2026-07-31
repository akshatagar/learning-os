// The goals view. The concept store answers "what do I hold?"; this answers
// "what do I hold against what I said I wanted?" — which is the only question
// on this surface whose answer could not be read off the seed list.
import { el } from "./dom.js";
import { meter } from "./meter.js";

const body = document.getElementById("surface-body");
const count = document.getElementById("surface-count");

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

function goalBlock(goal, similarity, confidence) {
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

  return block;
}

export async function renderGoals() {
  const payload = await fetch("/goals").then((response) => response.json());
  const { goals } = payload;
  const similarity = payload.similarity_threshold;
  const confidence = payload.confidence_threshold;

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
    body.appendChild(goalBlock(goal, similarity, confidence));
  }
}
