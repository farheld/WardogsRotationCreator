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

// Rules (same as rotate.py):
// - Several maps: no entry is ever repeated, the same map never plays twice in a row, and maps
//   are spread as evenly as their number of combinations allows.
// - One map: entries may repeat (every combination is used before any repeats), but the same
//   entry never plays twice in a row.

function groupByMap(pool) {
  const byMap = new Map();
  for (const c of pool) {
    if (!byMap.has(c.display)) byMap.set(c.display, []);
    byMap.get(c.display).push(c);
  }
  return byMap;
}

/** Spread `count` as evenly as possible without going over each map's cap. */
function fillCounts(caps, count) {
  const counts = new Map([...caps.keys()].map((m) => [m, 0]));
  for (let i = 0; i < count; i++) {
    const open = [...caps.keys()].filter((m) => counts.get(m) < caps.get(m));
    if (!open.length) return null;
    const low = open.reduce((a, b) => (counts.get(b) < counts.get(a) ? b : a));
    counts.set(low, counts.get(low) + 1);
  }
  return counts;
}

/** Can these per-map counts be ordered without the same map twice in a row? */
function arrangeable(counts) {
  const values = [...counts.values()];
  const total = values.reduce((a, b) => a + b, 0);
  const top = Math.max(...values);
  return top <= total - top + 1;
}

/** Longest rotation the pool allows under the rules. Infinity = no limit (single map). */
export function maxCount(pool) {
  const byMap = groupByMap(pool);
  if (!byMap.size) return 0;
  if (byMap.size === 1) return pool.length > 1 ? Infinity : 1;
  const caps = new Map([...byMap].map(([m, cs]) => [m, cs.length]));
  let best = 0;
  for (let n = 1; n <= pool.length; n++) {
    const counts = fillCounts(caps, n);
    if (counts && arrangeable(counts)) best = n;
  }
  return best;
}

/** Explain why `count` is too many for this pool, or null if it's fine. */
export function limitMessage(pool, count) {
  const limit = maxCount(pool);
  if (count <= limit) return null;
  const byMap = groupByMap(pool);
  if (byMap.size === 1)
    return `${[...byMap.keys()][0]} has only one lighting/zone combination selected, so it would ` +
      "play the same entry twice in a row. Select more lighting or zones.";
  return `These choices allow at most ${limit} maps without repeating an entry or playing the ` +
    "same map twice in a row. Lower the number of maps, or select more maps, lighting or zones.";
}

export function pickEntries(pool, count, rng) {
  if (!pool.length) throw new Error("No combinations match those choices.");
  const problem = limitMessage(pool, count);
  if (problem) throw new Error(problem);

  const byMap = groupByMap(pool);
  if (byMap.size === 1) return pickSingleMap(pool, count, rng);

  // How many entries each map gets: as even as possible, with random tie-breaks.
  const caps = new Map([...byMap].map(([m, cs]) => [m, cs.length]));
  const counts = new Map([...caps.keys()].map((m) => [m, 0]));
  for (let i = 0; i < count; i++) {
    const open = [...caps.keys()].filter((m) => counts.get(m) < caps.get(m));
    const low = Math.min(...open.map((m) => counts.get(m)));
    const m = choice(open.filter((x) => counts.get(x) === low), rng);
    counts.set(m, counts.get(m) + 1);
  }

  // Order the maps: always take the map with the most left (never the previous one), which
  // guarantees no back-to-back maps whenever that is possible. Ties are broken randomly.
  const remaining = new Map(counts);
  const order = [];
  let prev = null;
  for (let i = 0; i < count; i++) {
    const options = [...remaining.keys()].filter((m) => remaining.get(m) > 0 && m !== prev);
    const top = Math.max(...options.map((m) => remaining.get(m)));
    prev = choice(options.filter((m) => remaining.get(m) === top), rng);
    remaining.set(prev, remaining.get(prev) - 1);
    order.push(prev);
  }

  // Give each slot a different random combination from its map.
  const decks = new Map([...byMap].map(([m, cs]) => [m, shuffle([...cs], rng).slice(0, counts.get(m))]));
  return order.map((m) => decks.get(m).pop());
}

