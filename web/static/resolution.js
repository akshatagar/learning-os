// Resolution. The audit trail of every automatic adjudication — what the model
// decided, how sure it was against the line that governed that branch, and
// what actually became of the candidate.
//
// The panel's only surface with no actions: adjudication happens inside
// ingestion, which is why this lamp follows the ingest job.
import { el } from "./dom.js";
import { meter } from "./meter.js";

const body = document.getElementById("surface-body");
const count = document.getElementById("surface-count");

const QUEUED_BY_RESOLUTION = {
  approved_merge: "QUEUED · YOU MERGED IT",
  approved_new: "QUEUED · YOU INSERTED IT AS NEW",
  rejected: "QUEUED · YOU DISMISSED IT",
};

function outcomeText(row) {
  if (row.outcome === "merged") return "MERGED AUTOMATICALLY";
  if (row.outcome === "created") return "CREATED AUTOMATICALLY";
  if (row.outcome === "queued") {
    return QUEUED_BY_RESOLUTION[row.human_resolution] || "QUEUED · STILL WAITING";
  }
  // An unlinked row that is neither match nor new cannot come from
  // resolve_candidate. Naming it beats inventing an outcome for it.
  return "OUTCOME NOT RECORDED";
}

function decisionLine(row) {
  const decision = (row.model_decision || "NO DECISION").toUpperCase();
  // created_at is nullable, and a made-up date in an audit trail is worse
  // than no date.
  const stamp = row.created_at ? ` · ${row.created_at.slice(0, 10)}` : "";
  return el("p", "board__note", `${decision}${stamp}`);
}

function adjudicationRow(row) {
  const item = el("li", "board__row");
  item.appendChild(el("p", "board__title", row.candidate_name));
  item.appendChild(decisionLine(row));
  // The tick sits at whichever threshold governed this row's branch, and an
  // uncertain call gets none: neither branch was reachable.
  item.appendChild(meter(row.model_confidence, row.threshold));
  item.appendChild(el("p", "board__note", outcomeText(row)));
  if (row.model_reasoning) {
    item.appendChild(el("p", "board__detail", row.model_reasoning));
  }
  return item;
}

export async function renderResolution() {
  const payload = await fetch("/resolution")
    .then((response) => response.json());
  const { total, adjudications } = payload;

  body.replaceChildren();
  count.textContent = total ? `${total} JUDGED` : "";

  if (!adjudications.length) {
    body.appendChild(el("p", "surface__empty", "Nothing ingested yet."));
    return;
  }

  // Only when it actually truncated, and reporting what was returned rather
  // than a constant. A capped view must never look like the whole log.
  if (adjudications.length < total) {
    body.appendChild(el(
      "p",
      "board__note",
      `SHOWING THE MOST RECENT ${adjudications.length}`,
    ));
  }

  const list = el("ul", "board__list");
  for (const row of adjudications) {
    list.appendChild(adjudicationRow(row));
  }
  body.appendChild(list);
}
