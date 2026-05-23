"""CLI for the SCSP 2.1 -> Spine JSON converter.

Usage:
    python main.py hero.scsp
    python main.py hero.scsp.decompressed
    python main.py ./portraits --ext decompressed
    python main.py ./assets --lz4 --ext scsp

Spine **3.8** SCSP files are skipped automatically; use the companion
`scsp38-json` tool for those: https://github.com/himeope/scsp38-json
"""

from __future__ import annotations

import argparse
import os
import sys

import lz4_processor
import scsp_dec_to_json_21


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert Epic Seven SCSP 2.1.27 files to Spine 2.1 JSON.",
    )
    parser.add_argument(
        "target",
        help="Path to a .scsp / .scsp.decompressed file, or a directory to walk.",
    )
    parser.add_argument(
        "--ext",
        default="decompressed",
        help=(
            "Extension to scan when target is a directory "
            "(default: decompressed). Use scsp with --lz4."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Explicit output path (only when target is a single file).",
    )
    parser.add_argument(
        "--no-animations",
        action="store_true",
        help="Skip parsing animations; emit setup pose / skins / events only.",
    )
    parser.add_argument(
        "--lz4",
        action="store_true",
        help=(
            "When scanning a directory, decompress .scsp files with LZ4 first "
            "(writes *.scsp.decompressed beside each source, then converts)."
        ),
    )
    args = parser.parse_args()

    target = args.target
    include_animations = not args.no_animations
    extension = args.ext.lstrip(".")

    if os.path.isdir(target):
        if args.lz4 or extension == "scsp":
            print(f"decompressing .scsp under {target} ...")
            lz4_processor.process_folder(target)
            extension = "decompressed"
        n = scsp_dec_to_json_21.batch_convert_files(
            target, extension=extension, include_animations=include_animations,
        )
        print(f"converted {n} file(s)")
        return 0

    if os.path.isfile(target):
        out = scsp_dec_to_json_21.convert_file(
            target, args.output, include_animations=include_animations,
        )
        print(f"wrote {out}")
        return 0

    print(f"path not found: {target}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
