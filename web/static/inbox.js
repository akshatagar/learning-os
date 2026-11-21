// Reel Inbox: every stored reel that has not been dropped, newest first,
// with the summary written when it was processed.
import { el, showing } from "./dom.js";

const body = document.getElementById("surface-body");
const count = document.getElementById("surface-count");
const inboxButton = document.getElementById("inbox-open");
const inboxCount = document.getElementById("inbox-count");

const STATUS_TEXT = {
  pending: "Waiting to be processed.",
  failed: "Could not be processed",
};

async function post(path, body) {
  const response = await fetch(path, body === undefined ? { method: "POST" } : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  // An unhandled server error answers in plain text, not JSON.
  const data = await response.json().catch(() => ({}));
  return { ok: response.ok, status: response.status, ...data };
}

// While a run is going the page re-reads itself, so the reel being processed
// shows as locked and drops back when it is done. Never while a form is open.
const REFRESH_MS = 3000;
let refreshTimer = null;
let writing = false;

async function readInbox() {
  const state = await fetch("/inbox").then((response) => response.json());
  const total = state.reels.length;
  inboxCount.textContent = total ? String(total) : "";
  inboxButton.setAttribute("aria-label", `Inbox, ${total} reels`);
  return state;
}

function button(text, onClick) {
  const node = el("button", "gate__button", text);
  node.type = "button";
  node.addEventListener("click", onClick);
  return node;
}

function dateLabel(iso) {
  return new Date(iso).toLocaleDateString(undefined, {
    day: "numeric", month: "short", year: "numeric",
  }).toUpperCase();
}

function reelPath(reel, action) {
  return `/inbox/reels/${encodeURIComponent(reel.id)}/${action}`;
}

// A title and description in place of the LLM summary. Replaces the card's
// status line and buttons until it is saved or cancelled.
function writeForm(reel) {
  const form = el("form", "goals__editor");
  const title = el("input", "goals__input");
  title.placeholder = "Title";
  title.maxLength = 200;
  title.required = true;
  title.setAttribute("aria-label", "Title");
  const description = el("textarea", "goals__textarea");
  description.placeholder = "Description (optional)";
  description.maxLength = 2000;
  description.rows = 3;
  description.setAttribute("aria-label", "Description");
  const error = el("p", "goals__warning");
  error.hidden = true;

  const save = el("button", "gate__button gate__button--primary", "SAVE");
  save.type = "submit";
  const actions = el("div", "gate__actions");
  // Cancel redraws from the server: the card may have changed while the
  // form was open (the run reached it, or finished it).
  actions.append(save, button("CANCEL", () => { writing = false; renderInbox(); }));
  form.append(title, description, error, actions);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    save.disabled = true;
    try {
      const answer = await post(reelPath(reel, "manual"),
        { title: title.value, description: description.value });
      // 409: the reel is being processed or already summarized, so the form
      // no longer applies; redraw to show what it is now.
      if (answer.ok || answer.status === 409) {
        writing = false;
        renderInbox();
        return;
      }
      error.textContent = typeof answer.detail === "string" ? answer.detail : "Could not save.";
      error.hidden = false;
    } catch {
      error.textContent = "Could not reach the app.";
      error.hidden = false;
    } finally {
      save.disabled = false;
    }
  });
  return form;
}

function reelRow(reel, current) {
  const row = el("li", "inbox__reel");
  row.appendChild(el("p", "gate__legend", dateLabel(reel.captured_at)));
  if (reel.note) row.appendChild(el("p", "inbox__note", reel.note));
  if (reel.title) row.appendChild(el("p", "inbox__title", reel.title));

  const processing = reel.id === current;
  const rest = [];
  if (reel.summary) {
    rest.push(el("p", "inbox__summary", reel.summary));
  } else if (!reel.title) {
    const reason = reel.status === "failed" && reel.fail_reason ? `: ${reel.fail_reason}.` : "";
    rest.push(el("p", "surface__empty", processing ? "Being processed now."
      : `${STATUS_TEXT[reel.status] || ""}${reason}`));
  }

  const actions = el("div", "gate__actions");
  actions.append(button("OPEN REEL", () => post(reelPath(reel, "open"))));
  const unsummarized = reel.status === "pending" || reel.status === "failed";
  if (unsummarized && !processing) {
    actions.append(button("WRITE IT", () => {
      writing = true;
      for (const node of rest) node.remove();
      row.appendChild(writeForm(reel));
      row.querySelector("input").focus();
    }));
  }
  if (reel.status === "failed") {
    actions.append(button("RETRY", async () => {
      await post(reelPath(reel, "retry"));
      renderInbox();
    }));
  }
  const drop = button(processing ? "PROCESSING…" : "DROP", async () => {
    const answer = await post(reelPath(reel, "drop"));
    if (!answer.ok) drop.textContent = "PROCESSING…";
    renderInbox();
  });
  drop.disabled = processing;
  actions.append(drop);
  rest.push(actions);
  row.append(...rest);
  return row;
}

