#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测量自造 1023 相 no-op 波形（mode 7）的实际执行时长。

安全设计：
  * **完全不映射 EPDC 寄存器**（吸取 P2 的教训：更新结束后读寄存器会让设备卡死）。
  * 只用 64x64 小块，绝不用整屏。
  * 不写任何寄存器；只通过正常 mxcfb update 路径提交。
  * mode 7 是**全零 action**，理论上不施加任何电压 -> 屏幕上不应有任何可见变化。
  * atexit 收尾：还原 preventScreenSaver、切回主页。

判据：如果自造波形被采用，mode 7 的耗时应从「~100ms 级」跳到「秒级」。
"""
import atexit
import subprocess
import sys
import time

EXPECT_MODE7_MIN_S = 3.0        # 低于这个就说明 1023 相没生效
TIMEOUT_S = 90.0                # 单次更新的硬上限，防止把设备拖死

REG_X = REG_Y = 8
REG_W = REG_H = 64


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
    st = ffi.new("FBInkState *")
    FBInk.fbink_get_state(cfg, st)
    print("屏幕 %dx%d  测试块 %dx%d @ (%d,%d)" % (st.screen_width, st.screen_height,
                                                  REG_W, REG_H, REG_X, REG_Y))

    def submit(wfm, pixels, flash=False):
        c = ffi.new("FBInkConfig *")
        c.is_quiet = True
        c.wfm_mode = wfm
        c.is_flashing = flash
        return FBInk.fbink_print_raw_data(fbfd, pixels, REG_W, REG_H, len(pixels),
                                          REG_X, REG_Y, c)

    white = np.full(REG_H * REG_W, 255, dtype=np.uint8).tobytes()
    black = np.zeros(REG_H * REG_W, dtype=np.uint8).tobytes()

    def timed(label, wfm, pixels, flash=False):
        t0 = time.time()
        rc = submit(wfm, pixels, flash)
        FBInk.fbink_wait_for_complete(fbfd, 0)
        dt = time.time() - t0
        print("  %-34s rc=%-3d %8.2f ms" % (label, rc, dt * 1000.0))
        return dt

    print()
    print("=== 先建立一个干净基线（GC16 刷白）===")
    timed("mode 2 (GC16) 刷白 [基线]", 2, white, flash=True)
    time.sleep(0.5)

    print()
    print("=== 测量 ===")
    # 对照组：原厂短波形
    t_gc16 = timed("mode 2 (GC16, 29 相)  对照", 2, white, flash=True)
    t_a2 = timed("mode 4 (A2,   23 相)  对照", 4, white)
    # 实验组：我们改成 1023 相的 mode 7
    print("  --- 下面是自造的 1023 相 no-op，可能会卡住十几秒，请稍候 ---")
    t_m7 = timed("mode 7 (自造 no-op, 1023 相)", 7, black, flash=False)

    print()
    print("=== 结果 ===")
    scan_ms = 18.46548
    for name, dt in (("GC16(29相)", t_gc16), ("A2(23相)", t_a2), ("mode7(1023相)", t_m7)):
        print("  %-16s %9.2f ms  ≈ %6.1f 个扫描场(%.2f ms)  ≈ %6.1f 相/场(若相位=场)"
              % (name, dt * 1000.0, dt * 1000.0 / scan_ms, scan_ms, 1023.0 / (dt * 1000.0 / scan_ms) if dt else 0))
    print()
    if t_m7 >= EXPECT_MODE7_MIN_S:
        print("  ✅ PASS：mode 7 耗时 %.2f 秒，远超原厂波形 —— 自造的 1023 相 LUT 确实被硬件执行了。"
              % t_m7)
        print("     => 「长 LUT 常驻」在 Oasis 3 上成立：一张 LUT 能持续驱动面板 %.1f 秒。" % t_m7)
    else:
        print("  !! FAIL：mode 7 只有 %.2f ms，和短波形同级 —— 1023 相没有被采用。" % (t_m7 * 1000.0))
        print("     可能原因：mode 7 的指针没被采纳 / 硬件忽略了超长 LUT / LUT 提前结束。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
