// The skills gate. This is the one table only the operator writes, and the
// only stage whose lamp holds when its count is zero — so every write has to
// tell the panel, or adding the first skill leaves the stage lit behind you.
import { el } from "./dom.js";

const body = document.getElementById("surface-body");
const count = document.getElementById("surface-count");

function skillRow(skill) {
  const row = el("li", "skills__row");
  row.appendChild(el("p", "skills__name", skill.name));
  row.appendChild(el("p", "skills__band", skill.band.toUpperCase()));
  return row;
}

function bandButtons(bands, onPick) {
  const group = el("div", "skills__bands");
  for (const band of bands) {
    const button = el("button", "gate__button", band.label.toUpperCase());
    button.type = "button";
    button.addEventListener("click", () => onPick(band.key));
    group.appendChild(button);
  }
  return group;
}

function notice(text) {
  return el("p", "skills__notice", text);
}

async function send(url, method, payload) {
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return { ok: response.ok, payload: await response.json() };
}

export async function renderSkills(onChanged) {
  const { skills, bands } = await fetch("/skills")
    .then((response) => response.json());

  body.replaceChildren();
  count.textContent = skills.length ? `${skills.length} ON RECORD` : "";

  const field = document.createElement("input");
  field.type = "text";
  field.id = "skill-name";
  field.className = "ingest__field";
  field.placeholder = "Skill name";

  const label = el("label", "gate__legend", "ADD A SKILL");
  label.htmlFor = field.id;

  const form = el("div", "skills__form");
  form.append(label, field);
  form.appendChild(bandButtons(bands, (key) => add(field.value, key)));
  body.appendChild(form);

  // Declared after the form so the handlers above can call it; both run only
  // on click, by which point the whole surface exists.
  async function add(name, band) {
    const result = await send("/skills", "POST", { name, band });
    if (!result.ok) {
      body.appendChild(notice(`That did not go through: ${result.payload.detail}`));
      return;
    }
    if (!result.payload.created) {
      offerChange(result.payload.skill);
      return;
    }
    // The lamp is the point: the first skill added must darken the stage.
    await renderSkills(onChanged);
    onChanged();
  }

  function offerChange(skill) {
    body.appendChild(notice(
      `"${skill.name}" is already on record as ${skill.band}.`,
    ));
    body.appendChild(el("p", "gate__legend", "CHANGE IT TO"));
    body.appendChild(bandButtons(bands, async (key) => {
      const result = await send(`/skills/${skill.id}`, "PATCH", { band: key });
      if (!result.ok) {
        body.appendChild(notice(`That did not go through: ${result.payload.detail}`));
        return;
      }
      await renderSkills(onChanged);
      onChanged();
    }));
  }

  if (!skills.length) {
    body.appendChild(el(
      "p",
      "surface__empty",
      "No skills on record. Feasibility scoring has nothing to match against "
        + "until there are.",
    ));
    return;
  }

  body.appendChild(el("p", "gate__legend", "ON RECORD"));
  const list = el("ul", "skills__list");
  for (const skill of skills) {
    list.appendChild(skillRow(skill));
  }
  body.appendChild(list);
}
