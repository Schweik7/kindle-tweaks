#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上机前验穿：确认自造的 1023 相 no-op WRF 只改了它该改的东西。

检查项：
  1. 除「mode 7 的 14 个温度指针」和「文件末尾追加块」以外，与原厂 WRF 逐字节相同
  2. 追加块：uint64 frame_count == 1023，其后 1023×512 字节全零
  3. mode 7 的 14 个温度指针全部指向追加块
  4. 结构自洽：8 + frame_count×512 的跨度关系
  5. gzip 往返无损
"""
import gzip
import hashlib
import struct
import sys

ORIG = ".work/active_waveform.wrf"
NOOP = ".work/active_waveform_noop1023.wrf"
NOOP_GZ = ".work/active_waveform_noop1023.wrf.gz"
PREFIX = 0x3F                 # WRF 文件头 48B + 温度表 14B + 1B padding
PHASE_BYTES = 512
MODES = 10
TEMPS = 14


def sha(b):
    return hashlib.sha256(b).hexdigest()


def u64(b, o):
    return struct.unpack_from("<Q", b, o)[0]


def main():
    orig = open(ORIG, "rb").read()
    noop = open(NOOP, "rb").read()
    print("原厂 WRF      %d 字节  sha256 %s" % (len(orig), sha(orig)[:16] + "…"))
    print("自造 WRF      %d 字节  sha256 %s" % (len(noop), sha(noop)[:16] + "…"))
    print("预期 = %d + 3(对齐) + 8(count) + 1023*512 = %d"
          % (len(orig), len(orig) + 3 + 8 + 1023 * 512))
    ok = True
    if len(noop) != len(orig) + 3 + 8 + 1023 * 512:
        print("  !! 长度不符"); ok = False

    # ---- payload 视图 ----
    po = orig[PREFIX:]
    pn = noop[PREFIX:]
    print()
    print("payload: 原厂 %d 字节 / 自造 %d 字节" % (len(po), len(pn)))

    # ---- 1. 差异定位 ----
    n = min(len(po), len(pn))
    diff = [i for i in range(n) if po[i] != pn[i]]
    print()
    print("=== 1 差异字节统计 ===")
    print("  公共前缀内不同字节数: %d" % len(diff))
    # 把差异归成连续区间
    ranges = []
    for i in diff:
        if ranges and i == ranges[-1][1] + 1:
            ranges[-1][1] = i
        else:
            ranges.append([i, i])
    for a, b in ranges:
        print("    0x%06x..0x%06x (%d 字节)" % (a, b, b - a + 1))
    # 允许的差异区：mode 7 的 14 个指针（由 mode_off[7] 起算）
    top = [u64(po, i * 8) for i in range(16)]
    mode_off = [u64(po, i * 8) for i in range(MODES)]
    tcount = (mode_off[1] - mode_off[0]) // 8
    m7 = mode_off[7]
    allowed_m7 = set(range(m7, m7 + TEMPS * 8))
    allowed_tail = set(range(len(po), len(pn)))
    bad = [i for i in diff if i not in allowed_m7]
    print("  指向 mode7 温度表的差异: %d 个 (预期 %d)" % (len(diff) - len(bad), TEMPS * 8))
    if bad:
        print("  !! 出现了不该有的差异，前几个: %s" % ["0x%x" % x for x in bad[:8]])
        ok = False
    else:
        print("  ✅ 公共前缀内的差异全部落在 mode 7 的温度指针表内")
    if len(pn) > len(po):
        tail = pn[len(po):]
        print("  追加区 %d 字节，其中非零 %d 字节" % (len(tail), sum(1 for x in tail if x)))
    print("  温度档数 = %d（由 mode0→mode1 步长推出）" % tcount)

    # ---- 2. 追加块 ----
    print()
    print("=== 2 追加块内容 ===")
    # 追加块起点 = 对齐后的原 payload 末尾
    blk = len(po)
    while blk % 8:
        blk += 1
    print("  追加块 payload 偏移 = 0x%06x（原文即为 0x25c550）" % blk)
    fc = u64(pn, blk)
    print("  frame_count = %d" % fc)
    data = pn[blk + 8: blk + 8 + fc * PHASE_BYTES]
    nz = sum(1 for x in data if x)
    print("  相位数据 %d 字节，非零 %d 字节 -> %s"
          % (len(data), nz, "全零 no-op ✅" if nz == 0 else "!! 有非零"))
    if fc != 1023 or nz:
        ok = False

    # ---- 3. mode7 指针 ----
    print()
    print("=== 3 mode 7 的 14 个温度指针 ===")
    ptrs = [u64(pn, m7 + t * 8) for t in range(TEMPS)]
    print("  %s" % " ".join("0x%x" % p for p in ptrs))
    if all(p == blk for p in ptrs):
        print("  ✅ 全部指向追加块")
    else:
        print("  !! 有不指向追加块的"); ok = False
    # 原厂 mode7 各温度档
    o7 = [u64(po, m7 + t * 8) for t in range(TEMPS)]
    print("  原厂: %s" % " ".join("0x%x" % p for p in o7))
    print("  原厂这些块: %s" % " ".join("%d相" % u64(po, p) for p in o7))

    # ---- 4. 结构自洽：全表跨度 ----
    print()
    print("=== 4 全表结构自洽（8 + frame_count×512 跨度）===")
    blocks = {}
    for m in range(MODES):
        for t in range(tcount):
            blocks[u64(pn, mode_off[m] + t * 8)] = None
    offs = sorted(blocks)
    bad2 = 0
    for i in range(len(offs) - 1):
        span = offs[i + 1] - offs[i]
        fc_i = u64(pn, offs[i])
        if span != 8 + fc_i * PHASE_BYTES:
            bad2 += 1
            if bad2 <= 3:
                print("    !! 0x%x 跨度 %d != 8+%d*512=%d" % (offs[i], span, fc_i, 8 + fc_i * PHASE_BYTES))
    print("  唯一数据块 %d 个，跨度不符 %d 个 -> %s"
          % (len(offs), bad2, "全部自洽 ✅" if bad2 == 0 else "有问题"))

    # ---- 5. gzip 往返 ----
    print()
    print("=== 5 gzip 往返 ===")
    gz = open(NOOP_GZ, "rb").read()
    back = gzip.decompress(gz)
    print("  .gz %d 字节 -> 解压 %d 字节，往返%s"
          % (len(gz), len(back), "一致 ✅" if back == noop else "不一致 !!"))
    if back != noop:
        ok = False

    print()
    print("结论: %s" % ("✅ 通过，可以上机" if ok else "!! 未通过，不要上机"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
