import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_SELECTION,
  STALE_MINUTES,
  ageMinutes,
  formatDuration,
  staleness,
  selectRows,
  newlyAvailable,
  normalizeSelection,
} from "./logic.js";

const NOW = new Date("2026-10-17T16:30:00Z");
const D_VISA = "Long-stay visa (D-visa) application";
const PASSPORT = "Renewal of Estonian citizen`s passport/ID-card";

function svc(available, extra = {}) {
  return {
    available,
    available_since: available ? "2026-10-17T16:00:00Z" : null,
    dates: null,
    last_seen_available: available ? "2026-10-17T16:00:00Z" : null,
    ...extra,
  };
}

function makeStatus(overrides = {}) {
  return {
    last_checked: "2026-10-17T16:25:00Z",
    last_success: "2026-10-17T16:25:00Z",
    service_catalog: [D_VISA, PASSPORT],
    embassies: {
      "40": {
        name: "Embassy of the Republic of Estonia in New Delhi",
        ok: true,
        checked_at: "2026-10-17T16:25:00Z",
        services: { [D_VISA]: svc(true) },
      },
      "10": {
        name: "Embassy of the Republic of Estonia in Brussels",
        ok: true,
        checked_at: "2026-10-17T16:25:00Z",
        services: { [D_VISA]: svc(false), [PASSPORT]: svc(true) },
      },
      "20": {
        name: "Embassy of the Republic of Estonia in Broken",
        ok: false,
        checked_at: "2026-10-17T16:25:00Z",
        services: {},
      },
    },
    ...overrides,
  };
}

test("constants", () => {
  assert.deepEqual(DEFAULT_SELECTION, {
    embassies: ["40"],
    services: [D_VISA],
  });
  assert.equal(STALE_MINUTES, 30);
});

test("ageMinutes", () => {
  assert.equal(ageMinutes("2026-10-17T16:00:00Z", NOW), 30);
  assert.equal(ageMinutes(null, NOW), Infinity);
  assert.equal(ageMinutes("garbage", NOW), Infinity);
});

test("staleness: fresh success is not stale", () => {
  assert.deepEqual(staleness(makeStatus(), NOW), {
    stale: false,
    reason: null,
    minutes: 5,
  });
});

test("staleness: 31 min old with equal last_success is old", () => {
  const t = "2026-10-17T15:59:00Z";
  const r = staleness(makeStatus({ last_checked: t, last_success: t }), NOW);
  assert.equal(r.stale, true);
  assert.equal(r.reason, "old");
  assert.equal(r.minutes, 31);
});

test("staleness: exactly 30 min is not stale", () => {
  const t = "2026-10-17T16:00:00Z";
  const r = staleness(makeStatus({ last_checked: t, last_success: t }), NOW);
  assert.equal(r.stale, false);
  assert.equal(r.reason, null);
});

test("staleness: last_success earlier than last_checked is failing", () => {
  const r = staleness(
    makeStatus({ last_success: "2026-10-17T15:00:00Z" }),
    NOW,
  );
  assert.equal(r.stale, true);
  assert.equal(r.reason, "failing");
});

test("staleness: null last_success is failing", () => {
  const r = staleness(makeStatus({ last_success: null }), NOW);
  assert.equal(r.stale, true);
  assert.equal(r.reason, "failing");
});

test("staleness: announced maintenance in the future is maintenance", () => {
  const r = staleness(
    makeStatus({
      last_success: "2026-10-17T15:00:00Z",
      maintenance_until: "2026-10-17T20:00:00Z",
    }),
    NOW,
  );
  assert.equal(r.stale, true);
  assert.equal(r.reason, "maintenance");
  assert.equal(r.until, "2026-10-17T20:00:00Z");
});

test("staleness: maintenance past its announced end but freshly seen is overrunning", () => {
  const r = staleness(
    makeStatus({
      last_checked: NOW.toISOString(),
      last_success: "2026-10-17T15:00:00Z",
      maintenance_until: "2026-10-17T16:00:00Z",
    }),
    NOW,
  );
  assert.equal(r.stale, true);
  assert.equal(r.reason, "maintenance");
  assert.equal(r.overrun, true);
  assert.equal(r.until, "2026-10-17T16:00:00Z");
});

