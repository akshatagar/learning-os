// The ingest surface. A run takes minutes, so the one thing this adds over
// the lamp is how long it has been going — enough to tell a slow parse from
// a stuck one, and no claim about which step it is on, because a single
// LangGraph invoke offers no way to know.
import { el } from "./dom.js";

const body = document.getElementById("surface-body");
const count = document.getElementById("surface-count");

let ticking = null;

function clock(seconds) {
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${minutes}:${rest}`;
}

function form(onStart, running) {
  const wrap = el("div", "ingest__form");

  const field = document.createElement("input");
  field.type = "text";
  field.id = "ingest-source";
  field.className = "ingest__field";
  field.placeholder = "URL or file path";
  field.disabled = running;

  const label = el("label", "gate__legend", "SOURCE");
  label.htmlFor = field.id;

  const kinds = el("div", "ingest__kinds");
  for (const [value, text] of [["paper", "PAPER"], ["note", "NOTE"]]) {
    const choice = el("label", "ingest__kind");
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "ingest-kind";
    radio.value = value;
    radio.checked = value === "paper";
    radio.disabled = running;
    choice.appendChild(radio);
    choice.append(text);
    kinds.appendChild(choice);
  }

  const start = el("button", "gate__button", "START");
  start.type = "button";
  start.disabled = running;
  start.addEventListener("click", () => {
    const kind = kinds.querySelector("input:checked").value;
    onStart(field.value, kind);
  });

  kinds.appendChild(start);
  wrap.append(label, field, kinds);
  return wrap;
}

function historyRow(entry) {
  const row = el("li", "ingest__entry");
  row.appendChild(el("p", "ingest__source", entry.source_path || "unknown source"));
  const date = entry.ingested_at ? entry.ingested_at.slice(0, 10) : "no date";
  row.appendChild(el(
    "p",
    "ingest__meta",
    `${(entry.source_type || "unknown").toUpperCase()} · `
      + `${entry.concept_count} CONCEPTS · ${date}`,
  ));
  return row;
}

function startTicking(seconds, line) {
  stopTicking();
  let elapsed = seconds;
  const paint = () => { line.textContent = `RUNNING · ${clock(elapsed)} ELAPSED`; };
  paint();
  ticking = setInterval(() => { elapsed += 1; paint(); }, 1000);
}

export function stopTicking() {
  if (ticking !== null) clearInterval(ticking);
  ticking = null;
}

async function post(source, kind, onStarted) {
  const response = await fetch("/ingest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source, kind }),
  });
  if (!response.ok) {
    const problem = await response.json();
    body.appendChild(
      el("p", "surface__empty", `That did not start: ${problem.detail}`),
    );
    return;
  }
  await renderIngest(onStarted);
  onStarted();
}

export async function renderIngest(onStarted) {
  const [history, running] = await Promise.all([
    fetch("/ingest/history").then((response) => response.json()),
    fetch("/jobs/running").then((response) => response.json()),
  ]);
  // Read back from the server rather than remembered locally, so a surface
  // opened during a run still knows how long it has been going.
  const job = running.jobs.find((candidate) => candidate.kind === "ingest");

  stopTicking();
  body.replaceChildren();
  count.textContent = history.entries.length
    ? `${history.entries.length} INGESTED`
    : "";

  body.appendChild(
    form((source, kind) => post(source, kind, onStarted), job !== undefined),
  );

  if (job !== undefined) {
    const line = el("p", "gate__model");
    body.appendChild(line);
    startTicking(job.elapsed_seconds, line);
  }

  if (history.entries.length) {
    body.appendChild(el("p", "gate__legend", "PREVIOUSLY INGESTED"));
    const list = el("ul", "ingest__history");
    for (const entry of history.entries) {
      list.appendChild(historyRow(entry));
    }
    body.appendChild(list);
  }
}
