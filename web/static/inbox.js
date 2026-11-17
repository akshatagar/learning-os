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

async function post(path) {
  const response = await fetch(path, { method: "POST" });
  return response.json();
}

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

function reelRow(reel) {
  const row = el("li", "inbox__reel");
  row.appendChild(el("p", "gate__legend", dateLabel(reel.captured_at)));
  if (reel.note) row.appendChild(el("p", "inbox__note", reel.note));

  if (reel.summary) {
    row.appendChild(el("p", "inbox__summary", reel.summary));
  } else {
    const reason = reel.status === "failed" && reel.fail_reason ? `: ${reel.fail_reason}.` : "";
    row.appendChild(el("p", "surface__empty",
      `${STATUS_TEXT[reel.status] || ""}${reason}`));
  }

  const actions = el("div", "gate__actions");
  actions.append(
    button("OPEN REEL", () => post(`/inbox/reels/${encodeURIComponent(reel.id)}/open`)),
    button("DROP", async () => {
      await post(`/inbox/reels/${encodeURIComponent(reel.id)}/drop`);
      renderInbox();
    }),
  );
  row.appendChild(actions);
  return row;
}

function footer(state) {
  const wrap = el("div", "inbox__footer");
  const c = state.counts;
  wrap.appendChild(el("p", "gate__tally",
    `${c.ready} READY · ${c.pending} PENDING · ${c.failed} FAILED · ${c.dropped} DROPPED`));
  const worker = state.worker;
  const process = button(worker && worker.running ? "PROCESSING…" : "PROCESS NOW", async () => {
    await post("/inbox/process");
    renderInbox();
  });
  process.disabled = !worker || worker.running;
  wrap.appendChild(process);
  if (worker && worker.last_error) {
    wrap.appendChild(el("p", "surface__empty", worker.last_error));
  }
  return wrap;
}

export async function renderInbox() {
  const state = await readInbox();
  if (!showing("inbox")) return;
  body.replaceChildren();
  count.textContent = state.reels.length ? `${state.reels.length} REELS` : "";

  if (state.reels.length) {
    const list = el("ul", "inbox__list");
    for (const reel of state.reels) list.appendChild(reelRow(reel));
    body.appendChild(list);
  } else {
    body.appendChild(el("p", "surface__empty",
      "No reels yet. Share one to Save to Reel Inbox on your phone."));
  }
  body.appendChild(footer(state));
}

export function initInbox() {
  readInbox();
}
