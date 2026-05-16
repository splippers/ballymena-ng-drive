#!/usr/bin/env python3
"""Copy output/levels/ballymena into your BeamNG userfolder as an unpacked mod.

Typical userfolders:
  Windows: %USERPROFILE%\\Documents\\BeamNG.drive
  Linux (Steam): ~/.steam/steam/steamapps/compatdata/<id>/pfx/drive_c/users/steamuser/My Documents/BeamNG.drive
  Or search Steam Library for BeamNG.drive next to the game.

Usage:
  python install_to_beamng.py "C:/Users/You/Documents/BeamNG.drive"
"""
import argparse
import json
import os
import shutil
import sys


def main():
    ap = argparse.ArgumentParser(description='Install built Ballymena level into BeamNG mods folder.')
    ap.add_argument(
        'beamng_userfolder',
        help='BeamNG userfolder path (the folder that contains a mods/ directory)',
    )
    ap.add_argument('--mod-name', default='ballymena-ng-drive', help='Mod folder name under mods/')
    args = ap.parse_args()

    repo_root = os.path.dirname(os.path.abspath(__file__))
    src = os.path.join(repo_root, 'output', 'levels', 'ballymena')
    if not os.path.isdir(src):
        print(f'ERROR: No built level at:\n  {src}\nBuild first:\n  cd src && python3 run.py all', file=sys.stderr)
        return 1

    uf = os.path.expanduser(args.beamng_userfolder)
    mods_root = os.path.join(uf, 'mods')
    if not os.path.isdir(mods_root):
        print(f'WARNING: mods/ not found — creating:\n  {mods_root}', file=sys.stderr)
        os.makedirs(mods_root, exist_ok=True)

    dst_mod = os.path.join(mods_root, args.mod_name)
    dst_level = os.path.join(dst_mod, 'levels', 'ballymena')
    os.makedirs(os.path.dirname(dst_level), exist_ok=True)

    if os.path.isdir(dst_level):
        shutil.rmtree(dst_level)
    shutil.copytree(src, dst_level)

    mod_info = {
        'name': args.mod_name,
        'title': 'Ballymena Town Centre (OSM)',
        'version': '0.1.0',
        'author': 'ballymena-ng-drive',
        'description': 'OpenStreetMap roads and buildings — Ballymena town centre.',
    }
    with open(os.path.join(dst_mod, 'mod_info.json'), 'w', encoding='utf-8') as f:
        json.dump(mod_info, f, indent=2)

    print(f'Installed level to:\n  {dst_level}')
    print('\nIn BeamNG: Repository → Mod Manager → enable "{}" → Play → Free Roam → choose map **Ballymena Town Centre**.'.format(args.mod_name))
    return 0


if __name__ == '__main__':
    sys.exit(main())