// Why a run ended early, when it was not the reels' fault.
const STOPPED_TEXT = {
  llm_unavailable: "Ollama isn't running. Start it from the home page, then Process now.",
  login_wall: "Instagram wants a login. Sign in to Instagram in Firefox or Chrome, then try again.",
  rate_limited: "Instagram is rate-limiting. Try again later.",
};

// What the last Process now did, in one line.
function runSummary(report) {
  const parts = [];
  if (report.processed) parts.push(`${report.processed} summarized`);
  if (report.failed) parts.push(`${report.failed} failed`);
  if (report.retry_next_run) parts.push(`${report.retry_next_run} will retry`);
  const done = parts.length ? `Last run: ${parts.join(", ")}.` : "";
  const stopped = STOPPED_TEXT[report.stopped];
  if (stopped) return done ? `${done} Then stopped: ${stopped}` : stopped;
  if (report.stopped === "stop_requested") return done || "Last run was stopped.";
  return done || "Nothing to process.";
}

function footer(state) {
  const wrap = el("div", "inbox__footer");
  const c = state.counts;
  wrap.appendChild(el("p", "gate__tally",
    `${c.ready} READY · ${c.pending} PENDING · ${c.failed} FAILED · ${c.dropped} DROPPED`));
  // Two separate jobs, both by hand: PULL fetches new reels from the phone's
  // mailbox, PROCESS NOW runs the LLM over stored ones. One at a time.
  const worker = state.worker;
  const job = worker && worker.running ? worker.job : null;
  const pull = button(job === "pull" ? "PULLING…" : "PULL", async () => {
    await post("/inbox/pull");
    renderInbox();
  });
  const process = button(job === "process" ? "PROCESSING…" : "PROCESS NOW", async () => {
    await post("/inbox/process");
    renderInbox();
  });
  pull.disabled = process.disabled = !worker || Boolean(job);
  wrap.append(pull, process);
  if (worker && !job && worker.last_pulled !== null && !worker.last_pull_error) {
    wrap.appendChild(el("p", "gate__tally",
      worker.last_pulled === 1 ? "1 NEW" : `${worker.last_pulled} NEW`));
  }
  if (worker && job !== "process" && worker.last_report) {
    wrap.appendChild(el("p", "surface__empty", runSummary(worker.last_report)));
  }
  for (const error of [worker && worker.last_pull_error, worker && worker.last_error]) {
    if (error) wrap.appendChild(el("p", "surface__empty", error));
  }
  return wrap;
}

function scheduleRefresh(state) {
  clearTimeout(refreshTimer);
  refreshTimer = null;
  if (state.worker && state.worker.running) {
    refreshTimer = setTimeout(() => {
      if (!writing && showing("inbox")) renderInbox();
      else if (showing("inbox")) scheduleRefresh(state);
    }, REFRESH_MS);
  }
}

export async function renderInbox() {
  const state = await readInbox();
  if (!showing("inbox")) return;
  writing = false;
  body.replaceChildren();
  count.textContent = state.reels.length ? `${state.reels.length} REELS` : "";
  const current = state.worker ? state.worker.current : null;

  if (state.reels.length) {
    const list = el("ul", "inbox__list");
    for (const reel of state.reels) list.appendChild(reelRow(reel, current));
    body.appendChild(list);
  } else {
    body.appendChild(el("p", "surface__empty",
      "No reels yet. Share one to Save to Reel Inbox on your phone."));
  }
  body.appendChild(footer(state));
  scheduleRefresh(state);
}

export function initInbox() {
  readInbox();
}
