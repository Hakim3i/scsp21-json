# scsp21-json

中文 | [English](README.md)

将 Epic Seven **Spine 2.1.27**（`2.1.xx.scsp`）资源转换为 Spine 2.1 JSON。

- 支持 **tagged**（2021-06 之后，`scsp` magic）与 **untagged**（旧版 portrait / NPC）两种 2.1 布局
- 解析 bones、slots、skins（region / mesh / skinnedmesh）、events、animations
- 内置 **LZ4 解压**（`lz4_processor.py`），可单独处理 `.scsp` 或已解压的 `.scsp.decompressed`
- **Spine 3.8**（`3.8.xx.scsp`）请使用姊妹项目 **[scsp38-json](https://github.com/himeope/scsp38-json)**

## 安装

```bash
git clone https://github.com/Hakim3i/scsp21-json.git
cd scsp21-json
pip install -r requirements.txt
```

## 用法

| 选项 | 说明 | 默认 |
|------|------|------|
| `-o`, `--output` | 单文件输出 JSON 路径 | 与输入同目录的 `.json` |
| `--no-animations` | 不解析动画（仅 setup pose） | 解析动画 |
| `--ext` | 目录扫描时的扩展名 | `decompressed` |
| `--lz4` | 目录模式下先解压 `.scsp` | 不解压 |

### 示例

```bash
# 单个已解压文件
python main.py path/to/unit.scsp.decompressed

# 单个压缩 SCSP（自动 LZ4 解压后转换）
python main.py path/to/unit.scsp

# 递归转换目录下所有 *.scsp.decompressed
python main.py path/to/folder --ext decompressed

# 目录内先解压 *.scsp 再转换
python main.py path/to/folder --lz4
```

仅解压（不转 JSON）：

```bash
python lz4_processor.py path/to/unit.scsp
```

## 模块说明

| 文件 | 作用 |
|------|------|
| `main.py` | 命令行入口 |
| `scsp_dec_to_json_21.py` | 公开 API：`convert()`, `convert_file()`, `load_scsp_bytes()` |
| `_scsp21_reader.py` | SCSP 2.1 二进制读取（bones / slots / skins / events） |
| `_scsp21_anim.py` | 动画时间轴解析 |
| `lz4_processor.py` | Epic Seven SCSP 的 LZ4 流解压（与 scsp38-json 相同格式） |
| `FORMAT_2_1.md` | 2.1 二进制布局笔记 |

## Python API

```python
from scsp_dec_to_json_21 import convert, load_scsp_bytes

data = load_scsp_bytes("unit.scsp")  # .scsp 或 .scsp.decompressed
doc = convert(data, include_animations=True)
```

## 相关项目

- **[scsp38-json](https://github.com/himeope/scsp38-json)** — Spine **3.8.99** SCSP → JSON（共享同一 LZ4 容器格式）
- **[SpineViewer](https://github.com/ww-rm/SpineViewer)** — 查看导出的 JSON + atlas
- **[EpicSevenAssetRipper](https://github.com/CeciliaBot/EpicSevenAssetRipper)** — 从客户端解包资源

## 免责声明

仅供学习与交流，请勿将转换结果用于商业或违法用途。

## 许可

[GNU AGPL v3](LICENSE)（与 scsp38-json 相同）
