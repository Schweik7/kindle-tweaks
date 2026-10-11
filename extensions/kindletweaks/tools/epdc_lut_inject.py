#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EPDC 长 LUT **热注入**：直接改 DDR 里那张波形 blob，不碰分区、不重启。

## 为什么可以这样
  驱动在 probe 时只做一件事：把 WRF payload 整块 memcpy 到 DDR，把地址写进 EPDC_WVADDR。
  它**从不解析** mode 偏移表 —— 那张表的寻址是 **EPDC 硬件**在每次跑 LUT 时自己去 DDR 走的。
  所以只要改掉 DDR 里 mode 7 的 14 个温度指针，指向我们自己准备的相位块，
  下一次更新就会用新 LUT。纯内存写，驱动完全不知情，**立刻生效**。

## 内存布局（都从只读来源拿，不猜）
  * waveform blob 物理地址：从 dmesg 的 `allocate N byte @ XXXXXXXX for waveform` 取
    （每次启动都会变，读到 `0x92800000` / `0xa3793000` 两种）
  * mode 7 的温度指针表偏移：从 blob 自身的顶层表读出（本机为 0x380），14 × uint64
  * 相位块存放处：**working buffer 保留区尾部**
    保留区 0x9C000000..0x9C4FFFFF 共 5,242,880 B，WB 只用 1264*1680*2 = 4,247,040 B
    （结束于 0x9C40CE00），尾部 995,840 B 空闲；本工具用 **0x9C410000** 起。
  * mode 7 对应 mxcfb 索引 10（实测），是原厂一个"全零单相 no-op"模板，改它不影响 UI。

## 安全
  * 全程只写 DDR，**不写任何 EPDC 寄存器**
  * 首次安装时把原厂 14 个指针存到 /mnt/us/waveform_backup/mode7_ptr.json
  * 指针处于"未知状态"时拒绝动手（除非 --force）
  * `--restore` 一键还原；重启也能还原

用法：
  epdc_lut_inject.py --show
  epdc_lut_inject.py --install block.bin
  epdc_lut_inject.py --restore
