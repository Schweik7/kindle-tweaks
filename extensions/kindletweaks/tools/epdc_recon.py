#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EPDC v2 只读侦察工具（Kindle Oasis 3 / i.MX7D，内核 4.1.15-lab126）。

## 它能做什么
  1. 读 EPDC 寄存器（白名单，全部是"基寄存器"，无副作用）
  2. 从 EPDC pixel clock + TCE 时序寄存器计算扫描帧率，并用更新耗时交叉验证
  3. 从 EPDC_WVADDR 指向的 DDR 里 dump 并解码波形/LUT blob 的布局与各 mode 帧数

## 安全设计（按血泪教训写的，改之前先读）
  * **只读，绝不写任何寄存器。** 只读基寄存器偏移；所有 +4/+8/+0xC 的
    _SET/_CLEAR/_TOGGLE 别名是**写语义**，读它们无定义。
  * 读之前必须确认 EPDC 已上电：`EPDC_CTRL.CLKGATE`(bit30) 置位时读任何寄存器都
    无意义（可能总线错误）。驱动 `pwndown_delay=0`，队列一空就 CLKGATE + 断 VCOM，
    所以本工具**在"保持一次小区域更新在飞"的窗口里读寄存器**。
  * `power/control`（runtime PM，内核正规接口）用 on/auto 包裹，并用 atexit 兜底还原。
  * **⚠ 只用小区域更新做"保活"，绝不用整屏！** 曾经用整屏纯白做保活，进程被中断后
    屏幕就停在那一帧白（用户看到"白屏"）。保活区域固定 64x64，且结束时会切回主页
    让系统重绘，不会把测试图案留在屏上。

## 用法（在设备上跑）
    LD_LIBRARY_PATH=/mnt/us/python3/lib PYTHONIOENCODING=utf-8 \
      /mnt/us/python3/bin/python3.9 /mnt/us/extensions/kindletweaks/tools/epdc_recon.py
    选项： --no-regs / --no-fps / --no-blob 只跑其中一部分

## 寄存器偏移来源
  NXP linux-imx `imx_4.9.11_1.0.0_ga`（与 Kindle 的 4.1.15-lab126 同代）：
  drivers/video/fbdev/mxc/epdc_v2_regs.h。EPDC v2 从未进入 mainline。
