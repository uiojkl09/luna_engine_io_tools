"""Custom mesh regression: blender -b --factory-startup --python tests/blender_custom_model_export.py.

Builds a minimal skeletal model template; no game assets are required.
"""
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
if '--' in sys.argv:
    ROOT = Path(sys.argv[sys.argv.index('--') + 1])
spec = importlib.util.spec_from_file_location(
    "luna_engine_io_tools", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
luna = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = luna
spec.loader.exec_module(luna)
luna.register()
reg = luna._registration
export = reg.model_export
hashes = reg.hashes.BLOCK_HASHES
POINTS = [(0.5, 0.2, 0.1), (1.2, 0.2, 0.1), (0.5, 0.8, 0.1), (0.5, 0.2, 0.9)]


def active(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def new_mesh(arm, name, points, faces, parent=True):
    data = bpy.data.meshes.new(name)
    data.from_pydata(points, [], faces)
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    if parent:
        obj.parent = arm
    obj.modifiers.new('Rig', 'ARMATURE').object = arm
    obj.vertex_groups.new(name=arm.data.bones[0].name).add(list(range(len(points))), 1, 'REPLACE')
    return obj


def write_template(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.object.armature_add()
    arm = bpy.context.active_object
    arm.data.bones[0].name = 'root'
    arm.data.bones[0]['engine_joint_index'] = 0
    obj = new_mesh(arm, 'Original', [(0, 0, 0), (.1, 0, 0), (0, .1, 0)], [(0, 1, 2)])
    chunks = export._build_subset_geometry_chunks(obj, arm, 0, b'', 1)
    vertices, indices, uv1, uv2, _, _ = chunks[0]
    subset, geom, stats = export._build_subset_geometry_from_data(
        obj, arm, 0, b'', 0, vertices, indices, uv1, uv2)
    built = bytearray(export.MODEL_BUILT_SIZE)
    struct.pack_into('<Q', built, 0, export.MODEL_FLAG_HAS_SKINNING | export.MODEL_FLAG_HAS_GPU_SKINNING)
    seed = SimpleNamespace(blocks={hashes['ModelBuilt']: (0, len(built))}, payload=lambda _: bytes(built))
    built = export._build_model_built_block(seed, [stats], arm=arm)
    look = bytearray(export.MODEL_LOOK_SIZE)
    for lod in range(8):
        struct.pack_into('<HH', look, lod * 4, 0, 1)
    name_hash = reg.hashes.string_crc32('default')
    look_built = struct.pack('<7Q6H3I', 80, 82, 82, 82, 82, 82, 82,
                             1, 0, 0, 0, 0, 0, name_hash, name_hash, 0) + b'\0\0'
    group = b'\1' + struct.pack('<QH6sIIH', 24, 1, b'\0' * 6, name_hash, 0, 0)
    payloads = {
        hashes['ModelBuilt']: built,
        hashes['ModelMaterial']: struct.pack('<IIIIQII', 0, 0, 0, 0, 1, name_hash, 0),
        hashes['ModelLook']: bytes(look),
        hashes['ModelLookBuilt']: look_built,
        hashes['ModelLookGroup']: group,
        hashes['ModelSubset']: subset,
        hashes['ModelSubsetGeomData']: geom,
        hashes['ModelJointHierarchy']: struct.pack('<4H', 0, 1, 1, 0),
        hashes['ModelJoint']: struct.pack('<hHHHII', -1, 0, 0, 0, reg.hashes.string_crc32('root'), 16) + b'root\0',
        hashes['ModelBindPose']: struct.pack('<12f', 1, 1, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0),
    }
    cursor = 16 + len(payloads) * 12
    table = bytearray()
    body = bytearray()
    for tag, payload in sorted(payloads.items()):
        aligned = (cursor + 15) & ~15
        body += b'\0' * (aligned - cursor)
        table += struct.pack('<III', tag, aligned, len(payload))
        body += payload
        cursor = aligned + len(payload)
    path.write_bytes(struct.pack('<IIIHH', 0x44415431, 0x41DFFB44, cursor, len(payloads), 0) + table + body)


def run_case(template, output, parent, remove_original, exclude=False):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    assert bpy.ops.import_scene.engine_model(filepath=str(template)) == {'FINISHED'}
    arm = bpy.context.active_object
    original = next(o for o in bpy.data.objects if o.type == 'MESH')
    if remove_original:
        bpy.data.objects.remove(original, do_unlink=True)
    obj = new_mesh(arm, 'Replacement', POINTS, [(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)], parent)
    # Helper meshes using the rig must not become exported model geometry.
    guide = new_mesh(arm, 'Hair Weight Guide', POINTS[:3], [(0, 1, 2)], False)
    guide['engine_hair_curve_object'] = 'Hair Owner'
    bounds = new_mesh(arm, 'Bounds', POINTS[:3], [(0, 1, 2)])
    bounds['engine_bounds_type'] = 'subset_aabb'
    if exclude:
        active(obj)
        assert bpy.ops.model.add_selected_to_luna_look() == {'FINISHED'}
        assert bpy.ops.model.remove_selected_from_luna_look() == {'FINISHED'}
    else:
        # Look preview may have hidden an unregistered mesh before export.
        obj.hide_viewport = True
    active(arm)
    assert bpy.ops.export_scene.engine_model(filepath=str(output)) == {'FINISHED'}
    assert obj.parent == (arm if parent else None)
    raw, blocks, _ = reg.dat1.get_dat1_data(str(output))
    subset_count = blocks[hashes['ModelSubset']][1] // export.MODEL_SUBSET_RECORD_SIZE
    assert subset_count == (1 if remove_original else 2), subset_count
    assert obj.hide_viewport == exclude
    subset_id = int(obj['engine_subset_index'])
    assert subset_id >= 1  # Never borrow a deleted original subset's identity.
    assert 'engine_subset_index' not in guide and 'engine_subset_index' not in bounds
    looks = reg.model_import._parse_model_looks_metadata(raw, blocks)
    replacement_id = 0 if remove_original else 1
    assert (replacement_id in looks[0]['subset_ids']) == (not exclude), looks
    assert len(bpy.data.objects) == (4 if remove_original else 5)
    first = output.read_bytes()
    active(obj)  # Re-export also works with only the bound mesh selected.
    assert bpy.ops.export_scene.engine_model(filepath=str(output)) == {'FINISHED'}
    assert output.read_bytes() == first
    bpy.ops.wm.read_factory_settings(use_empty=True)
    assert bpy.ops.import_scene.engine_model(filepath=str(output)) == {'FINISHED'}
    meshes = [o for o in bpy.data.objects if o.type == 'MESH']
    assert len(meshes) == subset_count, len(meshes)
    replacement = next(o for o in meshes if int(o['engine_subset_index']) == replacement_id)
    assert len(replacement.data.polygons) == 4
    for point in POINTS:
        assert any((vertex.co - Vector(point)).length < .001 for vertex in replacement.data.vertices), point
    # Geometry is also retained when look membership is intentionally excluded.
    # Native look references, checked above, control whether it is visible.
    print('CUSTOM_MODEL_EXPORT_PASS', json.dumps({'parented': parent, 'replace': remove_original, 'excluded': exclude}))


def run_controls_case(template, output, parent):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    assert bpy.ops.import_scene.engine_model(filepath=str(template)) == {'FINISHED'}
    arm = bpy.context.active_object
    source_mesh = next(o for o in bpy.data.objects if o.type == 'MESH')
    source_mesh.shape_key_add(name='Basis')
    shape = source_mesh.shape_key_add(name='Squash')
    for point in shape.data:
        point.co.x *= .5
    assert bpy.ops.export_scene.engine_model(filepath=str(output)) == {'FINISHED'}
    bpy.ops.wm.read_factory_settings(use_empty=True)
    assert bpy.ops.import_scene.engine_model(filepath=str(output)) == {'FINISHED'}
    arm = bpy.context.active_object
    for obj in list(bpy.data.objects):
        if obj.type == 'MESH':
            bpy.data.objects.remove(obj, do_unlink=True)
    custom = new_mesh(arm, 'Custom Shapes', POINTS, [(0, 1, 2)], parent)
    helpers = []
    for name, prop, value in (
        ('Bounds', 'engine_bounds_type', 'subset_aabb'),
        ('Hair Guide', 'engine_hair_curve_object', 'Hair Owner'),
    ):
        helper = new_mesh(arm, name, POINTS[:3], [(0, 1, 2)], parent)
        helper[prop] = value
        helper.shape_key_add(name='Basis')
        helper.shape_key_add(name='Squash').value = .25
        helpers.append(helper)
    active(custom)
    assert bpy.ops.model.create_original_blendshape_names() == {'FINISHED'}
    assert custom.parent == (arm if parent else None)
    assert custom.data.shape_keys.key_blocks.get('Squash') is not None
    controls = json.loads(arm['engine_model_morph_controls_json'])
    assert len(controls) == 1 and controls[0]['mesh_count'] == 1, controls
    preview = arm.engine_model_morph_previews[controls[0]['preview_index']]
    preview.value = .75
    assert custom.data.shape_keys.key_blocks['Squash'].value == .75
    for helper in helpers:
        assert helper.data.shape_keys.key_blocks['Squash'].value == .25, (helper.name, dict(helper.items()), helper.data.shape_keys.key_blocks['Squash'].value)
    assert bpy.ops.model.sync_morph_controls() == {'FINISHED'}
    assert custom.data.shape_keys.key_blocks['Squash'].value == .75
    assert reg.operators._ziva_selected_meshes(bpy.context, arm) == [custom]
    print('CUSTOM_MORPH_CONTROLS_PASS', json.dumps({'parented': parent}))


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    template = tmp / 'template.model'
    write_template(template)
    for parent in (False, True):
        for replace in (False, True):
            run_case(template, tmp / 'custom.model', parent, replace)
    run_case(template, tmp / 'excluded.model', False, False, exclude=True)
    for parent in (False, True):
        run_controls_case(template, tmp / 'morph_source.model', parent)
print('CUSTOM_MODEL_EXPORT_REGRESSION_PASS')
