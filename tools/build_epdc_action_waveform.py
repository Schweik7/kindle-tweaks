#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成带真实 action 的长 LUT（替换原厂某个全零单相 mode）。

与原厂无关的假设尽量减少：
  * 结构完全沿用原厂 WRF（头部、温度表、advanced/VCD/ACD/XSWI 全部原样保留），
    只在 blob 末尾追加一个新数据块，并把目标 mode 的 14 个温度指针改过去。
  * action 取值只用 0/1/2 —— 这是从原厂 GC16 波形里实测出来的全部取值（0=不驱动，
    1 与 2 是相反极性；哪个推向黑需要一次实测，见 --polarity）。

pattern：
  all1    全部 1024 项 = 1        （零假设探针：不论索引布局，所有像素都被同向驱动）
  all2    全部 1024 项 = 2
  probe   全部 = 1，但把 480..511 改成 2
          （480..511 在 dst 外层布局下 = 所有 target=15 的项 ⇒ 白目标像素被反向驱动，
            屏幕上会看到黑白分区；在 src 外层布局下 = 所有 current=15 的项 ⇒ 驱动
            写 WB 时若 current 恒为 0 则整屏同色。两种结果可区分布局。）
  target  按 target 灰度决定推向哪边（真正用来做视频的图案）
  drive   同 target，但只按 target 是否为 0/15 区分（1bit 视频用）
