"""
<summary>
  module: _scsp21_anim
  purpose: animation-timeline parser for Epic Seven SCSP 2.1.27.
           ported from nORb Dragon's epic7_scsp2json v1.0
           (_epic7_scsp2json_v2_1_27.py:_scsp_readAnimations) with corrected
           sentinels and Spine 2.1 JSON output shape.

  contents:
    read_animations  - read all animations between current stream position and
                       the end of the binary block; resolves bone/slot/skin
                       references by index into the lists produced by
                       Scsp21Reader.
</summary>
"""

from __future__ import annotations

import re
import struct
from collections import OrderedDict
from typing import Any

from _scsp21_reader import NO_STRING, Scsp21Reader, _color_hex, _round_compact

TIMELINE_SCALE = 0
TIMELINE_ROTATE = 1
TIMELINE_TRANSLATE = 2
TIMELINE_COLOR = 3
TIMELINE_ATTACHMENT = 4
TIMELINE_EVENT = 5
TIMELINE_DRAWORDER = 6
TIMELINE_FFD = 7
TIMELINE_IK = 8
TIMELINE_FLIPX = 9
TIMELINE_FLIPY = 10
CURVE_LINEAR = 0
CURVE_STEPPED = 1
CURVE_BEZIER = 2
CURVE_NONE_SENTINELS = (0xFFFE, 0xFFFF)
_ANIM_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_MAX_TIMELINE_ITEMS = 2000


def _looks_like_animation_header(reader: Scsp21Reader, pos: int, pos_end: int) -> bool:
    """True when ``pos`` looks like ``name_ptr / pad / item_count / first mode``."""
    if pos + 16 > pos_end:
        return False
    name_ptr = struct.unpack_from("<I", reader.data, pos)[0]
    if name_ptr == 0:
        item_count = struct.unpack_from("<I", reader.data, pos + 8)[0]
        return item_count == 0
    if name_ptr >= reader.strings_size:
        return False
    name = reader.get_string(name_ptr)
    if not name or len(name) > 48 or not _ANIM_NAME_RE.match(name):
        return False
    if reader.skeleton_hash and name == reader.skeleton_hash:
        return False
    item_count = struct.unpack_from("<I", reader.data, pos + 8)[0]
    if not (1 <= item_count <= _MAX_TIMELINE_ITEMS):
        return False
    if pos + 12 + item_count * 8 > pos_end:
        return False
    mode = struct.unpack_from("<I", reader.data, pos + 12)[0]
    return mode <= TIMELINE_FLIPY


def _quick_validate_first_timeline(
    reader: Scsp21Reader,
    pos: int,
    pos_end: int,
    bones: list[OrderedDict[str, Any]],
    slots: list[OrderedDict[str, Any]],
) -> bool:
    """Cheap check that the first timeline entry after a header looks sane."""
    if pos + 20 > pos_end:
        return False
    mode = struct.unpack_from("<I", reader.data, pos + 12)[0]
    if mode > TIMELINE_FLIPY:
        return False
    if mode in (TIMELINE_SCALE, TIMELINE_ROTATE, TIMELINE_TRANSLATE, TIMELINE_FLIPX, TIMELINE_FLIPY):
        bone_idx = struct.unpack_from("<I", reader.data, pos + 16)[0]
        return 0 <= bone_idx < len(bones)
    if mode in (TIMELINE_COLOR, TIMELINE_ATTACHMENT):
        slot_idx = struct.unpack_from("<I", reader.data, pos + 16)[0]
        return 0 <= slot_idx < len(slots)
    if mode == TIMELINE_FFD:
        frame_count = struct.unpack_from("<I", reader.data, pos + 16)[0]
        return 0 < frame_count <= 10000
    return True


def _parse_animation_at(
    reader: Scsp21Reader,
    pos: int,
    pos_end: int,
    bones: list[OrderedDict[str, Any]],
    slots: list[OrderedDict[str, Any]],
    ffd_index: list[dict[str, Any]],
) -> tuple[str, OrderedDict[str, Any], int] | None:
    """Try to parse one animation at ``pos``; return ``(name, anim, end_pos)``."""
    saved_pos = reader.pos
    if not _looks_like_animation_header(reader, pos, pos_end):
        return None
    name_ptr = struct.unpack_from("<I", reader.data, pos)[0]
    item_count = struct.unpack_from("<I", reader.data, pos + 8)[0]
    if name_ptr == 0 and item_count == 0:
        return "", OrderedDict(), pos + 12
    if not _quick_validate_first_timeline(reader, pos, pos_end, bones, slots):
        reader.pos = saved_pos
        return None
    anim_name = reader.get_string(name_ptr)
    reader.pos = pos + 12
    anim: OrderedDict[str, Any] = OrderedDict()
    try:
        for _ in range(item_count):
            if reader.pos + 4 > pos_end:
                raise ValueError("truncated animation timeline")
            mode = reader.u32()
            if mode > TIMELINE_FLIPY:
                raise ValueError(f"unsupported timeline mode {mode}")
            _read_timeline(reader, mode, bones, slots, ffd_index, anim)
    except (ValueError, struct.error):
        reader.pos = saved_pos
        return None
    if not anim_name or not anim:
        reader.pos = saved_pos
        return None
    return anim_name, anim, reader.pos


