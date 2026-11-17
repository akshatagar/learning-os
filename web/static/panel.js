// Draws the flow nodes on the home page from /state (plus the Inbox count,
// which belongs to the Reel Inbox package rather than to /state).
const SVG = "http://www.w3.org/2000/svg";
const WIDTH = 120;
const HEIGHT = 48;

function element(name, attrs, text) {
  const node = document.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attrs)) {
    node.setAttribute(key, value);
  }
  if (text !== undefined) node.textContent = text;
  return node;
}

const LAMP_IN_WORDS = {
  holding: "waiting on you",
  running: "running",
  unlit: "clear",
};

// The word after each count, so a node reads as a sentence: "6 to decide".
const UNITS = {
  inbox: "reels",
  ingest: "ingested",
  resolution: "judged",
  queue: "doubtful",
  concepts: "held",
  goals: "goals",
  skills: "on record",
  ideas: "generated",
  approval: "to decide",
  scoring: "scored",
  planning: "planned",
};

const LABELS = { queue: "Merge queue", concepts: "Concepts", planning: "Plans" };

function drawStage(group, stage) {
  group.replaceChildren();
  group.dataset.lamp = stage.lamp;
  const label = LABELS[stage.id] || stage.label;

  // A node opens its section, so it is a control: reachable and readable
  // without the drawing.
  group.setAttribute("tabindex", "0");
  group.setAttribute("role", "button");
  group.setAttribute(
    "aria-label", `${label}, ${stage.count} ${UNITS[stage.id] || ""}, ${LAMP_IN_WORDS[stage.lamp]}`,
  );

  group.appendChild(element("rect", {
    class: "stage__body", x: 0.5, y: 0.5, width: WIDTH - 1, height: HEIGHT - 1, rx: 2,
  }));
  group.appendChild(element("text", { class: "stage__label", x: 11, y: 18 }, label.toUpperCase()));

  const count = element("text", { class: "stage__count", x: 11, y: 38 }, String(stage.count));
  count.appendChild(element("tspan", { class: "stage__unit", dx: 6 }, UNITS[stage.id] || ""));
  group.appendChild(count);

  group.appendChild(element("circle", {
    class: "stage__lamp", cx: WIDTH - 10, cy: 10, r: 3.5,
  }));
}

export function renderPanel(state) {
  for (const stage of state.stages) {
    for (const group of document.querySelectorAll(`.stage[data-stage="${stage.id}"]`)) {
      drawStage(group, stage);
    }
  }
}

export function summarize(state) {
  const holding = state.stages.filter((s) => s.lamp === "holding");
  if (!holding.length) return "Nothing is waiting on you.";
  return holding.length === 1
    ? "One thing is waiting on you."
    : `${holding.length} things are waiting on you.`;
}
