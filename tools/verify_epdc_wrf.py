#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用校验：确认自造 WRF 相对原厂只改了「目标 mode 的 14 个温度指针 + 末尾追加块」。

用法： verify_epdc_wrf.py 原厂.wrf 自造.wrf.gz [--mode 7] [--frames 256]
"""
import argparse
import gzip
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_epdc_waveform import PHASE_BYTES, infer_layout  # noqa: E402


def load(p):
    raw = Path(p).read_bytes()
    return gzip.decompress(raw) if p.lower().endswith(".gz") else raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("orig")
    ap.add_argument("built")
    ap.add_argument("--mode", type=int, default=7)
    ap.add_argument("--frames", type=int, default=256)
    a = ap.parse_args()

    orig, built = load(a.orig), load(a.built)
    print("原厂 %d B / 自造 %d B" % (len(orig), len(built)))
    expected = len(orig) + (-(len(orig) - 0x3F)) % 8 + 8 + a.frames * PHASE_BYTES
    print("预期长度 %d -> %s" % (expected, "一致 ✅" if len(built) == expected else "不一致 !!"))
    ok = len(built) == expected

    # 64 字节前缀（文件头 + 温度表 + padding）必须完全相同
    prefix = 48 + (orig[38] + 1) + 1
    same_prefix = orig[:prefix] == built[:prefix]
    print("前 %d 字节（头部+温度表）相同: %s" % (prefix, "✅" if same_prefix else "!!"))
    ok &= same_prefix

    po, pn = orig[prefix:], built[prefix:]
    layout = infer_layout(po)
    temp_table = layout["top"][a.mode]
    allowed = set(range(temp_table, temp_table + layout["temp_count"] * 8))
    diff = [i for i in range(min(len(po), len(pn))) if po[i] != pn[i]]
    stray = [i for i in diff if i not in allowed]
    print("公共前缀内差异字节 %d 个（允许区 %d 字节）" % (len(diff), len(allowed)))
    if stray:
        print("  !! 越界差异 %d 个，前几个: %s" % (len(stray), ["0x%x" % x for x in stray[:6]]))
        ok = False
    else:
        print("  ✅ 差异全部落在 mode %d 的温度指针表内" % a.mode)

    blk = (-len(po)) % 8 + len(po)
    fc = struct.unpack_from("<Q", pn, blk)[0]
    print("追加块 payload 偏移 0x%x，frame_count=%d" % (blk, fc))
    if fc != a.frames:
        print("  !! frame_count 与 --frames 不符"); ok = False
    ptrs = [struct.unpack_from("<Q", pn, temp_table + t * 8)[0] for t in range(layout["temp_count"])]
    if all(p == blk for p in ptrs):
        print("  ✅ mode %d 的 %d 个温度指针全部指向追加块" % (a.mode, len(ptrs)))
    else:
        print("  !! 有指针未指向追加块: %s" % ["0x%x" % p for p in ptrs]); ok = False

    data = pn[blk + 8: blk + 8 + fc * PHASE_BYTES]
    from collections import Counter
    c = Counter(data)
    print("相位数据 %d 字节，字节值分布: %s" % (len(data), {hex(k): v for k, v in c.most_common(6)}))
    nz = sum(1 for x in data if x)
    print("  非零字节 %d（%s）" % (nz, "全零 no-op" if nz == 0 else "含真实 action"))

    v = infer_layout(bytes(pn))
    print("advanced 指针: %s -> %s" % (" ".join("0x%x" % x for x in layout["advanced"]),
                                       " ".join("0x%x" % x for x in v["advanced"])))
    if layout["advanced"] != v["advanced"]:
        print("  !! advanced 指针被改动"); ok = False

    print()
    print("结论: %s" % ("✅ 通过" if ok else "!! 未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
