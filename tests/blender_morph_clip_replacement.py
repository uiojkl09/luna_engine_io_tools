"""Regression: replacing a clip must not retain previous imported morph tracks."""
import importlib.util
from pathlib import Path
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
bpy.ops.object.armature_add()
arm = bpy.context.active_object


def mesh_with_keys(names):
    mesh = bpy.data.meshes.new("Replacement Test")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new("Replacement Test", mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = arm
    obj.shape_key_add(name="Basis")
    result = []
    for name in names:
        key = obj.shape_key_add(name=name)
        key.data[1].co.z += 0.5
        key.value = 0
        result.append(key)
    return obj, result


def constant_key(key, value):
    for frame in (0, 4):
        key.value = value
        key.keyframe_insert(data_path="value", frame=frame)


first_obj, (first, same_mesh) = mesh_with_keys(["First", "SameMesh"])
second_obj, (second,) = mesh_with_keys(["Second"])
constant_key(first, 0.8)
constant_key(same_mesh, 0.9)
constant_key(second, 0.4)
scene = bpy.context.scene
scene.engine_export_frame_start = 0
scene.engine_export_frame_end = 4
scene.engine_anim_fps = 30
scene.engine_root_motion_export_mode = "INPLACE"
for field in ("engine_export_frame_start", "engine_export_frame_end", "engine_anim_fps", "engine_root_motion_export_mode"):
    arm["engine_luna_setting_" + field] = getattr(scene, field)
bpy.context.view_layer.objects.active = arm

with tempfile.TemporaryDirectory() as tmp:
    full_path = str(Path(tmp) / "full.animclip")
    subset_path = str(Path(tmp) / "subset.animclip")
    bone_path = str(Path(tmp) / "bones.animclip")
    assert bpy.ops.export_anim.engine_anim(filepath=full_path) == {"FINISHED"}
    first_obj.data.shape_keys.animation_data.action = None
    first.value = same_mesh.value = 0
    assert bpy.ops.export_anim.engine_anim(filepath=subset_path) == {"FINISHED"}
    second_obj.data.shape_keys.animation_data.action = None
    second.value = 0
    arm.pose.bones[0].keyframe_insert(data_path="location", frame=0)
    assert bpy.ops.export_anim.engine_anim(filepath=bone_path) == {"FINISHED"}

    authored_obj, (authored_key,) = mesh_with_keys(["Authored"])
    constant_key(authored_key, 0.6)
    authored_action = authored_obj.data.shape_keys.animation_data.action

    assert bpy.ops.import_anim.engine_anim(filepath=full_path) == {"FINISHED"}
    scene.frame_set(0)
    assert abs(first.value - 0.8) < 0.0001
    assert abs(same_mesh.value - 0.9) < 0.0001
    assert bpy.ops.import_anim.engine_anim(filepath=subset_path) == {"FINISHED"}
    scene.frame_set(0)
    assert abs(first.value) < 0.0001
    assert abs(same_mesh.value) < 0.0001
    assert abs(second.value - 0.4) < 0.0001
    assert authored_obj.data.shape_keys.animation_data.action == authored_action
    assert abs(authored_key.value - 0.6) < 0.0001
    assert bpy.ops.import_anim.engine_anim(filepath=bone_path) == {"FINISHED"}
    scene.frame_set(0)
    assert abs(second.value) < 0.0001
    assert authored_obj.data.shape_keys.animation_data.action == authored_action
    assert abs(authored_key.value - 0.6) < 0.0001
    assert bpy.ops.import_anim.engine_anim(filepath=full_path) == {"FINISHED"}
    scene.frame_set(4)
    assert abs(first.value - 0.8) < 0.0001
    assert abs(second.value - 0.4) < 0.0001

print("MORPH_CLIP_REPLACEMENT_PASS")
