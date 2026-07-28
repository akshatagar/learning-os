import { connectEvents } from "./events.js";
import { renderPanel, summarize } from "./panel.js";

const plantState = document.getElementById("plant-state");
const fault = document.getElementById("fault");

async function refresh() {
  const response = await fetch("/state");
  const state = await response.json();
  renderPanel(state);
  plantState.textContent = summarize(state);
}

// The event says something moved; the detail is read back from the endpoint
// that owns it. Same rule as the panel itself: one authority per fact.
async function showFault(jobId) {
  const response = await fetch(`/jobs/${jobId}`);
  const job = await response.json();
  fault.textContent = `${job.kind} stopped: ${job.error}. Start it again to `
    + `continue — every stage picks up the rows it has not finished.`;
  fault.hidden = false;
}

// The surface opens below the drawing, with the plant still visible: you
// never lose your place in the run to look at one stage.
const surface = document.getElementById("surface");
const surfaceTitle = document.getElementById("surface-title");
let opener = null;

function openStage(group) {
  opener = group;
  surfaceTitle.textContent = group.dataset.stage.toUpperCase();
  surface.hidden = false;
}

// Both drawings are covered; the hidden one simply cannot be reached.
for (const group of document.querySelectorAll(".stage")) {
  group.addEventListener("click", () => openStage(group));
  group.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openStage(group);
    }
  });
}

document.getElementById("surface-close").addEventListener("click", () => {
  surface.hidden = true;
  if (opener) opener.focus();
});

// Every event re-reads /state rather than patching the DOM from the payload.
// One authority for what is on screen, and the panel is ten rows.
connectEvents((event) => {
  if (event.type === "job" && event.status === "failed") showFault(event.id);
  if (event.type === "job" && event.status === "running") fault.hidden = true;
  refresh();
});
refresh();
