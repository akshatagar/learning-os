// A number is a position on a scale. Where a threshold governs that scale,
// the tick marks where the system's behaviour changes — and where nothing
// is governed there is no tick, because drawing one would assert a rule the
// pipeline does not have.
const SVG = "http://www.w3.org/2000/svg";
const WIDTH = 160;
const HEIGHT = 10;

function node(name, attrs) {
  const element = document.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attrs)) {
    element.setAttribute(key, value);
  }
  return element;
}

function describe(value, threshold, label, format) {
  if (value === null) return `${label} not recorded`;
  const reading = `${label} ${format(value)}`;
  if (threshold === null) return reading;
  return `${reading}, ${value >= threshold ? "at or above" : "below"}`
    + ` the ${threshold} threshold`;
}

// format governs the numeral and the aria-label together. Formatting only the
// visible one would have a screen reader announce "skill match 0.67" while the
// screen reads 67%.
export function meter(value, threshold = null, label = "confidence",
                      format = (v) => v.toFixed(2)) {
  const scale = node("svg", {
    class: "meter__scale",
    viewBox: `0 0 ${WIDTH} ${HEIGHT}`,
    width: WIDTH,
    height: HEIGHT,
    role: "img",
    // A meter that communicates only by bar length is not readable.
    "aria-label": describe(value, threshold, label, format),
  });

  scale.appendChild(node("line", {
    class: "meter__track", x1: 0, y1: HEIGHT / 2, x2: WIDTH, y2: HEIGHT / 2,
  }));

  if (value !== null) {
    scale.appendChild(node("line", {
      class: "meter__fill",
      x1: 0, y1: HEIGHT / 2, x2: WIDTH * value, y2: HEIGHT / 2,
    }));
  }

  if (threshold !== null) {
    scale.appendChild(node("line", {
      class: "meter__tick",
      x1: WIDTH * threshold, y1: 0, x2: WIDTH * threshold, y2: HEIGHT,
    }));
  }

  const wrap = document.createElement("span");
  wrap.className = "meter";
  wrap.appendChild(scale);

  const numeral = document.createElement("span");
  numeral.className = "meter__value";
  numeral.textContent = value === null ? "NO CONFIDENCE" : format(value);
  wrap.appendChild(numeral);

  return wrap;
}
