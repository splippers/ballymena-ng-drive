# ballymena-ng-drive

OpenStreetMap → BeamNG.drive level pipeline for Ballymena town centre.

## HyperIterate (one-time setup + full build)

Use a **venv** so `pip` works on Linux/macOS (PEP 668):

```bash
cd /path/to/ballymena-ng-drive
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cd src
python run.py all                  # fetch OSM → roads/buildings → level
cd ..
python package_beamng.py           # fills packaged_for_beamng/ + dist/*.zip
```

Then copy the mod into BeamNG:

- **Option A — folder:** merge `packaged_for_beamng/mods/ballymena-ng-drive` into your userfolder’s `mods/` directory.
- **Option B — zip:** unzip `dist/ballymena-ng-drive-mod.zip` into `mods/` so you get `mods/ballymena-ng-drive/...`.

**Windows userfolder:** `%USERPROFILE%\Documents\BeamNG.drive`  
**Linux (Steam):** search for `BeamNG.drive` under Steam compatdata (app **227300**) or Proton prefixes.

**In game:** **Repository → Mod Manager** → enable **ballymena-ng-drive** → **Play → Free Roam** → **Ballymena Town Centre**.

---

## Fast path (after venv exists)

```bash
source .venv/bin/activate
cd src && python run.py all && cd ..
python install_to_beamng.py "$HOME/Documents/BeamNG.drive"   # adjust path
```

Already have `data/osm/*.json`?

```bash
cd src && python run.py process build
```

---

## Layout

| Step | Script |
|------|--------|
| Fetch OSM | `python run.py fetch` |
| Fetch OSNI 1 m LiDAR terrain | `python run.py lidar` |
| Fetch SRTM terrain (fallback) | `python run.py dem` |
| Roads + buildings NDJSON | `python run.py process` |
| Pack level → `output/levels/ballymena/` | `python run.py build` |
| Copy mod into packaged / ZIP | `python package_beamng.py` or `python install_to_beamng.py <userfolder>` |

See `src/run.py` for all commands.

---

## Terrain data

Terrain comes from the **OSNI River Basin LIDAR 2010** survey — the Ballymena
**1 m DTM** (flown 23/04/2009), published by Land & Property Services on
[Open Data NI](https://www.opendatani.gov.uk/) under the Open Government
Licence. `python run.py lidar` (`src/fetch_lidar.py`) streams only the
GeoTIFF tiles that intersect the map BBOX via HTTP range requests, decodes
them (Zstandard + float32 horizontal predictor, no GDAL required) and
resamples them onto a 1025×1025 lat/lon grid → `data/dem/elevation_grid_lidar.json`.

`build_map.py` prefers that file and falls back to
`data/dem/elevation_grid.json` (NASA SRTM via Open-Elevation) when the LiDAR
grid is absent, so the map still builds offline.

**Attribution:** Contains OSNI LiDAR data © Crown copyright 2010, reproduced
with the permission of Land & Property Services under the Open Government
Licence v3. Road data © OpenStreetMap contributors (ODbL).

---

## Game elements (auto-derived)

`python run.py build` also derives BeamNG road furniture straight from the OSM
tags — no hand-placement. The shared algorithm (`src/game_elements.py`, a port
of the module used by `felsted-ng-drive` and `maldon-ng-drive`) reads the full
tag set in `data/osm/ballymena_osm_raw.json` (`src/osm_parse.py`) and emits:

| Element | Source tags | BeamNG |
|---------|-------------|--------|
| Central reservation | paired opposing one-way `motorway`/`trunk`/`primary`/`secondary` ways, or `dual_carriageway=yes` | `DecalRoad` in the `DecalRoads` group |
| Sidewalk | `sidewalk=both/left/right/yes` | `DecalRoad` |
| Guard rail | `barrier=guard_rail/…` | `DecalRoad` |
| Cycleway | `cycleway=lane/track/…` | `DecalRoad` |
| Speed limit | `maxspeed=*` (mph → km/h) | `TSStatic` marker, every 400 m |
| Street lamp | `lit=yes` | `TSStatic` marker, every 35 m |
| Bridge / tunnel | `bridge=*` / `tunnel=*` | `TSStatic` marker |

Point markers land in a `GameElements` SimGroup inside the level; linear
elements join the `DecalRoads` group. Materials (`median_concrete`,
`median_grass`, `sidewalk`, `cycleway`, `guard_rail`) are the ng-drive art-pack
names — they render (grey) until that pack is installed.

