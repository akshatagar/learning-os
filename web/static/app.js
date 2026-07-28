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

// Every event re-reads /state rather than patching the DOM from the payload.
// One authority for what is on screen, and the panel is ten rows.
connectEvents((event) => {
  if (event.type === "job" && event.status === "failed") showFault(event.id);
  if (event.type === "job" && event.status === "running") fault.hidden = true;
  refresh();
});
refresh();
