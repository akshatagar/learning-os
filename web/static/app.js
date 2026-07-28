import { renderPanel, summarize } from "./panel.js";

const plantState = document.getElementById("plant-state");

async function refresh() {
  const response = await fetch("/state");
  const state = await response.json();
  renderPanel(state);
  plantState.textContent = summarize(state);
}

refresh();
