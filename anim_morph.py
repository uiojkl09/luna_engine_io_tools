"""Native AnimClip morph-weight tracks and Blender shape-key animation.

The binary layout follows AnimClipMorphInfo, AnimClipMorphUnpackFrame and
ContentAnimClip::ProcessMorphTargetAnimPack / SerializeMorphTargetAnim.
Morph tracks use the clip's full sample rate, independently of resident bones.
"""

from .utils import *
from .hashes import BLOCK_HASHES, string_crc32

ANIM_MORPH_INFO_FORMAT = "<H2xff5B3xI"
ANIM_MORPH_INFO_SIZE = struct.calcsize(ANIM_MORPH_INFO_FORMAT)
ANIM_MORPH_WEIGHT_BITS = 15  # Bit 15 of the runtime u16 is the presence flag.
ANIM_MORPH_TARGET_LIMIT = 255  # 256 runtime result elements, including sentinel.
ANIM_MORPH_VERT_TYPE = 1


def _anim_morph_write_bits(buffer, cursor, value, count):
    if not 0 <= int(value) < (1 << int(count)):
        raise ValueError("Morph packed value exceeds its bit count.")
    end = int(cursor) + int(count)
    if len(buffer) < (end + 7) // 8:
        buffer.extend(b"\x00" * ((end + 7) // 8 - len(buffer)))
    for bit in range(int(count)):
        if (int(value) >> bit) & 1:
            position = int(cursor) + bit
            buffer[position >> 3] |= 1 << (position & 7)
    return end


def _anim_morph_read_bits(buffer, cursor, count):
    if not 0 <= int(count) <= 32 or int(cursor) < 0:
        raise ValueError("Invalid morph bit field.")
    if int(cursor) + int(count) > len(buffer) * 8:
        raise ValueError("Morph bit data is truncated.")
    if not count:
        return 0
    start = int(cursor) // 8
    end = (int(cursor) + int(count) + 7) // 8
    return (int.from_bytes(buffer[start:end], "little") >> (int(cursor) & 7)) & ((1 << int(count)) - 1)


def encode_anim_morph(targets, samples, name_offset_base=0):
    """Return rebuilt morph blocks, string bytes and target metadata.

    Input columns follow targets; output targets are sorted by unsigned hash,
    as required by the native blend/lookup code. All-zero tracks are omitted.
    """
    if not samples or not targets:
        return None
    if any(len(row) != len(targets) for row in samples):
        raise ValueError("Morph samples do not match the target table.")
    if any(not math.isfinite(float(value)) for row in samples for value in row):
        raise ValueError("Shape-key values must be finite.")
    active = [i for i in range(len(targets)) if any(float(row[i]) != 0.0 for row in samples)]
    if not active:
        return None
    active.sort(key=lambda i: int(targets[i]["hash"]) & 0xffffffff)
    if len(active) > ANIM_MORPH_TARGET_LIMIT:
        raise ValueError(f"An AnimClip supports at most {ANIM_MORPH_TARGET_LIMIT} morph targets in this exporter.")
    ordered = [targets[i] for i in active]
    hashes = [int(target["hash"]) & 0xffffffff for target in ordered]
    if len(set(hashes)) != len(hashes) or 0xffffffff in hashes:
        raise ValueError("Morph target hashes collide or use the engine's sentinel.")
    rows = [[float(row[i]) for i in active] for row in samples]
    minimum = min(0.0, min(value for row in rows for value in row))
    maximum = max(0.0, max(value for row in rows for value in row))
    # Serialized values are float32, so quantize against those exact bounds.
    scale = struct.unpack("<f", struct.pack("<f", maximum - minimum))[0]
    offset = struct.unpack("<f", struct.pack("<f", minimum))[0]
    if not math.isfinite(scale) or scale <= 0.0 or not math.isfinite(offset):
        raise ValueError("Shape-key value range is outside the native float32 format.")
    quant_max = (1 << ANIM_MORPH_WEIGHT_BITS) - 1
    # Keep zero entries too. This prevents a target disappearing at a keyframe
    # and preserves one shared quantization range across signed weights.
    count = len(ordered)
    count_bits = max(1, count.bit_length())
    base_bits = 1  # Every frame begins with target index zero.
    step_bits = 1  # Dense ascending target indices, incremented by one.
    frame_data = bytearray()
    word_offsets = []
    for row in rows:
        word_offsets.append(len(frame_data) // 4)
        packed = bytearray()
        cursor = 0
        for index, value in enumerate(row):
            cursor = _anim_morph_write_bits(packed, cursor, 0 if index == 0 else 1,
                                           base_bits if index == 0 else step_bits)
            quant = max(0, min(quant_max, int(math.floor(((value - offset) / scale) * quant_max + 0.5))))
            cursor = _anim_morph_write_bits(packed, cursor, quant, ANIM_MORPH_WEIGHT_BITS)
        packed.extend(b"\x00" * ((-len(packed)) & 3))
        frame_data.extend(packed)
    offset_bits = max(1, max(word_offsets).bit_length())
    if offset_bits > 32:
        raise ValueError("Morph frame data exceeds the native offset range.")
    lookup = bytearray()
    cursor = 0
    for word_offset in word_offsets:
        cursor = _anim_morph_write_bits(lookup, cursor, count, count_bits)
        cursor = _anim_morph_write_bits(lookup, cursor, word_offset, offset_bits)
    lookup.extend(b"\x00" * ((-len(lookup)) & 3))
    names = bytearray()
    name_offsets = []
    for target in ordered:
        raw = str(target["name"]).encode("ascii")
        if not raw or len(raw) > 127 or b"\x00" in raw:
            raise ValueError("Morph names must contain 1–127 ASCII characters.")
        name_offsets.append(int(name_offset_base) + len(names))
        names.extend(raw + b"\x00")
    info = struct.pack(ANIM_MORPH_INFO_FORMAT, count, scale, offset,
                       count_bits, offset_bits, base_bits, step_bits,
                       ANIM_MORPH_WEIGHT_BITS, len(lookup))
    info += struct.pack(f"<{count}I", *hashes)
    info += struct.pack(f"<{count}I", *name_offsets)
    info += bytes(lookup)
    return {"info": info, "frame_data": bytes(frame_data), "strings": bytes(names),
            "targets": [{"name": item["name"], "hash": int(item["hash"]) & 0xffffffff} for item in ordered],
            "sample_count": len(rows), "quantization_error_bound": scale / quant_max / 2.0}


def decode_anim_morph(info, frame_data, sample_count, strings=None):
    """Decode native packed morph weights, with strict section bounds checks."""
    if len(info) < ANIM_MORPH_INFO_SIZE:
        raise ValueError("AnimClipMorphInfo is truncated.")
    count, scale, offset, count_bits, offset_bits, base_bits, step_bits, weight_bits, lookup_size = struct.unpack_from(ANIM_MORPH_INFO_FORMAT, info)
    if not 0 < count <= 4096 or not 0 < weight_bits <= 15:
        raise ValueError("Unsupported morph target count or weight precision.")
    if any(not 0 <= bits <= 32 for bits in (count_bits, offset_bits, base_bits, step_bits)):
        raise ValueError("Invalid morph lookup/index precision.")
    if not math.isfinite(scale) or scale <= 0 or not math.isfinite(offset):
        raise ValueError("Invalid morph weight scale/offset.")
    lookup_start = ANIM_MORPH_INFO_SIZE + count * 8
    if lookup_start + lookup_size > len(info):
        raise ValueError("Morph target tables or lookup are truncated.")
    hashes = list(struct.unpack_from(f"<{count}I", info, ANIM_MORPH_INFO_SIZE))
    offsets = list(struct.unpack_from(f"<{count}I", info, ANIM_MORPH_INFO_SIZE + count * 4))
    if hashes != sorted(set(hashes)) or 0xffffffff in hashes:
        raise ValueError("Morph target hashes must be unique and sorted.")
    lookup = info[lookup_start:lookup_start + lookup_size]
    if int(sample_count) * (count_bits + offset_bits) > lookup_size * 8:
        raise ValueError("Morph frame lookup does not contain all clip samples.")
    names = []
    for index, name_offset in enumerate(offsets):
        name = f"Morph_{hashes[index]:08X}"
        if strings is not None:
            if name_offset >= len(strings):
                raise ValueError("Morph name offset exceeds the string buffer.")
            end = strings.find(b"\x00", name_offset)
            if end < 0:
                raise ValueError("Morph target name is not terminated.")
            name = strings[name_offset:end].decode("ascii")
        names.append(name)
    rows = []
    quant_scale = scale / ((1 << weight_bits) - 1)
    for frame in range(int(sample_count)):
        cursor = frame * (count_bits + offset_bits)
        frame_count = _anim_morph_read_bits(lookup, cursor, count_bits)
        word_offset = _anim_morph_read_bits(lookup, cursor + count_bits, offset_bits)
        if frame_count > count:
            raise ValueError("Morph frame target count exceeds its target table.")
        cursor = word_offset * 32
        row = [0.0] * count
        index = 0
        for item in range(frame_count):
            bits = base_bits if item == 0 else step_bits
            step = _anim_morph_read_bits(frame_data, cursor, bits)
            cursor += bits
            index = step if item == 0 else index + step
            if index >= count or (item > 0 and step == 0):
                raise ValueError("Morph frame target indices are invalid.")
            quant = _anim_morph_read_bits(frame_data, cursor, weight_bits)
            cursor += weight_bits
            row[index] = quant * quant_scale + offset
        rows.append(row)
    return {"targets": [{"name": name, "hash": h} for name, h in zip(names, hashes)],
            "samples": rows, "weight_scale": scale, "weight_offset": offset}


def collect_anim_morph_targets(arm):
    """Use the same mesh shape-key names/hashes as model export."""
    targets = {}
    for obj in bpy.data.objects:
        if obj.type != 'MESH' or obj.get("engine_bounds_type", "") == "subset_aabb":
            continue
        belongs = obj.parent == arm or any(mod.type == 'ARMATURE' and mod.object == arm for mod in obj.modifiers)
        if not belongs:
            continue
        keys = obj.data.shape_keys
        if keys is None or len(keys.key_blocks) <= 1:
            continue
        if not keys.use_relative:
            raise ValueError(f"{obj.name}: use relative shape keys for native morph animation.")
        try:
            metadata = json.loads(str(obj.get("engine_morph_targets_json", "{}") or "{}"))
        except Exception:
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        basis = keys.key_blocks[0]
        for key in list(keys.key_blocks)[1:]:
            if metadata and key.name not in metadata:
                continue  # Match the model exporter's imported-target selection.
            if key.relative_key != basis or key.vertex_group:
                raise ValueError(f"{obj.name}/{key.name}: use Basis as Relative To and no shape-key vertex group.")
            if len(key.data) != len(basis.data):
                raise ValueError(f"{obj.name}/{key.name}: shape-key vertex count differs from Basis.")
            if not any((point.co - basis.data[i].co).length > 1e-8 for i, point in enumerate(key.data)):
                continue
            stored = metadata.get(key.name, {})
            name = str(stored.get("name", key.name)) if isinstance(stored, dict) else key.name
            name_hash = int(stored.get("hash", string_crc32(name))) & 0xffffffff if isinstance(stored, dict) else string_crc32(name)
            previous = targets.get(name_hash)
            if previous is not None and previous["name"] != name:
                raise ValueError(f"Morph name hash collision: {previous['name']!r} and {name!r}.")
            target = targets.setdefault(name_hash, {"name": name, "hash": name_hash, "keys": []})
            target["keys"].append((obj, key))
    return [targets[h] for h in sorted(targets)]


def armature_has_morph_animation(arm):
    for target in collect_anim_morph_targets(arm):
        for obj, key in target["keys"]:
            anim = obj.data.shape_keys.animation_data
            if anim and (anim.action or anim.nla_tracks or anim.drivers):
                return True
    return False


def sample_anim_morph_values(targets):
    row = []
    for target in targets:
        values = [0.0 if key.mute else float(key.value) for obj, key in target["keys"]]
        if any(not math.isfinite(value) for value in values):
            raise ValueError(f"{target['name']}: shape-key value is not finite.")
        if values and max(values) - min(values) > 1e-6:
            raise ValueError(f"{target['name']}: keys with this name on different meshes need matching values. Rename independent shapes.")
        row.append(values[0] if values else 0.0)
    return row


def import_anim_morph_keys(arm, morph, fps, clip_name, frame_rate=None):
    """Give each mesh Key datablock its own Blender action (standard workflow)."""
    existing = {target["hash"]: target for target in collect_anim_morph_targets(arm)}
    actions = {}
    missing = []
    rows = morph["samples"]
    for column, target in enumerate(morph["targets"]):
        matching = existing.get(target["hash"])
        if matching is None:
            missing.append(target["name"])
            continue
        values = [float(row[column]) for row in rows]
        for obj, key in matching["keys"]:
            keys = obj.data.shape_keys
            if keys not in actions:
                action = bpy.data.actions.new(f"{clip_name} - {obj.name} Shape Keys")
                action.use_fake_user = True
                keys.animation_data_create()
                keys.animation_data.action = action
                actions[keys] = action
            try:
                key.driver_remove("value")
            except Exception:
                pass
            key.mute = False
            key.slider_min = min(float(key.slider_min), min(values))
            key.slider_max = max(float(key.slider_max), max(values))
            action = actions[keys]
            path = key.path_from_id("value")
            if hasattr(action, "fcurve_ensure_for_datablock"):
                curve = action.fcurve_ensure_for_datablock(datablock=keys, data_path=path, index=0)
            else:
                curve = action.fcurves.new(data_path=path, index=0)
            curve.keyframe_points.add(len(values))
            co = []
            for frame, value in enumerate(values):
                co.extend((float(frame) * (float(frame_rate or fps) / float(fps)), value))
            curve.keyframe_points.foreach_set("co", co)
            for point in curve.keyframe_points:
                point.interpolation = 'LINEAR'
            curve.update()
            # Same seconds as the resident rig, even if morph samples are finer.
            if fps > 0:
                action["engine_morph_sample_fps"] = float(fps)
    return len(morph["targets"]) - len(missing), missing, actions
