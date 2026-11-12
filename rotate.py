#!/usr/bin/env python3
"""Generate Wardogs map rotations from data/catalog.json.

Output files match the bot's import/export format (schema/rotation.schema.json).
Run `python rotate.py --help` for options, `python rotate.py --list` to see the catalog.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CATALOG_PATH = ROOT / "data" / "catalog.json"
OUT_DIR = ROOT / "rotations"
ENTRY_KEYS = ["map", "experience", "modifiers", "lighting", "zoneAlternator"]
TOP_KEYS = ["kind", "name", "mode", "entries"]


class RotationError(Exception):
    pass


# --------------------------------------------------------------------------- catalog

def load_catalog(path: Path = CATALOG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def zone_label(zone: str) -> str:
    """'ZoneAlternator.Bakurani.Farmland.Circle' -> 'Farmland.Circle'; '' -> 'Default'."""
    if not zone:
        return "Default"
    parts = zone.split(".")
    return ".".join(parts[2:]) if len(parts) > 2 else zone


def is_default_zone(zone: str) -> bool:
    """A blank zone in bot exports is the same as the map's Default zone."""
    return zone == "" or zone_label(zone).lower().split(".")[0] == "default"


def normalize_zone(entry: dict, catalog: dict) -> str:
    """Map a blank zone to the map's explicit Default zone from the catalog."""
    if entry["zoneAlternator"]:
        return entry["zoneAlternator"]
    for m in catalog["maps"].values():
        if m["map"] == entry["map"]:
            for z in m["zones"]:
                if is_default_zone(z):
                    return z
    return ""


def build_pool(catalog: dict, modifiers=()) -> list[dict]:
    """Expand the catalog into every valid combination for one modifier choice.

    `modifiers` are modifier names (e.g. "InfantryOnly") applied to EVERY entry, so the
    game mode never changes between maps. Empty = standard game mode. Modes that don't
    support all the chosen modifiers are left out.
    """
    chosen = set(modifiers)
    pool = []
    for display, m in catalog["maps"].items():
        for mode_name, mode in m["modes"].items():
            available = mode.get("modifiers", {})
            if not chosen <= set(available):
                continue
            mod_ids = [mod_id for name, mod_id in available.items() if name in chosen]
            for light in mode.get("lighting", m["lighting"]):
                for zone in mode.get("zones", m["zones"]):
                    pool.append({
                        "display": display,
                        "modeName": mode_name,
                        "legacy": bool(mode.get("legacy")),
                        "entry": {
                            "map": m["map"],
                            "experience": mode["experience"],
                            "modifiers": list(mod_ids),
                            "lighting": light,
                            "zoneAlternator": zone,
                        },
                    })
    return pool


def modifier_names(catalog: dict, maps=None) -> list[str]:
    """All modifier names offered by the given maps (display names), in catalog order."""
    names = []
    for display, m in catalog["maps"].items():
        if maps and display not in maps:
            continue
        for mode in m["modes"].values():
            names.extend(n for n in mode.get("modifiers", {}) if n not in names)
    return names


def resolve_modifiers(catalog: dict, specs) -> list[str]:
    """Turn user input ('infantry', 'KOTH_Hardcore', 'none', ...) into modifier names."""
    known = {}
    for m in catalog["maps"].values():
        for mode in m["modes"].values():
            for name, mod_id in mode.get("modifiers", {}).items():
                known.setdefault(name, set()).add(mod_id.lower())
    out = []
    for spec in specs or []:
        s = spec.strip().lower()
        if s in ("none", "standard", "default"):
            continue
        matches = [n for n, ids in known.items() if s == n.lower() or s in ids] or \
                  [n for n in known if n.lower().startswith(s)]
        if len(matches) != 1:
            raise RotationError(f"Unknown modifier '{spec}'. Available: {', '.join(known)} (or 'none').")
        if matches[0] not in out:
            out.append(matches[0])
    return out


def entry_key(entry: dict) -> tuple:
    return (entry["map"], entry["experience"], tuple(entry["modifiers"]),
            entry["lighting"], entry["zoneAlternator"])


# --------------------------------------------------------------------------- filtering

def _norm(values):
    return {v.strip().lower() for v in values} if values else None


