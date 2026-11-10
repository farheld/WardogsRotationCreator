// Helper for tests/test_rotate.py: generates a rotation with the web logic and prints the JSON.
// Usage: node tests/web_generate.mjs '{"count":20,"seed":1,"modifiers":[],"maps":null,"includeLegacy":false}'
import { readFileSync } from "node:fs";
import { buildPool, filterPool, pickEntries, buildRotation, mulberry32, toJson } from "../web/rotation.js";

const opts = JSON.parse(process.argv[2] || "{}");
const catalog = JSON.parse(readFileSync(new URL("../data/catalog.json", import.meta.url), "utf8"));
const pool = filterPool(buildPool(catalog, opts.modifiers || []), opts);
const picks = pickEntries(pool, opts.count ?? 10, mulberry32(opts.seed ?? 1));
process.stdout.write(toJson(buildRotation(opts.name || "Web test", picks)));
