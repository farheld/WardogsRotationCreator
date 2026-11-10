# Wardogs Rotation Creator

Generate random map rotations for a **WARDOGS** server, ready to import into the
[WarDogs Server Commands](https://wardogsbot.com/) dashboard (**Dashboard → Rotation**).

Pick how many maps you want, which maps, lighting/weather and zones. The tool builds a
balanced rotation, so the same map is never played twice in a row and no entry repeats. It
saves the rotation as a JSON file in the exact format the dashboard exports, so you can import
it as-is.

> This is a community tool. It isn't affiliated with the WARDOGS developers or with
> wardogsbot.com. The file format follows rotations exported from the wardogsbot.com dashboard.

## Requirements

- Python 3.9 or newer ([python.org](https://www.python.org/downloads/)). On Windows, tick
  **"Add python.exe to PATH"** during setup.
- Nothing else. The tool only uses Python's standard library.

## Quick start

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

All maps support every lighting preset:

| Lighting | Tags |
|---|---|
| `DayStartClear` | dawn, clear |
| `DayEarlyClear` | morning, clear |
| `DayEarlyFog` | morning, fog |
| `DayClear` | midday, clear |
| `DayLateClear` | afternoon, clear |
| `DayLateGray` | afternoon, overcast |
| `DayLateGrayFog` | afternoon, overcast, fog |
| `DayLateRain` | afternoon, rain |
| `DayEndClear` | dusk, clear |

All entries use the `KOTH_InfantryOnly` modifier. `Bakurani_KOTH_01` (the old spawns) is never
picked unless you ask for it.

## Command-line mode

Passing any option skips the prompts, which is handy for scripting:

```bash
python rotate.py --count 10                        # all maps, balanced, no back-to-back repeats
python rotate.py --name "Night Ops" --count 12
python rotate.py --maps Bakurani                   # single map
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
| `rotate.py` | The generator: interactive prompts and command line |
| `data/catalog.json` | Every valid map / mode / modifier / lighting / zone option |
| `Rotation Creator.bat` | Windows double-click launcher |
| `rotations/` | Your generated rotations (git-ignored) |
| `schema/rotation.schema.json` | JSON Schema for the dashboard's rotation import/export format |
| `schema/catalog.schema.json` | JSON Schema for `data/catalog.json` |
| `examples/` | Dashboard exports, used as reference and test fixtures |
| `tests/` | Unit tests |

To run it, you only need `rotate.py` and `data/catalog.json`, kept in the same folder layout.

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
- **Mode:** add an entry under the map's `modes` with its `experience` id and allowed `modifiers`
  sets. Add `"legacy": true` to make it opt-in. A mode can have its own `lighting` / `zones` lists
  if it only supports some of them.
- **Map:** add a new key under `maps` with its internal `map` name, modes, lighting and zones.

The easiest way to find the internal names is to build a rotation that uses the new options in
the dashboard, export it, and copy the values from the export.

## Development

```bash
python -m unittest
```

The tests check that the example exports validate, that generated rotations follow the format
and the rules (no back-to-back maps, no duplicates, balanced maps, legacy modes opt-in), and that
the filters work.

## License

[MIT](LICENSE)
