#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成一个"相位块"原始文件（供设备端热注入用），不涉及任何 WRF 容器。

格式与 EPDC 在 DDR 里期望的完全一致：
    uint64 LE frame_count
    frame_count × 512 字节相位数据
（每相 512 B = 32×32 个 4-bit action，nibble 低 4 位在前；索引 = current*32 + target）

用法：
  emit_epdc_lut_block.py --pattern bit1 --frames 512 --out block.bin
"""
import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_epdc_waveform import PHASE_BYTES, pack_phase  # noqa: E402
from build_epdc_action_waveform import make_matrix  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pattern", default="bit1",
                    choices=["all1", "all2", "probe", "target", "drive", "bit1"])
    ap.add_argument("--polarity", default="a_black", choices=["a_black", "a_white"])
    ap.add_argument("--frames", type=int, default=512)
    ap.add_argument("--duty", type=int, default=1)
    ap.add_argument("--high-first", action="store_true")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()

    matrix = make_matrix(a.pattern, a.polarity, None)
    drive_phase = pack_phase(matrix, not a.high_first)
    nop = bytes(PHASE_BYTES)
    blob = bytearray(struct.pack("<Q", a.frames))
    for i in range(a.frames):
        blob.extend(drive_phase if (a.duty <= 1 or i % a.duty == 0) else nop)
    a.out.write_bytes(bytes(blob))
    from collections import Counter
    c = Counter(drive_phase)
    print("pattern=%s polarity=%s frames=%d duty=%d nibble=%s"
          % (a.pattern, a.polarity, a.frames, a.duty,
             "high-first" if a.high_first else "low-first"))
    print("单相字节分布: %s" % {hex(k): v for k, v in c.most_common(4)})
    print("块大小 = 8 + %d*%d = %d 字节 -> %s" % (a.frames, PHASE_BYTES, len(blob), a.out))
    print("预计时长 ≈ %.2f s（11.833 ms/相）" % (a.frames * 0.011833))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
