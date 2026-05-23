"""Epic Seven SCSP LZ4 wrapper (8-byte header + lz4.block stream).

Bundled with scsp21-json so the converter runs standalone. The same module
lives in the companion [scsp38-json](https://github.com/himeope/scsp38-json)
repository for Spine 3.8 assets.
"""

from __future__ import annotations

import argparse
import io
import os
import struct
import sys

import lz4.block


def _decompress_stream(f_in: io.BufferedReader | io.BytesIO, endian: str = "<") -> bytes:
    out = io.BytesIO()
    block_index = 0
    while True:
        hdr = f_in.read(8)
        if not hdr:
            break
        if len(hdr) < 8:
            raise EOFError(
                f"incomplete block header at block {block_index} (got {len(hdr)} bytes)"
            )

        decomp_size, comp_len = struct.unpack(endian + "II", hdr)

        if comp_len == 0:
            if decomp_size:
                out.write(b"\x00" * decomp_size)
            block_index += 1
            continue

        comp = f_in.read(comp_len)
        if len(comp) < comp_len:
            raise EOFError(
                f"incomplete block payload at block {block_index} "
                f"(expected {comp_len}, got {len(comp)})"
            )

        data = lz4.block.decompress(comp, uncompressed_size=decomp_size)
        if len(data) != decomp_size:
            sys.stderr.write(
                f"warning: block {block_index} decompressed to {len(data)} bytes, "
                f"expected {decomp_size}\n"
            )

        out.write(data)
        block_index += 1

    return out.getvalue()


def process_file(in_path: str, out_path: str, endian: str = "<") -> int:
    with open(in_path, "rb") as f_in, open(out_path, "wb") as f_out:
        data = _decompress_stream(f_in, endian=endian)
        f_out.write(data)
        return len(data)


def decompress_to_bytes(in_path: str, *, endian: str = "<") -> bytes:
    """Decompress a compressed ``.scsp`` file and return the raw buffer."""
    with open(in_path, "rb") as f_in:
        return _decompress_stream(f_in, endian=endian)


def decompress_single_file(file_path: str, output_dir: str | None = None, endian: str = "<") -> bool:
    if not os.path.isfile(file_path):
        sys.stderr.write(f"input file not found: {file_path}\n")
        return False

    if output_dir:
        out_path = os.path.join(output_dir, os.path.basename(file_path) + ".decompressed")
    else:
        out_path = file_path + ".decompressed"

    try:
        written = process_file(file_path, out_path, endian=endian)
        print(f"wrote {written} bytes to {out_path}")
        return True
    except Exception as exc:
        sys.stderr.write(f"decompression failed: {exc}\n")
        return False


def process_folder(folder_path: str, output_dir: str | None = None, endian: str = "<") -> None:
    scsp_files: list[str] = []
    for root, _dirs, files in os.walk(folder_path):
        for file in files:
            if file.lower().endswith(".scsp"):
                scsp_files.append(os.path.join(root, file))

    if not scsp_files:
        print(f"no .scsp files under {folder_path}")
        return

    print(f"found {len(scsp_files)} .scsp file(s)")
    for file_path in scsp_files:
        print(f"decompressing {file_path}")
        decompress_single_file(file_path, output_dir, endian)


def handle_path(input_path: str, output_dir: str | None = None, endian: str = "<") -> bool:
    if os.path.isdir(input_path):
        process_folder(input_path, output_dir, endian)
    elif os.path.isfile(input_path):
        return decompress_single_file(input_path, output_dir, endian)
    else:
        sys.stderr.write(f"path not found: {input_path}\n")
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Decompress Epic Seven SCSP files (8-byte header + lz4.block stream). "
            "Header: u32 decompressed size, u32 compressed length."
        )
    )
    parser.add_argument("input", help="input .scsp file or directory")
    parser.add_argument(
        "-o",
        "--output",
        help="output directory (default: write <input>.decompressed beside source)",
    )
    parser.add_argument(
        "--big-endian",
        action="store_true",
        help="header uses big-endian integers (default: little-endian)",
    )
    args = parser.parse_args()
    handle_path(args.input, args.output, ">" if args.big_endian else "<")


if __name__ == "__main__":
    main()