"""
import argparse
import hashlib
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_epdc_waveform import PHASE_BYTES, STATES, infer_layout, pack_phase  # noqa: E402

HEADER_BYTES = 48
MAX_FRAMES = 1023
NOP, A, B = 0, 1, 2


def read_file(path):
    import gzip
    raw = path.read_bytes()
    if path.name.lower().endswith(".gz"):
        return gzip.decompress(raw)
    return raw


def write_file(path, data):
    import gzip
    if path.name.lower().endswith(".gz"):
        with path.open("wb") as out:
            with gzip.GzipFile(filename="", mode="wb", fileobj=out, mtime=0) as s:
                s.write(data)
    else:
        path.write_bytes(data)


def make_matrix(pattern, polarity, fade):
    """返回 matrix[src][dst] = action。src=当前灰度状态, dst=目标状态（按分析器约定）。"""
    black_action = A if polarity == "a_black" else B
    white_action = B if polarity == "a_black" else A
    m = [[NOP] * STATES for _ in range(STATES)]
    for src in range(STATES):
        for dst in range(STATES):
            if pattern == "all1":
                m[src][dst] = A
            elif pattern == "all2":
                m[src][dst] = B
            elif pattern == "probe":
                m[src][dst] = B if 480 <= (dst * STATES + src) <= 511 else A
            elif pattern == "target":
                # 32 个状态里，灰度取低 4 位；目标越黑越推向黑
                st, ss = dst & 0xF, src & 0xF
                if st < ss:
                    m[src][dst] = black_action
                elif st > ss:
                    m[src][dst] = white_action
                else:
                    m[src][dst] = NOP
            elif pattern == "drive":
                st = dst & 0xF
                if st <= 7:
                    m[src][dst] = black_action
                elif st >= 8:
                    m[src][dst] = white_action
                else:
                    m[src][dst] = NOP
            elif pattern == "bit1":
                # 2026-10-11 真机探针证明：表索引是 current*32 + target，
                # 而不是分析器假定的 target*32 + current（见 docs/18 §4.7）。
                # 为了让动作只依赖 target、且对「索引 = target」与
                # 「索引 = current*32 + target」两种解释都成立，令存储值只依赖 j % 32。
                # 分析器把 matrix[src][dst] 存在 j = dst*32 + src，所以这里必须用 src。
                # 只对 target 0（黑）与 15（白）驱动；1..14 一律不动 —— 于是背景可以
                # 用中灰当"不驱动"，既省直流又不干扰画面。
                st = src & 0xF
                if st == 0:
                    m[src][dst] = black_action
                elif st == 15:
                    m[src][dst] = white_action
                else:
                    m[src][dst] = NOP
            else:
                raise ValueError("unknown pattern %s" % pattern)
    _ = fade
    return m


def build(wrf, mode, frames, pattern, polarity, duty, low_first):
    if len(wrf) < HEADER_BYTES:
        raise ValueError("WRF shorter than 48-byte header")
    header_mode_count = wrf[37] + 1
    header_temp_count = wrf[38] + 1
    payload_offset = HEADER_BYTES + header_temp_count + 1
    blob = bytearray(wrf[payload_offset:])
    layout = infer_layout(blob)
    if layout["mode_count"] != header_mode_count or layout["temp_count"] != header_temp_count:
        raise ValueError("header/payload count mismatch")
    if not 0 <= mode < layout["mode_count"]:
        raise ValueError("mode out of range")
    blocks, counts = layout["modes"][mode]
    for temp, (block, count) in enumerate(zip(blocks, counts)):
        if count != 1 or blob[block + 8:block + 8 + PHASE_BYTES] != bytes(PHASE_BYTES):
            raise ValueError("mode %d temp %d is not an all-zero one-phase template" % (mode, temp))

    # 生成相位数据：duty=K 表示每 K 相里只有第 0 相驱动，其余全不驱动（降低直流）
    matrix = make_matrix(pattern, polarity, None)
    drive_phase = pack_phase(matrix, low_first)
    nop_phase = bytes(PHASE_BYTES)
    phases = []
    for i in range(frames):
        phases.append(drive_phase if (duty <= 1 or i % duty == 0) else nop_phase)

    padding = (-len(blob)) % 8
    blob.extend(bytes(padding))
    block_offset = len(blob)
    blob.extend(struct.pack("<Q", frames))
    for p in phases:
        blob.extend(p)

    temp_table = layout["top"][mode]
    for temp in range(layout["temp_count"]):
        struct.pack_into("<Q", blob, temp_table + temp * 8, block_offset)

    rebuilt = bytes(wrf[:payload_offset]) + bytes(blob)
    v = infer_layout(bytes(blob))
    nb, nc = v["modes"][mode]
    if set(nb) != {block_offset} or set(nc) != {frames}:
        raise AssertionError("round-trip failed")
    if v["advanced"] != layout["advanced"]:
        raise AssertionError("advanced pointers changed")
    return rebuilt, payload_offset, block_offset, padding, layout, phases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--mode", type=int, default=7)
    ap.add_argument("--frames", type=int, default=256)
    ap.add_argument("--pattern", default="target",
                    choices=["all1", "all2", "probe", "target", "drive", "bit1"])
    ap.add_argument("--polarity", default="a_black", choices=["a_black", "a_white"],
                    help="a_black: action 1 推向黑（第三方资料的说法）；a_white: 反之")
    ap.add_argument("--duty", type=int, default=1, help="每 K 相驱动一次，其余不驱动")
    ap.add_argument("--high-first", action="store_true", help="nibble 用高 4 位在前")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if not 1 <= args.frames <= MAX_FRAMES:
        ap.error("--frames 1..%d" % MAX_FRAMES)
    if args.duty < 1:
        ap.error("--duty must be >= 1")
    if args.input.resolve() == args.output.resolve():
        ap.error("input/output must differ")
    if args.output.exists() and not args.force:
        ap.error("output exists; use --force")

    src = read_file(args.input)
    rebuilt, poff, boff, pad, layout, phases = build(
        src, args.mode, args.frames, args.pattern, args.polarity, args.duty,
        not args.high_first)
    write_file(args.output, rebuilt)

    print("input  %d B sha256=%s" % (len(src), hashlib.sha256(src).hexdigest()[:16]))
    print("output %d B sha256=%s" % (len(rebuilt), hashlib.sha256(rebuilt).hexdigest()[:16]))
    print("payload_offset=0x%x  block=0x%x  pad=%d  frames=%d  phase_bytes=%d"
          % (poff, boff, pad, args.frames, PHASE_BYTES))
    print("pattern=%s polarity=%s duty=%d nibble=%s"
          % (args.pattern, args.polarity, args.duty, "high-first" if args.high_first else "low-first"))
    print("advanced preserved: %s" % " ".join("0x%x" % x for x in layout["advanced"]))
    # 相位内容摘要
    from collections import Counter
    c = Counter()
    for p in phases:
        c.update(p)
    print("phase bytes summary: %s" % dict(c.most_common(5)))
    print("expected duration ~ %.2f s (%.3f ms/phase)" % (args.frames * 0.011833, 11.833))
    print("OFFLINE ONLY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
