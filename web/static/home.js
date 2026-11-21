// The home dashboard below the flow: what is waiting on you, goal coverage,
// and the latest reels. Each panel reads its own endpoint, so a slow one
// (goals, about a second) never holds the others back.
import { el } from "./dom.js";

const needs = document.getElementById("needs");
const coverage = document.getElementById("coverage");
const latest = document.getElementById("latest");

function head(title, linkText, onLink) {
  const row = el("div", "panel__head");
  row.appendChild(el("h2", null, title));
  if (linkText) {
    const link = el("button", "panel__link", linkText);
    link.type = "button";
    link.addEventListener("click", onLink);
    row.appendChild(link);
  }
  return row;
}

function button(text, onClick, primary = false) {
  const node = el("button", primary ? "gate__button gate__button--primary" : "gate__button", text);
  node.type = "button";
  node.addEventListener("click", onClick);
  return node;
}

function greeting(now = new Date()) {
  const hour = now.getHours();
  if (hour < 12) return "Good morning.";
  if (hour < 18) return "Good afternoon.";
  return "Good evening.";
}

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

// What each waiting stage asks of you, in words, and the button that goes there.
const ASKS = {
  approval: (n) => [plural(n, "idea to approve", "ideas to approve"), "Keep or drop each one", "Review"],
  queue: (n) => [plural(n, "concept to resolve", "concepts to resolve"), "The model was unsure whether they are new", "Resolve"],
  goals: () => ["A goal has no requirements", "Draft them before gaps can be measured", "Draft"],
  skills: () => ["No skills on record", "Scoring needs to know what you can do", "Add skills"],
};

export function renderNeeds(state, inbox, open, process, ollama = null) {
  const waiting = state.stages.filter((s) => s.lamp === "holding" && ASKS[s.id]);
  const pending = inbox ? inbox.counts.pending : 0;

  const date = new Date().toLocaleDateString(undefined, {
    weekday: "long", day: "numeric", month: "long",
  });
  const rows = [];
  waiting.forEach((stage, i) => {
    const [what, why, action] = ASKS[stage.id](stage.count);
    rows.push([what, why, button(action, () => open(stage.id), i === 0)]);
  });
  if (pending) {
    // One job at a time: while a pull or a run is going, the button says so
    // and waits, instead of starting nothing.
    const job = inbox.worker && inbox.worker.running ? inbox.worker.job : null;
    const action = button(
      { process: "Processing…", pull: "Pulling…" }[job] || "Process now", process);
    action.disabled = Boolean(job);
    rows.push([plural(pending, "reel still to process", "reels still to process"),
      "Summaries are written when you click Process now", action]);
  }

  const lede = waiting.length
    ? `${plural(waiting.length, "thing is", "things are")} waiting on you.`
    : "Nothing is waiting on you.";
  needs.replaceChildren(
    el("p", "label", date),
    el("h1", "home__greeting", greeting()),
    el("p", "home__lede", lede),
  );
  for (const [what, why, action] of rows) {
    const row = el("div", "todo");
    const text = el("div", "todo__what", what);
    text.appendChild(el("small", null, why));
    row.append(text, action);
    needs.appendChild(row);
  }
  if (!rows.length) {
    const row = el("div", "todo todo--clear");
    const text = el("div", "todo__what", "All clear");
    text.appendChild(el("small", null, "Ingest a paper or save a reel to keep things moving"));
    row.append(text, button("Ingest", () => open("ingest")));
    needs.appendChild(row);
  }
  needs.appendChild(ollamaRow(ollama));
}

// Ollama runs the summaries, drafts, matching and resolution, and is not
// started at login here, so the home page can start and stop it. Starting
// takes a few seconds: the row says so and checks until it answers.
const OLLAMA_WAIT_MS = 1000;
const OLLAMA_WAIT_TRIES = 30;