def filter_pool(pool: list[dict], catalog: dict, args) -> list[dict]:
    tags = {k: {t.lower() for t in v} for k, v in catalog.get("lightingTags", {}).items()}
    maps = _norm(args.maps)
    modes = _norm(args.modes)
    lighting = _norm(args.lighting)
    ex_lighting = _norm(args.exclude_lighting)
    weather = _norm(args.weather)
    ex_weather = _norm(args.exclude_weather)
    zones = _norm(args.zones)
    ex_zones = _norm(args.exclude_zones)

    def zone_match(zone: str, wanted: set) -> bool:
        if is_default_zone(zone) and ("default" in wanted or "none" in wanted):
            return True
        z = zone.lower()
        label = zone_label(zone).lower()          # e.g. "farmland.circle"
        short = label.split(".")[0]               # e.g. "farmland"
        return any(w in (z, label, short) for w in wanted)

    out = []
    for c in pool:
        e = c["entry"]
        light_tags = tags.get(e["lighting"], set())
        if maps and c["display"].lower() not in maps and e["map"].lower() not in maps:
            continue
        mode_named = bool(modes) and (c["modeName"].lower() in modes or e["experience"].lower() in modes)
        if modes and not mode_named:
            continue
        if c["legacy"] and not (args.include_legacy or mode_named):
            continue
        if lighting and e["lighting"].lower() not in lighting:
            continue
        if ex_lighting and e["lighting"].lower() in ex_lighting:
            continue
        if weather and not (light_tags & weather):
            continue
        if ex_weather and (light_tags & ex_weather):
            continue
        if zones and not zone_match(e["zoneAlternator"], zones):
            continue
        if ex_zones and zone_match(e["zoneAlternator"], ex_zones):
            continue
        if args.no_default_zone and is_default_zone(e["zoneAlternator"]):
            continue
        if args.default_zone_only and not is_default_zone(e["zoneAlternator"]):
            continue
        out.append(c)
    return out


# --------------------------------------------------------------------------- picking

# Rules (web/rotation.js follows the same ones):
# - Several maps: no entry is ever repeated, the same map never plays twice in a row, and maps
#   are spread as evenly as their number of combinations allows.
# - One map: entries may repeat (every combination is used before any repeats), but the same
#   entry never plays twice in a row.

def _group_by_map(pool: list[dict]) -> dict[str, list[dict]]:
    by_map: dict[str, list[dict]] = {}
    for c in pool:
        by_map.setdefault(c["display"], []).append(c)
    return by_map


def _fill_counts(caps: dict[str, int], count: int) -> dict[str, int] | None:
    """Spread `count` as evenly as possible without going over each map's cap."""
    counts = {m: 0 for m in caps}
    for _ in range(count):
        open_maps = [m for m in caps if counts[m] < caps[m]]
        if not open_maps:
            return None
        counts[min(open_maps, key=lambda m: counts[m])] += 1
    return counts


def _arrangeable(counts: dict[str, int]) -> bool:
    """Can these per-map counts be ordered without the same map twice in a row?"""
    total, top = sum(counts.values()), max(counts.values())
    return top <= total - top + 1


def max_count(pool: list[dict]) -> int | None:
    """Longest rotation the pool allows under the rules. None = no limit (single map)."""
    by_map = _group_by_map(pool)
    if not by_map:
        return 0
    if len(by_map) == 1:
        return None if len(pool) > 1 else 1
    caps = {m: len(cs) for m, cs in by_map.items()}
    best = 0
    for n in range(1, sum(caps.values()) + 1):
        counts = _fill_counts(caps, n)
        if counts and _arrangeable(counts):
            best = n
    return best


def limit_message(pool: list[dict], count: int) -> str | None:
    """Explain why `count` is too many for this pool, or None if it's fine."""
    limit = max_count(pool)
    if limit is None or count <= limit:
        return None
    by_map = _group_by_map(pool)
    if len(by_map) == 1:
        return (f"{next(iter(by_map))} has only one lighting/zone combination selected, so it would "
                f"play the same entry twice in a row. Select more lighting or zones.")
    return (f"These choices allow at most {limit} maps without repeating an entry or playing the "
            f"same map twice in a row. Lower the number of maps, or select more maps, lighting or zones.")


