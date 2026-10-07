"""Export regressions: blender -b --factory-startup --python tests/blender_animation_export_edges.py."""
import importlib.util
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
reg = luna._registration
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.object.armature_add(enter_editmode=True)
arm = bpy.context.active_object
root = arm.data.edit_bones[0]
root.name = "root"
child = arm.data.edit_bones.new("child")
child.head = (0, 0, 1)
child.tail = (0, 0, 2)
child.parent = root
bpy.ops.object.mode_set(mode='OBJECT')
arm.data.bones["child"]["engine_joint_flags"] = 0x81
scene = bpy.context.scene
scene.engine_export_frame_start = 0
scene.engine_export_frame_end = 4
scene.engine_anim_fps = 30
scene.engine_root_motion_export_mode = 'INPLACE'
scene.engine_export_use_original_values = False
for field in ("engine_export_frame_start", "engine_export_frame_end", "engine_anim_fps",
              "engine_root_motion_export_mode", "engine_export_use_original_values"):
    arm["engine_luna_setting_" + field] = getattr(scene, field)

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    # A later sample, on just one parent axis, can round to zero even if the
    # original Blender scale is positive. Do not write a runtime divide by zero.
    for frame, scale in ((0, (1, 1, 1)), (4, (1, .00001, 1))):
        arm.pose.bones["root"].scale = scale
        arm.pose.bones["root"].keyframe_insert(data_path="scale", frame=frame)
    scene.frame_set(2)
    try:
        bpy.ops.export_anim.engine_anim(filepath=str(tmp / "unsafe.animclip"))
    except RuntimeError as exc:
        assert "rounds to zero" in str(exc), exc
    else:
        raise AssertionError("A zero quantized parent scale was accepted")
    assert not (tmp / "unsafe.animclip").exists()
    assert scene.frame_current == 2

    arm.animation_data.action = None
    arm.pose.bones["root"].scale = (1, 1, 1)
    arm.pose.bones["root"].keyframe_insert(data_path="scale", frame=0)
    mesh = bpy.data.meshes.new("Mesh")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new("Morph Mesh", mesh)
    bpy.context.collection.objects.link(obj)
    obj.parent = arm
    obj.shape_key_add(name="Basis")
    key = obj.shape_key_add(name="Squash")
    key.data[1].co.z += .5
    for frame, value in ((0, 0), (2, 1), (4, 0)):
        key.value = value
        key.keyframe_insert(data_path="value", frame=frame)
    original = tmp / "original.animclip"
    assert bpy.ops.export_anim.engine_anim(filepath=str(original)) == {'FINISHED'}
    assert bpy.ops.import_anim.engine_anim(filepath=str(original)) == {'FINISHED'}
    stored_hash = int(arm["engine_clip_name_hash"]) & 0xffffffff
    scene.engine_export_use_original_values = True
    arm["engine_luna_setting_engine_export_use_original_values"] = True

    # Imported name hashes allow an accented output filename. Morph target name
    # offsets must count UTF-8 bytes rather than filename characters.
    renamed = tmp / "animation_é.animclip"
    assert bpy.ops.export_anim.engine_anim(filepath=str(renamed)) == {'FINISHED'}
    raw, blocks, table_end = reg.dat1.get_dat1_data(str(renamed))
    built, _ = blocks[reg.hashes.BLOCK_HASHES["AnimClipBuilt"]]
    assert struct.unpack_from("<I", raw, built + 4)[0] == stored_hash
    info, info_size = blocks[reg.hashes.BLOCK_HASHES["AnimClipMorphInfo"]]
    frames, frame_size = blocks[reg.hashes.BLOCK_HASHES["AnimClipMorphFrameData"]]
    strings_end = min(offset for offset, size in blocks.values())
    decoded = reg.anim_morph.decode_anim_morph(raw[info:info + info_size],
        raw[frames:frames + frame_size], 5, raw[table_end:strings_end])
    assert [target["name"] for target in decoded["targets"]] == ["Squash"]
    assert bpy.ops.import_anim.engine_anim(filepath=str(renamed)) == {'FINISHED'}
    for frame, expected in ((0, 0), (2, 1), (4, 0)):
        scene.frame_set(frame)
        assert abs(key.value - expected) < .00005, (frame, key.value)

    # Also cover ordinary bone clips, where no morph string table is emitted.
    key.mute = True
    assert bpy.ops.export_anim.engine_anim(filepath=str(tmp / "bone_é.animclip")) == {'FINISHED'}

print("ANIMATION_EXPORT_EDGES_PASS")
