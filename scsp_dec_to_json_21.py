"""
<summary>
  module: scsp_dec_to_json_21
  purpose: public entry point that converts a decompressed Epic Seven SCSP
           2.1.27 buffer into a Spine 2.1 JSON skeleton. orchestrates
           Scsp21Reader (header/bones/slots/skins) and the animation parser.

  contents:
    convert                            - bytes -> Spine 2.1 JSON dict
    convert_file                       - read file, write *.json next to it
    batch_convert_decompressed_files   - walk a directory, convert every 2.1
    VERSION_2_1 / VERSION_3_8          - kept for backward compatibility with
                                         scripts/scsp_convert.py
</summary>
"""

from __future__ import annotations

import json
import os
from collections import OrderedDict
from typing import Any

import lz4_processor
from _scsp21_anim import read_animations
from _scsp21_reader import SCSP_MAGIC, Scsp21Reader, VERSION_TAGGED, detect_2_1

VERSION_2_1 = VERSION_TAGGED
VERSION_3_8 = 0x00007531


def load_scsp_bytes(path: str | os.PathLike[str]) -> bytes:
    """Read decompressed SCSP bytes from ``*.scsp.decompressed`` or decompress ``*.scsp``."""
    path = os.fspath(path)
    lower = path.lower()
    if lower.endswith(".decompressed"):
        with open(path, "rb") as f:
            return f.read()
    if lower.endswith(".scsp"):
        return lz4_processor.decompress_to_bytes(path)
    raise ValueError(f"expected .scsp or .scsp.decompressed, got: {path}")


def convert(
    data: bytes,
    atlas_path: str | os.PathLike[str] | None = None,
    *,
    include_animations: bool = True,
) -> OrderedDict[str, Any]:
    """Parse decompressed SCSP 2.1 bytes; ``atlas_path`` is accepted for
    backward compatibility with the previous heuristic parser but is no
    longer needed (the new reader is deterministic). Pass
    ``include_animations=False`` to emit the skeleton/bones/slots/skins/events
    only (animations dict is still present but empty, which Spine 2.1 accepts).
    """
    del atlas_path
    reader = Scsp21Reader(data)
    skeleton = reader.parse_skeleton()
    bones = reader.parse_bones()
    slots = reader.parse_slots(bones)
    skins, ffd_index = reader.parse_skins(slots)
    events = reader.parse_events()
    expected_animations = reader.animations_count
    if include_animations:
        try:
            animations = read_animations(reader, bones, slots, ffd_index)
        except Exception:
            animations = OrderedDict()
    else:
        animations = OrderedDict()

    out: OrderedDict[str, Any] = OrderedDict()
    out["skeleton"] = skeleton
    if include_animations and expected_animations > 0 and not animations:
        skeleton["_animations_unavailable"] = True
    out["bones"] = bones
    out["slots"] = slots
    out["skins"] = skins
    if events:
        out["events"] = events
    out["animations"] = animations
    return out


def _default_json_path(in_path: str) -> str:
    base, _ = os.path.splitext(in_path)
    if base.endswith(".scsp"):
        base = base[: -len(".scsp")]
    return base + ".json"


def convert_file(
    in_path: str,
    out_path: str | None = None,
    *,
    include_animations: bool = True,
) -> str:
    data = load_scsp_bytes(in_path)
    if out_path is None:
        out_path = _default_json_path(in_path)
    result = convert(data, include_animations=include_animations)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=4)
    return out_path


def batch_convert_files(
    directory: str,
    *,
    extension: str = "decompressed",
    include_animations: bool = True,
) -> int:
    converted = 0
    suffix = "." + extension.lstrip(".")
    for root, _dirs, files in os.walk(directory):
        for fname in files:
            if not fname.lower().endswith(suffix):
                continue
            path = os.path.join(root, fname)
            try:
                data = load_scsp_bytes(path)
                if not detect_2_1(data):
                    continue
                out_path = convert_file(path, include_animations=include_animations)
                print(f"OK  {path} -> {out_path}")
                converted += 1
            except Exception as exc:
                print(f"ERR {path}: {exc}")
    return converted


def batch_convert_decompressed_files(
    directory: str,
    extension: str = "decompressed",
    *,
    include_animations: bool = True,
) -> int:
    """Backward-compatible alias for :func:`batch_convert_files`."""
    return batch_convert_files(
        directory,
        extension=extension,
        include_animations=include_animations,
    )


__all__ = [
    "convert",
    "convert_file",
    "load_scsp_bytes",
    "batch_convert_files",
    "batch_convert_decompressed_files",
    "VERSION_2_1",
    "VERSION_3_8",
    "SCSP_MAGIC",
]