def pick_entries(pool: list[dict], count: int, rng: random.Random) -> list[dict]:
    if not pool:
        raise RotationError("No combinations match those filters.")
    problem = limit_message(pool, count)
    if problem:
        raise RotationError(problem)

    by_map = _group_by_map(pool)
    if len(by_map) == 1:
        return _pick_single_map(pool, count, rng)

    # How many entries each map gets: as even as possible, with random tie-breaks.
    caps = {m: len(cs) for m, cs in by_map.items()}
    counts = {m: 0 for m in caps}
    for _ in range(count):
        open_maps = [m for m in caps if counts[m] < caps[m]]
        low = min(counts[m] for m in open_maps)
        counts[rng.choice([m for m in open_maps if counts[m] == low])] += 1

    # Order the maps: always take the map with the most left (never the previous one), which
    # guarantees no back-to-back maps whenever that is possible. Ties are broken randomly.
    remaining = dict(counts)
    order, prev = [], None
    for _ in range(count):
        options = [m for m in remaining if remaining[m] > 0 and m != prev]
        top = max(remaining[m] for m in options)
        prev = rng.choice([m for m in options if remaining[m] == top])
        remaining[prev] -= 1
        order.append(prev)

    # Give each slot a different random combination from its map.
    decks = {m: rng.sample(cs, counts[m]) for m, cs in by_map.items()}
    return [decks[m].pop() for m in order]


def _pick_single_map(pool: list[dict], count: int, rng: random.Random) -> list[dict]:
    """Deal shuffled rounds of every combination, so nothing repeats until all are used and the
    same entry never plays twice in a row."""
    picks: list[dict] = []
    while len(picks) < count:
        deck = rng.sample(pool, len(pool))
        if picks and len(deck) > 1 and entry_key(deck[0]["entry"]) == entry_key(picks[-1]["entry"]):
            deck[0], deck[-1] = deck[-1], deck[0]
        picks.extend(deck)
    return picks[:count]


# --------------------------------------------------------------------------- validation

def validate_rotation(obj, catalog: dict | None = None) -> list[str]:
    """Mirror of schema/rotation.schema.json, plus optional catalog membership checks."""
    errs = []
    if not isinstance(obj, dict):
        return ["root must be an object"]
    if set(obj) != set(TOP_KEYS):
        errs.append(f"top-level keys must be exactly {TOP_KEYS}, got {list(obj)}")
    if obj.get("kind") != "wardogs-rotation":
        errs.append("kind must be 'wardogs-rotation'")
    for k in ("name", "mode"):
        if not isinstance(obj.get(k), str) or not obj.get(k):
            errs.append(f"{k} must be a non-empty string")
    entries = obj.get("entries")
    if not isinstance(entries, list) or not entries:
        errs.append("entries must be a non-empty array")
        return errs

    valid = mode_mods = None
    if catalog:
        valid = {entry_key(c["entry"]) for c in build_pool(catalog)}  # without modifiers
        mode_mods = {(m["map"], mode["experience"]): set(mode.get("modifiers", {}).values())
                     for m in catalog["maps"].values() for mode in m["modes"].values()}
    for i, e in enumerate(entries):
        where = f"entries[{i}]"
        if not isinstance(e, dict):
            errs.append(f"{where} must be an object")
            continue
        if set(e) != set(ENTRY_KEYS):
            errs.append(f"{where} keys must be exactly {ENTRY_KEYS}, got {list(e)}")
            continue
        for k in ("map", "experience", "lighting", "zoneAlternator"):
            if not isinstance(e[k], str):
                errs.append(f"{where}.{k} must be a string")
        if not isinstance(e["modifiers"], list) or not all(isinstance(m, str) for m in e["modifiers"]):
            errs.append(f"{where}.modifiers must be an array of strings")
        elif valid is not None:
            base = {**e, "modifiers": [], "zoneAlternator": normalize_zone(e, catalog)}
            if entry_key(base) not in valid:
                errs.append(f"{where} is not a combination listed in the catalog: {e}")
            else:
                allowed = mode_mods.get((e["map"], e["experience"]), set())
                bad = [m for m in e["modifiers"] if m not in allowed]
                if bad or len(set(e["modifiers"])) != len(e["modifiers"]):
                    errs.append(f"{where} has invalid or duplicate modifiers for {e['experience']}: {e['modifiers']}")
    return errs


