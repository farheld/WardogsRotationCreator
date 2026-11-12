// Rotation generation logic for the web version.
// Mirrors rotate.py: same catalog, same rules (balanced maps, no back-to-back maps,
// no duplicate entries, one modifier set for the whole rotation, legacy modes opt-in).

export const ENTRY_KEYS = ["map", "experience", "modifiers", "lighting", "zoneAlternator"];

/** 'ZoneAlternator.Bakurani.Farmland.Circle' -> 'Farmland' */
export function zoneShort(zone) {
  if (!zone) return "Default";
  const parts = zone.split(".");
  return parts.length > 2 ? parts[2] : zone;
}

export function isDefaultZone(zone) {
  return zone === "" || zoneShort(zone).toLowerCase() === "default";
}

/** Modifier names offered by the given maps (display names), in catalog order. */
export function modifierNames(catalog, maps) {
  const names = [];
  for (const [display, m] of Object.entries(catalog.maps)) {
    if (maps && !maps.includes(display)) continue;
    for (const mode of Object.values(m.modes)) {
      for (const n of Object.keys(mode.modifiers || {})) if (!names.includes(n)) names.push(n);
    }
  }
  return names;
}

/** Every valid combination for one modifier choice (applied to every entry). */
export function buildPool(catalog, modifiers = []) {
  const chosen = new Set(modifiers);
  const pool = [];
  for (const [display, m] of Object.entries(catalog.maps)) {
    for (const [modeName, mode] of Object.entries(m.modes)) {
      const available = mode.modifiers || {};
      if (![...chosen].every((n) => n in available)) continue;
      const modIds = Object.entries(available).filter(([n]) => chosen.has(n)).map(([, id]) => id);
      for (const lighting of mode.lighting || m.lighting) {
        for (const zone of mode.zones || m.zones) {
          pool.push({
            display,
            modeName,
            legacy: Boolean(mode.legacy),
            entry: { map: m.map, experience: mode.experience, modifiers: [...modIds], lighting, zoneAlternator: zone },
          });
        }
      }
    }
  }
  return pool;
}

/**
 * opts: { maps?: string[], includeLegacy?: boolean, lighting?: string[], zones?: string[] }
 * Omitted / null lists mean "all".
 */
export function filterPool(pool, opts = {}) {
  const maps = opts.maps ? new Set(opts.maps) : null;
  const lighting = opts.lighting ? new Set(opts.lighting) : null;
  const zones = opts.zones ? new Set(opts.zones) : null;
  return pool.filter((c) => {
    if (maps && !maps.has(c.display)) return false;
    if (c.legacy && !opts.includeLegacy) return false;
    if (lighting && !lighting.has(c.entry.lighting)) return false;
    if (zones && !zones.has(c.entry.zoneAlternator)) return false;
    return true;
  });
}

export const entryKey = (e) =>
  JSON.stringify([e.map, e.experience, e.modifiers, e.lighting, e.zoneAlternator]);

/** Small seeded PRNG so a seed (and a share link) always gives the same rotation. */
export function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function shuffle(arr, rng) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

const choice = (arr, rng) => arr[Math.floor(rng() * arr.length)];

/** Balanced pick: least-used map first, never the same map twice in a row, no duplicates. */
export function pickEntries(pool, count, rng) {
  if (!pool.length) throw new Error("No combinations match those choices.");
  const byMap = new Map();
  for (const c of pool) {
    if (!byMap.has(c.display)) byMap.set(c.display, []);
    byMap.get(c.display).push(c);
  }
  const mapNames = [...byMap.keys()];
  const used = new Set();
  const uses = new Map(mapNames.map((m) => [m, 0]));
  const picks = [];
  let prev = null;

  for (let i = 0; i < count; i++) {
    let choices = mapNames.filter((m) => m !== prev);
    if (!choices.length) choices = mapNames;
    // A map that has used up its combinations steps aside while others still have fresh ones.
    const fresh = choices.filter((m) => byMap.get(m).some((c) => !used.has(entryKey(c.entry))));
    if (fresh.length) choices = fresh;
    const least = Math.min(...choices.map((m) => uses.get(m)));
    choices = shuffle(choices.filter((m) => uses.get(m) === least), rng);

    let chosen = null;
    for (const m of choices) {
      const candidates = byMap.get(m).filter((c) => !used.has(entryKey(c.entry)));
      if (candidates.length) { chosen = choice(candidates, rng); break; }
    }
    if (!chosen) chosen = choice(choices.flatMap((m) => byMap.get(m)), rng);

    picks.push(chosen);
    used.add(entryKey(chosen.entry));
    uses.set(chosen.display, uses.get(chosen.display) + 1);
    prev = chosen.display;
  }
  return picks;
}

export function buildRotation(name, picks, mode = "Ordered") {
  return {
    kind: "wardogs-rotation",
    name,
    mode,
    entries: picks.map((p) => Object.fromEntries(ENTRY_KEYS.map((k) => [k, structuredClone(p.entry[k])]))),
  };
}

export function slugify(name) {
  const s = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return s || "rotation";
}

export function defaultFilename(name) {
  const slug = slugify(name);
  return `${slug.startsWith("rotation") ? slug : "rotation-" + slug}.json`;
}

/** Same JSON layout as rotate.py (2-space indent, trailing newline). */
export const toJson = (rotation) => JSON.stringify(rotation, null, 2) + "\n";
