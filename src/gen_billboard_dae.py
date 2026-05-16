#!/usr/bin/env python3
"""Generate a unit plane Collada .dae for photo-spot billboards.

The plane is 1×1 in the XZ plane (X: -0.5 to 0.5, Z: 0 to 1, Y = 0).
Front face normal = +Y (faces north by default).
UV: (0,0)=bottom-left, (1,1)=top-right as seen from the viewer side (-Y).

Scale via TSStatic: [width_m, thickness_m, height_m].
Rotate via TSStatic rotationMatrix to face the required heading.
"""
import os


def generate_billboard_dae(output_path):
    """Generate the plane DAE; double-sided (front +Y normal, back -Y normal)."""

    # --- geometry ----------------------------------------------------------
    # 4 unique vertex positions
    vp = [
        (-0.5, 0.0, 0.0),   # 0 bottom-left
        ( 0.5, 0.0, 0.0),   # 1 bottom-right
        ( 0.5, 0.0, 1.0),   # 2 top-right
        (-0.5, 0.0, 1.0),   # 3 top-left
    ]

    # Front face (+Y normal): triangles (0,2,1) and (0,3,2)
    # Back face (-Y normal):  triangles (0,1,2) and (0,2,3)
    FRONT = [(0, 2, 1), (0, 3, 2)]
    BACK  = [(0, 1, 2), (0, 2, 3)]

    # UV: indexed by vertex index
    vu = {0: (0, 0), 1: (1, 0), 2: (1, 1), 3: (0, 1)}
    # Back-face UV: mirror U so the image reads correctly from both sides
    vu_back = {0: (1, 0), 1: (0, 0), 2: (0, 1), 3: (1, 1)}

    pos_f, nrm_f, uv_f, p_idx = [], [], [], []
    idx = 0
    for tri in FRONT:
        for vi in tri:
            pos_f.extend(vp[vi])
            nrm_f.extend((0.0, 1.0, 0.0))
            uv_f.extend(vu[vi])
            p_idx.extend((idx, idx, idx))
            idx += 1
    for tri in BACK:
        for vi in tri:
            pos_f.extend(vp[vi])
            nrm_f.extend((0.0, -1.0, 0.0))
            uv_f.extend(vu_back[vi])
            p_idx.extend((idx, idx, idx))
            idx += 1

    n_tri = len(FRONT) + len(BACK)   # 4
    n_corners = n_tri * 3             # 12

    pos_str = ' '.join(f'{v:.6f}' for v in pos_f)
    nrm_str = ' '.join(f'{v:.6f}' for v in nrm_f)
    uv_str  = ' '.join(f'{v:.6f}' for v in uv_f)
    p_str   = ' '.join(str(x) for x in p_idx)

    dae = f'''<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
  <asset>
    <contributor><author>gen_billboard_dae</author><authoring_tool>ballymena-ng-drive</authoring_tool></contributor>
    <created>2026-05-16T00:00:00</created>
    <modified>2026-05-16T00:00:00</modified>
    <unit name="meter" meter="1"/>
    <up_axis>Z_UP</up_axis>
  </asset>
  <library_effects>
    <effect id="billboard_effect">
      <profile_COMMON>
        <technique sid="common">
          <lambert>
            <diffuse><color sid="diffuse">0.9 0.9 0.9 1</color></diffuse>
          </lambert>
        </technique>
      </profile_COMMON>
    </effect>
  </library_effects>
  <library_materials>
    <material id="billboard_mat" name="billboard_mat">
      <instance_effect url="#billboard_effect"/>
    </material>
  </library_materials>
  <library_geometries>
    <geometry id="plane_mesh" name="billboard_plane">
      <mesh>
        <source id="plane_positions">
          <float_array id="plane_positions_array" count="{len(pos_f)}">{pos_str}</float_array>
          <technique_common><accessor source="#plane_positions_array" count="{n_corners}" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common>
        </source>
        <source id="plane_normals">
          <float_array id="plane_normals_array" count="{len(nrm_f)}">{nrm_str}</float_array>
          <technique_common><accessor source="#plane_normals_array" count="{n_corners}" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common>
        </source>
        <source id="plane_uvs">
          <float_array id="plane_uvs_array" count="{len(uv_f)}">{uv_str}</float_array>
          <technique_common><accessor source="#plane_uvs_array" count="{n_corners}" stride="2"><param name="S" type="float"/><param name="T" type="float"/></accessor></technique_common>
        </source>
        <vertices id="plane_vertices"><input semantic="POSITION" source="#plane_positions"/></vertices>
        <triangles material="billboard_mat" count="{n_tri}">
          <input semantic="VERTEX"   source="#plane_vertices" offset="0"/>
          <input semantic="NORMAL"   source="#plane_normals"  offset="1"/>
          <input semantic="TEXCOORD" source="#plane_uvs"      offset="2" set="0"/>
          <p>{p_str}</p>
        </triangles>
      </mesh>
    </geometry>
  </library_geometries>
  <library_visual_scenes>
    <visual_scene id="Scene">
      <node id="billboard_plane" name="billboard_plane">
        <instance_geometry url="#plane_mesh"><bind_material><technique_common><instance_material symbol="billboard_mat" target="#billboard_mat"/></technique_common></bind_material></instance_geometry>
      </node>
    </visual_scene>
  </library_visual_scenes>
  <scene><instance_visual_scene url="#Scene"/></scene>
</COLLADA>'''

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(dae)


if __name__ == '__main__':
    out = os.path.join(os.path.dirname(__file__), '..', 'output', 'levels', 'ballymena',
                       'art', 'shapes', 'billboard', 'plane.dae')
    generate_billboard_dae(out)
    print(f'Generated: {out}')
