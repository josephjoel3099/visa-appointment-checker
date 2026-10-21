// Pure site logic: no DOM, no localStorage, no clock access (pass `now`).

export const DEFAULT_SELECTION = Object.freeze({
  embassies: Object.freeze(["40"]),
  services: Object.freeze(["Long-stay visa (D-visa) application"]),
});

export const STALE_MINUTES = 30;

export function ageMinutes(iso, now) {
  if (typeof iso !== "string") return Infinity;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return Infinity;
  return (now.getTime() - t) / 60000;
}

export function formatDuration(minutes) {
  if (minutes < 1) return "less than a minute";
  const m = Math.floor(minutes);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h} h`;
  return `${Math.floor(h / 24)} days`;
}

// How long a finished availability window lasted, or null if it is unknown.
function windowMinutes(entry) {
  if (!entry || entry.available) return null;
  const end = Date.parse(entry.last_seen_available);
  const minutes = ageMinutes(entry.last_available_from, new Date(end));
  return Number.isFinite(minutes) && minutes >= 0 ? minutes : null;
}

export function staleness(status, now) {
  const minutes = ageMinutes(status?.last_checked ?? null, now);
  // The checker records an announced portal maintenance window; it only counts
  // while its end is still in the future.
  const until = status?.maintenance_until;
  if (ageMinutes(until, now) < 0) {
    return { stale: true, reason: "maintenance", minutes, until };
  }
  if (!status || status.last_success !== status.last_checked) {
    return { stale: true, reason: "failing", minutes };
  }
  if (minutes > STALE_MINUTES) {
    return { stale: true, reason: "old", minutes };
  }
  return { stale: false, reason: null, minutes };
}

export function selectRows(status, selection) {
  const embassies = status?.embassies ?? {};
  const rows = [];
  for (const embassyId of selection?.embassies ?? []) {
    const embassy = embassies[embassyId];
    if (!embassy) continue;
    for (const service of selection?.services ?? []) {
      const entry = embassy.services?.[service];
      let state;
      if (embassy.ok === false) state = "error";
      else state = entry && entry.available ? "available" : "full";
      rows.push({
        embassyId,
        embassyName: embassy.name ?? embassyId,
        service,
        state,
        dates: entry?.dates ?? null,
        availableSince: entry?.available_since ?? null,
        lastSeenAvailable: entry?.last_seen_available ?? null,
        wasAvailableMinutes: windowMinutes(entry),
      });
    }
  }
  rows.sort(
    (a, b) =>
      a.embassyName.localeCompare(b.embassyName) ||
      a.service.localeCompare(b.service),
  );
  return rows;
}

export function newlyAvailable(prevRows, nextRows) {
  const key = (r) => JSON.stringify([r.embassyId, r.service]);
  // A previous "error" means the earlier availability is unknown, so a row
  // recovering from it is not announced as newly available.
  const known = new Set(
    (prevRows ?? [])
      .filter((r) => r.state === "available" || r.state === "error")
      .map(key),
  );
  return (nextRows ?? []).filter(
    (r) => r.state === "available" && !known.has(key(r)),
  );
}

function isStringArray(v) {
  return Array.isArray(v) && v.every((x) => typeof x === "string");
}

export function normalizeSelection(saved) {
  if (
    saved !== null &&
    typeof saved === "object" &&
    isStringArray(saved.embassies) &&
    isStringArray(saved.services)
  ) {
    return { embassies: [...saved.embassies], services: [...saved.services] };
  }
  return {
    embassies: [...DEFAULT_SELECTION.embassies],
    services: [...DEFAULT_SELECTION.services],
  };
}