def _find_next_animation(
    reader: Scsp21Reader,
    start: int,
    pos_end: int,
    bones: list[OrderedDict[str, Any]],
    slots: list[OrderedDict[str, Any]],
    ffd_index: list[dict[str, Any]],
    *,
    scan_limit: int = 128,
) -> tuple[str, OrderedDict[str, Any], int] | None:
    """Scan forward from ``start`` for the next valid animation or empty sentinel."""
    scan_end = min(pos_end - 12, start + scan_limit)
    pos = start
    while pos <= scan_end:
        if _looks_like_animation_header(reader, pos, pos_end):
            parsed = _parse_animation_at(
                reader, pos, pos_end, bones, slots, ffd_index
            )
            if parsed is not None:
                return parsed
        pos += 1
    return None


def read_animations(
    reader: Scsp21Reader,
    bones: list[OrderedDict[str, Any]],
    slots: list[OrderedDict[str, Any]],
    ffd_index: list[dict[str, Any]],
) -> OrderedDict[str, Any]:
    animations: OrderedDict[str, Any] = OrderedDict()
    if reader.animations_count <= 0:
        return animations
    pos_end = 8 + reader.data_size
    if reader.pos >= pos_end:
        return animations
    reader.skip(4)  # leading sentinel before first animation
    while len(animations) < reader.animations_count and reader.pos < pos_end:
        scan_limit = pos_end - reader.pos if not animations else 256
        parsed = _find_next_animation(
            reader, reader.pos, pos_end, bones, slots, ffd_index, scan_limit=scan_limit
        )
        if parsed is None:
            break
        anim_name, anim, end_pos = parsed
        reader.pos = end_pos
        if not anim_name:
            continue
        animations[anim_name] = anim
    return animations


def _read_timeline(
    reader: Scsp21Reader,
    mode: int,
    bones: list[OrderedDict[str, Any]],
    slots: list[OrderedDict[str, Any]],
    ffd_index: list[dict[str, Any]],
    anim: OrderedDict[str, Any],
) -> None:
    if mode == TIMELINE_SCALE:
        _read_bone_xy_timeline(reader, bones, anim, key="scale", default=1.0)
    elif mode == TIMELINE_ROTATE:
        _read_bone_rotate(reader, bones, anim)
    elif mode == TIMELINE_TRANSLATE:
        _read_bone_xy_timeline(reader, bones, anim, key="translate", default=0.0)
    elif mode == TIMELINE_COLOR:
        _read_slot_color(reader, slots, anim)
    elif mode == TIMELINE_ATTACHMENT:
        _read_slot_attachment(reader, slots, anim)
    elif mode == TIMELINE_FFD:
        _read_ffd(reader, ffd_index, anim)
    elif mode == TIMELINE_DRAWORDER:
        _read_draw_order(reader, slots, anim)
    elif mode == TIMELINE_IK:
        _read_ik(reader, bones, anim)
    elif mode == TIMELINE_FLIPX:
        _read_bone_flip(reader, bones, anim, key="flipX", field="x")
    elif mode == TIMELINE_FLIPY:
        _read_bone_flip(reader, bones, anim, key="flipY", field="y")
    elif mode == TIMELINE_EVENT:
        _read_event(reader, anim)
    else:
        raise ValueError(f"unsupported timeline mode {mode} at pos {reader.pos}")


def _read_bone_xy_timeline(
    reader: Scsp21Reader,
    bones: list[OrderedDict[str, Any]],
    anim: OrderedDict[str, Any],
    *,
    key: str,
    default: float,
) -> None:
    del default
    bone_idx = reader.u32()
    frame_count = reader.u32() // 3
    entries: list[OrderedDict[str, Any]] = []
    for _ in range(frame_count):
        time = _round_compact(reader.f32(), 4)
        x = _round_compact(reader.f32(), 4)
        y = _round_compact(reader.f32(), 4)
        entry: OrderedDict[str, Any] = OrderedDict()
        entry["time"] = time
        entry["x"] = x
        entry["y"] = y
        entries.append(entry)
    _attach_curves(reader, entries)
    _store_bone_timeline(anim, bones, bone_idx, key, entries)


