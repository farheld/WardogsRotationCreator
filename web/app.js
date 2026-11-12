import {
  buildPool, filterPool, pickEntries, maxCount, limitMessage, buildRotation, mulberry32, modifierNames,
  zoneShort, defaultFilename, toJson, rotationIssues, pickToken, pickFromToken, shuffleOrder,
} from "./rotation.js?v=6";

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
// The running order on screen: picks (pool items), whether it was edited by hand (edited),
// whether it differs from what the seed generates (custom, saved in share links), and the
// rotation/filename built from it.
let current = null; // { picks, edited, custom, rotation, filename }
let openEditor = null; // index of the row whose editor is open

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
  if (current?.custom) p.set("o", current.picks.map(pickToken).join(","));
  history.replaceState(null, "", `${location.pathname}?${p}`);
}

/** Every valid entry for the current modifiers, ignoring the lighting/zone/map filters. */
const fullPool = () => buildPool(catalog, [...state.modifiers]);

/** Running order saved in a share link ("o" param), if it is still valid. */
function readEditedOrder() {
  const o = new URLSearchParams(location.search).get("o");
  if (!o) return null;
  const pool = fullPool();
  const picks = o.split(",").map((t) => pickFromToken(pool, t));
  return picks.length && picks.every(Boolean) ? picks : null;
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

function clearOrder() {
  current = null;
  openEditor = null;
  $("order").replaceChildren();
  $("issues").replaceChildren();
  $("order-hint").hidden = true;
  $("summary").textContent = "";
  setActionsEnabled(false);
}

function regenerate({ keepSeed = false } = {}) {
  if (!keepSeed) state.seed = newSeed();
  $("notes").replaceChildren();
  clearOrder();
  writeUrl();

  const chosenMaps = allMaps().filter((d) => state.maps.has(d));
  const pool = filterPool(buildPool(catalog, [...state.modifiers]), {
    maps: chosenMaps, includeLegacy: state.legacy, lighting: [...state.lighting], zones: [...state.zones],
  });

  if (!chosenMaps.length) note("Select at least one map.", "error");
  else if (!state.lighting.size) note("Select at least one lighting option.", "error");
  else if (!pool.length) note("Nothing matches these choices. Select lighting and a zone that a chosen map supports.", "error");

  if (!pool.length) return;

  const missing = chosenMaps.filter((d) => !pool.some((c) => c.display === d));
  if (missing.length)
    note(`None of the selected lighting or zones are available on ${missing.join(" and ")}, ` +
         `so ${missing.length > 1 ? "they're" : "it's"} left out.`);
  const problem = limitMessage(pool, state.count);
  if (problem) {
    note(problem, "error");
    const limit = maxCount(pool);
    if (limit > 1 && Number.isFinite(limit)) {
      const fix = document.createElement("button");
      fix.type = "button";
      fix.className = "btn btn-quiet note-action";
      fix.textContent = `Use ${limit} maps`;
      fix.addEventListener("click", () => {
        state.count = limit;
        $("count").value = limit;
        regenerate();
      });
      $("notes").lastElementChild.append(fix);
    }
    return;
  }
  if (new Set(pool.map((c) => c.display)).size === 1 && state.count > pool.length)
    note(`With one map and ${pool.length} combinations, entries repeat after every ${pool.length} maps (never twice in a row).`);

  current = { picks: pickEntries(pool, state.count, mulberry32(state.seed)), edited: false, custom: false };
  renderOrder();
}

// ---------- Running order (view + manual edits) ----------
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** Rebuild the rotation from current.picks and redraw the list. */
function renderOrder({ focus } = {}) {
  const { picks } = current;
  current.rotation = buildRotation(state.name.trim() || `Rotation ${today()}`, picks);
  current.filename = defaultFilename(current.rotation.name);

  const mods = [...state.modifiers].map(humanize);
  $("summary").textContent =
    `${picks.length} ${picks.length === 1 ? "map" : "maps"}, ` +
    (mods.length ? `${mods.join(" + ")} on every map.` : "standard game mode.");

  // Warnings for hand edits that break the usual rules. They don't block the download.
  const issues = rotationIssues(picks);
  const flagged = new Set(issues.flatMap((i) => i.indices));
  const box = $("issues");
  box.replaceChildren();
  if (current.edited) {
    box.append(el("p", "info", "You've edited this running order. New rotation or changing a setting replaces it."));
  }
  issues.forEach((i) => box.append(el("p", "", i.text)));

  const tags = catalog.lightingTags || {};
  $("order").replaceChildren(...picks.map((p, i) => {
    const li = el("li");
    if (flagged.has(i)) li.classList.add("has-issue");

    const handle = el("button", "slot-handle");
    handle.type = "button";
    handle.setAttribute("aria-label", `Move map ${i + 1}, ${p.display}. Use the up and down arrow keys.`);
    handle.innerHTML = '<svg viewBox="0 0 12 18" aria-hidden="true"><g fill="currentColor"><circle cx="3" cy="3" r="1.6"/><circle cx="9" cy="3" r="1.6"/><circle cx="3" cy="9" r="1.6"/><circle cx="9" cy="9" r="1.6"/><circle cx="3" cy="15" r="1.6"/><circle cx="9" cy="15" r="1.6"/></g></svg>';
    handle.addEventListener("keydown", (e) => {
      const to = e.key === "ArrowUp" ? i - 1 : e.key === "ArrowDown" ? i + 1 : null;
      if (to === null) return;
      e.preventDefault();
      if (to < 0 || to >= picks.length) return;
      movePick(i, to);
      renderOrder({ focus: `[data-handle="${to}"]` });
    });
    handle.dataset.handle = i;

    const sky = el("i", "sky");
    sky.style.setProperty("--sky", skyFor(p.entry.lighting, tags[p.entry.lighting]));
    sky.setAttribute("aria-hidden", "true");

    const main = el("div", "slot-main");
    main.append(el("span", "slot-map", p.display));
    if (p.legacy) main.append(el("span", "slot-legacy", p.entry.experience));
    main.append(el("span", "slot-zone", `${zoneShort(p.entry.zoneAlternator)} zone`));

    const light = el("span", "slot-light", p.entry.lighting);

    const edit = el("button", "slot-edit", openEditor === i ? "Done" : "Edit");
    edit.type = "button";
    edit.setAttribute("aria-expanded", String(openEditor === i));
    edit.setAttribute("aria-label", `${openEditor === i ? "Close editor for" : "Edit"} map ${i + 1}, ${p.display}`);
    edit.dataset.edit = i;
    edit.addEventListener("click", () => {
      openEditor = openEditor === i ? null : i;
      renderOrder({ focus: openEditor === i ? `#slot-${i}-map` : `[data-edit="${i}"]` });
    });

    li.append(handle, sky, main, light, edit);
    if (openEditor === i) li.append(editorFor(i));
    return li;
  }));

  $("order-hint").hidden = false;
  setActionsEnabled(true);
  writeUrl();
  if (focus) document.querySelector(focus)?.focus();
}

function movePick(from, to) {
  const [moved] = current.picks.splice(from, 1);
  current.picks.splice(to, 0, moved);
  current.edited = current.custom = true;
  openEditor = null;
}

/** Inline editor: map, mode (if there's a choice), lighting and zone for one row. */
function editorFor(i) {
  const p = current.picks[i];
  const pool = fullPool();
  const box = el("div", "slot-editor");
  box.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { openEditor = null; renderOrder({ focus: `[data-edit="${i}"]` }); }
  });

  const select = (key, label, options, value, onChange) => {
    const wrap = el("label", "editor-field");
    wrap.append(el("span", "editor-label", label));
    const s = el("select");
    s.id = `slot-${i}-${key}`;
    for (const [v, text] of options) {
      const o = el("option", "", text);
      o.value = v;
      o.selected = v === value;
      s.append(o);
    }
    s.addEventListener("change", () => onChange(s.value));
    wrap.append(s);
    return wrap;
  };
  const uniq = (arr) => [...new Set(arr)];
  const forMap = (d) => pool.filter((c) => c.display === d);
  const forMode = (d, m) => forMap(d).filter((c) => c.modeName === m);

  const replace = (display, modeName, lighting, zone, key) => {
    const options = forMode(display, modeName);
    const next =
      options.find((c) => c.entry.lighting === lighting && c.entry.zoneAlternator === zone) ||
      options.find((c) => c.entry.lighting === lighting) ||
      options.find((c) => c.entry.zoneAlternator === zone) ||
      options[0];
    current.picks[i] = next;
    current.edited = current.custom = true;
    renderOrder({ focus: `#slot-${i}-${key}` });
  };

  const maps = uniq(pool.map((c) => c.display));
  box.append(select("map", "Map", maps.map((d) => [d, d]), p.display, (d) => {
    const modes = uniq(forMap(d).map((c) => c.modeName));
    const mode = modes.find((m) => !forMode(d, m)[0].legacy) || modes[0];
    const zones = forMode(d, mode).map((c) => c.entry.zoneAlternator);
    replace(d, mode, p.entry.lighting, zones.find((z) => zoneShort(z) === "Default") ?? zones[0], "map");
  }));

  const modes = uniq(forMap(p.display).map((c) => c.modeName));
  if (modes.length > 1) {
    box.append(select("mode", "Mode", modes.map((m) => {
      const c = forMode(p.display, m)[0];
      return [m, c.legacy ? `${c.entry.experience} (old spawns)` : c.entry.experience];
    }), p.modeName, (m) => replace(p.display, m, p.entry.lighting, p.entry.zoneAlternator, "mode")));
  }

  const options = forMode(p.display, p.modeName);
  box.append(select("lighting", "Lighting", uniq(options.map((c) => c.entry.lighting)).map((l) => [l, l]),
    p.entry.lighting, (l) => replace(p.display, p.modeName, l, p.entry.zoneAlternator, "lighting")));
  box.append(select("zone", "Zone", uniq(options.map((c) => c.entry.zoneAlternator)).map((z) => [z, zoneShort(z)]),
    p.entry.zoneAlternator, (z) => replace(p.display, p.modeName, p.entry.lighting, z, "zone")));
  return box;
}

