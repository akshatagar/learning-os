import { renderApproval } from "./approval.js";
import { renderConcepts } from "./concepts.js";
import { connectEvents } from "./events.js";
import { renderGoals } from "./goals.js";
import { renderCoverage, renderLatest, renderNeeds } from "./home.js";
import { renderIdeas } from "./ideas.js";
import { initInbox, renderInbox } from "./inbox.js";
import { renderIngest, stopTicking } from "./ingest.js";
import { renderPanel } from "./panel.js";
import { renderPlanning } from "./planning.js";
import { renderQueue } from "./queue.js";
import { renderResolution } from "./resolution.js";
import { renderScoring } from "./scoring.js";
import { renderSkills } from "./skills.js";

const fault = document.getElementById("fault");
const surface = document.getElementById("surface");
const surfaceTitle = document.getElementById("surface-title");
const surfaceBody = document.getElementById("surface-body");
const surfaceCount = document.getElementById("surface-count");
const navButtons = [...document.querySelectorAll(".topbar__nav [data-surface]")];
let opener = null;

const TITLES = {
  inbox: "Inbox", ingest: "Ingest", resolution: "Resolution", queue: "Merge queue",
  concepts: "Concepts", goals: "Goals", ideas: "Ideas", approval: "Approval",
  scoring: "Scoring", planning: "Plans", skills: "Skills",
};

async function readInbox() {
  try {
    return await fetch("/inbox").then((response) => response.json());
  } catch {
    return null;
  }
}

// One read of /state draws the flow and the nav dots; the Inbox node and the
// home panels add their own endpoints.
async function refresh() {
  const [state, inbox] = await Promise.all([
    fetch("/state").then((response) => response.json()),
    readInbox(),
  ]);
  const inboxStage = {
    id: "inbox", label: "Inbox",
    count: inbox ? inbox.reels.length : 0,
    lamp: inbox && inbox.worker && inbox.worker.running ? "running" : "unlit",
  };
  renderPanel({ stages: [inboxStage, ...state.stages] });

  const holding = new Set(state.stages.filter((s) => s.lamp === "holding").map((s) => s.id));
  for (const nav of navButtons) {
    nav.classList.toggle("is-waiting", holding.has(nav.dataset.surface));
  }

  if (surface.hidden) {
    renderNeeds(state, inbox, openById, processInbox);
    renderLatest(inbox, openById);
    renderCoverage(openById);
  }
}

async function processInbox() {
  await fetch("/inbox/process", { method: "POST" });
  refresh();
}

async function showFault(jobId) {
  const response = await fetch(`/jobs/${jobId}`);
  const job = await response.json();
  fault.textContent = `${job.kind} stopped: ${job.error}. Start it again to `
    + `continue — every stage picks up the rows it has not finished.`;
  fault.hidden = false;
}

// Shown the moment a section opens, so the previous section's rows never sit
// under the new title while the new request is in flight.
function showLoading() {
  surfaceCount.textContent = "";
  const note = document.createElement("p");
  note.className = "surface__empty";
  note.textContent = "Reading…";
  surfaceBody.replaceChildren(note);
}

function showPlaceholder() {
  surfaceCount.textContent = "";
  const note = document.createElement("p");
  note.className = "surface__empty";
  note.textContent = "This section has no page wired. That is a defect.";
  surfaceBody.replaceChildren(note);
}

async function openStage(control) {
  opener = control;
  // Flow nodes carry data-stage, nav buttons data-surface; both open the same page.
  const stage = control.dataset.stage || control.dataset.surface;
  stopTicking();
  surfaceTitle.textContent = TITLES[stage] || stage;
  // Read by showing() in dom.js: a render whose stage is no longer open drops
  // its response instead of painting it here.
  surface.dataset.stage = stage;
  showLoading();
  surface.hidden = false;
  document.body.dataset.surface = "open";
  for (const nav of navButtons) {
    if (nav.dataset.surface === stage) nav.setAttribute("aria-current", "page");
    else nav.removeAttribute("aria-current");
  }
  window.scrollTo(0, 0);
  if (stage === "queue") await renderQueue(refresh);
  else if (stage === "concepts") await renderConcepts();
  else if (stage === "ingest") await renderIngest(refresh);
  else if (stage === "skills") await renderSkills(refresh);
  else if (stage === "goals") await renderGoals(refresh);
  else if (stage === "approval") await renderApproval(refresh);
  else if (stage === "ideas") await renderIdeas(refresh);
  else if (stage === "scoring") await renderScoring(refresh);
  else if (stage === "planning") await renderPlanning(refresh);
  else if (stage === "resolution") await renderResolution();
  else if (stage === "inbox") await renderInbox();
  else showPlaceholder();
}

function openById(id) {
  const control = navButtons.find((nav) => nav.dataset.surface === id)
    || document.querySelector(`.stage[data-stage="${id}"]`);
  if (control) openStage(control);
}

for (const nav of navButtons) {
  nav.addEventListener("click", () => openStage(nav));
}
for (const group of document.querySelectorAll(".stage")) {
  group.addEventListener("click", () => openStage(group));
  group.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openStage(group);
    }
  });
}

function closeSurface() {
  // A hidden page must not keep a timer running behind it.
  stopTicking();
  surface.hidden = true;
  delete document.body.dataset.surface;
  for (const nav of navButtons) nav.removeAttribute("aria-current");
  refresh();
  // Focus returns to whatever opened the page, if it is on screen.
  if (opener && opener.getClientRects().length) opener.focus();
  else document.getElementById("home").focus();
}

document.getElementById("surface-close").addEventListener("click", closeSurface);

// The name in the top bar is the way back home from any section.
document.getElementById("home").addEventListener("click", () => {
  if (!surface.hidden) closeSurface();
});

// Escape closes the page, the same as Close.
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !surface.hidden) {
    event.preventDefault();
    closeSurface();
  }
});

initInbox();

// Every event re-reads the endpoints rather than patching the DOM from the
// payload: one authority for what is on screen.
connectEvents((event) => {
  if (event.type === "job" && event.status === "failed") showFault(event.id);
  if (event.type === "job" && event.status === "running") fault.hidden = true;
  const open = surface.hidden ? null : surface.dataset.stage;
  if (event.type === "job" && event.kind === "ingest") {
    if (open === "ingest") renderIngest(refresh);
    if (open === "resolution") renderResolution();
  }
  if (event.type === "job"
      && (event.kind === "recommend" || event.kind === "draft-requirements")
      && open === "goals") {
    renderGoals(refresh);
  }
  if (event.type === "job" && event.kind === "generate-ideas") {
    if (open === "ideas") renderIdeas(refresh);
    if (open === "approval") renderApproval(refresh);
  }
  if (event.type === "job"
      && (event.kind === "score-opportunities" || event.kind === "plan-opportunities")) {
    if (open === "scoring") renderScoring(refresh);
    if (open === "planning") renderPlanning(refresh);
  }
  refresh();
});
refresh();