def _read_bone_rotate(
    reader: Scsp21Reader,
    bones: list[OrderedDict[str, Any]],
    anim: OrderedDict[str, Any],
) -> None:
    bone_idx = reader.u32()
    frame_count = reader.u32() // 2
    entries: list[OrderedDict[str, Any]] = []
    for _ in range(frame_count):
        time = _round_compact(reader.f32(), 4)
        angle = _round_compact(reader.f32(), 4)
        entry: OrderedDict[str, Any] = OrderedDict()
        entry["time"] = time
        entry["angle"] = angle
        entries.append(entry)
    _attach_curves(reader, entries)
    _store_bone_timeline(anim, bones, bone_idx, "rotate", entries)


def _read_slot_color(
    reader: Scsp21Reader,
    slots: list[OrderedDict[str, Any]],
    anim: OrderedDict[str, Any],
) -> None:
    slot_idx = reader.u32()
    frame_count = reader.u32() // 5
    entries: list[OrderedDict[str, Any]] = []
    for _ in range(frame_count):
        time = _round_compact(reader.f32(), 4)
        color = _color_hex(reader.f32(), reader.f32(), reader.f32(), reader.f32())
        entry: OrderedDict[str, Any] = OrderedDict()
        entry["time"] = time
        entry["color"] = color
        entries.append(entry)
    _attach_curves(reader, entries)
    _store_slot_timeline(anim, slots, slot_idx, "color", entries)


def _read_slot_attachment(
    reader: Scsp21Reader,
    slots: list[OrderedDict[str, Any]],
    anim: OrderedDict[str, Any],
) -> None:
    slot_idx = reader.u32()
    frame_count = reader.u32()
    times = [_round_compact(reader.f32(), 4) for _ in range(frame_count)]
    names: list[str | None] = []
    for _ in range(frame_count):
        ptr = reader.u32()
        if 0 <= ptr < reader.strings_size:
            names.append(reader.get_string(ptr))
        else:
            names.append(None)
    entries = [OrderedDict([("time", t), ("name", n)]) for t, n in zip(times, names)]
    _store_slot_timeline(anim, slots, slot_idx, "attachment", entries)


def _read_bone_flip(
    reader: Scsp21Reader,
    bones: list[OrderedDict[str, Any]],
    anim: OrderedDict[str, Any],
    *,
    key: str,
    field: str,
) -> None:
    """Read flipX / flipY (Spine 2.1 modes 9 / 10).

    Layout: ``bone_idx``, ``frame_count`` (may be 0), ``total_floats``
    (= ``frame_count * 2``), then ``total_floats // 2`` pairs of
    ``(time f32, flip f32)``.  No curve section.
    """
    bone_idx = reader.u32()
    reader.u32()  # frame_count; total_floats is authoritative
    total_floats = reader.u32()
    frame_count = total_floats // 2
    entries: list[OrderedDict[str, Any]] = []
    for _ in range(frame_count):
        time = _round_compact(reader.f32(), 4)
        flip = bool(int(reader.f32()))
        entry: OrderedDict[str, Any] = OrderedDict()
        entry["time"] = time
        entry[field] = flip
        entries.append(entry)
    _store_bone_timeline(anim, bones, bone_idx, key, entries)


def _order_permutation_to_offsets(
    order: list[int],
    slots: list[OrderedDict[str, Any]],
) -> list[OrderedDict[str, Any]]:
    pairs: list[tuple[int, int]] = []
    slot_total = len(slots)
    for new_index, slot_index in enumerate(order):
        if slot_index < 0 or slot_index >= slot_total:
            continue
        if new_index != slot_index:
            pairs.append((slot_index, new_index))
    pairs.sort(key=lambda item: item[0])
    offsets: list[OrderedDict[str, Any]] = []
    for slot_index, new_index in pairs:
        entry: OrderedDict[str, Any] = OrderedDict()
        entry["slot"] = slots[slot_index]["name"]
        entry["offset"] = new_index - slot_index
        offsets.append(entry)
    return offsets


