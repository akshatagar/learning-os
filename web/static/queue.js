// The merge-queue gate. One entry at a time, in full, because the decision
// needs the model's reasoning and the live neighbours side by side.
import { el } from "./dom.js";
import { meter } from "./meter.js";

const body = document.getElementById("surface-body");
const count = document.getElementById("surface-count");

function modelLine(entry) {
  const line = el("p", "gate__model");
  line.append(
    entry.model_decision
      ? `MODEL SAID ${entry.model_decision.toUpperCase()}`
      : "NO RECORDED DECISION",
  );
  // The tick sits at whichever threshold governed this entry's branch, which
  // is why the server sends it rather than the page assuming one.
  line.appendChild(meter(entry.llm_confidence, entry.threshold));
  return line;
}

function neighborRow(neighbor, onMerge) {
  const row = el("li", "gate__neighbor");
  row.appendChild(el("span", "gate__neighbor-id", `#${neighbor.id}`));
  row.appendChild(el("span", "gate__neighbor-name", neighbor.name));
  // No tick: similarity is context for the model's prompt and is never
  // compared to a constant anywhere in the pipeline.
  row.appendChild(meter(neighbor.similarity_score, null, "similarity"));
  // The id travels with the button, so two concepts sharing a name are still
  // two unambiguous choices.
  row.appendChild(actionButton("MERGE", () => onMerge(neighbor.id)));
  return row;
}

function tallyLine(tally) {
  const total = tally.agreed + tally.disagreed + tally.dismissed;
  const text = total === 0
    ? "NOTHING REVIEWED YET"
    : `AGREED ${tally.agreed} · DISAGREED ${tally.disagreed}`
      + ` · DISMISSED ${tally.dismissed}`;
  return el("p", "gate__tally", text);
}

async function resolve(entryId, action, targetConceptId, onResolved) {
  const response = await fetch(`/queue/${entryId}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, target_concept_id: targetConceptId }),
  });
  if (!response.ok) {
    const problem = await response.json();
    body.appendChild(
      el("p", "gate__reasoning", `That did not go through: ${problem.detail}`),
    );
    return;
  }
  // The lamp is the point: resolving the last entry must darken the stage.
  await renderQueue(onResolved);
  onResolved();
}

function actionButton(label, onClick) {
  const button = el("button", "gate__button", label);
  button.type = "button";
  button.addEventListener("click", onClick);
  return button;
}

export async function renderQueue(onResolved) {
  const [next, tally] = await Promise.all([
    fetch("/queue/next").then((response) => response.json()),
    fetch("/queue/agreement").then((response) => response.json()),
  ]);

  body.replaceChildren();
  count.textContent = next.remaining ? `${next.remaining} WAITING` : "";

  if (!next.entry) {
    body.appendChild(
      el("p", "surface__empty", "Nothing waiting in the merge queue."),
    );
    body.appendChild(tallyLine(tally));
    return;
  }

  const entry = next.entry;
  const act = (action, targetConceptId = null) =>
    resolve(entry.id, action, targetConceptId, onResolved);

  body.appendChild(el("p", "gate__name", entry.candidate_name));
  if (entry.candidate_category) {
    body.appendChild(
      el("p", "gate__category", entry.candidate_category.toUpperCase()),
    );
  }
  body.appendChild(modelLine(entry));
  body.appendChild(
    el("p", "gate__reasoning", entry.llm_reasoning || "No reasoning recorded."),
  );

  if (next.neighbors.length) {
    body.appendChild(el("p", "gate__legend", "NEAREST CONCEPTS"));
    const list = el("ul", "gate__neighbors");
    for (const neighbor of next.neighbors) {
      list.appendChild(neighborRow(neighbor, (id) => act("merge", id)));
    }
    body.appendChild(list);
  } else {
    body.appendChild(
      el("p", "gate__reasoning", "No existing concepts to merge into."),
    );
  }

  const actions = el("div", "gate__actions");
  actions.appendChild(actionButton("INSERT AS NEW", () => act("new")));
  actions.appendChild(actionButton("DISMISS", () => act("dismiss")));
  body.appendChild(actions);

  body.appendChild(tallyLine(tally));
}