// Drag and drop (mouse and touch) via SortableJS. If it can't load, the keyboard and the
// arrow keys on each handle still reorder the list.
async function enableDragging() {
  try {
    const { default: Sortable } = await import("https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/modular/sortable.esm.js");
    Sortable.create($("order"), {
      handle: ".slot-handle",
      animation: 150,
      forceFallback: true, // pointer-based dragging: same behaviour for mouse and touch
      fallbackTolerance: 3,
      ghostClass: "is-ghost",
      chosenClass: "is-chosen",
      onEnd: ({ oldIndex, newIndex }) => {
        if (!current || oldIndex === newIndex) return;
        movePick(oldIndex, newIndex);
        renderOrder();
      },
    });
  } catch {
    // Keyboard reordering still works.
  }
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
  $("shuffle").addEventListener("click", () => {
    if (!current) return;
    current.picks = shuffleOrder(current.picks, mulberry32(newSeed()));
    current.custom = true;
    openEditor = null;
    renderOrder();
    toast("Shuffled the order");
  });
  $("regenerate")?.addEventListener("click", () => regenerate()); // may be missing from a cached older page

  $("name").addEventListener("input", (e) => {
    state.name = e.target.value;
    if (current) renderOrder(); // renaming keeps the running order, including edits
    else writeUrl();
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
  enableDragging();
  const edited = readEditedOrder();
  if (edited) {
    state.count = edited.length;
    $("count").value = edited.length;
    current = { picks: edited, edited: false, custom: true };
    renderOrder();
  } else {
    regenerate({ keepSeed: true });
  }
}

start();