def _store_draw_order_entry(
    entries: list[OrderedDict[str, Any]],
    time: float,
    order: list[int] | None,
    slots: list[OrderedDict[str, Any]],
) -> None:
    entry: OrderedDict[str, Any] = OrderedDict()
    entry["time"] = time
    if order is not None:
        offsets = _order_permutation_to_offsets(order, slots)
        if offsets:
            entry["offsets"] = offsets
    entries.append(entry)


def _read_draw_order(
    reader: Scsp21Reader,
    slots: list[OrderedDict[str, Any]],
    anim: OrderedDict[str, Any],
) -> None:
    slot_count = reader.u32()
    frame_count = reader.u32()
    entries: list[OrderedDict[str, Any]] = []

    if frame_count == 1:
        time = _round_compact(reader.f32(), 4)
        order = None
        if reader.u8() == 1:
            order = [reader.u32() for _ in range(slot_count)]
        _store_draw_order_entry(entries, time, order, slots)
    else:
        times = [_round_compact(reader.f32(), 4) for _ in range(frame_count)]
        if reader.u16() == 0x0100:
            _store_draw_order_entry(entries, times[0], None, slots)
            for idx in range(1, frame_count):
                order = None
                if idx == 1:
                    order = [reader.u32() for _ in range(slot_count)]
                else:
                    flag = reader.u8()
                    if flag == 1:
                        order = [reader.u32() for _ in range(slot_count)]
                    elif flag not in (0, 1):
                        raise ValueError(
                            f"unsupported draworder frame flag {flag} at pos {reader.pos - 1}"
                        )
                _store_draw_order_entry(entries, times[idx], order, slots)
        else:
            reader.skip(-2)
            for idx in range(frame_count):
                flag = reader.u8()
                order = None
                if flag == 1:
                    order = [reader.u32() for _ in range(slot_count)]
                elif flag not in (0, 1):
                    raise ValueError(
                        f"unsupported draworder frame flag {flag} at pos {reader.pos - 1}"
                    )
                _store_draw_order_entry(entries, times[idx], order, slots)

    if entries:
        anim["draworder"] = entries


def _read_ik(
    reader: Scsp21Reader,
    bones: list[OrderedDict[str, Any]],
    anim: OrderedDict[str, Any],
) -> None:
    del bones
    ik_idx = reader.u32()
    frame_count = reader.u32() // 3
    entries: list[OrderedDict[str, Any]] = []
    for _ in range(frame_count):
        time = _round_compact(reader.f32(), 4)
        mix = _round_compact(reader.f32(), 4)
        bend = reader.f32()
        entry: OrderedDict[str, Any] = OrderedDict()
        entry["time"] = time
        entry["mix"] = mix
        entry["bendPositive"] = bend >= 0
        entries.append(entry)
    _attach_curves(reader, entries)
    ik_bucket = anim.setdefault("ik", OrderedDict())
    ik_bucket[str(ik_idx)] = entries


def _read_event(
    reader: Scsp21Reader,
    anim: OrderedDict[str, Any],
) -> None:
    frame_count = reader.u32()
    times = [_round_compact(reader.f32(), 4) for _ in range(frame_count)]
    entries: list[OrderedDict[str, Any]] = []
    event_names = reader.event_names
    for idx, time in enumerate(times):
        event_ref = reader.u32()
        if event_ref == NO_STRING:
            continue
        entry: OrderedDict[str, Any] = OrderedDict()
        entry["time"] = time
        if event_names and event_ref < len(event_names):
            entry["name"] = event_names[event_ref]
        elif 0 <= event_ref < reader.strings_size:
            name = reader.get_string(event_ref)
            if name:
                entry["name"] = name
        if "name" not in entry:
            continue
        entries.append(entry)
    if entries:
        anim["events"] = entries


