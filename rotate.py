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
from collections import Counter
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
    """'ZoneAlternator.Bakurani.Farmland.Circle' -> 'Farmland.Circle'; '' -> 'Default (blank)'."""
    if not zone:
        return "Default (blank)"
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


def build_pool(catalog: dict) -> list[dict]:
    """Expand the catalog into every valid combination."""
    pool = []
    for display, m in catalog["maps"].items():
        for mode_name, mode in m["modes"].items():
            lighting = mode.get("lighting", m["lighting"])
            zones = mode.get("zones", m["zones"])
            for mods in mode["modifiers"]:
                for light in lighting:
                    for zone in zones:
                        pool.append({
                            "display": display,
                            "modeName": mode_name,
                            "legacy": bool(mode.get("legacy")),
                            "entry": {
                                "map": m["map"],
                                "experience": mode["experience"],
                                "modifiers": list(mods),
                                "lighting": light,
                                "zoneAlternator": zone,
                            },
                        })
    return pool


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

    if args.modifiers is None:
        modifier_sets = None
    else:
        modifier_sets = set()
        for spec in args.modifiers:
            parts = [] if spec.lower() == "none" else [p for p in spec.split("+") if p]
            modifier_sets.add(tuple(sorted(p.lower() for p in parts)))

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
        if modifier_sets is not None and tuple(sorted(m.lower() for m in e["modifiers"])) not in modifier_sets:
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

def pick_entries(pool: list[dict], count: int, rng: random.Random, allow_repeats: bool) -> list[dict]:
    """Balanced pick: least-used map first, never the same map back-to-back
    (when more than one map is available), no duplicate entries unless the pool runs out."""
    if not pool:
        raise RotationError("No combinations match those filters.")

    by_map: dict[str, list[dict]] = {}
    for c in pool:
        by_map.setdefault(c["display"], []).append(c)
    map_names = list(by_map)

    used_keys: set = set()
    map_uses: Counter = Counter()
    picks: list[dict] = []
    prev = None

    for _ in range(count):
        choices = [m for m in map_names if m != prev] or map_names
        least = min(map_uses[m] for m in choices)
        choices = [m for m in choices if map_uses[m] == least]
        rng.shuffle(choices)

        chosen = None
        for m in choices:
            candidates = by_map[m] if allow_repeats else \
                [c for c in by_map[m] if entry_key(c["entry"]) not in used_keys]
            if candidates:
                chosen = rng.choice(candidates)
                break
        if chosen is None:
            # Every unique combo used: fall back to repeats, still avoiding back-to-back maps.
            fallback = [c for m in choices for c in by_map[m]] or pool
            chosen = rng.choice(fallback)

        picks.append(chosen)
        used_keys.add(entry_key(chosen["entry"]))
        map_uses[chosen["display"]] += 1
        prev = chosen["display"]
    return picks


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

    valid = {entry_key(c["entry"]) for c in build_pool(catalog)} if catalog else None
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
        elif valid is not None and entry_key({**e, "zoneAlternator": normalize_zone(e, catalog)}) not in valid:
            errs.append(f"{where} is not a combination listed in the catalog: {e}")
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
    lines = []
    for i, e in enumerate(rotation["entries"], 1):
        mods = "+".join(e["modifiers"]) or "no modifiers"
        lines.append(f"{i:>3}. {internal_to_display.get(e['map'], e['map']):<10} "
                     f"{e['experience']:<18} {e['lighting']:<15} "
                     f"{zone_label(e['zoneAlternator']):<16} {mods}")
    return "\n".join(lines)


def list_catalog(catalog: dict) -> None:
    for display, m in catalog["maps"].items():
        print(f"{display}  (internal: {m['map']})")
        for mode_name, mode in m["modes"].items():
            mods = ", ".join("+".join(s) or "none" for s in mode["modifiers"])
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
    print(f"total combinations: {len(build_pool(catalog))}")


# --------------------------------------------------------------------------- CLI

def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Generate a Wardogs map rotation.")
    lst = dict(nargs="+", metavar="X")
    p.add_argument("--maps", **lst, help="Display or internal map names, e.g. Bakurani Ozeti")
    p.add_argument("--modes", **lst, help="Mode names (catalog key) or experience ids, e.g. KOTH")
    p.add_argument("--include-legacy", action="store_true",
                   help="Also use legacy modes (e.g. Bakurani_KOTH_01) alongside the current ones")
    p.add_argument("--modifiers", **lst,
                   help="Allowed modifier sets; join several with '+', use 'none' for no modifiers")
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
    p.add_argument("--allow-repeats", action="store_true", help="Allow identical entries to repeat")
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

    pool = filter_pool(build_pool(catalog), catalog, args)
    rng = random.Random(args.seed)
    try:
        picks = pick_entries(pool, args.count, rng, args.allow_repeats)
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
        maps=maps, modes=None, modifiers=None,
        lighting=[light_opts[k] for k in lights] if lights else None, exclude_lighting=None,
        weather=None, exclude_weather=None,
        zones=[zone_opts[k] for k in zones] if zones else None, exclude_zones=None,
        no_default_zone=False, default_zone_only=False,
        include_legacy=include_legacy, allow_repeats=False)
    return name, count, args


def interactive(catalog: dict) -> int:
    print("=" * 60)
    print(" Wardogs Rotation Creator")
    print(" Press Enter to accept the [default] shown for any question.")
    print("=" * 60)
    try:
        while True:
            name, count, args = _ask_settings(catalog)
            pool = filter_pool(build_pool(catalog), catalog, args)
            if not pool:
                print("\nNothing matches those choices. Let's try again.")
                continue
            wanted = args.maps or list(catalog["maps"])
            missing = [m for m in wanted if not any(c["display"] == m for c in pool)]
            if missing:
                print(f"\nNote: no zones were picked for {', '.join(missing)}, so "
                      f"{'it' if len(missing) == 1 else 'they'} won't appear in this rotation.")
            if count > len(pool):
                print(f"\nNote: your choices only allow {len(pool)} different combinations, "
                      f"so some of the {count} maps will repeat.")

            saved = False
            while True:
                picks = pick_entries(pool, count, random.Random(), False)
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
