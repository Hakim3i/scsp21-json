# Epic Seven SCSP 2.1.27 binary format

Reverse-engineered from `libur.so` (Twistzz's IDA dump of
`spSkeletonData_createWithSCSP`) and nORb Dragon's `epic7_scsp2json v1.0`
Python parser, then verified empirically against 1154 model + portrait files
(220 portraits, 219 tagged-2.1 models, 935 untagged-2.1 models, including
`melissa` with a known good e7herder reference dump).

> **Important context.** The reference JSONs in `tools/e7herder/` were dumped
> from an older revision of Epic Seven. Several portraits have been re-exported
> since (e.g. `c1001` was bumped to `3.8.99.scsp`; `c1002` went from 172 bones
> to 180). We validate structural correctness + load in SpineViewer, not
> byte-for-byte parity with e7herder.

> **Two SCSP variants share this format.** Bones, slots, skins, events and
> animations bodies are byte-identical between the two. They differ only in
> the *header*:
>
> * **tagged** (post-2021-06-10): bytes 8..11 are the ASCII magic `"scsp"`,
>   12..15 hold `0x00000001`, header has a `header_size` field at +16 and a
>   variable-length sub-header. Skeleton hash + spine come from u32 string
>   offsets stored in that sub-header.
> * **untagged** (pre-2021-06-10): no magic; counts immediately follow the
>   two size fields, fixed 88-byte header, width/height at +72/+76, bones
>   start at +88. Skeleton hash + spine are the **first two null-terminated
>   strings** in the strings table.
>
> Both variants ship together inside `e7data/model` (and a handful inside
> `e7data/portrait`), so detection is done by sniffing for the `"scsp"`
> magic at +8 and falling back to the untagged shape when it's absent.

## Top-level wrapper

```
+----------------------+
| u32 data_size        |  byte 0  : size of the binary-data block
| u32 strings_size     |  byte 4  : size of the strings table
+----------------------+
| binary data ...      |  byte 8  : starts with the "scsp" magic
|                      |
+----------------------+  byte 8 + data_size : strings table begins here
| null-terminated      |
| strings ...          |
+----------------------+  byte 8 + data_size + strings_size : EOF
```

Verified on `c1002`: `data_size=171902`, `strings_size=5208`, total file
`177118` bytes.

## Strings table

Flat sequence of null-terminated UTF-8 strings. All `u32 *_ptr` fields below
are **byte offsets into this table** (not file offsets). The sentinel
`0xFFFFFFFF` means "no string".

## Binary header (file offsets 8..107)

The first 12 bytes of the data block are a fixed magic+version preamble.
The 16 bytes after that are an outer header (geometry); they are followed by
a variable-size sub-header whose length lives at offset 16.

```
+8    "scsp"                       (4 bytes magic)
+12   u32 version                  always 0x00000001 (= 2.1.27 SCSP)
+16   u32 header_size              clamped to 88 by libur; bones start at 28+header_size
+20   f32 width                    skeleton.width
+24   f32 height                   skeleton.height
+28   16 bytes                     skeleton bbox (x/y/x2/y2 floats)
+44   u32 bones_count              authoritative bone-record count
+48   u32 unknown_1                IK or transform constraints count (0 in all portraits we tested)
+52   u32 slots_count              authoritative slot-record count
+56   u32 skins_count              authoritative skin-record count (NOT events!)
+60   u32 events_count
+64   u32 animations_count         informational; the parser reads animations until EOF
+68   u32 unknown_2
+72   u32 hash_ptr        ╮
+76   u32 spine_ptr       │       string offsets for skeleton.hash / .spine
       ... padding ...    │       (the actual offsets depend on header_size,
+(28+header_size)-4       │        the field locations above are c1002-specific)
+(28+header_size)         ╯
```

For c1002: `header_size = 88`, bone data starts at file offset
`28 + 88 = 116`.

The `hash_ptr` and `spine_ptr` strings live at offsets
`8 + 12 + header_size` and `8 + 16 + header_size` respectively (i.e. just
*after* the variable sub-header).

### Untagged-variant header (pre-2021-06-10)

