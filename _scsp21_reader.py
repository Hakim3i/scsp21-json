"""
<summary>
  module: _scsp21_reader
  purpose: stream parser for Epic Seven SCSP version 2.1.27 decompressed files.
           handles BOTH variants of Spine 2.1.27:
             * tagged (post-2021-06-10): 'scsp' magic at +8, version u32 at
               +12, dynamic header size, counts at fixed offsets after the
               header. ground truth: libur.so spSkeletonData_createWithSCSP.
             * untagged (pre-2021-06-10): no magic, counts immediately follow
               the two size fields, fixed 88-byte header, hash/spine are the
               first two null-terminated strings in the refStrings block.
               ground truth: nORb's _epic7_scsp2json_v2_1_27.py.
           bones/slots/skins/events/animations binary records are identical
           between the two variants; only the header differs.

  contents:
    Scsp21Reader  - holds buffer + cursor + string pool; emits skeleton/bones/
                    slots/skins/events; exposes the position after events so
                    the animation parser can stream the tail of the file.
    decompress    - LZ4 outer-wrapper unpack for *.scsp files.
    detect_2_1    - true when the buffer is any Spine 2.1.27 SCSP (tagged or
                    untagged).
    detect_variant - 'tagged' | 'untagged' | None.
</summary>
"""

from __future__ import annotations

import struct
from collections import OrderedDict
from typing import Any

SCSP_MAGIC = b"scsp"
VERSION_TAGGED = 0x00000001
VERSION_38 = 0x00007531
VARIANT_TAGGED = "tagged"
VARIANT_UNTAGGED = "untagged"
ATT_REGION = 0
ATT_BBOX = 1
ATT_MESH = 2
ATT_SKINNED = 3
BLEND_NAMES = {1: "additive", 2: "multiply", 3: "screen"}
NO_PARENT = 0xFFFF
NO_STRING = 0xFFFFFFFF


def decompress(raw: bytes) -> bytes:
    import lz4.block

    decomp_size, comp_len = struct.unpack_from("<II", raw, 0)
    return lz4.block.decompress(raw[8 : 8 + comp_len], uncompressed_size=decomp_size)


def detect_variant(data: bytes) -> str | None:
    """Return ``'tagged'``, ``'untagged'`` or ``None`` for the buffer.

    Both variants start with u32 data_size, u32 strings_size at offset 0..7.
    The tagged variant then has the ``scsp`` magic + version 0x00000001 at
    +8..+15. The untagged variant goes straight to bones_count at +8.

    Works with a header-only buffer (>= 88 bytes); does not require the full
    file. If the caller hands us the entire file we also assert that
    ``8 + data_size + strings_size`` matches the buffer length, otherwise
    we only sanity-check the counts.
    """
    if len(data) < 88:
        return None
    if data[8:12] == SCSP_MAGIC:
        version = struct.unpack_from("<I", data, 12)[0]
        return VARIANT_TAGGED if version == VERSION_TAGGED else None
    data_size, strings_size = struct.unpack_from("<II", data, 0)
    expected = 8 + data_size + strings_size
    if len(data) > 88 and len(data) != expected:
        return None
    bones_count, _ik, slots_count = struct.unpack_from("<III", data, 8)
    if not (0 < bones_count < 10_000) or not (0 < slots_count < 10_000):
        return None
    return VARIANT_UNTAGGED


def detect_2_1(data: bytes) -> bool:
    return detect_variant(data) is not None


def _color_hex(r: float, g: float, b: float, a: float) -> str:
    def chan(v: float) -> int:
        if v != v or v <= 0:
            return 0
        if v >= 1:
            return 255
        return int(round(v * 255))
    return f"{chan(r):02X}{chan(g):02X}{chan(b):02X}{chan(a):02X}"


def _round_compact(v: float, n: int) -> float | int:
    if v != v or v == float("inf") or v == float("-inf"):
        return 0
    r = round(v, n)
    if r == int(r):
        return int(r)
    return r


