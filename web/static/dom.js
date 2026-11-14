export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  // textContent, never innerHTML: names and model reasoning are strings the
  // model wrote, and this page has no business executing them.
  if (text !== undefined) node.textContent = text;
  return node;
}

// A surface load is two awaits long, and the stage can change under it: the
// person opens Goals (about a second) and then Ingest (instant). Every render
// asks this after its fetch and before it touches the body, so only the
// stage that is open right now gets to paint.
export function showing(stage) {
  const surface = document.getElementById("surface");
  return !surface.hidden && surface.dataset.stage === stage;
}