```
+0    u32 data_size
+4    u32 strings_size
+8    u32 bones_count
+12   u32 ik_count                (always 0 in everything we tested)
+16   u32 slots_count
+20   u32 skins_count
+24   u32 events_count            (always 0 in the files we tested)
+28   u32 animations_count
+32   40 bytes unknown
+72   f32 width
+76   f32 height
+80   8 bytes unknown
+88   bones array starts
```

`hash` and `spine` are the **first two null-terminated strings** in the
strings table (no pointers — positional). Verified on `melissa.scsp`
(234 bones, 88 slots, 1 skin with 185 attachments).

## Sub-section: bones (sequential, 46 bytes per record)

Starts at file offset `28 + header_size`. Records are **sequential** — bone
`i`'s transform lives in record `i`, not record `i-1`. The "phase-shifted
record" interpretation in earlier docs was a compensating bug; the actual
layout is straightforward.

| Offset | Type | Field | Notes |
|--------|------|-------|-------|
| 0      | f32  | `length`         | bone length |
| 4      | f32  | `x`              | local x |
| 8      | f32  | `y`              | local y |
| 12     | f32  | `rotation`       | degrees |
| 16     | f32  | `scaleX`         | default 1 |
| 20     | f32  | `scaleY`         | default 1 |
| 24     | i32  | `flipX`          | 0 = false (default), 1 = true |
| 28     | i32  | `flipY`          | 0 = false (default), 1 = true |
| 32     | i32  | `inheritScale`   | 1 = true (default), 0 = false |
| 36     | i32  | `inheritRotation`| 1 = true (default), 0 = false |
| 40     | u32  | `name_ptr`       | offset into strings table |
| 44     | u16  | `parent_idx`     | 0xFFFF = root (no parent) |

`bone[0]` is the root: zero-valued transforms, no parent. All Spine 2.1
default values are omitted in the JSON output to match the e7herder style.

## Sub-section: slots (sequential, 30 bytes per record)

Immediately follows the bone block. The slot count is exact (no early
termination needed).

| Offset | Type | Field | Notes |
|--------|------|-------|-------|
| 0      | u32  | `name_ptr`       | -> strings table |
| 4      | u16  | `bone_idx`       | index into bones array |
| 6      | u32  | `attachment_ptr` | strings-table offset; 0xFFFFFFFF = none |
| 10     | f32  | `color.r`        | default 1 |
| 14     | f32  | `color.g`        | default 1 |
| 18     | f32  | `color.b`        | default 1 |
| 22     | f32  | `color.a`        | default 1 |
| 26     | i32  | `blend_code`     | 0=normal, 1=additive, 2=multiply, 3=screen |

The slot record does **not** carry a dark-color field (that is a 3.8
extension).

## Sub-section: skins (deterministic, variable-size)

Immediately follows the slot block. The skin count comes from the header
field at +56. Each skin starts with:

| Offset | Type | Field | Notes |
|--------|------|-------|-------|
| 0 | u32 | `skin_name_ptr` | -> strings table |
| 4 | u16 | `sub_count`     | number of attachment sub-records in this skin |

After the 6-byte skin header come `sub_count` sub-records. Each sub-record
begins with a 20-byte common header followed by a type-specific body.

### Common sub-record header (20 bytes)

| Offset | Type | Field |
|--------|------|-------|
| 0  | u32 | `attachment_key_ptr` | the *key* under which the attachment is stored in `skin[slot]` |
| 4  | u32 | `slot_idx`           |
| 8  | u32 | `attachment_type`    | 0=region, 1=boundingbox, 2=mesh, 3=skinnedmesh |
| 12 | u32 | `record_name_ptr`    | attachment.name |
| 16 | u32 | `record_path_ptr`    | attachment.path |

### Type 0 (region) body — 132 bytes

```
f32 x, y, scaleX, scaleY, rotation
8 bytes unknown
f32 color.r, g, b, a
8 bytes unknown
i32 width, height
72 bytes unknown
```

### Type 1 (boundingbox) sub-record

Unlike every other attachment type, bbox sub-records **do not** carry a
`record_path_ptr` field; the 5th u32 of the sub-record header is reused as
the body's `vertex_floats_count` and the body is then just that many
floats. Layout for the whole sub-record:

