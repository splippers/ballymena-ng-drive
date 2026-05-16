#!/usr/bin/env python3
"""Validate data/photos/photo_manifest.json entries.

Exit codes:
  0 — all entries valid (warnings are OK)
  1 — at least one structural error (missing field, bad coordinates, duplicate ID)

Run in CI: python src/validate_photos.py
"""
import json, os, sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST_PATH = os.path.join(BASE_DIR, 'data', 'photos', 'photo_manifest.json')
IMAGES_DIR    = os.path.join(BASE_DIR, 'data', 'photos')

BBOX = (54.856, -6.293, 54.874, -6.262)  # south, west, north, east

REQUIRED_FIELDS = ('id', 'lat', 'lon', 'description', 'image_then')


def validate():
    if not os.path.exists(MANIFEST_PATH):
        print(f'ERROR: manifest not found: {MANIFEST_PATH}')
        sys.exit(1)

    with open(MANIFEST_PATH) as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as exc:
            print(f'ERROR: invalid JSON — {exc}')
            sys.exit(1)

    photos = data.get('photos', [])
    errors, warnings = [], []
    seen_ids = set()

    for i, p in enumerate(photos):
        pid = p.get('id', f'entry[{i}]')
        tag = f'[{i}] {pid}'

        for field in REQUIRED_FIELDS:
            if not p.get(field):
                errors.append(f'{tag}: missing required field "{field}"')

        if pid in seen_ids:
            errors.append(f'{tag}: duplicate id "{pid}"')
        seen_ids.add(pid)

        lat, lon = p.get('lat', 0.0), p.get('lon', 0.0)
        s, w, n, e = BBOX
        if not (s <= lat <= n and w <= lon <= e):
            errors.append(f'{tag}: ({lat}, {lon}) is outside BBOX '
                          f'({s}–{n}N, {w}–{e}E)')

        img_then = p.get('image_then', '')
        if img_then and not img_then.startswith('http'):
            full = os.path.join(IMAGES_DIR, img_then)
            if not os.path.exists(full):
                warnings.append(f'{tag}: image_then not found (wanted: {img_then}) — '
                                f'upload the image to data/photos/{img_then}')

        if not p.get('image_now'):
            warnings.append(f'{tag}: image_now missing — a present-day comparison photo is wanted')

        heading = p.get('heading', 0)
        if not isinstance(heading, (int, float)) or not (0 <= heading < 360):
            errors.append(f'{tag}: heading must be 0–359, got {heading!r}')

    for w in warnings:
        print(f'  WARN  {w}')
    for e in errors:
        print(f'  ERROR {e}')

    print(f'\n{len(photos)} entries — {len(errors)} error(s), {len(warnings)} warning(s)')

    if errors:
        sys.exit(1)
    print('Manifest OK.')


if __name__ == '__main__':
    validate()
