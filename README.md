# Wardogs Rotation Creator

Generate random map rotations for a **WARDOGS** server, ready to import into the
[WarDogs Server Commands](https://wardogsbot.com/) dashboard (**Dashboard → Rotation**).

Pick how many maps you want, which maps, lighting/weather and zones. The tool builds a
balanced rotation: the same map never plays twice in a row, and entries only repeat in
single-map rotations (see [Repeat rules](#repeat-rules)). It saves the rotation as a JSON file in the exact format the dashboard exports, so you can import it
as-is.

> This is a community tool. It isn't affiliated with the WARDOGS developers or with
> wardogsbot.com. The file format follows rotations exported from the wardogsbot.com dashboard.

## Use it online

**[farheld.github.io/WardogsRotationCreator](https://farheld.github.io/WardogsRotationCreator/)**
is free, needs no install, and runs entirely in your browser.

1. Pick your maps, game mode, lighting and zones. Everything is selected by default except the
   modifiers, which default to the standard game mode.
2. Use **New rotation** to pick a fresh set of entries, and **Shuffle order** to rearrange the
   current entries without changing them. Neither puts the same map twice in a row.
3. Fine-tune it by hand if you want:
   - **Reorder:** drag a row by its handle (⠿). With the keyboard, focus the handle and use the
     up and down arrow keys.
   - **Change an entry:** select **Edit** on a row to pick its map, lighting and zone (and mode,
     where a map has more than one). The options are everything that map supports, even if you
     filtered it out above.
   - The page warns, but doesn't stop you, if an edit puts the same map twice in a row or repeats
     an entry. **Shuffle order** keeps your edited entries; **New rotation** or changing a setting
     replaces them.
4. Select **Download rotation**, then import the file in the dashboard under **Rotation**.

**Copy share link** gives a link that opens the exact same rotation and settings, including
your edits, which is handy for sharing in Discord.

## Use it on your computer

### Requirements

- Python 3.9 or newer ([python.org](https://www.python.org/downloads/)). On Windows, tick
  **"Add python.exe to PATH"** during setup.
- Nothing else. The tool only uses Python's standard library.

### Quick start

1. Download this repository (**Code → Download ZIP**) and unzip it, or `git clone` it.
2. Start the tool:
   - **Windows:** double-click `Rotation Creator.bat`
   - **Any OS:** `python rotate.py`
3. Answer the prompts. Press Enter to accept the default in `[brackets]`. For lists, Enter means
   *all*, or type numbers (e.g. `1,3`) to use only those.
4. Choose **[S]ave**. The file is written to `rotations/`.
5. In the wardogsbot.com dashboard, open **Rotation** and import the saved JSON file.

```
Rotation name [Rotation 2026-11-10]: Night Ops
Number of maps in the rotation [10]: 12

Maps:
    1. Zestafona
    2. Ozeti
    3. Bakurani
Maps to include - numbers separated by commas, Enter for all maps:
...
[S]ave  [R]eroll  [C]hange settings  [Q]uit:
```

## Maps and options

| Map | Internal name | Mode | Zones |
|---|---|---|---|
| Zestafona | `NorthAmerica` | `Detroit_KOTH_01` | Default, Houses, SmallFactory, WaterTreatment |
| Ozeti | `Europe` | `Madrid_KOTH_01` | Default, Church, Farmland, River |
| Bakurani | `Kavkazi` | `Bakurani_KOTH_02` (`Bakurani_KOTH_01` legacy, opt-in) | Default, Farmland, Lumberyard |
| Sabatulo | `Russia` | `Moscow_KOTH_01` | Default only |

Lighting presets and the maps that allow them:

| Lighting | Tags | Maps |
|---|---|---|
| `DayStartClear` | dawn, clear | All except Sabatulo |
| `DayEarlyClear` | morning, clear | All except Sabatulo |
| `DayEarlyFog` | morning, fog | All except Sabatulo |
| `DayClear` | midday, clear | All |
| `DayLateClear` | afternoon, clear | All |
| `DayLateGray` | afternoon, overcast | All |
| `DayLateGrayFog` | afternoon, overcast, fog | All except Sabatulo |
| `DayLateRain` | afternoon, rain | All |
| `DayEndClear` | dusk, clear | All except Sabatulo |

`Bakurani_KOTH_01` (the old spawns) is never picked unless you ask for it.

### Repeat rules

- **Several maps:** no entry is ever repeated, and the same map never plays twice in a row. Maps
  are spread as evenly as their number of combinations allows. If you ask for more maps than
  that allows, the tool tells you the maximum and offers to use it. For example, Sabatulo has only
  4 lighting/zone combinations, so Sabatulo + Ozeti allows at most 9 maps: 4 Sabatulo entries
  with Ozeti between and around them.
- **One map:** entries can repeat, which lets you build, for example, a 10-map rotation of a
  single map. Every combination is used before any repeats, and the same entry never plays twice
  in a row.

### Modifiers

By default, rotations use the **standard game mode** (no modifiers). You can add any combination
of these modifiers. Whatever you choose applies to **every map in the rotation**, so the game mode
never changes between maps.

| Modifier | Id | What it does |
|---|---|---|
| InfantryOnly | `KOTH_InfantryOnly` | Infantry only |
| Hardcore | `KOTH_Hardcore` | Hardcore rules |
| LimitedGear | `KOTH_LimitedGear` | Limits the vendor to a fixed item list, and turns off some stationary weapons and the hot-zone magnet buildable |

### Server allow lists (Season 03)

Your server skips any rotation entry whose map, game mode or modifier isn't on its allow lists.
The lists live in your hosting provider's patch `Game.ini`; they can't be set in `server.ini`.
To use Sabatulo and Limited Gear, make sure your provider's `Game.ini` includes:

```ini
[/Script/WDGame.WDServerMapRotationSettings]
+AllowedMaps=Russia
+AllowedExperiences=Moscow_KOTH_01
+AllowedExperiences=KOTH_LimitedGear
```

## Command-line mode

Passing any option skips the prompts, which is handy for scripting:

```bash
python rotate.py --count 10                        # all maps, balanced, no back-to-back repeats
python rotate.py --name "Night Ops" --count 12
python rotate.py --maps Bakurani                   # single map
python rotate.py --modifiers InfantryOnly          # infantry only on every map
python rotate.py --modifiers InfantryOnly LimitedGear  # stack modifiers on every map
python rotate.py --weather rain fog                # only lighting tagged rain or fog
python rotate.py --exclude-weather fog
python rotate.py --lighting DayClear DayLateRain   # exact lighting presets
python rotate.py --zones Farmland Church Default
python rotate.py --no-default-zone
python rotate.py --include-legacy                  # also allow Bakurani_KOTH_01
python rotate.py --seed 42                         # same seed = same rotation
python rotate.py --list                            # show everything in the catalog
python rotate.py --validate path/to/rotation.json  # check a file against the format and catalog
```

Map names can be display names or internal names, and filters ignore case. Run
`python rotate.py --help` for every option.

## Project layout

| Path | Purpose |
|---|---|
| `index.html`, `web/` | The website (GitHub Pages). `web/rotation.js` holds the generation logic |
| `rotate.py` | The command-line generator: interactive prompts and options |
| `data/catalog.json` | Every valid map / mode / modifier / lighting / zone option |
| `Rotation Creator.bat` | Windows double-click launcher |
| `rotations/` | Your generated rotations (git-ignored) |
| `schema/rotation.schema.json` | JSON Schema for the dashboard's rotation import/export format |
| `schema/catalog.schema.json` | JSON Schema for `data/catalog.json` |
| `examples/` | Dashboard exports, used as reference and test fixtures |
| `tests/` | Unit tests |

To run the command-line version, you only need `rotate.py` and `data/catalog.json`, kept in the
same folder layout. Both the website and `rotate.py` read the same `data/catalog.json`, and they
follow the same rules.

## Rotation file format

```json
{
  "kind": "wardogs-rotation",
  "name": "Night Ops",
  "mode": "Ordered",
  "entries": [
    {
      "map": "Kavkazi",
      "experience": "Bakurani_KOTH_02",
      "modifiers": ["KOTH_InfantryOnly"],
      "lighting": "DayLateRain",
      "zoneAlternator": "ZoneAlternator.Bakurani.Farmland.Circle"
    }
  ]
}
```

A blank `zoneAlternator` (`""`) in a dashboard export means the map's Default zone. This tool
always writes the explicit Default zone instead.

## Updating the catalog

When maps, lighting or zones are added to the game, edit `data/catalog.json`:

- **Lighting:** add the preset to each map's `lighting` list, and add its tags under
  `lightingTags`.
- **Zone:** add the full id (e.g. `ZoneAlternator.Ozeti.Market.Circle`) to the map's `zones`.
- **Modifier:** add `"Name": "ModifierId"` to each mode's `modifiers`. The order there is the
  order they're written in rotation files.
- **Mode:** add an entry under the map's `modes` with its `experience` id and supported
  `modifiers`. Add `"legacy": true` to make it opt-in. A mode can have its own `lighting` / `zones` lists
  if it only supports some of them.
- **Map:** add a new key under `maps` with its internal `map` name, modes, lighting and zones.

The easiest way to find the internal names is to build a rotation that uses the new options in
the dashboard, export it, and copy the values from the export.

## Development

```bash
python -m unittest           # Python tests, plus website logic tests if Node.js is installed
python -m http.server 8000   # preview the website at http://localhost:8000
```

The website is a static page served by GitHub Pages from the root of `main`. There is no build
step and no server. If you open `index.html` straight from disk, the browser blocks it from
loading the catalog, so use a local server as shown above.

When you change files in `web/`, bump the `?v=` number on the links in `index.html` and on the
`rotation.js` import in `web/app.js`. GitHub Pages caches files for about 10 minutes, and the
version number makes browsers load the new files together. Drag and drop uses
[SortableJS](https://sortablejs.github.io/Sortable/), loaded from a CDN. If it can't load, the
keyboard reordering still works.

The tests check that the example exports validate, that generated rotations follow the format
and the rules (no back-to-back maps, no duplicates, balanced maps, legacy modes opt-in, the same
modifiers on every map), and that the filters work.

## License

[MIT](LICENSE)
