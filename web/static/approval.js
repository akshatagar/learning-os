// The approval gate. Every pending idea at once, because this decision is
// comparative: you are choosing what to build, and what else is on offer
// changes the answer. The merge queue shows one at a time for the opposite
// reason — that decision is independent of every other one.
import { el } from "./dom.js";

const body = document.getElementById("surface-body");
const count = document.getElementById("surface-count");

function actionButton(label, onClick) {
  const button = el("button", "gate__button", label);
  button.type = "button";
  button.addEventListener("click", onClick);
  return button;
}

function detailLine(label, values) {
  return el(
    "p",
    "approval__meta",
    `${label} ${values.length ? values.join(" · ") : "(none recorded)"}`,
  );
}

async function resolve(id, action, onResolved) {
  const response = await fetch(`/opportunities/${id}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
  if (!response.ok) {
    const problem = await response.json();
    body.appendChild(
      el("p", "recs__error", `That did not go through: ${problem.detail}`),
    );
    return;
  }
  // The lamp is the point: deciding the last idea must darken the stage.
  await renderApproval(onResolved);
  onResolved();
}

function ideaBlock(idea, onResolved) {
  const block = el("div", "approval__idea");
  block.appendChild(el("p", "gate__name", idea.title));
  block.appendChild(el("p", "gate__reasoning", idea.description));
  block.appendChild(detailLine("FROM CONCEPTS", idea.source_concepts));
  block.appendChild(detailLine("REQUIRES", idea.required_skills));

  const actions = el("div", "gate__actions");
  actions.appendChild(
    actionButton("KEEP", () => resolve(idea.id, "approve", onResolved)),
  );
  actions.appendChild(
    actionButton("DROP", () => resolve(idea.id, "reject", onResolved)),
  );
  block.appendChild(actions);
  return block;
}

export async function renderApproval(onResolved) {
  const { opportunities } = await fetch("/approval")
    .then((response) => response.json());

  body.replaceChildren();
  count.textContent = opportunities.length
    ? `${opportunities.length} WAITING`
    : "";

  if (!opportunities.length) {
    body.appendChild(
      el("p", "surface__empty", "Nothing waiting for approval."),
    );
    return;
  }

  for (const idea of opportunities) {
    body.appendChild(ideaBlock(idea, onResolved));
  }
}
