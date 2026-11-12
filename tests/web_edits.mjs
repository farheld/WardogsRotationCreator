// Checks the website's helpers for hand-edited running orders. Run by tests/test_rotate.py.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  buildPool, filterPool, pickEntries, mulberry32, shuffleOrder, rotationIssues, pickToken, pickFromToken,
} from "../web/rotation.js";

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

// Shuffle order: same entries, new order, rules kept, including tight cases.
const sameEntries = (x, y) =>
  assert.deepEqual(x.map(pickToken).sort(), y.map(pickToken).sort());
const cases = [
  filterPool(pool, { maps: ["Sabatulo", "Ozeti"] }),               // tight: max 9
  filterPool(pool, {}),                                             // all maps
  filterPool(pool, { maps: ["Sabatulo"] }),                         // single map, repeats
];
for (const [n, p] of [[9, cases[0]], [30, cases[1]], [10, cases[2]]]) {
  for (let seed = 1; seed <= 200; seed++) {
    const picks = pickEntries(p, n, mulberry32(seed));
    const shuffled = shuffleOrder(picks, mulberry32(seed + 1000));
    sameEntries(picks, shuffled);
    assert.deepEqual(rotationIssues(shuffled), [], `seed ${seed}, ${n} maps`);
  }
}
// Shuffling actually changes the order (at least sometimes).
const base = pickEntries(cases[1], 12, mulberry32(7));
assert.ok([1, 2, 3, 4, 5].some((s) => shuffleOrder(base, mulberry32(s)).map(pickToken).join() !== base.map(pickToken).join()));

console.log("ok");
