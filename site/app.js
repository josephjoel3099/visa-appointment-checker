import {
  newlyAvailable,
  normalizeSelection,
  selectRows,
  staleness,
} from "./logic.js";

const PORTAL_URL = "https://broneering.mfa.ee/en/";
const STORAGE_KEY = "visa-checker-selection-v1";
const REFRESH_MS = 60 * 1000;
const TICK_MS = 30 * 1000;

const $ = (id) => document.getElementById(id);
const baseTitle = document.title;

// ---- state -------------------------------------------------------------

let status = null; // last successfully fetched status.json
let fetchFailed = false;
let inflight = false;
let selection = loadSelection();
let prevRows = null; // rows from the previous render, for change detection
let listsKey = null;
let resultsKey = null;

// ---- storage (every access guarded) -------------------------------------

function dedupe(list) {
  return [...new Set(list)];
}

function loadSelection() {
  let saved = null;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw !== null) saved = JSON.parse(raw);
  } catch (_) {
    saved = null;
  }
  const sel = normalizeSelection(saved);
  return { embassies: dedupe(sel.embassies), services: dedupe(sel.services) };
}

function saveSelection() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(selection));
  } catch (_) {
    /* storage unavailable: selection just lasts for this page view */
  }
}

// ---- formatting ---------------------------------------------------------