# --------------------------------------------------------------------------- output

def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "rotation"


def build_rotation(name: str, mode: str, picks: list[dict]) -> dict:
    return {
        "kind": "wardogs-rotation",
        "name": name,
        "mode": mode,
        "entries": [{k: p["entry"][k] for k in ENTRY_KEYS} for p in picks],
    }


def write_rotation(rotation: dict, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rotation, f, indent=2, ensure_ascii=False)
        f.write("\n")


def summarize(rotation: dict, catalog: dict) -> str:
    internal_to_display = {m["map"]: d for d, m in catalog["maps"].items()}
    mod_sets = {tuple(e["modifiers"]) for e in rotation["entries"]}
    if len(mod_sets) == 1:
        mods = " + ".join(next(iter(mod_sets))) or "none (standard game mode)"
        lines = [f"Modifiers on every map: {mods}", ""]
    else:
        lines = ["Modifiers: differ between maps", ""]
    for i, e in enumerate(rotation["entries"], 1):
        extra = f"  {'+'.join(e['modifiers']) or 'none'}" if len(mod_sets) > 1 else ""
        lines.append(f"{i:>3}. {internal_to_display.get(e['map'], e['map']):<10} "
                     f"{e['experience']:<18} {e['lighting']:<15} "
                     f"{zone_label(e['zoneAlternator'])}{extra}")
    return "\n".join(lines)


def list_catalog(catalog: dict) -> None:
    for display, m in catalog["maps"].items():
        print(f"{display}  (internal: {m['map']})")
        for mode_name, mode in m["modes"].items():
            mods = ", ".join(f"{n} ({i})" for n, i in mode.get("modifiers", {}).items()) or "none"
            legacy = "  [legacy: only if requested]" if mode.get("legacy") else ""
            print(f"  mode {mode_name}: {mode['experience']}  modifiers: {mods}{legacy}")
            if "lighting" in mode:
                print(f"    lighting override: {', '.join(mode['lighting'])}")
            if "zones" in mode:
                print(f"    zones override: {', '.join(zone_label(z) for z in mode['zones'])}")
        print(f"  lighting: {', '.join(m['lighting'])}")
        print(f"  zones:    {', '.join(zone_label(z) for z in m['zones'])}")
    tags = sorted({t for v in catalog.get("lightingTags", {}).values() for t in v})
    print(f"weather/time tags: {', '.join(tags)}")
    print(f"combinations per modifier choice: {len(build_pool(catalog))} "
          "(modifiers are optional and apply to every map in a rotation)")


# --------------------------------------------------------------------------- CLI

