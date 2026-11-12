// Checks the website's helpers for hand-edited running orders. Run by tests/test_rotate.py.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildPool, rotationIssues, pickToken, pickFromToken } from "../web/rotation.js";

const catalog = JSON.parse(readFileSync(new URL("../data/catalog.json", import.meta.url), "utf8"));
const pool = buildPool(catalog, ["InfantryOnly"]);
const find = (map, lighting, zoneShort) =>
  pool.find((c) => c.display === map && !c.legacy && c.entry.lighting === lighting &&
    (c.entry.zoneAlternator.split(".")[2] || "Default") === zoneShort);

const a = find("Ozeti", "DayClear", "River");
const b = find("Ozeti", "DayEarlyFog", "Church");
const c = find("Sabatulo", "DayLateRain", "Default");

// Share-link tokens round-trip, including Sabatulo's blank zone.
for (const p of [a, b, c]) assert.equal(pickFromToken(pool, pickToken(p)), p);
assert.equal(pickToken(c), "Sabatulo~KOTH~DayLateRain~Default");
assert.equal(pickFromToken(pool, "Nowhere~KOTH~DayClear~Default"), null);

// Several maps: back-to-back maps and duplicates are flagged; a clean order has no issues.
assert.deepEqual(rotationIssues([a, c, b]), []);
assert.deepEqual(rotationIssues([a, b, c]).map((i) => i.indices), [[0, 1]]);
assert.deepEqual(rotationIssues([a, c, a]).map((i) => i.indices), [[0, 2]]);

// One map: same map in a row is fine, the same entry in a row is not.
assert.deepEqual(rotationIssues([a, b, a]), []);
assert.deepEqual(rotationIssues([a, a, b]).map((i) => i.indices), [[0, 1]]);

console.log("ok");
