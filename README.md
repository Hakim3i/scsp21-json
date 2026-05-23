# scsp21-json

[中文](README.zh.md) | English

Convert Epic Seven **Spine 2.1.27** (`2.1.xx.scsp`) assets to Spine 2.1 JSON.

- Supports both **tagged** (post-2021-06, `scsp` magic) and **untagged** (older portraits / NPCs) 2.1 layouts
- Parses bones, slots, skins (region / mesh / skinnedmesh), events, and animations
- Ships with **LZ4 decompression** (`lz4_processor.py`) so you can feed `.scsp` or pre-decompressed `.scsp.decompressed` files
- For **Spine 3.8** (`3.8.xx.scsp`), use the companion **[scsp38-json](https://github.com/himeope/scsp38-json)** project instead

## Install

```bash
git clone https://github.com/Hakim3i/scsp21-json.git
cd scsp21-json
pip install -r requirements.txt
```

## CLI

| Option | Description | Default |
|--------|-------------|---------|
| `-o`, `--output` | Output JSON path (single file only) | `<input>.json` |
| `--no-animations` | Skip animations (setup pose only) | parse animations |
| `--ext` | Extension when scanning a directory | `decompressed` |
| `--lz4` | Decompress `.scsp` files in a directory first | off |

### Examples

```bash
# Single decompressed file
python main.py path/to/unit.scsp.decompressed

# Single compressed SCSP (LZ4 decompress in memory, then convert)
python main.py path/to/unit.scsp

# Convert every *.scsp.decompressed under a folder
python main.py path/to/folder --ext decompressed

# Decompress *.scsp in a folder, then convert
python main.py path/to/folder --lz4
```

Decompress only (no JSON):

```bash
python lz4_processor.py path/to/unit.scsp
```

## Layout

| File | Role |
|------|------|
| `main.py` | CLI entry point |
| `scsp_dec_to_json_21.py` | Public API: `convert()`, `convert_file()`, `load_scsp_bytes()` |
| `_scsp21_reader.py` | SCSP 2.1 binary reader (bones / slots / skins / events) |
| `_scsp21_anim.py` | Animation timeline parser |
| `lz4_processor.py` | Epic Seven SCSP LZ4 stream decompressor (same format as scsp38-json) |
| `FORMAT_2_1.md` | Reverse-engineered 2.1 binary notes |
| `KNOWN_ISSUES.md` | Known visual / reference mismatches |

## Python API

```python
from scsp_dec_to_json_21 import convert, load_scsp_bytes

data = load_scsp_bytes("unit.scsp")  # .scsp or .scsp.decompressed
doc = convert(data, include_animations=True)
```

## Related projects

- **[scsp38-json](https://github.com/himeope/scsp38-json)** — Spine **3.8.99** SCSP → JSON (same LZ4 container; use this repo for 2.1)
- **[SpineViewer](https://github.com/ww-rm/SpineViewer)** — view exported JSON + atlas
- **[EpicSevenAssetRipper](https://github.com/CeciliaBot/EpicSevenAssetRipper)** — rip assets from the game client

## Disclaimer

For educational use only. Do not use converted files for commercial or illegal purposes.

## License

[GNU AGPL v3](LICENSE) (same as scsp38-json)