def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Generate a Wardogs map rotation.")
    lst = dict(nargs="+", metavar="X")
    p.add_argument("--maps", **lst, help="Display or internal map names, e.g. Bakurani Ozeti")
    p.add_argument("--modes", **lst, help="Mode names (catalog key) or experience ids, e.g. KOTH")
    p.add_argument("--include-legacy", action="store_true",
                   help="Also use legacy modes (e.g. Bakurani_KOTH_01) alongside the current ones")
    p.add_argument("--modifiers", **lst,
                   help="Modifiers applied to EVERY map, e.g. InfantryOnly Hardcore. "
                        "Default: none (standard game mode)")
    p.add_argument("--lighting", **lst, help="Exact lighting presets to allow")
    p.add_argument("--exclude-lighting", **lst, help="Lighting presets to exclude")
    p.add_argument("--weather", **lst, help="Allow lighting with any of these tags, e.g. rain fog")
    p.add_argument("--exclude-weather", **lst, help="Exclude lighting with any of these tags")
    p.add_argument("--zones", **lst, help="Zone short names or full ids, e.g. Farmland Default")
    p.add_argument("--exclude-zones", **lst, help="Zones to exclude")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--no-default-zone", action="store_true", help="Never use the Default zone")
    g.add_argument("--default-zone-only", action="store_true", help="Only use the Default zone")
    p.add_argument("--count", type=int, default=10, help="Number of entries (default 10)")
    p.add_argument("--name", help="Rotation name shown in the bot")
    p.add_argument("--mode", default="Ordered", help="Rotation playback mode (default Ordered)")
    p.add_argument("--seed", type=int, help="Random seed for a reproducible rotation")
    p.add_argument("--out", type=Path, help="Output file (default rotations/rotation-<name>.json)")
    p.add_argument("--catalog", type=Path, default=CATALOG_PATH, help=argparse.SUPPRESS)
    p.add_argument("--list", action="store_true", help="Show everything in the catalog and exit")
    p.add_argument("--validate", type=Path, metavar="FILE", help="Validate an existing rotation file and exit")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    catalog = load_catalog(args.catalog)

    if args.list:
        list_catalog(catalog)
        return 0

    if args.validate:
        with open(args.validate, encoding="utf-8") as f:
            obj = json.load(f)
        errs = validate_rotation(obj, catalog)
        if errs:
            print("INVALID:\n  " + "\n  ".join(errs))
            return 1
        print(f"OK: {args.validate} ({len(obj['entries'])} entries)")
        return 0

    if args.count < 1:
        print("error: --count must be at least 1", file=sys.stderr)
        return 2

    rng = random.Random(args.seed)
    try:
        mods = resolve_modifiers(catalog, args.modifiers)
        pool = filter_pool(build_pool(catalog, mods), catalog, args)
        picks = pick_entries(pool, args.count, rng)
    except RotationError as e:
        print(f"error: {e} Run with --list to see what's available.", file=sys.stderr)
        return 1

    name = args.name or f"Rotation {_dt.date.today().isoformat()}"
    rotation = build_rotation(name, args.mode, picks)
    errs = validate_rotation(rotation, catalog)
    if errs:  # should never happen; guards against catalog/format drift
        print("internal error, generated rotation failed validation:\n  " + "\n  ".join(errs), file=sys.stderr)
        return 3

    out = args.out or default_out(name)
    write_rotation(rotation, out)
    unique = len({entry_key(p["entry"]) for p in picks})
    print(summarize(rotation, catalog))
    print(f"\nWrote {out}  ({len(picks)} entries, {unique} unique, pool of {len(pool)} combinations)")
    return 0


def default_out(name: str) -> Path:
    slug = slugify(name)
    return OUT_DIR / f"{slug if slug.startswith('rotation') else 'rotation-' + slug}.json"


# --------------------------------------------------------------------------- interactive

def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    return input(f"{prompt}{suffix}: ").strip() or default


def _ask_yes(prompt: str, default: bool = False) -> bool:
    ans = input(f"{prompt} (y/n) [{'y' if default else 'n'}]: ").strip().lower()
    return default if not ans else ans.startswith("y")


def _ask_int(prompt: str, default: int) -> int:
    while True:
        ans = _ask(prompt, str(default))
        if ans.isdigit() and int(ans) >= 1:
            return int(ans)
        print("   Please enter a whole number of 1 or more.")


def _ask_pick(prompt: str, options: list[str], blank: str) -> list[str] | None:
    """Numbered multi-select. Returns the chosen options, or None if left blank."""
    for i, o in enumerate(options, 1):
        print(f"   {i:>2}. {o}")
    while True:
        ans = input(f"{prompt} - numbers separated by commas, Enter for {blank}: ").strip()
        if not ans:
            return None
        try:
            idx = [int(x) for x in re.split(r"[,\s]+", ans) if x]
        except ValueError:
            idx = []
        if idx and all(1 <= i <= len(options) for i in idx):
            return [options[i - 1] for i in dict.fromkeys(idx)]
        print(f"   Please enter numbers between 1 and {len(options)}, e.g. 1,3")


