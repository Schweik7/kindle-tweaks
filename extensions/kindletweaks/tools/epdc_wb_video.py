#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EPDC 长 LUT + 直接写 WB 的视频演示（K4 那条路的可行性验证）。

思路（见 docs/18 §4.7）：
  1. 用一次 mxcfb 索引 10 的更新启动自造的 512 相 LUT（≈6.06 s），**不等完成**；
  2. 期间直接往预留区 0x9C000000（EPDC working buffer）写每帧内容；
  3. 自造表只对 target=0（推黑）与 target=15（推白）动作，其它 target 完全不驱动
     —— 于是"驱动一段时间后把 target 改回 8"就等于**停止驱动**，而 e-ink 像素会保持
     状态不变。这样像素只在跃变期间被驱动，直流负载被压到最小。

⚠ 时序要点（第一版踩过的坑）：**驱动时长必须按墙钟时间算，不能按软件帧数**。
   实测软件写 WB 可达 ~1000 帧/秒，而面板扫描只有 84.5 场/秒 —— 若按"4 帧"驱动，
   实际只驱动了几毫秒，不到一个扫描场，屏幕上什么都不会发生。

WB 每个像素 16 位：bit15:12 = LUT 号，bit11 = partial，bit7:4 = target 灰度，
bit3:0 = current 灰度（由硬件维护，我们不动它）。

