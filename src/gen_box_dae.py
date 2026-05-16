#!/usr/bin/env python3
"""Generate a simple unit box Collada .dae file for building proxies."""
import os


def generate_unit_box_dae(output_path):
    """Generate a 1×1×1 m box .dae centered at origin, Z-up, valid COLLADA 1.4.

    Uses one position + one normal per triangle corner (36 vertices) so each face
    has constant shading normals without invalid <vertices> semantics.
    """
    # Half-extent cube [-0.5, 0.5]; six faces × two triangles × three corners
    corners = {
        'px': ((0.5, -0.5, -0.5), (0.5, 0.5, -0.5), (0.5, 0.5, 0.5), (0.5, -0.5, 0.5)),
        'nx': ((-0.5, -0.5, -0.5), (-0.5, -0.5, 0.5), (-0.5, 0.5, 0.5), (-0.5, 0.5, -0.5)),
        'py': ((-0.5, 0.5, -0.5), (-0.5, 0.5, 0.5), (0.5, 0.5, 0.5), (0.5, 0.5, -0.5)),
        'ny': ((-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.5, -0.5, 0.5), (-0.5, -0.5, 0.5)),
        'pz': ((-0.5, -0.5, 0.5), (0.5, -0.5, 0.5), (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5)),
        'nz': ((-0.5, -0.5, -0.5), (-0.5, 0.5, -0.5), (0.5, 0.5, -0.5), (0.5, -0.5, -0.5)),
    }
    normals = {
        'px': (1, 0, 0),
        'nx': (-1, 0, 0),
        'py': (0, 1, 0),
        'ny': (0, -1, 0),
        'pz': (0, 0, 1),
        'nz': (0, 0, -1),
    }
    pos_floats = []
    nrm_floats = []
    p_pairs = []
    i = 0
    for key in ('nz', 'pz', 'ny', 'py', 'nx', 'px'):
        quad = corners[key]
        n = normals[key]
        tris = ((0, 1, 2), (0, 2, 3))
        for a, b, c in tris:
            for k in (a, b, c):
                x, y, z = quad[k]
                pos_floats.extend((x, y, z))
                nrm_floats.extend(n)
                p_pairs.extend((i, i))
                i += 1

    pos_str = ' '.join(f'{v:.6f}' for v in pos_floats)
    nrm_str = ' '.join(f'{v:.6f}' for v in nrm_floats)
    idx_str = ' '.join(str(x) for x in p_pairs)

    dae = f'''<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
  <asset>
    <contributor><author>gen_box_dae</author><authoring_tool>ballymena-ng-drive</authoring_tool></contributor>
    <created>2026-05-10T00:00:00</created>
    <modified>2026-05-10T00:00:00</modified>
    <unit name="meter" meter="1"/>
    <up_axis>Z_UP</up_axis>
  </asset>
  <library_effects>
    <effect id="building_effect">
      <profile_COMMON>
        <technique sid="common">
          <lambert>
            <diffuse><color sid="diffuse">0.7 0.7 0.7 1</color></diffuse>
          </lambert>
        </technique>
      </profile_COMMON>
    </effect>
  </library_effects>
  <library_materials>
    <material id="building_mat" name="building_mat">
      <instance_effect url="#building_effect"/>
    </material>
  </library_materials>
  <library_geometries>
    <geometry id="box_mesh" name="box">
      <mesh>
        <source id="box_positions">
          <float_array id="box_positions_array" count="{len(pos_floats)}">{pos_str}</float_array>
          <technique_common><accessor source="#box_positions_array" count="{len(pos_floats)//3}" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common>
        </source>
        <source id="box_normals">
          <float_array id="box_normals_array" count="{len(nrm_floats)}">{nrm_str}</float_array>
          <technique_common><accessor source="#box_normals_array" count="{len(nrm_floats)//3}" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common>
        </source>
        <vertices id="box_vertices"><input semantic="POSITION" source="#box_positions"/></vertices>
        <triangles material="building_mat" count="12">
          <input semantic="VERTEX" source="#box_vertices" offset="0"/>
          <input semantic="NORMAL" source="#box_normals" offset="1"/>
          <p>{idx_str}</p>
        </triangles>
      </mesh>
    </geometry>
  </library_geometries>
  <library_visual_scenes>
    <visual_scene id="Scene">
      <node id="box" name="box">
        <instance_geometry url="#box_mesh"><bind_material><technique_common><instance_material symbol="building_mat" target="#building_mat"/></technique_common></bind_material></instance_geometry>
      </node>
    </visual_scene>
  </library_visual_scenes>
  <scene><instance_visual_scene url="#Scene"/></scene>
</COLLADA>'''
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(dae)


if __name__ == '__main__':
    out = os.path.join(os.path.dirname(__file__), '..', 'output', 'levels', 'ballymena', 'art', 'shapes', 'buildings', 'box.dae')
    generate_unit_box_dae(out)
    print(f"Generated: {out}")