"""
import argparse
import atexit
import glob
import mmap
import os
import struct
import subprocess
import sys
import time

EPDC_PHYS = 0x306f0000
EPDC_SIZE = 0x10000
PM_DIR = "/sys/devices/platform/soc/30400000.aips-bus/306f0000.epdc/power"

# 只读白名单：全是"基寄存器"，避开所有 +4/+8/+0xC 别名
REGS = [
    ("EPDC_CTRL", 0x000), ("EPDC_WB_ADDR_TCE", 0x010), ("EPDC_WVADDR", 0x020),
    ("EPDC_WB_ADDR", 0x030), ("EPDC_RES", 0x040), ("EPDC_FORMAT", 0x050),
    ("EPDC_WB_FIELD0", 0x060), ("EPDC_FIFOCTRL", 0x0A0),
    ("EPDC_UPD_ADDR", 0x100), ("EPDC_UPD_STRIDE", 0x110), ("EPDC_UPD_CORD", 0x120),
    ("EPDC_UPD_SIZE", 0x140), ("EPDC_UPD_CTRL", 0x160), ("EPDC_UPD_FIXED", 0x180),
    ("EPDC_TEMP", 0x1A0), ("EPDC_TCE_CTRL", 0x200), ("EPDC_TCE_SDCFG", 0x220),
    ("EPDC_TCE_HSCAN1", 0x260), ("EPDC_TCE_HSCAN2", 0x280), ("EPDC_TCE_VSCAN", 0x2A0),
    ("EPDC_IRQ1", 0x3E0), ("EPDC_IRQ2", 0x3F0), ("EPDC_IRQ_MASK", 0x400),
    ("EPDC_IRQ", 0x420), ("EPDC_STATUS_LUTS", 0x440), ("EPDC_STATUS_LUTS2", 0x450),
    ("EPDC_STATUS_NEXTLUT", 0x460), ("EPDC_STATUS_COL", 0x480), ("EPDC_STATUS", 0x4A0),
    ("EPDC_DEBUG", 0x500), ("EPDC_DEBUG_LUT", 0x530), ("EPDC_GPIO", 0x700),
    ("EPDC_VERSION", 0x7F0),
]

IRQ_BITS = {23: "PWR", 22: "UPD_DONE", 21: "TCE_IDLE", 20: "BUS_ERR", 19: "FRAME_END",
            18: "TCE_UNDERRUN", 17: "LUT_COL", 16: "WB_CMPLT"}
CTRL_CLKGATE = 1 << 30
BLOB_MAP_SIZE = 0x400000           # 原厂固件约 3.6 MiB；旧值 1 MiB 会在 mode 2 越界
DEFAULT_FW = "/lib/firmware/imx/epdc/epdc_ED070KC1.fw"
KEEPALIVE_W = KEEPALIVE_H = 64      # 保活更新只用这么小一块，绝不整屏
KEEPALIVE_XY = (8, 8)               # 左上角，避开主要内容


def lipc(prop, val, intval=False):
    pub, _, name = prop.rpartition(".")
    cmd = ["lipc-set-prop"] + (["-i"] if intval else []) + ["--", pub, name, str(val)]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-regs", action="store_true")
    ap.add_argument("--no-fps", action="store_true")
    ap.add_argument("--no-blob", action="store_true")
    args = ap.parse_args()

    from _fbink import ffi, lib as FBInk
    import numpy as np

    print("=== 0 准备 / 上电 ===")
    pm = PM_DIR if os.path.isdir(PM_DIR) else None
    if pm:
        print("  PM: control=%s status=%s" % (open(pm + "/control").read().strip(),
                                              open(pm + "/runtime_status").read().strip()))
        open(pm + "/control", "w").write("on")     # 内核正规接口，不是寄存器写
        atexit.register(lambda: open(pm + "/control", "w").write("auto"))
        print("  已设 control=on（退出时自动还原 auto）")
    lipc("com.lab126.powerd.wakeUp", 1, True)
    lipc("com.lab126.powerd.preventScreenSaver", 1, True)
    atexit.register(lambda: lipc("com.lab126.powerd.preventScreenSaver", 0, True))
    # 结束时让系统重绘，别把测试图案留在屏上
    atexit.register(lambda: lipc("com.lab126.appmgrd.start", "app://com.lab126.booklet.home"))

    fd = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
    reg = mmap.mmap(fd, EPDC_SIZE, mmap.MAP_SHARED, mmap.PROT_READ, offset=EPDC_PHYS)

    def rd(off):
        return struct.unpack_from("<I", reg, off)[0]

    fbfd = FBInk.fbink_open()
    cfg = ffi.new("FBInkConfig *")
    cfg.is_quiet = True
    FBInk.fbink_init(fbfd, cfg)
    st = ffi.new("FBInkState *")
    FBInk.fbink_get_state(cfg, st)
    print("  屏幕 %dx%d" % (st.screen_width, st.screen_height))

    # 保活用的白色小图（只占 64x64）
    keep_white = np.full(KEEPALIVE_H * KEEPALIVE_W, 255, dtype=np.uint8).tobytes()
    keep_black = np.zeros(KEEPALIVE_H * KEEPALIVE_W, dtype=np.uint8).tobytes()

    def keepalive(wfm=None, pixels=None):
        c = ffi.new("FBInkConfig *")
        c.is_quiet = True
        c.wfm_mode = FBInk.WFM_GC16 if wfm is None else wfm
        c.is_flashing = True
        pixels = keep_white if pixels is None else pixels
        FBInk.fbink_print_raw_data(fbfd, pixels, KEEPALIVE_W, KEEPALIVE_H, len(pixels),
                                   KEEPALIVE_XY[0], KEEPALIVE_XY[1], c)

    def wait():
        FBInk.fbink_wait_for_complete(fbfd, 0)

    def powered_read(offs):
        """保持一次更新在飞，确保 EPDC 上电，然后读寄存器。"""
        for attempt in range(5):
            keepalive()
            time.sleep(0.05)
            if not (rd(0x000) & CTRL_CLKGATE):
                return {n: rd(o) for n, o in offs}, True
            wait()
        return {}, False

    rc = 0
    try:
        # ---------------- 1 寄存器 ----------------
        vals = {}
        if not args.no_regs:
            print()
            print("=== 1 寄存器（在更新进行中读，保证上电）===")
            vals, ok = powered_read(REGS)
            if not ok:
                print("  !! CLKGATE 一直没清，放弃（安全第一）")
                return 1
            ver = vals["EPDC_VERSION"]
            print("  EPDC_VERSION = 0x%08x -> major=%d minor=%d step=%d  rev=%d  (%s)"
                  % (ver, (ver >> 24) & 0xFF, (ver >> 16) & 0xFF, ver & 0xFFFF,
                     ((ver >> 24) & 0xFF) * 10 + ((ver >> 16) & 0xFF),
                     "v2/64 LUT" if ((ver >> 24) & 0xFF) * 10 + ((ver >> 16) & 0xFF) >= 20 else "v1/16 LUT"))
            print("  %-22s %-6s %s" % ("寄存器", "偏移", "值"))
            for n, o in REGS:
                print("  %-22s 0x%03x  0x%08x" % (n, o, vals[n]))
            fmt = vals["EPDC_FORMAT"]
            print("  --- 解读 ---")
            print("  CTRL: SFTRST=%d CLKGATE=%d" % (1 if vals["EPDC_CTRL"] & (1 << 31) else 0,
                                                     1 if vals["EPDC_CTRL"] & CTRL_CLKGATE else 0))
            print("  FORMAT: WB_TYPE[13:12]=0b{:02b} BUF_PIXEL_FORMAT[10:8]=0b{:03b} TFT[2:0]=0b{:03b}"
                  .format((fmt >> 12) & 3, (fmt >> 8) & 7, fmt & 7))
            print("  WB_ADDR=0x%08x  WB_ADDR_TCE=0x%08x  WVADDR=0x%08x  TEMP=%d"
                  % (vals["EPDC_WB_ADDR"], vals["EPDC_WB_ADDR_TCE"], vals["EPDC_WVADDR"], vals["EPDC_TEMP"]))
            uc = vals["EPDC_UPD_CTRL"]
            print("  UPD_CTRL: USE_FIXED=%d LUT_SEL=%d WAVEFORM_MODE=%d AUTO=%d DRY=%d FULL=%d"
                  % ((uc >> 31) & 1, (uc >> 16) & 0x3F, (uc >> 8) & 0xFF,
                     (uc >> 2) & 1, (uc >> 1) & 1, uc & 1))
            irq = vals["EPDC_IRQ"]
            print("  IRQ=0x%08x -> %s" % (irq, ", ".join(n for b, n in IRQ_BITS.items() if irq & (1 << b)) or "无"))
            active_luts = vals["EPDC_STATUS_LUTS"] | (vals["EPDC_STATUS_LUTS2"] << 32)
            print("  STATUS_LUTS=0x%016x  NEXTLUT=0x%08x  STATUS=0x%08x"
                  % (active_luts, vals["EPDC_STATUS_NEXTLUT"], vals["EPDC_STATUS"]))
            print("  RES: H=%d V=%d" % (vals["EPDC_RES"] & 0x1FFF, (vals["EPDC_RES"] >> 16) & 0x1FFF))

        # ---------------- 2 波形 blob ----------------
        decoded_frame_counts = None
        decoded_temp_idx = None
        if not args.no_blob:
            print()
            fw_path = DEFAULT_FW if os.path.isfile(DEFAULT_FW) else next(
                iter(sorted(glob.glob("/lib/firmware/imx/epdc/*.fw"))), None)
            fw_header = None
            fw_blob = None
            if fw_path:
                with open(fw_path, "rb") as f:
                    fw_bytes = f.read()
                fw_header = fw_bytes[:48]
            if fw_header is not None and len(fw_header) == 48:
                hdr_luts, hdr_mc, hdr_trc = fw_header[36:39]
                advanced_waveform = (hdr_luts & 0x0C) == 4
                fw_data_off = 48 + hdr_trc + 1 + 1
                fw_blob = fw_bytes[fw_data_off:]
                print("  磁盘候选固件头: %s  luts=0x%02x mc=%d trc=%d -> %s"
                      % (fw_path, hdr_luts, hdr_mc, hdr_trc,
                         "advanced/AF（不按普通 4-bit 解码）" if advanced_waveform
                         else "普通 4-bit"))
            else:
                hdr_luts = hdr_mc = hdr_trc = None
                advanced_waveform = False
                print("  !! 找不到 48 字节固件头；mode/temp 数只能按内存表推测")
            wv = vals.get("EPDC_WVADDR")
            if wv is None:
                vals, ok = powered_read([("EPDC_WVADDR", 0x020), ("EPDC_TEMP", 0x1A0)])
                wv, temp_idx = (vals.get("EPDC_WVADDR"), vals.get("EPDC_TEMP")) if ok else (None, None)
            else:
                temp_idx = vals["EPDC_TEMP"]
            print("=== 2 波形/LUT blob 解码（EPDC_WVADDR=0x%08x，EPDC_TEMP=%s）===" % (wv, temp_idx))
            if wv is None or not (0x80000000 <= wv <= 0x9fffffff):
                print("  WVADDR 不是有效 DDR 地址，跳过")
            else:
                mm = mmap.mmap(fd, BLOB_MAP_SIZE, mmap.MAP_SHARED, mmap.PROT_READ, offset=wv)

                if fw_blob is not None:
                    compare_len = min(4096, len(fw_blob), len(mm))
                    same_prefix = bytes(mm[:compare_len]) == fw_blob[:compare_len]
                    print("  活跃 DMA blob 与磁盘 .fw 前 %d 字节: %s"
                          % (compare_len, "相同" if same_prefix else "不同"))
                    if not same_prefix:
                        print("  !! Amazon 可能在启动时加载了临时 WRF；磁盘 .fw 头只作元数据参考。")

                def u64(o):
                    if o < 0 or o + 8 > len(mm):
                        raise ValueError("blob 偏移越界: 0x%x（映射大小 0x%x）" % (o, len(mm)))
                    return struct.unpack_from("<Q", mm, o)[0]

                def frame_nibbles(block_off, frame_no, phase_bytes, low_first):
                    start = block_off + 8 + frame_no * phase_bytes
                    end = start + phase_bytes
                    if start < 0 or end > len(mm):
                        raise ValueError("LUT 帧越界: block=0x%x frame=%d" % (block_off, frame_no))
                    out = []
                    for b in mm[start:end]:
                        if low_first:
                            out.extend((b & 0x0F, b >> 4))
                        else:
                            out.extend((b >> 4, b & 0x0F))
                    return out

                ts = u64(0)
                print("  首个 uint64 = %d（= (mode 数) × 8）" % ts)
                if ts == 0 or ts % 8 or ts > 8192:
                    print("  布局不符预期，前 32 字节：%s"
                          % " ".join("%08x" % struct.unpack_from("<I", mm, i * 4)[0] for i in range(8)))
                else:
                    top_slots = ts // 8
                    mode_off = [u64(i * 8) for i in range(top_slots)]
                    # 活跃 blob 才是硬件真正使用的数据。标准 mode 的温度表在顶层表后连续排列：
                    # mode_off[0] == 顶层表大小，相邻 mode 表间距 == temp_count * 8。
                    temp_count = ((mode_off[1] - mode_off[0]) // 8
                                  if top_slots >= 2 else 0)
                    mode_count = 0
                    for i, off in enumerate(mode_off):
                        if off != mode_off[0] + i * temp_count * 8:
                            break
                        mode_count += 1
                    if mode_count > top_slots or temp_count <= 0 or temp_count > 256:
                        raise ValueError("活跃内存表异常: modes=%d temps=%d top_slots=%d"
                                         % (mode_count, temp_count, top_slots))
                    advanced_slots = top_slots - mode_count
                    print("  标准 mode 数 = %d   温度档数 = %d   顶层指针 = %d（高级算法指针 %d）"
                          % (mode_count, temp_count, top_slots, advanced_slots))
                    if hdr_mc is not None and (mode_count != hdr_mc + 1 or temp_count != hdr_trc + 1):
                        print("  !! 磁盘头与活跃 blob 不一致: 磁盘 modes=%d temps=%d"
                              % (hdr_mc + 1, hdr_trc + 1))
                    print("  mode 表偏移 = %s" % " ".join("%d:0x%x" % pair
                                                          for pair in enumerate(mode_off)))
                    print()
                    names = {0: "INIT", 1: "DU", 2: "GC16", 3: "GC4", 4: "A2/GLR16",
                             5: "GL16/GLD16", 6: "?", 7: "?", 8: "?", 9: "?", 10: "?"}
                    print("  %-5s %-16s %-44s %s" % ("mode", "名字", "各温度档帧数", "当前档帧数"))
                    frame_counts = []
                    block_offsets = []
                    for m in range(mode_count):
                        try:
                            blocks = [u64(mode_off[m] + t * 8) for t in range(temp_count)]
                            fcs = [u64(block) for block in blocks]
                            for t, (block, fc) in enumerate(zip(blocks, fcs)):
                                if fc <= 0 or fc > 1024:
                                    raise ValueError("temp %d 帧数异常: block=0x%x frames=%d"
                                                     % (t, block, fc))
                            frame_counts.append(fcs)
                            block_offsets.append(blocks)
                            used = fcs[temp_idx] if temp_idx is not None and temp_idx < len(fcs) else None
                            print("  %-5d %-16s %-44s %s"
                                  % (m, names.get(m, "?"), " ".join("%5d" % f for f in fcs),
                                     ("%d" % used) if used is not None else "-"))
                        except ValueError as exc:
                            frame_counts.append(None)
                            block_offsets.append(None)
                            print("  %-5d %-16s %-44s %s" %
                                  (m, names.get(m, "?"), "[不是普通 4-bit LUT 表]", str(exc)))
                    print()
                    print("  说明：帧数来自各 (mode,temp) 数据块开头的 uint64，与每项位宽无关。")
                    longest = max((fc, m, t) for m, fcs in enumerate(frame_counts) if fcs is not None
                                  for t, fc in enumerate(fcs))
                    print("  标准 mode 中最长 LUT = %d 帧（mode=%d temp=%d）" % longest)
                    # 相邻唯一数据块的跨度可揭示每个 phase 的实际字节数；共享块要先去重。
                    unique_blocks = {}
                    for m, blocks in enumerate(block_offsets):
                        if blocks is None:
                            continue
                        for t, block in enumerate(blocks):
                            unique_blocks.setdefault(block, frame_counts[m][t])
                    block_addrs = sorted(unique_blocks)
                    bytes_per_phase = {}
                    for i in range(len(block_addrs) - 1):
                        block, next_block = block_addrs[i], block_addrs[i + 1]
                        fc = unique_blocks[block]
                        payload = next_block - block - 8
                        if payload >= 0 and payload % fc == 0:
                            unit = payload // fc
                            bytes_per_phase[unit] = bytes_per_phase.get(unit, 0) + 1
                    dominant_phase_bytes = None
                    if bytes_per_phase:
                        print("  相邻块推导的 bytes/phase 分布: %s"
                              % ", ".join("%dB×%d" % pair
                                          for pair in sorted(bytes_per_phase.items())))
                        dominant_phase_bytes = max(bytes_per_phase, key=bytes_per_phase.get)
                    decoded_frame_counts = frame_counts
                    decoded_temp_idx = temp_idx
                    if advanced_waveform:
                        print("  本机 luts=0x%02x；512 B/phase 正好容纳 32×32 个 4-bit action，"
                              "与 AF 的 5-bit/32-state 布局吻合。" % hdr_luts)

                    # 用“稳定灰度不变(src==dst)应当全程 NOP(0/3)”作为 nibble 顺序的一致性判据。
                    # 5-bit AF 的 16 个显示灰度映射到偶数 state，只检查这些稳定端点。
                    if (dominant_phase_bytes in (128, 512)
                            and temp_idx is not None and temp_idx < temp_count
                            and mode_count >= 5
                            and frame_counts[4] is not None):
                        mode = 4
                        fc = frame_counts[mode][temp_idx]
                        block = block_offsets[mode][temp_idx]
                        states = 16 if dominant_phase_bytes == 128 else 32
                        stable_states = list(range(states)) if states == 16 else list(range(0, 32, 2))
                        print()
                        print("  mode 4 / temp %d action 解码（%d phase，%d-state）:"
                              % (temp_idx, fc, states))
                        scores = {}
                        for label, low_first in (("偶数索引=低 nibble", True),
                                                 ("偶数索引=高 nibble", False)):
                            frames = [frame_nibbles(block, f, dominant_phase_bytes, low_first)
                                      for f in range(fc)]
                            diagonal_drive = sum(1 for values in frames for gray in stable_states
                                                 if values[gray * (states + 1)] not in (0, 3))
                            scores[label] = diagonal_drive
                            print("    %-22s: 稳定 src==dst 的驱动项 %d / %d（越少越可信）"
                                  % (label, diagonal_drive, fc * len(stable_states)))
                            hi = states - 1 if states == 16 else 30
                            for src, dst in ((0, 0), (hi, hi), (0, hi), (hi, 0)):
                                idx = dst * states + src
                                seq = "".join("%x" % values[idx] for values in frames[:32])
                                print("      %2d->%2d 前32帧: %s" % (src, dst, seq))
                        best = min(scores, key=scores.get)
                        other = max(scores, key=scores.get)
                        total_diagonal = fc * len(stable_states)
                        if (scores[best] < scores[other]
                                and scores[best] <= total_diagonal // 20):
                            print("    判定：%s（对角线判据 %d vs %d）"
                                  % (best, scores[best], scores[other]))
                        else:
                            print("    判定：对角线本身大量驱动，差异不足以判 nibble 顺序；仍需实证。")
                mm.close()

        # ---------------- 3 扫描帧率 ----------------
        # FRAME_END 是状态/中断锁存位，不是可直接轮询计数的脉冲；内核也没有给 EPDC v2
        # 实现 MXCFB_WAIT_FOR_VSYNC。按 i.MX7DRM 13.6.4.22/25/26/27，所有水平量均为
        # PIXCLK 周期，垂直量为行数，活动区长度由 EPDC_RES 给出。因此可从时钟树与 TCE
        # 寄存器直接计算扫描场率，再用多个原厂波形的完成时间交叉验证。
        if not args.no_fps:
            print()
            print("=== 3 扫描帧率（TCE 时序计算 + 多波形耗时交叉验证）===")
            if decoded_frame_counts is None or decoded_temp_idx is None:
                print("  需要波形帧数；请不要同时使用 --no-blob 与扫描帧率测试。")
            else:
                timing_regs = vals
                if not all(k in timing_regs for k in ("EPDC_RES", "EPDC_TCE_HSCAN1",
                                                       "EPDC_TCE_HSCAN2", "EPDC_TCE_VSCAN")):
                    timing_regs, _ = powered_read([
                        ("EPDC_RES", 0x040), ("EPDC_TCE_HSCAN1", 0x260),
                        ("EPDC_TCE_HSCAN2", 0x280), ("EPDC_TCE_VSCAN", 0x2A0)])
                pixel_hz = None
                try:
                    with open("/sys/kernel/debug/clk/clk_summary") as clk_file:
                        for line in clk_file:
                            fields = line.split()
                            if fields and fields[0] == "epdc_pixel_root_clk" and len(fields) >= 4:
                                pixel_hz = int(fields[3])
                                break
                except (IOError, OSError, ValueError):
                    pass
                res = timing_regs.get("EPDC_RES", 0)
                hs1 = timing_regs.get("EPDC_TCE_HSCAN1", 0)
                hs2 = timing_regs.get("EPDC_TCE_HSCAN2", 0)
                vs = timing_regs.get("EPDC_TCE_VSCAN", 0)
                width, height = res & 0x1FFF, (res >> 16) & 0x1FFF
                line_sync = hs1 & 0xFFF
                line_begin, line_end = hs2 & 0xFFF, (hs2 >> 16) & 0xFFF
                frame_sync = vs & 0xFF
                frame_begin, frame_end = (vs >> 8) & 0xFF, (vs >> 16) & 0xFF
                htotal = line_sync + line_begin + width + line_end
                vtotal = frame_sync + frame_begin + height + frame_end
                scan_hz = (float(pixel_hz) / (htotal * vtotal)) if pixel_hz and htotal and vtotal else None
                if scan_hz:
                    print("  PIXCLK=%d Hz；水平=%d+%d+%d+%d=%d clocks；"
                          "垂直=%d+%d+%d+%d=%d lines"
                          % (pixel_hz, line_sync, line_begin, width, line_end, htotal,
                             frame_sync, frame_begin, height, frame_end, vtotal))
                    print("  TCE 扫描帧率 = %.3f 场/秒（周期 %.3f ms）" %
                          (scan_hz, 1000.0 / scan_hz))
                else:
                    print("  !! 无法读取 epdc_pixel_root_clk 或 TCE 时序，跳过公式计算")
                samples = []
                timing_names = {0: "INIT", 1: "DU", 2: "GC16", 3: "GC4",
                                4: "A2", 5: "GL16", 6: "mode6"}
                for mode in range(min(7, len(decoded_frame_counts))):
                    fcs = decoded_frame_counts[mode]
                    if fcs is None or decoded_temp_idx >= len(fcs):
                        continue
                    frames = fcs[decoded_temp_idx]
                    t0 = time.monotonic()
                    # 黑白交替，避免连续提交相同目标值被 advanced/AF 波形缩短成 no-op。
                    keepalive(mode, keep_black if mode % 2 == 0 else keep_white)
                    wait()
                    elapsed_ms = (time.monotonic() - t0) * 1000.0
                    samples.append((frames, elapsed_ms, mode))
                    if scan_hz:
                        scans = max(1, int(round(elapsed_ms * scan_hz / 1000.0)))
                        expected_ms = scans * 1000.0 / scan_hz
                        print("  mode %-2d %-6s 表头%3d -> %7.2f ms ≈ %2d 个扫描场（误差 %+5.2f ms）"
                              % (mode, timing_names.get(mode, "?"), frames, elapsed_ms,
                                 scans, elapsed_ms - expected_ms))
                    else:
                        print("  mode %-2d %-6s 表头%3d -> %7.2f ms" %
                              (mode, timing_names.get(mode, "?"), frames, elapsed_ms))
                print("  注：advanced/AF 的表头 frame_count 不是等时扫描场数；"
                      "这里不再对它做线性拟合。")
    finally:
        reg.close()
        os.close(fd)
        FBInk.fbink_close(fbfd)
    return rc


if __name__ == "__main__":
    sys.exit(main())