```
u32 attachment_key_ptr
u32 slot_idx
u32 attachment_type             (= 1)
u32 record_name_ptr
u32 vertex_floats_count         (e.g. 8 for a 4-corner box)
f32 vertices[vertex_floats_count]
```

Verified on `melissa.scsp`: two boxes (`turn_box`, `bounding_box`) each
emit exactly 8 floats (4 corners) and the next sub-record's header lies
immediately after.

### Type 2 (mesh) body

```
u32 vertex_floats_count
f32 vertices[vertex_floats_count]
u32 hull
f32 uvs_part_b[vertex_floats_count]    # stored second but emitted first in JSON
f32 uvs_part_a[vertex_floats_count]
u32 triangle_count
u32 triangles[triangle_count]
f32 color.r, g, b, a
48 bytes unknown
f32 width, height
```

### Type 3 (skinnedmesh) body

```
u32 bone_stream_count                  # interleaved (count, bone_id*count) groups
i32 bone_stream[bone_stream_count]
u32 weight_count                       # interleaved (x, y, w) triplets
f32 weights[weight_count]
u32 triangle_count
u32 triangles[triangle_count]
u32 uv_pair_count
f32 uvs[uv_pair_count * 2]
u32 hull
f32 color.r, g, b, a
48 bytes unknown
f32 width, height
```

The bone-stream + weights pair is converted into Spine 2.1's interleaved
`vertices` array (`[n, b0_id, b0_x, b0_y, b0_w, b1_id, ...]`).

## Sub-section: events (sequential, 24 bytes per record)

| Offset | Type | Field |
|--------|------|-------|
| 0  | u32 | `name_ptr`    |
| 4  | i32 | `int_value`   |
| 8  | f32 | `float_value` |
| 12 | u32 | `string_ptr`  |
| 16 | 8 bytes | padding   |

The event count comes from the header field at +60. Portraits typically
have zero events.

## Sub-section: animations (until EOF)

Animations occupy everything from the end of the events block until the end
of the binary data (file offset `8 + data_size`). A 4-byte sentinel (= 0)
precedes the first animation. Each animation begins with:

```
u32 name_ptr
4 bytes (animation duration float; unused by the JSON output)
u32 item_count                # total number of timelines in this animation
```

Then `item_count` timeline items follow. Each timeline starts with a
`u32 timeline_mode`:

**Combat / multi-block layout:** portrait files use one contiguous stream.
Combat models (and some NPCs) store animations in one or more groups separated
by an **empty sentinel** (`name_ptr = 0`, `item_count = 0`, 12 bytes total).
After the sentinel the same header/timeline format resumes — this is not a
different binary encoding, only a logical split in the stream.

Between consecutive animation records the file may insert **padding** that is
not a multiple of four bytes (gaps of ~20–30 bytes are typical; up to ~100
bytes observed). Headers are therefore not guaranteed to sit on a 4-byte
boundary relative to the previous record end. The parser resyncs by scanning
forward (up to 256 bytes) for the next valid header.

Animation names in game data use **lowercase** identifiers (`idle`, `skill1`,
`knock_down`, …). The converter rejects uppercase names when resyncing so
bone/slot attachment strings and skeleton-hash metadata are not mistaken for
animation headers.

After the last animation, a short **trailing padding** block (often 10–110
bytes, sometimes all zeros/`0xFF` fill) may remain before `8 + data_size`.
This padding is not another animation record.

| Mode | Name        | Spec |
|------|-------------|------|
| 0    | scale       | bone xy timeline |
| 1    | rotate      | bone angle timeline |
| 2    | translate   | bone xy timeline |
| 3    | color       | slot RGBA timeline |
| 4    | attachment  | slot attachment swap |
| 7    | ffd         | per-skin/slot/attachment vertex deformations |

Modes 5 (flipX) and 6 (flipY) exist in the libur enum but have not been
observed in any portrait file.

### Bone xy timelines (modes 0 + 2)

```
u32 bone_idx
u32 total_floats              # = frame_count * 3
{ f32 time, f32 x, f32 y }[frame_count]
curve_section                 # see below
```

### Bone rotation timeline (mode 1)

