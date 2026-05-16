#!/usr/bin/env python3
"""Generate per-type building COLLADA shapes for Ballymena.

Each shape is a unit solid (±0.5 in X/Y, 0–1 in Z) scaled via TSStatic.
Pitched-roof shapes have the gable ends along X (ridge runs left–right along
the WIDTH axis), so the longer footprint dimension naturally lines up with
the roof ridge.

Shape variants generated:
  pitched_brick   — gabled roof, Victorian red brick  (house / terrace / residential)
  pitched_render  — gabled roof, pebbledash render     (semidetached / detached / bungalow)
  flat_commercial — flat roof, sandstone/render        (apartments / office / school / yes)
  flat_retail     — flat roof, modern panel grey       (retail / supermarket)
  flat_industrial — flat roof, corrugated dark grey    (industrial / warehouse / garage)
  flat_church     — flat roof, limestone/whitewash     (church / chapel)
"""
import os, math

# Eave height as fraction of total building height (ridge is at Z=1.0 in unit space)
_EAVE = 0.65

# Precomputed slope normal components (for pitched roof faces)
_SR  = 0.5           # slope run in Y (eave to ridge)
_SRI = 1.0 - _EAVE  # slope rise = 0.35
_SM  = math.sqrt(_SR**2 + _SRI**2)  # ≈ 0.6103
_SNY = _SRI / _SM   # normal Y magnitude ≈ 0.5734
_SNZ = _SR  / _SM   # normal Z           ≈ 0.8192

# (OSM building tag) → shape name
OSM_TAG_TO_SHAPE = {
    'house':             'pitched_brick',
    'terrace':           'pitched_brick',
    'residential':       'pitched_brick',
    'semidetached_house':'pitched_render',
    'detached':          'pitched_render',
    'bungalow':          'pitched_render',
    'apartments':        'flat_commercial',
    'dormitory':         'flat_commercial',
    'commercial':        'flat_commercial',
    'office':            'flat_commercial',
    'civic':             'flat_commercial',
    'public':            'flat_commercial',
    'school':            'flat_commercial',
    'college':           'flat_commercial',
    'university':        'flat_commercial',
    'hospital':          'flat_commercial',
    'retail':            'flat_retail',
    'supermarket':       'flat_retail',
    'shop':              'flat_retail',
    'kiosk':             'flat_retail',
    'industrial':        'flat_industrial',
    'warehouse':         'flat_industrial',
    'factory':           'flat_industrial',
    'garages':           'flat_industrial',
    'garage':            'flat_industrial',
    'storage_tank':      'flat_industrial',
    'parking':           'flat_industrial',
    'grandstand':        'flat_industrial',
    'church':            'flat_church',
    'cathedral':         'flat_church',
    'chapel':            'flat_church',
    'synagogue':         'flat_church',
    'mosque':            'flat_church',
}
DEFAULT_SHAPE = 'flat_commercial'

# shape name → (geometry_type, diffuse RGB)
SHAPES = {
    'pitched_brick':   ('pitched', (0.63, 0.35, 0.26)),
    'pitched_render':  ('pitched', (0.84, 0.82, 0.78)),
    'flat_commercial': ('flat',    (0.74, 0.72, 0.68)),
    'flat_retail':     ('flat',    (0.60, 0.60, 0.62)),
    'flat_industrial': ('flat',    (0.44, 0.43, 0.41)),
    'flat_church':     ('flat',    (0.88, 0.86, 0.82)),
}


def shape_for_building(building_tag):
    """Return shape name for an OSM building tag string."""
    return OSM_TAG_TO_SHAPE.get(building_tag, DEFAULT_SHAPE)


def shape_dae_path(shape_name):
    """Return the in-level shapeName path for the given shape variant."""
    return f'/levels/ballymena/art/shapes/buildings/{shape_name}.dae'


# ── Geometry builders ────────────────────────────────────────────────────────

def _tri(va, vb, vc, n):
    """Return three (pos, normal) corner tuples for one triangle."""
    return [(va, n), (vb, n), (vc, n)]


def _quad(va, vb, vc, vd, n):
    """Fan-triangulate a quad into two triangles (va,vb,vc) and (va,vc,vd)."""
    return _tri(va, vb, vc, n) + _tri(va, vc, vd, n)


def _flat_corners():
    """5-face unit box (no bottom): list of (pos, normal) per corner."""
    E = _EAVE   # not used here; flat box goes 0→1 in Z
    corners = []
    E = 1.0  # flat box uses full height
    # +X face
    corners += _quad((0.5,-0.5,0),(0.5,0.5,0),(0.5,0.5,1),(0.5,-0.5,1),   (1,0,0))
    # -X face
    corners += _quad((-0.5,0.5,0),(-0.5,-0.5,0),(-0.5,-0.5,1),(-0.5,0.5,1), (-1,0,0))
    # +Y face
    corners += _quad((0.5,0.5,0),(-0.5,0.5,0),(-0.5,0.5,1),(0.5,0.5,1),   (0,1,0))
    # -Y face
    corners += _quad((-0.5,-0.5,0),(0.5,-0.5,0),(0.5,-0.5,1),(-0.5,-0.5,1),(0,-1,0))
    # +Z top face
    corners += _quad((-0.5,-0.5,1),(0.5,-0.5,1),(0.5,0.5,1),(-0.5,0.5,1),  (0,0,1))
    return corners