test("staleness: announced maintenance in the future is not an overrun", () => {
  const r = staleness(
    makeStatus({
      last_success: "2026-10-17T15:00:00Z",
      maintenance_until: "2026-10-17T20:00:00Z",
    }),
    NOW,
  );
  assert.equal(r.overrun, false);
});

test("staleness: maintenance recorded by an old check is just old data", () => {
  const r = staleness(
    makeStatus({
      last_checked: "2026-10-17T10:00:00Z",
      last_success: "2026-10-17T10:00:00Z",
      maintenance_until: "2026-10-17T11:00:00Z",
    }),
    NOW,
  );
  assert.notEqual(r.reason, "maintenance");
});

test("staleness: unparseable maintenance_until is failing", () => {
  const r = staleness(
    makeStatus({ last_success: null, maintenance_until: "soon" }),
    NOW,
  );
  assert.equal(r.reason, "failing");
});

test("selectRows: available, full, error states", () => {
  const rows = selectRows(makeStatus(), {
    embassies: ["40", "10", "20"],
    services: [D_VISA],
  });
  const byId = Object.fromEntries(rows.map((r) => [r.embassyId, r]));
  assert.equal(byId["40"].state, "available");
  assert.equal(byId["40"].availableSince, "2026-10-17T16:00:00Z");
  assert.equal(byId["40"].lastSeenAvailable, "2026-10-17T16:00:00Z");
  assert.equal(byId["40"].dates, null);
  assert.equal(byId["40"].embassyName, "Embassy of the Republic of Estonia in New Delhi");
  assert.equal(byId["40"].service, D_VISA);
  assert.equal(byId["10"].state, "full");
  assert.equal(byId["10"].availableSince, null);
  assert.equal(byId["20"].state, "error");
});

test("selectRows: service missing from embassy is full", () => {
  const rows = selectRows(makeStatus(), {
    embassies: ["40"],
    services: [PASSPORT],
  });
  assert.equal(rows.length, 1);
  assert.equal(rows[0].state, "full");
  assert.equal(rows[0].dates, null);
  assert.equal(rows[0].availableSince, null);
  assert.equal(rows[0].lastSeenAvailable, null);
});

test("selectRows: passes dates through when present", () => {
  const s = makeStatus();
  s.embassies["40"].services[D_VISA] = svc(true, { dates: ["2026-11-01"] });
  const rows = selectRows(s, { embassies: ["40"], services: [D_VISA] });
  assert.deepEqual(rows[0].dates, ["2026-11-01"]);
});

test("selectRows: ordered by embassy name then service", () => {
  const rows = selectRows(makeStatus(), {
    embassies: ["40", "10"],
    services: [PASSPORT, D_VISA],
  });
  assert.deepEqual(
    rows.map((r) => [r.embassyId, r.service]),
    [
      ["10", D_VISA],
      ["10", PASSPORT],
      ["40", D_VISA],
      ["40", PASSPORT],
    ],
  );
});

test("selectRows: skips embassy ids not in status", () => {
  const rows = selectRows(makeStatus(), {
    embassies: ["999", "40"],
    services: [D_VISA],
  });
  assert.deepEqual(rows.map((r) => r.embassyId), ["40"]);
});

test("selectRows: empty selection gives no rows", () => {
  assert.deepEqual(selectRows(makeStatus(), { embassies: [], services: [] }), []);
  assert.deepEqual(selectRows(makeStatus(), { embassies: ["40"], services: [] }), []);
  assert.deepEqual(selectRows(makeStatus(), { embassies: [], services: [D_VISA] }), []);
});

test("selectRows: service not in catalog yields full rows without throwing", () => {
  const rows = selectRows(makeStatus(), {
    embassies: ["40", "10"],
    services: ["No such service"],
  });
  assert.equal(rows.length, 2);
  assert.ok(rows.every((r) => r.state === "full"));
});