```
u32 bone_idx
u32 total_floats              # = frame_count * 2
{ f32 time, f32 angle }[frame_count]
curve_section
```

### Slot color timeline (mode 3)

```
u32 slot_idx
u32 total_floats              # = frame_count * 5
{ f32 time, f32 r, f32 g, f32 b, f32 a }[frame_count]
curve_section
```

### Slot attachment timeline (mode 4)

```
u32 slot_idx
u32 frame_count
f32 times[frame_count]
u32 name_ptrs[frame_count]
# no curve section
```

### FFD timeline (mode 7)

```
u32 frame_count
f32 times[frame_count]
4 bytes unknown
u32 floats_per_frame
f32 frame_vertices[frame_count][floats_per_frame]
curve_section
u32 skin_record_id            # index into the flat list of skin sub-records
```

**Important semantic detail (mesh vs skinnedmesh):** the `frame_vertices`
floats are stored in different spaces depending on the target attachment:

- ``mesh``: **absolute** mesh-vertex positions. Frame 0 is exactly equal to
  the setup-pose ``vertices`` array; subsequent frames deform around it.
  Spine 2.1 JSON, however, expects FFD ``vertices`` to be **deltas** (the
  runtime adds them to the attachment's setup vertices). So when emitting
  JSON we must compute ``delta[i] = frame[i] - setup[i]``; otherwise the
  runtime double-adds the setup pose and meshes render about 2× their
  intended size (the c1004 `1/mang` / `1/bady_S1` "looks bigger" symptom).
- ``skinnedmesh``: per-influence ``(dx, dy)`` deltas in pre-skin local space,
  already in the format Spine 2.1 expects. Emit verbatim.

`_read_ffd` in `_scsp21_anim.py` performs this conversion using the
attachment type and setup-vertex array recorded in `ffd_index`.

### Curve section

A trailing block on every timeline that has a curve concept (i.e. everything
except attachment). Layout:

```
u16 marker
if marker == 0xFFFE or marker == 0xFFFF:
    no curves
else:
    for i in 0 .. (frame_count - 2):
        u8 curve_type
        if curve_type == 0: linear (no extra data)
        if curve_type == 1: stepped (no extra data)
        if curve_type == 2: bezier - 4 unused bytes + 4 floats (cx1, cy1, cx2, cy2)
```

The leading `u16` is consumed unconditionally; it is **not** reused as the
first curve byte. This was the single hardest field to figure out — every
prior parser either dropped curves entirely or misaligned on the first
bezier curve in `idle`.

## Validation summary

The reader at `_scsp21_reader.py` + animation parser at `_scsp21_anim.py`:

- Loads all 206 SCSP 2.1.27 portraits in `e7data/portrait/` without errors.
- Parses combat model animations including post-sentinel groups (e.g. wyvern
  21/21, achates 21/21) with block-2 combat clips (`skill1`, `knock_down`,
  `run`, …).
- Stops at or near `8 + data_size` after the last animation timeline; a
  small trailing padding block (≤ ~110 bytes) may remain on some combat files.
- Produces bone counts, slot counts, and per-bone transform values that match
  the e7herder reference for every portrait where the file has not been
  re-exported by the game team. Most divergences are `+1` bone (game added a
  helper bone in a patch) or shifted face-bone geometry.
- See [KNOWN_ISSUES.md](KNOWN_ISSUES.md) for documented visual mismatches that
  are not converter bugs.

## Anchors in EpicSeven.exe (Ghidra)

| Item | Address / function |
|------|--------------------|
| `SkeletoneSCSPLoader` RTTI string | `1417cb350` |
| `skinnedmesh` string (2.1 attachment name) | `1415b5078` |
| `inheritScale` string (2.1 bone field) | `1415b5058` |
| Main SCSP entry `loadData` | `FUN_140331110` |
| Bones reader | `FUN_140331df0` |
| Slots reader | `FUN_140335240` |
| IK reader | `FUN_1403324e0` |
| Skins reader | `FUN_140332df0` (contains the `cmp [r15+0xc], 0x7531` version branch) |
| Animations reader | `FUN_140331590` |
| Events reader | `FUN_140332070` |
