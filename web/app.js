import {
  buildPool, filterPool, pickEntries, buildRotation, mulberry32, modifierNames,
  zoneShort, defaultFilename, toJson,
} from "./rotation.js";

const $ = (id) => document.getElementById(id);

// Sky swatch per lighting preset. Unknown presets fall back to a look based on their tags.
const SKIES = {
  DayStartClear: "linear-gradient(#3b4a78, #e98b6b 62%, #f6d29b)",
  DayEarlyClear: "linear-gradient(#8fbfe6, #f3e2b5)",
  DayEarlyFog: "linear-gradient(#b9c1c2, #e7e9e4)",
  DayClear: "linear-gradient(#3f8fd2, #bfe0f5)",
  DayLateClear: "linear-gradient(#6aa6d6, #f2c873)",
  DayLateGray: "linear-gradient(#7d878c, #b9bfc0)",
  DayLateGrayFog: "linear-gradient(#949c9e, #d9dcd8)",
  DayLateRain: "repeating-linear-gradient(105deg, transparent 0 5px, rgba(220,230,240,.35) 5px 6px), linear-gradient(#3f4a55, #76828c)",
  DayEndClear: "linear-gradient(#2d3561, #c05c7e 58%, #f3a65a)",
};
function skyFor(preset, tags = []) {
  if (SKIES[preset]) return SKIES[preset];
  if (tags.includes("rain")) return SKIES.DayLateRain;
  if (tags.includes("fog")) return SKIES.DayEarlyFog;
  if (tags.includes("overcast")) return SKIES.DayLateGray;
  if (tags.includes("dusk")) return SKIES.DayEndClear;
  if (tags.includes("dawn")) return SKIES.DayStartClear;
  return SKIES.DayClear;
}

// "InfantryOnly" -> "Infantry only"
const humanize = (s) => s.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/ (\w)/g, (_, c) => " " + c.toLowerCase());

let catalog;
const state = {
  name: "", count: 10, maps: new Set(), modifiers: new Set(), legacy: false,
  lighting: new Set(), zones: new Set(), seed: 0,
};
let current = null; // { rotation, filename }

const today = () => new Date().toISOString().slice(0, 10);
const newSeed = () => Math.floor(Math.random() * 2 ** 31);
const allMaps = () => Object.keys(catalog.maps);
const allLighting = () => [...new Set(allMaps().flatMap((d) => catalog.maps[d].lighting))];
const allZones = () => allMaps().flatMap((d) => catalog.maps[d].zones);
const zoneToken = (zone) => `${Object.keys(catalog.maps).find((d) => catalog.maps[d].zones.includes(zone))}.${zoneShort(zone)}`;

// ---------- URL <-> state ----------
function readUrl() {
  const p = new URLSearchParams(location.search);
  const list = (k) => (p.get(k) ? p.get(k).split(",").filter(Boolean) : null);
  state.name = p.get("n") || `Rotation ${today()}`;
  const c = parseInt(p.get("c"), 10);
  state.count = c >= 1 && c <= 100 ? c : 10;
  state.maps = new Set((list("m") || allMaps()).filter((m) => m in catalog.maps));
  state.modifiers = new Set((list("mod") || []).filter((m) => modifierNames(catalog).includes(m)));
  state.legacy = p.get("legacy") === "1";
  state.lighting = new Set((list("l") || allLighting()).filter((l) => allLighting().includes(l)));
  const tokens = list("z");
  state.zones = new Set(tokens ? allZones().filter((z) => tokens.includes(zoneToken(z))) : allZones());
  const s = parseInt(p.get("s"), 10);
  state.seed = Number.isFinite(s) ? s : newSeed();
}

function writeUrl() {
  const p = new URLSearchParams();
  const same = (set, all) => set.size === all.length && all.every((x) => set.has(x));
  if (state.name !== `Rotation ${today()}`) p.set("n", state.name);
  if (state.count !== 10) p.set("c", state.count);
  if (!same(state.maps, allMaps())) p.set("m", [...state.maps].join(","));
  if (state.modifiers.size) p.set("mod", [...state.modifiers].join(","));
  if (state.legacy) p.set("legacy", "1");
  if (!same(state.lighting, allLighting())) p.set("l", [...state.lighting].join(","));
  if (!same(state.zones, allZones())) p.set("z", [...state.zones].map(zoneToken).join(","));
  p.set("s", state.seed);
  history.replaceState(null, "", `${location.pathname}?${p}`);
}

