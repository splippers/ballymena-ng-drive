#!/usr/bin/env python3
"""Rebuild the drop-in mod under packaged_for_beamng/ and dist/*.zip (HyperIterate packaging)."""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DEST_UF = os.path.join(ROOT, 'packaged_for_beamng')
ZIP_BASE = os.path.join(ROOT, 'dist', 'ballymena-ng-drive-mod')


def main():
    os.makedirs(os.path.join(ROOT, 'dist'), exist_ok=True)
    install = os.path.join(ROOT, 'install_to_beamng.py')
    r = subprocess.run([sys.executable, install, DEST_UF], cwd=ROOT)
    if r.returncode != 0:
        return r.returncode
    zip_path = shutil.make_archive(
        ZIP_BASE,
        'zip',
        root_dir=os.path.join(DEST_UF, 'mods'),
        base_dir='ballymena-ng-drive',
    )
    mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f'\nZIP ready: {zip_path} ({mb:.1f} MB)\n'
          'Install: unzip into BeamNG userfolder mods/, or merge mods/ballymena-ng-drive.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