def _ask_settings(catalog: dict) -> tuple[str, int, argparse.Namespace]:
    print()
    name = _ask("Rotation name", f"Rotation {_dt.date.today().isoformat()}")
    count = _ask_int("Number of maps in the rotation", 10)

    print("\nMaps:")
    all_maps = list(catalog["maps"])
    maps = _ask_pick("Maps to include", all_maps, "all maps")
    chosen_maps = maps or all_maps

    legacy = [mode["experience"] for d in chosen_maps
              for mode in catalog["maps"][d]["modes"].values() if mode.get("legacy")]
    include_legacy = bool(legacy) and _ask_yes(
        f"\nAlso use legacy modes ({', '.join(legacy)})?", False)

    print("\nGame mode modifiers (applied to every map in the rotation):")
    mods = _ask_pick("Modifiers to use", modifier_names(catalog, chosen_maps),
                     "none (standard game mode)")

    tags = catalog.get("lightingTags", {})
    presets = list(dict.fromkeys(l for d in chosen_maps for l in catalog["maps"][d]["lighting"]))
    light_opts = {f"{p:<15} ({', '.join(tags.get(p, []))})" if tags.get(p) else p: p for p in presets}
    print("\nLighting / weather:")
    lights = _ask_pick("Lighting to use", list(light_opts), "all")

    zone_opts = {f"{d}: {zone_label(z).split('.')[0]}": z
                 for d in chosen_maps for z in catalog["maps"][d]["zones"]}
    print("\nZones:")
    zones = _ask_pick("Zones to use", list(zone_opts), "all")

    args = argparse.Namespace(
        maps=maps, modes=None, modifiers=mods or [],
        lighting=[light_opts[k] for k in lights] if lights else None, exclude_lighting=None,
        weather=None, exclude_weather=None,
        zones=[zone_opts[k] for k in zones] if zones else None, exclude_zones=None,
        no_default_zone=False, default_zone_only=False,
        include_legacy=include_legacy)
    return name, count, args


def interactive(catalog: dict) -> int:
    print("=" * 60)
    print(" Wardogs Rotation Creator")
    print(" Press Enter to accept the [default] shown for any question.")
    print("=" * 60)
    try:
        while True:
            name, count, args = _ask_settings(catalog)
            pool = filter_pool(build_pool(catalog, args.modifiers), catalog, args)
            if not pool:
                print("\nNothing matches those choices. Let's try again.")
                continue
            wanted = args.maps or list(catalog["maps"])
            missing = [m for m in wanted if not any(c["display"] == m for c in pool)]
            if missing:
                print(f"\nNote: none of the chosen lighting or zones are available on "
                      f"{' and '.join(missing)}, so {'it' if len(missing) == 1 else 'they'} "
                      f"won't appear in this rotation.")
            problem = limit_message(pool, count)
            if problem:
                print(f"\n{problem}")
                limit = max_count(pool)
                if limit and limit > 1 and _ask_yes(f"Use {limit} maps instead?", True):
                    count = limit
                else:
                    print("Let's try again.")
                    continue
            elif len({c['display'] for c in pool}) == 1 and count > len(pool):
                print(f"\nNote: with one map and {len(pool)} combinations, entries repeat after "
                      f"every {len(pool)} maps (never twice in a row).")

            saved = False
            while True:
                picks = pick_entries(pool, count, random.Random())
                rotation = build_rotation(name, "Ordered", picks)
                print(f"\n{name}  ({count} maps, picked from {len(pool)} combinations)\n")
                print(summarize(rotation, catalog))
                choice = input("\n[S]ave  [R]eroll  [C]hange settings  [Q]uit: ").strip().lower()[:1]
                if choice == "r":
                    continue
                if choice == "c":
                    break
                if choice == "q":
                    return 0
                if choice in ("s", ""):
                    out = default_out(name)
                    if out.exists() and not _ask_yes(f"{out.name} already exists. Overwrite?", False):
                        name = _ask("New rotation name", name)
                        rotation["name"] = name
                        out = default_out(name)
                    write_rotation(rotation, out)
                    print(f"\nSaved: {out}")
                    saved = True
                    break
                print("   Please type S, R, C or Q.")

            if saved and not _ask_yes("\nMake another rotation?", False):
                return 0
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 0


def run_interactive() -> int:
    try:
        catalog = load_catalog()
    except FileNotFoundError:
        print(f"Could not find {CATALOG_PATH}. Keep the 'data' folder next to rotate.py.")
        code = 1
    else:
        code = interactive(catalog)
    try:
        input("\nPress Enter to close...")
    except (KeyboardInterrupt, EOFError):
        pass
    return code


if __name__ == "__main__":
    # No arguments (e.g. double-clicked) -> interactive menu; any flags -> command-line mode.
    if len(sys.argv) == 1 or sys.argv[1:] in (["-i"], ["--interactive"]):
        sys.exit(run_interactive())
    sys.exit(main())
