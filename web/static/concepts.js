// The concept store. It is never a gate, so the ordering is the whole
// design: weakest first, because a concept under the threshold is invisible
// to idea generation and counts as weak against every goal.
import { el } from "./dom.js";
import { meter } from "./meter.js";

const body = document.getElementById("surface-body");
const count = document.getElementById("surface-count");

function conceptRow(concept, threshold) {
  const row = el("li", "concepts__row");
  row.appendChild(el("p", "concepts__name", concept.name));
  if (concept.category) {
    row.appendChild(
      el("p", "concepts__category", concept.category.toUpperCase()),
    );
  }
  row.appendChild(meter(concept.confidence_score, threshold));
  return row;
}

function conceptList(concepts, threshold) {
  const list = el("ul", "concepts__list");
  for (const concept of concepts) {
    list.appendChild(conceptRow(concept, threshold));
  }
  return list;
}

export async function renderConcepts() {
  const payload = await fetch("/concepts").then((response) => response.json());
  const { concepts, threshold } = payload;

  body.replaceChildren();
  count.textContent = concepts.length ? `${concepts.length} HELD` : "";

  if (!concepts.length) {
    body.appendChild(
      el("p", "surface__empty", "No concepts held yet. Ingest a paper or a note."),
    );
    return;
  }

  const below = concepts.filter((c) => (c.confidence_score ?? 0) < threshold);
  const rest = concepts.filter((c) => (c.confidence_score ?? 0) >= threshold);

  // Absent, not empty. Nothing below the line means nothing drawn — no
  // "0 items", no reassurance. This is the Unlit Rule inside a surface, and
  // against the current store it is the branch that renders.
  if (below.length) {
    body.appendChild(
      el("p", "gate__legend", `BELOW ${threshold} · NOT SAMPLED FOR IDEAS`),
    );
    body.appendChild(conceptList(below, threshold));
    body.appendChild(el("hr", "concepts__rule"));
  }

  body.appendChild(conceptList(rest, threshold));
}
