"""Synthetic clip regression: blender -b --factory-startup --python tests/blender_animation_roundtrip.py.

Creates its own rig and mesh; no game assets, rendering or external packages.
"""
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile

import bpy

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "luna_engine_io_tools", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
luna = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = luna
spec.loader.exec_module(luna)
luna.register()
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.object.armature_add(enter_editmode=True)
arm = bpy.context.active_object
arm.data.edit_bones.remove(arm.data.edit_bones[0])
root = arm.data.edit_bones.new("root")
root.head = (0, 0, 0)
root.tail = (0, 0, 1)
child = arm.data.edit_bones.new("child")
child.head = (0, 0, 1)
child.tail = (0, 0, 2)
child.parent = root
bpy.ops.object.mode_set(mode='OBJECT')
arm.data.bones["root"]["engine_joint_flags"] = 0
arm.data.bones["child"]["engine_joint_flags"] = 0x81

mesh = bpy.data.meshes.new("Morph Test Mesh")
mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)], [],
                 [(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)])
obj = bpy.data.objects.new("Morph Test", mesh)
bpy.context.collection.objects.link(obj)
obj.parent = arm
obj.shape_key_add(name="Basis")
squash = obj.shape_key_add(name="Squash")
stretch = obj.shape_key_add(name="Stretch")
for point in squash.data:
    point.co.z *= 0.2
for point in stretch.data:
    point.co.x *= 1.5
stretch.slider_min = -1
for frame, value in ((0, 0), (2, 1), (4, 0)):
    squash.value = value
    stretch.value = -0.5 * value
    squash.keyframe_insert(data_path="value", frame=frame)
    stretch.keyframe_insert(data_path="value", frame=frame)
    arm.pose.bones["root"].scale = (0.5 + frame * 0.1, 0.75, 1.1)
    arm.pose.bones["child"].scale = (0.8, 1.0 + frame * 0.05, 0.7)
    for bone in arm.pose.bones:
        bone.keyframe_insert(data_path="scale", frame=frame)

scene = bpy.context.scene
scene.engine_export_frame_start = 0
scene.engine_export_frame_end = 4
scene.engine_anim_fps = 30
scene.engine_root_motion_export_mode = 'INPLACE'
for field in ("engine_export_frame_start", "engine_export_frame_end", "engine_anim_fps", "engine_root_motion_export_mode"):
    arm["engine_luna_setting_" + field] = getattr(scene, field)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.select_all(action='DESELECT')
arm.select_set(True)
expected = []
for frame in range(5):
    scene.frame_set(frame)
    expected.append(([squash.value, stretch.value], {p.name: p.matrix.copy() for p in arm.pose.bones}))

with tempfile.TemporaryDirectory() as tmp:
    path = str(Path(tmp) / "morph_scale.animclip")
    assert bpy.ops.export_anim.engine_anim(filepath=path) == {'FINISHED'}
    raw, blocks, _ = luna._registration.dat1.get_dat1_data(path)
    hashes = luna._registration.hashes.BLOCK_HASHES
    off, _ = blocks[hashes["AnimClipBuilt"]]
    assert raw[off + 21] == 1
    assert struct.unpack_from("<H", raw, off + 50)[0] == 2
    assert struct.unpack_from("<I", raw, off + 8)[0] & 0x00100000
    arm.animation_data.action = None
    mesh.shape_keys.animation_data.action = None
    squash.value = stretch.value = 0
    assert bpy.ops.import_anim.engine_anim(filepath=path) == {'FINISHED'}
    weight_error = matrix_error = 0.0
    for frame, (values, matrices) in enumerate(expected):
        scene.frame_set(frame)
        weight_error = max(weight_error, abs(squash.value - values[0]), abs(stretch.value - values[1]))
        for bone in arm.pose.bones:
            matrix_error = max(matrix_error, max(abs(bone.matrix[r][c] - matrices[bone.name][r][c])
                                                for r in range(4) for c in range(4)))
    assert weight_error < 0.00005, weight_error
    assert matrix_error < 0.001, matrix_error
    assert bpy.ops.export_anim.engine_anim(filepath=str(Path(tmp) / "reexport.animclip")) == {'FINISHED'}
    arm.animation_data.action = None
    assert bpy.ops.export_anim.engine_anim(filepath=str(Path(tmp) / "shape_only.animclip")) == {'FINISHED'}
print("ANIMATION_ROUNDTRIP_PASS", json.dumps({"blender": bpy.app.version_string,
                                             "max_morph_weight_error": weight_error,
                                             "max_bone_matrix_error": matrix_error}))
