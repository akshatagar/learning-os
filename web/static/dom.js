export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  // textContent, never innerHTML: names and model reasoning are strings the
  // model wrote, and this page has no business executing them.
  if (text !== undefined) node.textContent = text;
  return node;
}