def _pitched_corners():
    """Gabled-roof unit building (ridge along X, eave at Z=_EAVE): corners list."""
    E = _EAVE
    corners = []
    # Left gable wall rectangle (X=-0.5, normal -X)
    corners += _quad((-0.5,0.5,0),(-0.5,-0.5,0),(-0.5,-0.5,E),(-0.5,0.5,E), (-1,0,0))
    # Left gable triangle above wall (normal -X)
    corners += _tri((-0.5,0.5,E),(-0.5,-0.5,E),(-0.5,0,1.0),               (-1,0,0))
    # Right gable wall rectangle (X=+0.5, normal +X)
    corners += _quad((0.5,-0.5,0),(0.5,0.5,0),(0.5,0.5,E),(0.5,-0.5,E),    (1,0,0))
    # Right gable triangle (normal +X)
    corners += _tri((0.5,-0.5,E),(0.5,0.5,E),(0.5,0,1.0),                  (1,0,0))
    # Front wall rectangle (Y=-0.5, normal -Y)
    corners += _quad((-0.5,-0.5,0),(0.5,-0.5,0),(0.5,-0.5,E),(-0.5,-0.5,E),(0,-1,0))
    # Back wall rectangle (Y=+0.5, normal +Y)
    corners += _quad((0.5,0.5,0),(-0.5,0.5,0),(-0.5,0.5,E),(0.5,0.5,E),   (0,1,0))
    # Front roof slope (from Y=-0.5 eave up to ridge at Y=0)
    corners += _quad((-0.5,-0.5,E),(0.5,-0.5,E),(0.5,0,1.0),(-0.5,0,1.0), (0,-_SNY,_SNZ))
    # Back roof slope (from ridge at Y=0 down to Y=+0.5 eave)
    corners += _quad((-0.5,0,1.0),(0.5,0,1.0),(0.5,0.5,E),(-0.5,0.5,E),   (0,_SNY,_SNZ))
    return corners


# ── COLLADA writer ───────────────────────────────────────────────────────────

def _write_dae(output_path, corners, color):
    """Write a COLLADA file from a list of (pos, normal) corner tuples."""
    r, g, b = color
    n_corners = len(corners)
    n_tris = n_corners // 3

    pos_f = [v for pos, _ in corners for v in pos]
    nrm_f = [v for _, nrm in corners for v in nrm]
    idx   = ' '.join(f'{i} {i}' for i in range(n_corners))

    pos_str = ' '.join(f'{v:.6f}' for v in pos_f)
    nrm_str = ' '.join(f'{v:.6f}' for v in nrm_f)

    dae = f'''<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
  <asset>
    <contributor><author>gen_building_shapes</author><authoring_tool>ballymena-ng-drive</authoring_tool></contributor>
    <created>2026-05-16T00:00:00</created>
    <modified>2026-05-16T00:00:00</modified>
    <unit name="meter" meter="1"/>
    <up_axis>Z_UP</up_axis>
  </asset>
  <library_effects>
    <effect id="bldg_effect">
      <profile_COMMON>
        <technique sid="common">
          <lambert>
            <diffuse><color sid="diffuse">{r:.4f} {g:.4f} {b:.4f} 1</color></diffuse>
          </lambert>
        </technique>
      </profile_COMMON>
    </effect>
  </library_effects>
  <library_materials>
    <material id="bldg_mat" name="bldg_mat">
      <instance_effect url="#bldg_effect"/>
    </material>
  </library_materials>
  <library_geometries>
    <geometry id="bldg_mesh" name="building">
      <mesh>
        <source id="bldg_positions">
          <float_array id="bldg_positions_array" count="{len(pos_f)}">{pos_str}</float_array>
          <technique_common><accessor source="#bldg_positions_array" count="{n_corners}" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common>
        </source>
        <source id="bldg_normals">
          <float_array id="bldg_normals_array" count="{len(nrm_f)}">{nrm_str}</float_array>
          <technique_common><accessor source="#bldg_normals_array" count="{n_corners}" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common>
        </source>
        <vertices id="bldg_vertices"><input semantic="POSITION" source="#bldg_positions"/></vertices>
        <triangles material="bldg_mat" count="{n_tris}">
          <input semantic="VERTEX" source="#bldg_vertices" offset="0"/>
          <input semantic="NORMAL" source="#bldg_normals"  offset="1"/>
          <p>{idx}</p>
        </triangles>
      </mesh>
    </geometry>
  </library_geometries>
  <library_visual_scenes>
    <visual_scene id="Scene">
      <node id="building" name="building">
        <instance_geometry url="#bldg_mesh"><bind_material><technique_common><instance_material symbol="bldg_mat" target="#bldg_mat"/></technique_common></bind_material></instance_geometry>
      </node>
    </visual_scene>
  </library_visual_scenes>
  <scene><instance_visual_scene url="#Scene"/></scene>
</COLLADA>'''

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(dae)


# ── Public API ───────────────────────────────────────────────────────────────

def generate_all_shapes(output_dir):
    """Write all shape variant DAEs into output_dir. Returns count generated."""
    os.makedirs(output_dir, exist_ok=True)
    for name, (geom, color) in SHAPES.items():
        corners = _pitched_corners() if geom == 'pitched' else _flat_corners()
        _write_dae(os.path.join(output_dir, f'{name}.dae'), corners, color)
    return len(SHAPES)


if __name__ == '__main__':
    out = os.path.join(os.path.dirname(__file__), '..', 'output',
                       'levels', 'ballymena', 'art', 'shapes', 'buildings')
    n = generate_all_shapes(out)
    print(f'Generated {n} building shape DAEs → {out}')
    for name in SHAPES:
        print(f'  {name}.dae')
