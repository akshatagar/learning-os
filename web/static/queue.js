// The merge-queue gate. One entry at a time, in full, because the decision
// needs the model's reasoning and the live neighbours side by side.
const body = document.getElementById("surface-body");
const count = document.getElementById("surface-count");

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  // textContent, never innerHTML: candidate names and model reasoning are
  // strings the model wrote, and this page has no business executing them.
  if (text !== undefined) node.textContent = text;
  return node;
}

function modelLine(entry) {
  const decision = entry.model_decision
    ? `MODEL SAID ${entry.model_decision.toUpperCase()}`
    : "NO RECORDED DECISION";
  const confidence = entry.llm_confidence === null
    ? "NO CONFIDENCE"
    : `CONFIDENCE ${entry.llm_confidence.toFixed(2)}`;
  return el("p", "gate__model", `${decision} · ${confidence}`);
}

function neighborRow(neighbor) {
  const row = el("li", "gate__neighbor");
  row.appendChild(el("span", "gate__neighbor-id", `#${neighbor.id}`));
  row.appendChild(el("span", "gate__neighbor-name", neighbor.name));
  row.appendChild(
    el("span", "gate__neighbor-score", neighbor.similarity_score.toFixed(2)),
  );
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

export async function renderQueue() {
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
      list.appendChild(neighborRow(neighbor));
    }
    body.appendChild(list);
  } else {
    body.appendChild(
      el("p", "gate__reasoning", "No existing concepts to merge into."),
    );
  }

  body.appendChild(tallyLine(tally));
}