安全：不碰任何 EPDC 寄存器；每轮 512 相 ≈6.06 s < 驱动 ~7.5 s 完成超时；只驱动动画区。
"""
import argparse
import atexit
import mmap
import os
import subprocess
import sys
import time

WFM = 10
WB_PHYS = 0x9C000000
W, H = 1264, 1680
NOOP_GRAY = 8
TARGET_BLACK, TARGET_WHITE = 0, 15


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

    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--seconds", type=float, default=4.5, help="每轮动画时长")
    ap.add_argument("--pause", type=float, default=1.0, help="轮与轮之间的停歇")
    ap.add_argument("--speed", type=float, default=300.0, help="竖条速度 px/秒")
    ap.add_argument("--bar-w", type=int, default=150)
    ap.add_argument("--drive-ms", type=float, default=160.0,
                    help="每列跃变后被驱动的墙钟时长（一个扫描场 ≈11.83 ms）")
    ap.add_argument("--band", default="560,1160", help="动画区 y0,y1")
    ap.add_argument("--hold", action="store_true")
    args = ap.parse_args()

    y0, y1 = [int(v) for v in args.band.split(",")]
    lipc("com.lab126.powerd.wakeUp", 1, True)
    lipc("com.lab126.powerd.preventScreenSaver", 1, True)
    atexit.register(lambda: lipc("com.lab126.powerd.preventScreenSaver", 0, True))

    fbfd = FBInk.fbink_open()
    cfg = ffi.new("FBInkConfig *")
    cfg.is_quiet = True
    FBInk.fbink_init(fbfd, cfg)
    st = ffi.new("FBInkState *")
    FBInk.fbink_get_state(cfg, st)

    fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    wb = mmap.mmap(fd, W * H * 2, mmap.MAP_SHARED,
                   mmap.PROT_READ | mmap.PROT_WRITE, offset=WB_PHYS)
    view = np.ndarray((H, W), dtype=np.uint16, buffer=wb)
    band = view[y0:y1, :]
    bh, bw = band.shape
    xs = np.arange(bw)
    drive_s = args.drive_ms / 1000.0

    print("屏幕 %dx%d  WB@0x%08x" % (st.screen_width, st.screen_height, WB_PHYS))
    print("动画区 y=%d..%d（%d 行，屏幕中部偏下那一大片）；白色竖条宽 %d px，"
          "以 %.0f px/秒向右匀速扫过；每列驱动 %.0f ms（≈%.1f 个扫描场）"
          % (y0, y1, bh, args.bar_w, args.speed, args.drive_ms, args.drive_ms / 11.833))
    print("共 %d 轮，每轮 %.1f 秒，轮间停 %.1f 秒" % (args.rounds, args.seconds, args.pause))
    print("=" * 60)
    sys.stdout.flush()

    gray = np.full(H * W, 128, dtype=np.uint8).tobytes()
    lut = None
    total_frames = 0
    total_loops = 0.0

    for rnd in range(1, args.rounds + 1):
        # 1) 启动长 LUT：提交全中灰画面（target≈7 ⇒ 我们的表不驱动任何像素）
        c = ffi.new("FBInkConfig *")
        c.is_quiet = True
        c.wfm_mode = WFM
        c.is_flashing = True
        FBInk.fbink_print_raw_data(fbfd, gray, W, H, len(gray), 0, 0, c)
        # 等 PxP 真的把 WB 重写成"全中灰"，再取 LUT 号 —— 否则可能读到上一轮的旧值
        w = int(view[y0 + 10, 100])
        for _ in range(80):
            w = int(view[y0 + 10, 100])
            if 5 <= ((w >> 4) & 0xF) <= 9:
                break
            time.sleep(0.01)
        lut = (w >> 12) & 0xF
        if rnd == 1:
            print("  驱动写入的 WB 字 = 0x%04x ⇒ LUT 号 = %d（每轮重新同步读取）" % (w, lut))

        def word(t, _lut=lut):
            return np.uint16((_lut << 12) | ((t & 0xF) << 4))

        # 2) 整条带先成型（背景黑、竖条白），给足驱动时间
        want = np.where((xs % bw) < args.bar_w, TARGET_WHITE, TARGET_BLACK).astype(np.int64)
        written = np.full(bw, NOOP_GRAY, dtype=np.int64)
        for x in range(bw):
            band[:, x] = word(int(want[x]))
        written[:] = want
        time.sleep(drive_s + 0.35)      # 让黑带和白条先完全成型

        # 3) 逐帧写 WB，位置按墙钟时间推进
        frames = 0
        writes = 0
        prev_want = want.copy()
        last_t = np.full(bw, time.time())
        t_anim = time.time()
        print("  第 %d/%d 轮：竖条开始从左侧扫过…" % (rnd, args.rounds))
        sys.stdout.flush()
        while True:
            now = time.time()
            el = now - t_anim
            if el >= args.seconds:
                break
            pos = int(args.speed * el) % bw
            want = np.where(((xs - pos) % bw) < args.bar_w,
                            TARGET_WHITE, TARGET_BLACK).astype(np.int64)
            chg = want != prev_want
            if chg.any():
                last_t[chg] = now
                prev_want = want
            tgt = np.where((now - last_t) < drive_s, want, NOOP_GRAY)
            diff = np.nonzero(tgt != written)[0]
            if diff.size:
                for x in diff:
                    band[:, int(x)] = word(int(tgt[x]))
                written[diff] = tgt[diff]
                writes += int(diff.size)
            frames += 1
        dt = time.time() - t_anim
        total_frames += frames
        total_loops += dt
        print("    本轮 %.3f s / %d 次迭代 ⇒ %.0f 帧/秒（写入 %d 列次）"
              % (dt, frames, frames / dt, writes))
        sys.stdout.flush()
        if rnd < args.rounds:
            time.sleep(args.pause)

    print("=" * 60)
    if total_loops:
        print("合计：%.1f 秒内 %d 次迭代 ⇒ 平均 **%.0f 帧/秒**（软件侧）"
              % (total_loops, total_frames, total_frames / total_loops))
        print("面板扫描场 ≈ 11.83 ms ⇒ 显示帧率上限约 84.5 Hz；软件侧富余 %.1f 倍"
              % ((total_frames / total_loops) / (1000 / 11.833)))

    if args.hold:
        print("--hold：动画停在当前位置（白竖条应停在动画区里）")
    else:
        print("切回主页重绘")
        lipc("com.lab126.appmgrd.start", "app://com.lab126.booklet.home")
        time.sleep(2)
    view = None
    wb.close()
    os.close(fd)
    FBInk.fbink_close(fbfd)
    lipc("com.lab126.powerd.preventScreenSaver", 0, True)
    print("结束")
    return 0


if __name__ == "__main__":
    sys.exit(main())
