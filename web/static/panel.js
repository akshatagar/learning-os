const SVG = "http://www.w3.org/2000/svg";
const WIDTH = 110;
const HEIGHT = 46;

function element(name, attrs) {
  const node = document.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attrs)) {
    node.setAttribute(key, value);
  }
  return node;
}

const LAMP_IN_WORDS = {
  holding: "waiting on you",
  running: "running",
  unlit: "clear",
};

function drawStage(group, stage) {
  group.replaceChildren();
  group.dataset.lamp = stage.lamp;

  // A stage opens a work surface, so it is a control and must be reachable
  // and readable without the drawing.
  group.setAttribute("tabindex", "0");
  group.setAttribute("role", "button");
  group.setAttribute(
    "aria-label",
    `${stage.label}, ${stage.count}, ${LAMP_IN_WORDS[stage.lamp]}`,
  );

  // Highlight first so the cut line sits on top of it.
  group.appendChild(element("rect", {
    class: "stage__highlight", x: 0, y: 0, width: WIDTH, height: HEIGHT,
  }));
  group.appendChild(element("rect", {
    class: "stage__body", x: 0, y: 0, width: WIDTH, height: HEIGHT,
  }));

  const label = element("text", { class: "stage__label", x: 8, y: -8 });
  label.textContent = stage.label.toUpperCase();
  group.appendChild(label);

  const count = element("text", { class: "stage__count", x: 8, y: 31 });
  count.textContent = stage.count;
  group.appendChild(count);

  group.appendChild(element("circle", {
    class: "stage__lamp", cx: WIDTH - 14, cy: 23, r: 5,
  }));
}

export function renderPanel(state) {
  // Two drawings carry the same ids - the wide plant and the narrow one - and
  // only one is displayed at a time. Both are kept current so a resize is a
  // redraw, never a repopulate.
  for (const stage of state.stages) {
    for (const group of document.querySelectorAll(`[data-stage="${stage.id}"]`)) {
      drawStage(group, stage);
    }
  }
}

export function summarize(state) {
  const holding = state.stages.filter((s) => s.lamp === "holding");
  const running = state.stages.filter((s) => s.lamp === "running");
  if (running.length) {
    return `${running[0].label.toUpperCase()} RUNNING`;
  }
  if (!holding.length) return "NOTHING WAITING";
  return holding.map((s) => s.label.toUpperCase()).join(" · ") + " WAITING";
}