// ---------- Controls ----------
function chip(value, label, checked, onChange, { sky } = {}) {
  const wrap = document.createElement("label");
  wrap.className = "chip";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.value = value;
  input.checked = checked;
  input.addEventListener("change", () => onChange(input.checked));
  const span = document.createElement("span");
  if (sky) {
    const s = document.createElement("i");
    s.className = "sky";
    s.style.setProperty("--sky", sky);
    s.setAttribute("aria-hidden", "true");
    span.append(s);
  }
  span.append(label);
  wrap.append(input, span);
  return wrap;
}

function toggleSet(set, value, on) { on ? set.add(value) : set.delete(value); }

function addGroupToggle(group, getAll, set) {
  const legend = document.querySelector(`[data-group="${group}"] legend`);
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "group-toggle";
  legend.append(btn);
  const refresh = () => {
    const all = getAll();
    const full = all.every((v) => set().has(v));
    btn.textContent = full ? "Clear" : "Select all";
  };
  btn.addEventListener("click", () => {
    const all = getAll();
    const full = all.every((v) => set().has(v));
    all.forEach((v) => (full ? set().delete(v) : set().add(v)));
    renderControls();
    regenerate();
  });
  return refresh;
}

let refreshToggles = [];

function renderControls() {
  const maps = $("maps");
  maps.replaceChildren(...allMaps().map((d) =>
    chip(d, d, state.maps.has(d), (on) => { toggleSet(state.maps, d, on); renderControls(); regenerate(); })));

  const chosenMaps = allMaps().filter((d) => state.maps.has(d));
  const mods = modifierNames(catalog, chosenMaps);
  $("modifiers").replaceChildren(...mods.map((m) =>
    chip(m, humanize(m), state.modifiers.has(m), (on) => { toggleSet(state.modifiers, m, on); regenerate(); })));

  const legacy = chosenMaps.flatMap((d) => Object.values(catalog.maps[d].modes).filter((x) => x.legacy).map((x) => x.experience));
  $("legacy-wrap").hidden = legacy.length === 0;
  $("legacy-label").textContent = `Include ${legacy.join(", ")} (old spawns)`;
  $("legacy").checked = state.legacy;

  const tags = catalog.lightingTags || {};
  $("lighting").replaceChildren(...allLighting().map((l) =>
    chip(l, l, state.lighting.has(l), (on) => { toggleSet(state.lighting, l, on); refreshAll(); regenerate(); },
      { sky: skyFor(l, tags[l]) })));

  $("zones").replaceChildren(...chosenMaps.map((d) => {
    const box = document.createElement("div");
    box.className = "zone-map";
    const h = document.createElement("h3");
    h.textContent = d;
    const row = document.createElement("div");
    row.className = "chips";
    row.append(...catalog.maps[d].zones.map((z) =>
      chip(z, zoneShort(z), state.zones.has(z), (on) => { toggleSet(state.zones, z, on); refreshAll(); regenerate(); })));
    box.append(h, row);
    return box;
  }));
  refreshAll();
}
const refreshAll = () => refreshToggles.forEach((f) => f());

// ---------- Generate + render ----------
function note(text, cls = "") {
  const p = document.createElement("p");
  if (cls) p.className = cls;
  p.textContent = text;
  $("notes").append(p);
}

