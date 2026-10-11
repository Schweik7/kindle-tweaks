#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""找出 mxcfb 的 waveform_mode 索引与实际 blob mode 的对应关系。

背景：我们把 blob 的 mode 7 改成了 1023 相 no-op，但用 mxcfb waveform_mode=7
提交的更新只花了 ~347ms（GC16 级），说明 **mxcfb 索引 != blob mode 序号**。

做法：把 mxcfb 索引 0..17 各提交一次 64x64 的 no-op 更新并计时。
谁变成秒级，谁就指向我们那个 1023 相块。全程只用正常 update 路径，不碰 EPDC 寄存器。
"""
import atexit
import subprocess
import sys
import time

REG_X = REG_Y = 8
REG_W = REG_H = 64
SCAN_MS = 18.46548
LONG_S = 2.0            # 超过这个就算"命中了长 LUT"
MAX_IDX = 17


def lipc(prop, value, intval=False):
    pub, _, name = prop.rpartition(".")
    cmd = ["lipc-set-prop"] + (["-i"] if intval else []) + ["--", pub, name, str(value)]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except Exception:
        pass


def main():
    from _fbink import ffi, lib as FBInk
    import numpy as np

    lipc("com.lab126.powerd.wakeUp", 1, True)
    lipc("com.lab126.powerd.preventScreenSaver", 1, True)
    atexit.register(lambda: lipc("com.lab126.powerd.preventScreenSaver", 0, True))
    atexit.register(lambda: lipc("com.lab126.appmgrd.start", "app://com.lab126.booklet.home"))

    fbfd = FBInk.fbink_open()
    cfg = ffi.new("FBInkConfig *")
    cfg.is_quiet = True
    FBInk.fbink_init(fbfd, cfg)

    black = np.zeros(REG_H * REG_W, dtype=np.uint8).tobytes()
    white = np.full(REG_H * REG_W, 255, dtype=np.uint8).tobytes()

    def run(wfm, pixels, flash=False):
        c = ffi.new("FBInkConfig *")
        c.is_quiet = True
        c.wfm_mode = wfm
        c.is_flashing = flash
        FBInk.fbink_print_raw_data(fbfd, pixels, REG_W, REG_H, len(pixels), REG_X, REG_Y, c)
        FBInk.fbink_wait_for_complete(fbfd, 0)

    print("mxcfb 索引扫描：找那个会卡住十几秒的（= 指向我们的 1023 相块）")
    print("扫描场 = %.2f ms；原厂短波形都在 100~450ms 量级" % SCAN_MS)
    print()
    print("  %-6s %-12s %-12s %s" % ("索引", "耗时", "约合扫描场", "判读"))
    hits = []
    for idx in range(MAX_IDX + 1):
        # 每轮先刷白，保证有"变化"可做（避免驱动判定无变化而跳过 LUT）
        run(2, white, flash=True)
        time.sleep(0.15)
        t0 = time.time()
        run(idx, black)
        dt = time.time() - t0
        fields = dt * 1000.0 / SCAN_MS
        if dt >= LONG_S:
            note = "★ 命中长 LUT！"
            hits.append((idx, dt))
            # 长 LUT 会占住 LUT 槽，等它跑完再继续
            time.sleep(min(dt + 0.5, 30))
        elif dt < 0.06:
            note = "快得可疑（可能被丢弃）"
        else:
            note = ""
        print("  %-6d %-12s %-12.1f %s" % (idx, "%.1f ms" % (dt * 1000), fields, note))
    print()
    if hits:
        print("结论：mxcfb 索引 %s 指向我们改过的 blob mode 7（1023 相）。"
              % ", ".join("%d(%.2fs)" % h for h in hits))
        print("      => mxcfb waveform_mode 与 blob mode 序号【不是】一一对应，")
        print("         之前按 mode 7 改是改错了槽位。")
    else:
        print("结论：0..%d 里没有任何索引变成秒级 —— 说明 1023 相没有被任何 mxcfb 索引用到。" % MAX_IDX)
        print("      可能原因：(a) 该 blob mode 根本没被 mxcfb 索引引用；")
        print("                (b) 驱动/硬件忽略了超长 frame_count（存在上限）；")
        print("                (c) 全零 action 的 LUT 被提前终止。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