"""
import argparse
import json
import mmap
import os
import re
import struct
import subprocess
import sys

BLOCK_PHYS = 0x9C410000
RESERVED_START = 0x9C000000
RESERVED_SIZE = 0x500000
WB_SIZE = 1264 * 1680 * 2
PTR_BACKUP = "/mnt/us/waveform_backup/mode7_ptr.json"
PHASE_BYTES = 512


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout


def find_waveform():
    """从 dmesg 里找 waveform blob 的物理地址与长度（只读来源，可靠）。"""
    out = sh("dmesg 2>/dev/null | grep 'for waveform'")
    m = None
    for line in out.splitlines():
        mm = re.search(r"allocate (\d+) byte @ ([0-9a-f]+) for waveform", line)
        if mm:
            m = (int(mm.group(2), 16), int(mm.group(1)))
    if not m:
        raise RuntimeError("dmesg 里找不到 waveform 分配记录")
    return m


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--show", action="store_true")
    g.add_argument("--install", metavar="BLOCK")
    g.add_argument("--restore", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    wf_phys, wf_size = find_waveform()
    print("waveform blob: 物理 0x%08x  大小 %d B" % (wf_phys, wf_size))

    fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    blob = mmap.mmap(fd, wf_size, mmap.MAP_SHARED,
                     mmap.PROT_READ | mmap.PROT_WRITE, offset=wf_phys)
    try:
        # 从顶层表推出 mode 7 的温度指针表偏移（与 analyze_epdc_waveform 同一约定）
        top0 = struct.unpack_from("<Q", blob, 0)[0]
        mode_count = top0 // 8
        temp_table = struct.unpack_from("<Q", blob, 7 * 8)[0]
        temp_count = (struct.unpack_from("<Q", blob, 1 * 8)[0] - top0) // 8
        ptrs = [struct.unpack_from("<Q", blob, temp_table + t * 8)[0]
                for t in range(temp_count)]
        print("顶层指针数 %d；mode 7 温度表偏移 0x%x，温度档数 %d" %
              (mode_count, temp_table, temp_count))
        print("当前 mode 7 的 %d 个指针: %s" %
              (temp_count, " ".join("0x%x" % p for p in ptrs)))

        def frame_count_at(off):
            return struct.unpack_from("<Q", blob, off)[0]

        # 保存/读取原厂指针
        orig = None
        if os.path.exists(PTR_BACKUP):
            orig = json.load(open(PTR_BACKUP))["ptrs"]
            print("已存的原厂指针: %s" % " ".join("0x%x" % p for p in orig))
        elif args.install:
            # 只在"确实还是原厂"时才记录
            if len(set(ptrs)) == 1 and frame_count_at(ptrs[0]) == 1:
                os.makedirs(os.path.dirname(PTR_BACKUP), exist_ok=True)
                json.dump({"ptrs": ptrs, "wf_phys": wf_phys}, open(PTR_BACKUP, "w"))
                orig = ptrs
                print("已记录原厂指针到 %s" % PTR_BACKUP)
            else:
                print("!! 当前指针不像原厂模板（期望 14 个相同且 frame_count==1），"
                      "拒绝记录；加 --force 可强行继续")

        if args.show:
            for i, p in enumerate(ptrs):
                extra = ""
                if RESERVED_START <= p < RESERVED_START + RESERVED_SIZE:
                    extra = "  <- 在我们注入的保留区尾部，frame_count=%d" % frame_count_at(p)
                elif p < wf_size:
                    extra = "  <- blob 内偏移，frame_count=%d" % frame_count_at(p)
                print("  temp %2d: 0x%08x%s" % (i, p, extra))
            return 0

        if args.restore:
            if not orig:
                print("!! 没有 %s，无法还原（重启即可恢复）" % PTR_BACKUP)
                return 1
            for t in range(temp_count):
                struct.pack_into("<Q", blob, temp_table + t * 8, orig[t])
            blob.flush()
            print("✅ 已还原原厂指针: %s" % " ".join("0x%x" % p for p in orig))
            return 0

        # ---- install ----
        data = open(args.install, "rb").read()
        fc = struct.unpack_from("<Q", data, 0)[0]
        need = 8 + fc * PHASE_BYTES
        if len(data) != need:
            print("!! 块大小不符：%d != 8 + %d*512 = %d" % (len(data), fc, need))
            return 1
        tail = RESERVED_START + RESERVED_SIZE
        if BLOCK_PHYS + need > tail:
            print("!! 块放不下")
            return 1
        if BLOCK_PHYS < RESERVED_START + WB_SIZE:
            print("!! 目标地址与 working buffer 重叠")
            return 1
        print("块: frame_count=%d  需要 %d B  目标 0x%08x..0x%08x（保留区尾部，WB 之外）"
              % (fc, need, BLOCK_PHYS, BLOCK_PHYS + need - 1))

        if not orig and not args.force:
            print("!! 不知道原厂指针，且 --force 未给，拒绝改指针")
            return 1
        known_ok = (len(set(ptrs)) == 1) or all(p == BLOCK_PHYS for p in ptrs)
        if not known_ok and not args.force:
            print("!! 当前指针既不是原厂模板也不是我们的块地址，拒绝覆盖（--force 可强改）")
            return 1

        # 1) 写相位块到保留区尾部
        blk = mmap.mmap(fd, need, mmap.MAP_SHARED,
                        mmap.PROT_READ | mmap.PROT_WRITE, offset=BLOCK_PHYS)
        blk[:] = data
        blk.flush()
        blk.close()
        print("  已写入相位块到 0x%08x" % BLOCK_PHYS)

        # 2) 改 mode 7 的 14 个温度指针
        for t in range(temp_count):
            struct.pack_into("<Q", blob, temp_table + t * 8, BLOCK_PHYS)
        blob.flush()
        verify = [struct.unpack_from("<Q", blob, temp_table + t * 8)[0]
                  for t in range(temp_count)]
        ok = all(p == BLOCK_PHYS for p in verify)
        print("  %s mode 7 指针已指向 0x%08x（%d 个）"
              % ("✅" if ok else "!!", BLOCK_PHYS, temp_count))
        print()
        print("现在用 mxcfb 索引 10 提交一次更新即可用上新 LUT（**无需重启**）。")
        print("还原： %s --restore   （或重启）" % sys.argv[0])
        return 0 if ok else 1
    finally:
        blob.close()
        os.close(fd)


if __name__ == "__main__":
    sys.exit(main())