function regenerate({ keepSeed = false } = {}) {
  if (!keepSeed) state.seed = newSeed();
  writeUrl();
  $("notes").replaceChildren();
  $("order").replaceChildren();
  current = null;

  const chosenMaps = allMaps().filter((d) => state.maps.has(d));
  const pool = filterPool(buildPool(catalog, [...state.modifiers]), {
    maps: chosenMaps, includeLegacy: state.legacy, lighting: [...state.lighting], zones: [...state.zones],
  });

  if (!chosenMaps.length) note("Select at least one map.", "error");
  else if (!state.lighting.size) note("Select at least one lighting option.", "error");
  else if (!pool.length) note("Nothing matches these choices. Select lighting and a zone that a chosen map supports.", "error");

  if (!pool.length) {
    $("summary").textContent = "";
    setActionsEnabled(false);
    return;
  }

  const missing = chosenMaps.filter((d) => !pool.some((c) => c.display === d));
  if (missing.length)
    note(`None of the selected lighting or zones are available on ${missing.join(" and ")}, ` +
         `so ${missing.length > 1 ? "they're" : "it's"} left out.`);
  if (state.count > pool.length)
    note(`These choices allow only ${pool.length} different combinations, so some of the ${state.count} maps repeat.`);

  const picks = pickEntries(pool, state.count, mulberry32(state.seed));
  const rotation = buildRotation(state.name.trim() || `Rotation ${today()}`, picks);
  current = { rotation, filename: defaultFilename(rotation.name) };

  const mods = [...state.modifiers].map(humanize);
  $("summary").textContent =
    `${state.count} ${state.count === 1 ? "map" : "maps"}, ` +
    (mods.length ? `${mods.join(" + ")} on every map.` : "standard game mode.");

  const tags = catalog.lightingTags || {};
  $("order").replaceChildren(...picks.map((p) => {
    const li = document.createElement("li");
    const sky = document.createElement("i");
    sky.className = "sky";
    sky.style.setProperty("--sky", skyFor(p.entry.lighting, tags[p.entry.lighting]));
    sky.setAttribute("aria-hidden", "true");
    const main = document.createElement("div");
    const name = document.createElement("span");
    name.className = "slot-map";
    name.textContent = p.display;
    main.append(name);
    if (p.legacy) {
      const lg = document.createElement("span");
      lg.className = "slot-legacy";
      lg.textContent = p.entry.experience;
      main.append(lg);
    }
    const zone = document.createElement("span");
    zone.className = "slot-zone";
    zone.textContent = `${zoneShort(p.entry.zoneAlternator)} zone`;
    main.append(zone);
    const light = document.createElement("span");
    light.className = "slot-light";
    light.textContent = p.entry.lighting;
    li.append(sky, main, light);
    return li;
  }));
  setActionsEnabled(true);
}

function setActionsEnabled(on) {
  ["download", "copy-json", "copy-link", "shuffle"].forEach((id) => ($(id).disabled = !on));
}

// ---------- Actions ----------
let toastTimer;
function toast(text) {
  $("toast").textContent = text;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => ($("toast").textContent = ""), 2500);
}

async function copy(text, done) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.append(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
  toast(done);
}

function wireActions() {
  $("download").addEventListener("click", () => {
    if (!current) return;
    const blob = new Blob([toJson(current.rotation)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = current.filename;
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    toast(`Downloaded ${current.filename}`);
  });
  $("copy-json").addEventListener("click", () => current && copy(toJson(current.rotation), "Copied JSON"));
  $("copy-link").addEventListener("click", () => copy(location.href, "Copied share link"));
  $("shuffle").addEventListener("click", () => regenerate());

  $("name").addEventListener("input", (e) => {
    state.name = e.target.value;
    regenerate({ keepSeed: true });
  });
  $("count").addEventListener("input", (e) => {
    const n = parseInt(e.target.value, 10);
    if (n >= 1 && n <= 100) { state.count = n; regenerate(); }
  });
  $("legacy").addEventListener("change", (e) => { state.legacy = e.target.checked; regenerate(); });
}

// ---------- Start ----------
async function start() {
  try {
    const res = await fetch("data/catalog.json", { cache: "no-cache" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    catalog = await res.json();
  } catch (err) {
    note(`Couldn't load the map list (data/catalog.json): ${err.message}. ` +
         "If you opened this file directly, run a local web server instead, e.g. python -m http.server.", "error");
    setActionsEnabled(false);
    return;
  }
  readUrl();
  $("name").value = state.name;
  $("count").value = state.count;
  refreshToggles = [
    addGroupToggle("maps", allMaps, () => state.maps),
    addGroupToggle("lighting", allLighting, () => state.lighting),
    addGroupToggle("zones", () => allZones().filter((z) => allMaps().some((d) => state.maps.has(d) && catalog.maps[d].zones.includes(z))), () => state.zones),
  ];
  renderControls();
  wireActions();
  regenerate({ keepSeed: true });
}

start();