function formatAge(minutes) {
  if (!Number.isFinite(minutes)) return "unknown";
  if (minutes < 1) return "just now";
  const m = Math.floor(minutes);
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.floor(h / 24)} days ago`;
}

function formatWhen(iso) {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return String(iso);
  return new Date(t).toLocaleString();
}

function formatDates(dates) {
  if (Array.isArray(dates)) return dates.map(String).join(", ");
  return String(dates);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// ---- rendering ----------------------------------------------------------

function currentRows() {
  return status ? selectRows(status, selection) : [];
}

function portalLink(primary) {
  const a = el(
    "a",
    primary ? "portal primary" : "portal",
    primary ? "Open the booking portal" : "Booking portal",
  );
  a.href = PORTAL_URL;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  return a;
}

function renderRow(row) {
  const card = el("article", `row ${row.state}`);
  card.appendChild(el("div", "emb", row.embassyName));
  card.appendChild(el("div", "svc", row.service));

  const label = {
    available: "Available",
    full: "No free appointments",
    error: "Check failing",
  }[row.state];
  const line = el("p", "detail");
  line.appendChild(el("span", `badge ${row.state}`, label));
  card.appendChild(line);

  if (row.state === "available") {
    const text =
      row.dates !== null && row.dates !== undefined
        ? `Dates: ${formatDates(row.dates)}`
        : "Available — open the portal to see dates";
    card.appendChild(el("p", "detail", text));
  } else if (row.state === "error") {
    card.appendChild(
      el("p", "detail", "Check failing — showing last known data"),
    );
  }

  if (row.lastSeenAvailable) {
    card.appendChild(
      el(
        "p",
        "detail small",
        `Last seen available: ${formatWhen(row.lastSeenAvailable)}`,
      ),
    );
  }
  card.appendChild(portalLink(row.state === "available"));
  return card;
}

function setText(node, text) {
  if (node.textContent !== text) node.textContent = text;
}

function renderResults() {
  const box = $("results");
  let key;
  let build;
  if (!status) {
    const msg = fetchFailed ? "Could not load availability data." : "Loading…";
    key = JSON.stringify(["msg", msg]);
    build = () => [el("p", "muted", msg)];
  } else if (selection.embassies.length === 0 || selection.services.length === 0) {
    const msg = "Pick at least one embassy and one appointment type below.";
    key = JSON.stringify(["msg", msg]);
    build = () => [el("p", "muted", msg)];
  } else {
    const rows = currentRows();
    if (rows.length === 0) {
      const msg = "None of the selected embassies are in the latest data.";
      key = JSON.stringify(["msg", msg]);
      build = () => [el("p", "muted", msg)];
    } else {
      key = JSON.stringify(["rows", rows]);
      build = () => rows.map(renderRow);
    }
  }
  // Skip the DOM update when nothing changed, so keyboard focus and
  // screen-reader live-region announcements are not disturbed on refresh.
  if (key === resultsKey) return;
  resultsKey = key;
  box.replaceChildren(...build());
}

function renderHeader() {
  const now = new Date();
  const banner = $("banner");
  let message = null;
  let lastText;

  // The banner message is deliberately age-free so it is stable between ticks;
  // the changing age lives only in the non-live "Last checked" line.
  if (!status) {
    lastText = "Last checked: unknown";
    if (fetchFailed) message = "Could not load status data. Retrying every minute.";
  } else {
    const s = staleness(status, now);
    lastText = `Last checked: ${formatAge(s.minutes)}`;
    if (fetchFailed) {
      message =
        "Could not refresh data — showing last known data. Retrying every minute.";
    } else if (s.stale && s.reason === "failing") {
      message =
        "The checker is currently failing — showing last known data, which may be out of date.";
    } else if (s.stale) {
      message =
        "This data may be outdated — the checker may have stopped. Confirm on the portal.";
    }
  }

  setText($("last-checked"), lastText);
  if (message === null) {
    if (!banner.hidden) {
      banner.hidden = true;
      banner.textContent = "";
    }
  } else {
    setText(banner, message);
    if (banner.hidden) banner.hidden = false;
  }
}

function makeCheckbox(group, value, text) {
  const label = el("label");
  const input = document.createElement("input");
  input.type = "checkbox";
  input.value = value;
  input.dataset.group = group;
  input.checked = selection[group].includes(value);
  label.appendChild(input);
  label.appendChild(el("span", "", text));
  return label;
}

function renderLists() {
  if (!status) return;
  const embassies = Object.entries(status.embassies ?? {})
    .map(([id, e]) => [id, e?.name ?? id])
    .sort((a, b) => a[1].localeCompare(b[1]) || a[0].localeCompare(b[0]));
  const services = Array.isArray(status.service_catalog)
    ? [...status.service_catalog].filter((s) => typeof s === "string")
    : [];

  const key = JSON.stringify([embassies, services]);
  if (key === listsKey) return; // unchanged: keep focus and scroll position
  listsKey = key;

  const eList = $("embassy-list");
  eList.replaceChildren();
  for (const [id, name] of embassies) eList.appendChild(makeCheckbox("embassies", id, name));
  const sList = $("service-list");
  sList.replaceChildren();
  for (const s of services) sList.appendChild(makeCheckbox("services", s, s));
}

function syncCheckboxes() {
  for (const input of document.querySelectorAll(".checklist input[type=checkbox]")) {
    input.checked = selection[input.dataset.group].includes(input.value);
  }
}

function renderAll() {
  renderHeader();
  renderLists();
  renderResults();
}

// ---- selection changes ----------------------------------------------------

function selectionChanged() {
  saveSelection();
  renderResults();
  // Changing what is watched must not trigger "newly available" alerts.
  prevRows = currentRows();
}

function onToggle(event) {
  const input = event.target;
  if (!(input instanceof HTMLInputElement) || input.type !== "checkbox") return;
  const group = input.dataset.group;
  if (group !== "embassies" && group !== "services") return;
  const set = new Set(selection[group]);
  if (input.checked) set.add(input.value);
  else set.delete(input.value);
  selection[group] = [...set];
  selectionChanged();
}

function onBulk(event) {
  const btn = event.target.closest?.("button[data-bulk]");
  if (!btn) return;
  const group = btn.dataset.bulk;
  if (btn.dataset.mode === "all") {
    const values = [
      ...document.querySelectorAll(`.checklist input[data-group="${group}"]`),
    ].map((i) => i.value);
    selection[group] = dedupe([...selection[group], ...values]);
  } else {
    selection[group] = [];
  }
  syncCheckboxes();
  selectionChanged();
}

// ---- notifications --------------------------------------------------------

function notificationPermission() {
  try {
    return typeof Notification === "undefined" ? "unsupported" : Notification.permission;
  } catch (_) {
    return "unsupported";
  }
}

function renderNotifyButton() {
  $("notify-btn").hidden = notificationPermission() !== "default";
}

function onNotifyClick() {
  try {
    const result = Notification.requestPermission();
    if (result && typeof result.then === "function") {
      result.then(renderNotifyButton, renderNotifyButton);
    } else {
      renderNotifyButton();
    }
  } catch (_) {
    renderNotifyButton();
  }
}

function announce(added) {
  if (document.hidden) {
    if (!document.title.startsWith("(!) ")) document.title = `(!) ${baseTitle}`;
  }
  if (notificationPermission() === "granted") {
    const names = added.map((r) => `${r.embassyName}: ${r.service}`);
    try {
      new Notification("Visa appointment available", { body: names.join("\n") });
    } catch (_) {
      /* some mobile browsers only allow service-worker notifications */
    }
  }
}

function onVisible() {
  if (!document.hidden) {
    document.title = baseTitle;
    refresh();
  }
}

// ---- fetching -------------------------------------------------------------

async function refresh() {
  if (inflight) return;
  inflight = true;
  try {
    const res = await fetch("./status.json", { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data === null || typeof data !== "object" || typeof data.embassies !== "object" || data.embassies === null) {
      throw new Error("unexpected status.json shape");
    }
    status = data;
    fetchFailed = false;
    const next = currentRows();
    if (prevRows !== null) {
      const added = newlyAvailable(prevRows, next);
      if (added.length > 0) announce(added);
    }
    prevRows = next;
  } catch (_) {
    fetchFailed = true; // keep last good `status`
  } finally {
    inflight = false;
  }
  renderAll();
}

// ---- boot -----------------------------------------------------------------

$("embassy-set").addEventListener("change", onToggle);
$("service-set").addEventListener("change", onToggle);
document.addEventListener("click", onBulk);
$("notify-btn").addEventListener("click", onNotifyClick);
window.addEventListener("focus", refresh);
document.addEventListener("visibilitychange", onVisible);
setInterval(refresh, REFRESH_MS);
setInterval(renderHeader, TICK_MS);

renderNotifyButton();
renderAll();
refresh();
