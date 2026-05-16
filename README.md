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
| Roads + buildings NDJSON | `python run.py process` |
| Pack level → `output/levels/ballymena/` | `python run.py build` |
| Copy mod into packaged / ZIP | `python package_beamng.py` or `python install_to_beamng.py <userfolder>` |

See `src/run.py` for all commands.
