#!/usr/bin/env python3
"""Generate a textured ground-plane COLLADA (.dae) for the satellite imagery layer.

The plane is a unit quad (±0.5 in X, ±0.5 in Y, Z=0) with UV coordinates mapped
to the satellite texture. The TSStatic in build_map.py scales it to
[level_size, level_size, 1], so it covers the entire map area.

UV layout (COLLADA convention: origin at bottom-left of texture):
  Corner (-0.5, -0.5)  SW  →  U=0,       V=1-v_max   (SW of satellite image)
  Corner (+0.5, -0.5)  SE  →  U=u_max,   V=1-v_max
  Corner (+0.5, +0.5)  NE  →  U=u_max,   V=1
  Corner (-0.5, +0.5)  NW  →  U=0,       V=1

The satellite PNG has north at its top (V=0 in image-space = top = north). In COLLADA
UV space V=0 is the bottom of the texture, so V=1 corresponds to image top = north.
After the power-of-2 pad, only the fraction (u_max, v_max) of the texture is
populated, so we clamp UVs to those values.
"""
import os

SAT_TEX_PATH = '/levels/ballymena/art/terrain/satellite.png'


def generate_sat_plane_dae(output_path, u_max=1.0, v_max=1.0):
    """Write satellite-plane DAE.

    u_max, v_max: the UV fractions that correspond to the real BBOX extent
                  (< 1 when the texture has been padded to a power-of-2 size).
    """
    # Unit quad vertices in CCW order viewed from above (+Z normal)
    # Listed as (x, y) pairs for the four corners
    #   0: SW (-0.5, -0.5)   1: SE (+0.5, -0.5)
    #   2: NE (+0.5, +0.5)   3: NW (-0.5, +0.5)
    verts = [
        (-0.5, -0.5, 0.0),
        ( 0.5, -0.5, 0.0),
        ( 0.5,  0.5, 0.0),
        (-0.5,  0.5, 0.0),
    ]
    # UV: satellite image has north at top (pixel row 0).
    # COLLADA V=0 = texture bottom = image bottom = south.
    # So: north maps to V=v_max, south maps to V=0.
    uvs = [
        (0.0,   0.0   ),   # SW → image bottom-left
        (u_max, 0.0   ),   # SE → image bottom-right
        (u_max, v_max ),   # NE → image top-right
        (0.0,   v_max ),   # NW → image top-left
    ]
    # Two triangles: (0,1,2) and (0,2,3)
    tris = [(0, 1, 2), (0, 2, 3)]

    pos_arr  = ' '.join(f'{v:.6f}' for vtx in verts for v in vtx)
    nrm_arr  = ' '.join('0.000000 0.000000 1.000000' for _ in range(4))
    uv_arr   = ' '.join(f'{u:.6f} {v:.6f}' for u, v in uvs)
    # p indices: each vertex listed 3 times (pos_idx, norm_idx, uv_idx are same)
    p_str = ' '.join(f'{i} {i} {i}' for tri in tris for i in tri)

    dae = f'''<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
  <asset>
    <contributor><authoring_tool>ballymena-ng-drive</authoring_tool></contributor>
    <created>2026-05-16T00:00:00</created>
    <modified>2026-05-16T00:00:00</modified>
    <unit name="meter" meter="1"/>
    <up_axis>Z_UP</up_axis>
  </asset>
  <library_images>
    <image id="sat_image" name="sat_image">
      <init_from>{SAT_TEX_PATH}</init_from>
    </image>
  </library_images>
  <library_effects>
    <effect id="sat_effect">
      <profile_COMMON>
        <newparam sid="sat_surface">
          <surface type="2D"><init_from>sat_image</init_from></surface>
        </newparam>
        <newparam sid="sat_sampler">
          <sampler2D><source>sat_surface</source></sampler2D>
        </newparam>
        <technique sid="common">
          <lambert>
            <diffuse><texture texture="sat_sampler" texcoord="CHANNEL0"/></diffuse>
            <transparent opaque="A_ONE"><color>1 1 1 1</color></transparent>
            <transparency><float>1.0</float></transparency>
          </lambert>
        </technique>
      </profile_COMMON>
    </effect>
  </library_effects>
  <library_materials>
    <material id="sat_mat" name="sat_mat">
      <instance_effect url="#sat_effect"/>
    </material>
  </library_materials>
  <library_geometries>
    <geometry id="plane_mesh" name="satellite_plane">
      <mesh>
        <source id="plane_pos">
          <float_array id="plane_pos_arr" count="12">{pos_arr}</float_array>
          <technique_common>
            <accessor source="#plane_pos_arr" count="4" stride="3">
              <param name="X" type="float"/>
              <param name="Y" type="float"/>
              <param name="Z" type="float"/>
            </accessor>
          </technique_common>
        </source>
        <source id="plane_nrm">
          <float_array id="plane_nrm_arr" count="12">{nrm_arr}</float_array>
          <technique_common>
            <accessor source="#plane_nrm_arr" count="4" stride="3">
              <param name="X" type="float"/>
              <param name="Y" type="float"/>
              <param name="Z" type="float"/>
            </accessor>
          </technique_common>
        </source>
        <source id="plane_uv">
          <float_array id="plane_uv_arr" count="8">{uv_arr}</float_array>
          <technique_common>
            <accessor source="#plane_uv_arr" count="4" stride="2">
              <param name="S" type="float"/>
              <param name="T" type="float"/>
            </accessor>
          </technique_common>
        </source>
        <vertices id="plane_verts">
          <input semantic="POSITION" source="#plane_pos"/>
        </vertices>
        <triangles material="sat_mat" count="2">
          <input semantic="VERTEX"   source="#plane_verts" offset="0"/>
          <input semantic="NORMAL"   source="#plane_nrm"   offset="1"/>
          <input semantic="TEXCOORD" source="#plane_uv"    offset="2" set="0"/>
          <p>{p_str}</p>
        </triangles>
      </mesh>
    </geometry>
  </library_geometries>
  <library_visual_scenes>
    <visual_scene id="Scene">
      <node id="satellite_plane" name="satellite_plane">
        <instance_geometry url="#plane_mesh">
          <bind_material><technique_common>
            <instance_material symbol="sat_mat" target="#sat_mat"/>
          </technique_common></bind_material>
        </instance_geometry>
      </node>
    </visual_scene>
  </library_visual_scenes>
  <scene><instance_visual_scene url="#Scene"/></scene>
</COLLADA>'''

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(dae)


if __name__ == '__main__':
    import sys
    out = os.path.join(os.path.dirname(__file__), '..', 'output',
                       'levels', 'ballymena', 'art', 'shapes', 'terrain', 'satellite_plane.dae')
    u_max = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
    v_max = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
    generate_sat_plane_dae(out, u_max, v_max)
    print(f'Generated: {out}  (u_max={u_max:.4f}, v_max={v_max:.4f})')