def _read_ffd(
    reader: Scsp21Reader,
    ffd_index: list[dict[str, Any]],
    anim: OrderedDict[str, Any],
) -> None:
    """Read one FFD timeline.

    SCSP stores per-frame floats verbatim. For ``mesh`` attachments those
    floats are *absolute* mesh-vertex positions (frame 0 equals the setup
    pose), while Spine 2.1 JSON expects per-frame *deltas* that the runtime
    adds to the setup vertices. Without subtracting we'd ship the setup pose
    twice and the rendered mesh looks ~2x bigger (the c1004 1/mang / 1/bady_S1
    symptom). ``skinnedmesh`` attachments already store deltas in pre-skin
    space and are passed through.
    """
    frame_count = reader.u32()
    times = [_round_compact(reader.f32(), 4) for _ in range(frame_count)]
    reader.skip(4)
    floats_per_frame = reader.u32()
    frame_vertices: list[list[float]] = []
    for _ in range(frame_count):
        frame_vertices.append([reader.f32() for _ in range(floats_per_frame)])
    curves = _attach_curves_to_count(reader, frame_count)
    skin_record_id = reader.u32()

    if not (0 <= skin_record_id < len(ffd_index)):
        return
    target = ffd_index[skin_record_id]
    att_type = target.get("type")
    setup_verts = target.get("setup_vertices") if att_type == "mesh" else None

    entries: list[OrderedDict[str, Any]] = []
    for idx, time in enumerate(times):
        entry: OrderedDict[str, Any] = OrderedDict()
        entry["time"] = time
        verts = frame_vertices[idx]
        if setup_verts is not None and len(setup_verts) == len(verts):
            deltas = [
                _round_compact(verts[i] - setup_verts[i], 4)
                for i in range(len(verts))
            ]
        else:
            deltas = [_round_compact(v, 8) for v in verts]
        if any(v != 0 for v in deltas):
            entry["vertices"] = deltas
        if idx < len(curves) and curves[idx] is not None:
            entry["curve"] = curves[idx]
        entries.append(entry)

    ffd_bucket = anim.setdefault("ffd", OrderedDict())
    skin_bucket = ffd_bucket.setdefault(target["skin"], OrderedDict())
    slot_bucket = skin_bucket.setdefault(target["slot"], OrderedDict())
    slot_bucket[target["attachment"]] = entries


def _attach_curves(reader: Scsp21Reader, entries: list[OrderedDict[str, Any]]) -> None:
    """Read per-entry curve bytes that trail a timeline.

    Layout (verified empirically on c1002 idle): always 2 leading bytes; if
    they decode to 0xFFFE/0xFFFF the section ends, otherwise read
    (len(entries) - 1) curve bytes where BEZIER (=2) is followed by 4 unused
    bytes plus 4 floats. The leading u16 is NOT reused as a curve byte.
    """
    if not entries:
        return
    if reader.u16() in CURVE_NONE_SENTINELS:
        return
    for entry_index in range(len(entries) - 1):
        curve = reader.u8()
        if curve == CURVE_STEPPED:
            entries[entry_index]["curve"] = "stepped"
        elif curve == CURVE_BEZIER:
            reader.skip(4)
            c1 = _round_compact(reader.f32(), 4)
            c2 = _round_compact(reader.f32(), 4)
            c3 = _round_compact(reader.f32(), 4)
            c4 = _round_compact(reader.f32(), 4)
            entries[entry_index]["curve"] = [c1, c2, c3, c4]
        elif curve != CURVE_LINEAR:
            raise ValueError(f"unknown curve byte {curve} at pos {reader.pos}")


def _attach_curves_to_count(reader: Scsp21Reader, count: int) -> list[Any]:
    curves: list[Any] = [None] * count
    if count == 0:
        return curves
    if reader.u16() in CURVE_NONE_SENTINELS:
        return curves
    for idx in range(count - 1):
        curve = reader.u8()
        if curve == CURVE_STEPPED:
            curves[idx] = "stepped"
        elif curve == CURVE_BEZIER:
            reader.skip(4)
            c1 = _round_compact(reader.f32(), 4)
            c2 = _round_compact(reader.f32(), 4)
            c3 = _round_compact(reader.f32(), 4)
            c4 = _round_compact(reader.f32(), 4)
            curves[idx] = [c1, c2, c3, c4]
        elif curve != CURVE_LINEAR:
            raise ValueError(f"unknown curve byte {curve} at pos {reader.pos}")
    return curves


def _store_bone_timeline(
    anim: OrderedDict[str, Any],
    bones: list[OrderedDict[str, Any]],
    bone_idx: int,
    key: str,
    entries: list[OrderedDict[str, Any]],
) -> None:
    if not (0 <= bone_idx < len(bones)):
        return
    bone_name = bones[bone_idx]["name"]
    bones_bucket = anim.setdefault("bones", OrderedDict())
    bone_bucket = bones_bucket.setdefault(bone_name, OrderedDict())
    bone_bucket[key] = entries


def _store_slot_timeline(
    anim: OrderedDict[str, Any],
    slots: list[OrderedDict[str, Any]],
    slot_idx: int,
    key: str,
    entries: list[OrderedDict[str, Any]],
) -> None:
    if not (0 <= slot_idx < len(slots)):
        return
    slot_name = slots[slot_idx]["name"]
    slots_bucket = anim.setdefault("slots", OrderedDict())
    slot_bucket = slots_bucket.setdefault(slot_name, OrderedDict())
    slot_bucket[key] = entries