class Scsp21Reader:
    def __init__(self, data: bytes) -> None:
        if len(data) < 88:
            raise ValueError(f"buffer too small ({len(data)} bytes)")
        variant = detect_variant(data)
        if variant is None:
            raise ValueError("not a recognized Spine 2.1.27 SCSP buffer")

        data_size, strings_size = struct.unpack_from("<II", data, 0)
        if 8 + data_size + strings_size > len(data):
            raise ValueError(
                f"sizes do not fit: data={data_size} strings={strings_size} total={len(data)}"
            )

        self.data = data
        self.variant = variant
        self.data_size = data_size
        self.strings_size = strings_size
        self.strings_data = data[8 + data_size : 8 + data_size + strings_size]

        if variant == VARIANT_TAGGED:
            self.header_size = struct.unpack_from("<I", data, 16)[0]
            self.bone_data_start = 28 + self.header_size
            self.width = struct.unpack_from("<f", data, 20)[0]
            self.height = struct.unpack_from("<f", data, 24)[0]
            self.bones_count = struct.unpack_from("<I", data, 44)[0]
            self.slots_count = struct.unpack_from("<I", data, 52)[0]
            self.skins_count = struct.unpack_from("<I", data, 56)[0]
            self.events_count = struct.unpack_from("<I", data, 60)[0]
            self.animations_count = struct.unpack_from("<I", data, 64)[0]
        else:
            self.header_size = 0
            self.bone_data_start = 88
            self.bones_count = struct.unpack_from("<I", data, 8)[0]
            self.slots_count = struct.unpack_from("<I", data, 16)[0]
            self.skins_count = struct.unpack_from("<I", data, 20)[0]
            self.events_count = struct.unpack_from("<I", data, 24)[0]
            self.animations_count = struct.unpack_from("<I", data, 28)[0]
            self.width = struct.unpack_from("<f", data, 72)[0]
            self.height = struct.unpack_from("<f", data, 76)[0]

        self.pos = self.bone_data_start
        self.event_names: list[str] = []
        self.skeleton_hash: str = ""

    def u16(self) -> int:
        v = struct.unpack_from("<H", self.data, self.pos)[0]
        self.pos += 2
        return v

    def i16(self) -> int:
        v = struct.unpack_from("<h", self.data, self.pos)[0]
        self.pos += 2
        return v

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return v

    def i32(self) -> int:
        v = struct.unpack_from("<i", self.data, self.pos)[0]
        self.pos += 4
        return v

    def f32(self) -> float:
        v = struct.unpack_from("<f", self.data, self.pos)[0]
        self.pos += 4
        return v

    def u8(self) -> int:
        v = self.data[self.pos]
        self.pos += 1
        return v

    def skip(self, n: int) -> None:
        self.pos += n

    def get_string(self, ptr: int) -> str:
        if ptr == NO_STRING or ptr < 0 or ptr >= self.strings_size:
            return ""
        end = self.strings_data.find(b"\x00", ptr)
        if end < 0:
            end = self.strings_size
        return self.strings_data[ptr:end].decode("utf-8", errors="replace")

    def parse_skeleton(self) -> OrderedDict[str, Any]:
        if self.variant == VARIANT_TAGGED:
            hash_ptr = struct.unpack_from("<I", self.data, 8 + 12 + self.header_size)[0]
            spine_ptr = struct.unpack_from("<I", self.data, 8 + 16 + self.header_size)[0]
            hash_str = self.get_string(hash_ptr)
            spine_str = self.get_string(spine_ptr)
        else:
            parts = self.strings_data.split(b"\x00", 2)
            hash_str = parts[0].decode("utf-8", errors="replace") if len(parts) > 0 else ""
            spine_str = parts[1].decode("utf-8", errors="replace") if len(parts) > 1 else ""
        skeleton: OrderedDict[str, Any] = OrderedDict()
        skeleton["hash"] = hash_str
        skeleton["spine"] = spine_str
        skeleton["x"] = 0
        skeleton["y"] = 0
        skeleton["width"] = _round_compact(self.width, 2)
        skeleton["height"] = _round_compact(self.height, 2)
        skeleton["images"] = ""
        skeleton["audio"] = ""
        self.skeleton_hash = hash_str
        return skeleton

    def parse_bones(self) -> list[OrderedDict[str, Any]]:
        self.pos = self.bone_data_start
        bones: list[OrderedDict[str, Any]] = []
        for _ in range(self.bones_count):
            length = self.f32()
            x = self.f32()
            y = self.f32()
            rotation = self.f32()
            scale_x = self.f32()
            scale_y = self.f32()
            flip_x = self.i32()
            flip_y = self.i32()
            inh_scale = self.i32()
            inh_rot = self.i32()
            name_ptr = self.u32()
            parent_idx = self.u16()

            bone: OrderedDict[str, Any] = OrderedDict()
            bone["name"] = self.get_string(name_ptr) or "?"
            if parent_idx != NO_PARENT and 0 <= parent_idx < len(bones):
                bone["parent"] = bones[parent_idx]["name"]
            if abs(length) > 1e-3:
                bone["length"] = _round_compact(length, 2)
            if abs(x) > 1e-3:
                bone["x"] = _round_compact(x, 2)
            if abs(y) > 1e-3:
                bone["y"] = _round_compact(y, 2)
            if abs(rotation) > 1e-3:
                bone["rotation"] = _round_compact(rotation, 2)
            if abs(scale_x - 1.0) > 1e-3:
                bone["scaleX"] = _round_compact(scale_x, 3)
            if abs(scale_y - 1.0) > 1e-3:
                bone["scaleY"] = _round_compact(scale_y, 3)
            if flip_x:
                bone["flipX"] = True
            if flip_y:
                bone["flipY"] = True
            if not inh_scale:
                bone["inheritScale"] = False
            if not inh_rot:
                bone["inheritRotation"] = False
            bones.append(bone)
        return bones

    def parse_slots(self, bones: list[OrderedDict[str, Any]]) -> list[OrderedDict[str, Any]]:
        slots: list[OrderedDict[str, Any]] = []
        for _ in range(self.slots_count):
            name_ptr = self.u32()
            bone_idx = self.u16()
            attachment_ptr = self.u32()
            r, g, b, a = self.f32(), self.f32(), self.f32(), self.f32()
            blend_code = self.i32()

            slot: OrderedDict[str, Any] = OrderedDict()
            slot["name"] = self.get_string(name_ptr) or "?"
            if 0 <= bone_idx < len(bones):
                slot["bone"] = bones[bone_idx]["name"]
            else:
                slot["bone"] = bones[0]["name"] if bones else "root"
            attachment = self.get_string(attachment_ptr)
            if attachment:
                slot["attachment"] = attachment
            color = _color_hex(r, g, b, a)
            if color != "FFFFFFFF":
                slot["color"] = color
            blend = BLEND_NAMES.get(blend_code)
            if blend:
                slot["blend"] = blend
            slots.append(slot)
        return slots

    def parse_skins(
        self,
        slots: list[OrderedDict[str, Any]],
    ) -> tuple[OrderedDict[str, Any], list[dict[str, Any]]]:
        """Parse the skins block; return (skins dict, flat FFD index list).

        The FFD index list mirrors the in-stream order of sub-records so that
        animation FFD timelines can resolve their skin/slot/attachment names
        by integer index (matching libur's `skin_record_id`).
        """
        skins: OrderedDict[str, Any] = OrderedDict()
        ffd_index: list[dict[str, str]] = []
        for _ in range(self.skins_count):
            skin_name = self.get_string(self.u32()) or "default"
            sub_count = self.u16()
            slot_map: OrderedDict[str, OrderedDict[str, Any]] = OrderedDict()
            for _ in range(sub_count):
                att_key = self.get_string(self.u32())
                slot_idx = self.u32()
                att_type = self.u32()
                rec_name = self.get_string(self.u32())
                # bbox sub-records replace the path_ptr field with the
                # bounding-box vertex_floats_count, so we leave that u32 in
                # the stream for `_parse_bbox` to consume itself.
                rec_path = "" if att_type == ATT_BBOX else self.get_string(self.u32())
                slot_name = (
                    slots[slot_idx]["name"]
                    if 0 <= slot_idx < len(slots)
                    else (slots[0]["name"] if slots else "root")
                )
                att = self._parse_attachment(att_type, rec_name, rec_path)
                slot_bucket = slot_map.setdefault(slot_name, OrderedDict())
                slot_bucket[att_key or rec_name] = att
                ffd_entry: dict[str, Any] = {
                    "skin": skin_name,
                    "slot": slot_name,
                    "attachment": att_key or rec_name,
                    "type": att.get("type"),
                }
                if att.get("type") == "mesh":
                    ffd_entry["setup_vertices"] = list(att.get("vertices") or [])
                ffd_index.append(ffd_entry)
            skins[skin_name] = slot_map
        if "default" not in skins:
            skins["default"] = OrderedDict()
            skins.move_to_end("default", last=False)
        return skins, ffd_index

    def _parse_attachment(self, att_type: int, name: str, path: str) -> OrderedDict[str, Any]:
        if att_type == ATT_REGION:
            return self._parse_region(name, path)
        if att_type == ATT_BBOX:
            return self._parse_bbox(name, path)
        if att_type == ATT_MESH:
            return self._parse_mesh(name, path)
        if att_type == ATT_SKINNED:
            return self._parse_skinned(name, path)
        raise ValueError(f"unknown attachment type {att_type} at pos {self.pos}")

    def _parse_region(self, name: str, path: str) -> OrderedDict[str, Any]:
        x, y, scale_x, scale_y, rotation = (self.f32() for _ in range(5))
        self.skip(8)
        r, g, b, a = (self.f32() for _ in range(4))
        self.skip(8)
        width = self.i32()
        height = self.i32()
        self.skip(72)
        att: OrderedDict[str, Any] = OrderedDict()
        att["type"] = "region"
        att["name"] = name
        att["path"] = path or name
        if abs(x) > 1e-3:
            att["x"] = _round_compact(x, 2)
        if abs(y) > 1e-3:
            att["y"] = _round_compact(y, 2)
        att["scaleX"] = _round_compact(scale_x, 5)
        att["scaleY"] = _round_compact(scale_y, 5)
        if abs(rotation) > 1e-3:
            att["rotation"] = _round_compact(rotation, 4)
        att["width"] = float(width)
        att["height"] = float(height)
        color = _color_hex(r, g, b, a)
        if color != "FFFFFFFF":
            att["color"] = color
        att["regionWidth"] = float(width)
        att["regionHeight"] = float(height)
        att["regionOriginalWidth"] = float(width)
        att["regionOriginalHeight"] = float(height)
        return att

    def _parse_bbox(self, name: str, path: str) -> OrderedDict[str, Any]:
        floats_count = self.u32()
        vertices = [_round_compact(self.f32(), 5) for _ in range(floats_count)]
        att: OrderedDict[str, Any] = OrderedDict()
        att["type"] = "boundingbox"
        att["name"] = name
        att["path"] = path or name
        att["vertices"] = vertices
        return att

    def _parse_mesh(self, name: str, path: str) -> OrderedDict[str, Any]:
        vertex_floats = self.u32()
        vertices = [_round_compact(self.f32(), 5) for _ in range(vertex_floats)]
        hull = self.u32()
        uvs_part_b = [_round_compact(self.f32(), 8) for _ in range(vertex_floats)]
        uvs_part_a = [_round_compact(self.f32(), 8) for _ in range(vertex_floats)]
        uvs = uvs_part_a + uvs_part_b
        tri_count = self.u32()
        triangles = [self.u32() for _ in range(tri_count)]
        r, g, b, a = (self.f32() for _ in range(4))
        self.skip(48)
        width = _round_compact(self.f32(), 2)
        height = _round_compact(self.f32(), 2)
        att: OrderedDict[str, Any] = OrderedDict()
        att["type"] = "mesh"
        att["name"] = name
        att["path"] = path or name
        att["vertices"] = vertices
        att["uvs"] = uvs
        att["triangles"] = triangles
        att["hull"] = hull
        color = _color_hex(r, g, b, a)
        if color != "FFFFFFFF":
            att["color"] = color
        att["width"] = width
        att["height"] = height
        return att

    def _find_animation_block_start(self, search_from: int) -> int | None:
        """Return file offset of the 4-byte ``0xFFFFFFFF`` animation sentinel."""
        pos_end = 8 + self.data_size
        needles = (b"appear\x00", b"idle\x00", b"attacked\x00")
        for needle in needles:
            idx = self.strings_data.find(needle)
            if idx < 0:
                continue
            for off in range(search_from + 4, pos_end - 3):
                if struct.unpack_from("<I", self.data, off)[0] != idx:
                    continue
                sentinel = off - 4
                if sentinel >= search_from and struct.unpack_from(
                    "<I", self.data, sentinel
                )[0] == 0xFFFFFFFF:
                    return sentinel
        return None

    def _compact_events_plausible(self, block_start: int) -> bool:
        """True when ``block_start`` looks like the 16-byte event table."""
        hash_name = self.get_string(0)
        pos = block_start
        for _ in range(self.events_count):
            if pos + 16 > 8 + self.data_size:
                return False
            name_ptr = struct.unpack_from("<I", self.data, pos + 4)[0]
            name = self.get_string(name_ptr)
            if not name or len(name) > 48 or name == hash_name:
                return False
            pos += 16
        return True

    def parse_events(self) -> OrderedDict[str, Any]:
        """Read the events table that sits between skins and animations.

        Record size is inferred from the gap to the animation sentinel (16 or
        24 bytes). Tagged units and some untagged combat units use the compact
        16-byte layout::

          u32 int_flag (0 or 0xFFFFFFFF) / u32 name_ptr / u32 0 / u32 0

        The legacy untagged layout uses 24 bytes::

          u32 name_ptr / i32 int_value / f32 float_value / u32 string_ptr / 8 pad
        """
        events: OrderedDict[str, Any] = OrderedDict()
        if self.events_count <= 0:
            return events

        block_start = self.pos
        anim_start = self._find_animation_block_start(block_start)
        if anim_start is not None and anim_start > block_start:
            gap = anim_start - block_start
            if gap % self.events_count == 0:
                record_size = gap // self.events_count
            else:
                record_size = 24
        elif self._compact_events_plausible(block_start):
            record_size = 16
        else:
            record_size = 24

        for _ in range(self.events_count):
            if record_size == 16:
                _int_flag = self.u32()
                del _int_flag
                name = self.get_string(self.u32())
                self.skip(8)
                events[name or "?"] = OrderedDict()
            else:
                name = self.get_string(self.u32())
                int_value = self.i32()
                float_value = self.f32()
                string_ptr = self.u32()
                self.skip(8)
                entry: OrderedDict[str, Any] = OrderedDict()
                if int_value:
                    entry["int"] = int_value
                if abs(float_value) > 1e-6:
                    entry["float"] = _round_compact(float_value, 4)
                string_value = self.get_string(string_ptr)
                if string_value:
                    entry["string"] = string_value
                events[name or "?"] = entry
        self.event_names = list(events.keys())
        return events

    def _parse_skinned(self, name: str, path: str) -> OrderedDict[str, Any]:
        bone_stream_count = self.u32()
        bone_stream = [self.i32() for _ in range(bone_stream_count)]
        weight_count = self.u32()
        weights = [self.f32() for _ in range(weight_count)]
        tri_count = self.u32()
        triangles = [self.u32() for _ in range(tri_count)]
        uv_pairs = self.u32()
        uvs = [_round_compact(self.f32(), 8) for _ in range(uv_pairs * 2)]
        hull = self.u32()
        r, g, b, a = (self.f32() for _ in range(4))
        self.skip(48)
        width = _round_compact(self.f32(), 2)
        height = _round_compact(self.f32(), 2)
        vertices = _expand_skinned_vertices(bone_stream, weights)
        att: OrderedDict[str, Any] = OrderedDict()
        att["type"] = "skinnedmesh"
        att["name"] = name
        att["path"] = path or name
        if vertices:
            att["vertices"] = vertices
        att["uvs"] = uvs
        att["triangles"] = triangles
        att["hull"] = hull
        color = _color_hex(r, g, b, a)
        if color != "FFFFFFFF":
            att["color"] = color
        att["width"] = width
        att["height"] = height
        return att


def _expand_skinned_vertices(bone_stream: list[int], weights: list[float]) -> list[float]:
    """E7 bone-index stream + (x,y,w) triplets -> Spine 2.1 weighted vertices."""
    out: list[float] = []
    wi = 0
    i = 0
    while i < len(bone_stream):
        n = bone_stream[i]
        i += 1
        if n <= 0:
            break
        ids = bone_stream[i : i + n]
        i += n
        out.append(float(n))
        for bid in ids:
            x, y, w = weights[wi], weights[wi + 1], weights[wi + 2]
            wi += 3
            out.extend([float(bid), _round_compact(x, 5), _round_compact(y, 5), _round_compact(w, 5)])
    return out