function ollamaRow(ollama) {
  const row = el("div", "todo");
  const known = ollama !== null;
  const text = el("div", "todo__what",
    !known ? "Ollama status unknown" : ollama.running ? "Ollama is running" : "Ollama is stopped");
  const why = el("small", null, "Summaries, drafts, matching and resolution use it");
  text.appendChild(why);
  const action = button(known && ollama.running ? "Stop Ollama" : "Start Ollama", async () => {
    action.disabled = true;
    if (known && ollama.running) {
      action.textContent = "Stopping…";
      await fetch("/ollama/stop", { method: "POST" });
    } else {
      action.textContent = "Starting…";
      const response = await fetch("/ollama/start", { method: "POST" });
      if (!response.ok) {
        const answer = await response.json().catch(() => ({}));
        why.textContent = answer.detail || "Could not start Ollama.";
        action.textContent = "Start Ollama";
        action.disabled = false;
        return;
      }
      for (let i = 0; i < OLLAMA_WAIT_TRIES && !(await readOllama())?.running; i++) {
        await new Promise((resolve) => setTimeout(resolve, OLLAMA_WAIT_MS));
      }
    }
    row.replaceWith(ollamaRow(await readOllama()));
  });
  row.append(text, action);
  return row;
}

export async function readOllama() {
  try {
    return await fetch("/ollama").then((response) => response.json());
  } catch {
    return null;
  }
}

export async function renderCoverage(open) {
  const payload = await fetch("/goals").then((response) => response.json());
  coverage.replaceChildren(head("Goal coverage", "All goals ›", () => open("goals")));
  const goals = payload.goals.filter((goal) => goal.requirements && goal.requirements.length);
  if (!goals.length) {
    coverage.appendChild(el("p", "surface__empty", "No goal has requirements yet."));
    return;
  }
  for (const goal of goals) {
    const present = goal.present.length;
    const weak = goal.weak.length;
    const missing = goal.missing.length;
    const total = present + weak + missing;
    const row = el("div", "coverage__goal");
    row.title = `${present} present, ${weak} weak, ${missing} missing`;
    row.appendChild(el("span", "coverage__name", goal.category));
    const bar = el("div", "coverage__bar");
    bar.setAttribute("role", "img");
    bar.setAttribute("aria-label", `${goal.category}: ${present} present, ${weak} weak, ${missing} missing`);
    for (const [cls, n] of [["present", present], ["weak", weak], ["missing", missing]]) {
      if (!n) continue;
      const part = el("i", `coverage__${cls}`);
      part.style.flex = String(n);
      bar.appendChild(part);
    }
    row.appendChild(bar);
    row.appendChild(el("span", "coverage__num", `${present} / ${total}`));
    coverage.appendChild(row);
  }
  const key = el("div", "coverage__key label");
  for (const [cls, text] of [["present", "Present"], ["weak", "Weak"], ["missing", "Missing"]]) {
    const item = el("span");
    item.append(el("i", `coverage__${cls}`), text);
    key.appendChild(item);
  }
  coverage.appendChild(key);
}

function shortDate(iso) {
  const d = new Date(iso);
  return [String(d.getDate()), d.toLocaleDateString(undefined, { month: "short" }).toUpperCase()];
}

export function renderLatest(inbox, open) {
  const reels = inbox ? inbox.reels : [];
  latest.replaceChildren(head("Inbox", reels.length ? `All ${reels.length} ›` : null, () => open("inbox")));
  if (!reels.length) {
    latest.appendChild(el("p", "surface__empty",
      "No reels yet. Share one to Save to Reel Inbox on your phone."));
    return;
  }
  for (const reel of reels.slice(0, 3)) {
    const row = el("div", "latest__reel");
    const [day, month] = shortDate(reel.captured_at);
    const when = el("div", "latest__when label");
    when.append(el("b", null, day), month);
    const body = el("div");
    if (reel.note) body.appendChild(el("p", "latest__note", reel.note));
    body.appendChild(el("p", reel.summary ? "latest__summary" : "latest__summary latest__summary--pending",
      reel.summary || (reel.status === "failed" ? "Could not be processed." : "Waiting to be processed.")));
    row.append(when, body);
    latest.appendChild(row);
  }
}