test("selectRows: tolerates missing embassies key", () => {
  assert.deepEqual(selectRows({}, DEFAULT_SELECTION), []);
});

const row = (embassyId, service, state) => ({
  embassyId,
  embassyName: "n",
  service,
  state,
  dates: null,
  availableSince: null,
  lastSeenAvailable: null,
});

test("newlyAvailable: full to available is included", () => {
  const out = newlyAvailable([row("40", "S", "full")], [row("40", "S", "available")]);
  assert.equal(out.length, 1);
  assert.equal(out[0].embassyId, "40");
});

test("newlyAvailable: available to available is excluded", () => {
  assert.deepEqual(
    newlyAvailable([row("40", "S", "available")], [row("40", "S", "available")]),
    [],
  );
});

test("newlyAvailable: unseen to available is included", () => {
  const out = newlyAvailable([], [row("40", "S", "available")]);
  assert.equal(out.length, 1);
});

test("newlyAvailable: available to full is excluded", () => {
  assert.deepEqual(
    newlyAvailable([row("40", "S", "available")], [row("40", "S", "full")]),
    [],
  );
});

test("newlyAvailable: error to available is excluded (previous state unknown); matches on id+service", () => {
  const out = newlyAvailable(
    [row("40", "S", "error"), row("40", "T", "available")],
    [row("40", "S", "available"), row("40", "T", "available")],
  );
  assert.deepEqual(out, []);
});

test("newlyAvailable: error to available is excluded", () => {
  assert.deepEqual(
    newlyAvailable([row("40", "S", "error")], [row("40", "S", "available")]),
    [],
  );
});

test("newlyAvailable: full to available is still included alongside an error row", () => {
  const out = newlyAvailable(
    [row("40", "S", "error"), row("40", "T", "full")],
    [row("40", "S", "available"), row("40", "T", "available")],
  );
  assert.deepEqual(out.map((r) => r.service), ["T"]);
});

test("normalizeSelection: invalid input gives a default copy", () => {
  for (const bad of [null, undefined, "x", 5, [], { embassies: [1] }, { embassies: ["40"] }, { embassies: ["40"], services: [2] }]) {
    const out = normalizeSelection(bad);
    assert.deepEqual(out, DEFAULT_SELECTION);
    assert.notEqual(out, DEFAULT_SELECTION);
    assert.notEqual(out.embassies, DEFAULT_SELECTION.embassies);
    assert.notEqual(out.services, DEFAULT_SELECTION.services);
  }
});

test("normalizeSelection: keeps explicit empty arrays", () => {
  assert.deepEqual(normalizeSelection({ embassies: [], services: [] }), {
    embassies: [],
    services: [],
  });
});

test("normalizeSelection: keeps valid selection", () => {
  const sel = { embassies: ["10", "40"], services: ["A"] };
  assert.deepEqual(normalizeSelection(sel), sel);
});

test("formatDuration", () => {
  assert.equal(formatDuration(0.4), "less than a minute");
  assert.equal(formatDuration(1), "1 min");
  assert.equal(formatDuration(59.9), "59 min");
  assert.equal(formatDuration(60), "1 h");
  assert.equal(formatDuration(47 * 60 + 59), "47 h");
  assert.equal(formatDuration(48 * 60), "2 days");
});

test("selectRows: unavailable service reports how long it was available", () => {
  const s = makeStatus();
  s.embassies["40"].services[D_VISA] = svc(false, {
    last_available_from: "2026-10-17T14:00:00Z",
    last_seen_available: "2026-10-17T15:30:00Z",
  });
  const [row] = selectRows(s, { embassies: ["40"], services: [D_VISA] });
  assert.equal(row.state, "full");
  assert.equal(row.wasAvailableMinutes, 90);
});

test("selectRows: no window without a recorded start, or while available", () => {
  const none = selectRows(makeStatus(), {
    embassies: ["10", "40"],
    services: [D_VISA],
  });
  assert.equal(none.find((r) => r.embassyId === "10").wasAvailableMinutes, null);
  assert.equal(none.find((r) => r.embassyId === "40").wasAvailableMinutes, null);
});