/** Shuffled rounds of every combination: no repeats until all are used, never twice in a row. */
function pickSingleMap(pool, count, rng) {
  const picks = [];
  while (picks.length < count) {
    const deck = shuffle([...pool], rng);
    if (picks.length && deck.length > 1 && entryKey(deck[0].entry) === entryKey(picks.at(-1).entry))
      [deck[0], deck[deck.length - 1]] = [deck[deck.length - 1], deck[0]];
    picks.push(...deck);
  }
  return picks.slice(0, count);
}

/**
 * Shuffle the order of the existing entries without changing them.
 * Several maps: the same map never plays twice in a row. One map: the same entry never plays
 * twice in a row. If hand edits make that impossible, it gets as close as it can.
 */
export function shuffleOrder(picks, rng) {
  const singleMap = new Set(picks.map((p) => p.display)).size === 1;
  const keyOf = singleMap ? (p) => entryKey(p.entry) : (p) => p.display;
  const groups = new Map();
  for (const p of shuffle([...picks], rng)) {
    const k = keyOf(p);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(p);
  }
  const remaining = new Map([...groups].map(([k, v]) => [k, v.length]));
  const left = () => [...remaining.values()].reduce((a, b) => a + b, 0);

  // After placing `placed`, can the rest still be ordered with no key twice in a row?
  const stillPossible = (placed) => {
    const sum = left();
    if (!sum) return true;
    const max = Math.max(...remaining.values());
    const maxKeys = [...remaining].filter(([, v]) => v === max).map(([k]) => k);
    const rest = sum - max;
    return max <= (maxKeys.length === 1 && maxKeys[0] === placed ? rest : rest + 1);
  };

  const out = [];
  let prev = null;
  while (left()) {
    const open = [...remaining.keys()].filter((k) => remaining.get(k) > 0);
    const options = open.filter((k) => k !== prev);
    const safe = options.filter((k) => {
      remaining.set(k, remaining.get(k) - 1);
      const ok = stillPossible(k);
      remaining.set(k, remaining.get(k) + 1);
      return ok;
    });
    const k = choice(safe.length ? safe : options.length ? options : open, rng);
    remaining.set(k, remaining.get(k) - 1);
    out.push(groups.get(k).pop());
    prev = k;
  }
  return out;
}

/**
 * Rule problems in a running order (e.g. after manual edits).
 * Returns [{ indices: [i, j], text }] with 0-based indices; text uses 1-based positions.
 */
export function rotationIssues(picks) {
  const issues = [];
  const singleMap = new Set(picks.map((p) => p.display)).size === 1;
  for (let i = 1; i < picks.length; i++) {
    const a = picks[i - 1], b = picks[i];
    if (singleMap) {
      if (entryKey(a.entry) === entryKey(b.entry))
        issues.push({ indices: [i - 1, i], text: `Maps ${i} and ${i + 1} are the same entry back to back.` });
    } else if (a.display === b.display) {
      issues.push({ indices: [i - 1, i], text: `Maps ${i} and ${i + 1} are both ${b.display}.` });
    }
  }
  if (!singleMap) {
    const seen = new Map();
    picks.forEach((p, i) => {
      const k = entryKey(p.entry);
      if (seen.has(k)) issues.push({ indices: [seen.get(k), i], text: `Maps ${seen.get(k) + 1} and ${i + 1} are identical.` });
      else seen.set(k, i);
    });
  }
  return issues;
}

/** Short, readable id for one entry, used in share links: "Ozeti~KOTH~DayClear~River". */
export const pickToken = (p) =>
  [p.display, p.modeName, p.entry.lighting, zoneShort(p.entry.zoneAlternator)].join("~");

export const pickFromToken = (pool, token) => pool.find((c) => pickToken(c) === token) || null;

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
