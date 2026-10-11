#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EPDC 长 LUT 探针：一次性判定 action 极性 + LUT 表索引布局。

原理（详见 docs/18）：
  探针表 = 全部 1024 项都是 action 1，只有 index 480..511 改成 action 2。
  屏幕画三条竖带：左=黑(target 0) 中=中灰(target 8) 右=白(target 15)。
    * 若表索引是「target 外层」(index = target*32 + current)：
      左/中 → action 1，右 → action 2  ⇒ 左中同色、右带不同色
    * 若表索引是「current 外层」(index = current*32 + target)：
      驱动写 WB 时 current 恒为 0，三条带全部落到 index 0..31 ⇒ action 1 ⇒ 整屏一色
  另外，最终颜色直接告诉我们 action 1 / 2 各自推向黑还是白。

安全：
  * 全屏但只跑 256 相（≈3.0 s），duty=2（每 2 相才驱动 1 相）→ 实际驱动 128 相，
    远低于驱动 7.5 s 完成超时，直流负载也减半。
  * 不映射 EPDC 寄存器；只在正常 mxcfb 路径提交一次更新（不等完成）。
  * atexit 收尾：还原屏保设置、切回主页重绘。
"""
import atexit
import argparse
import subprocess
import sys
import time

WFM = 10                 # 实测 mxcfb 索引 10 → blob mode 7（我们的自造 mode）
BANDS = [(0, 1 / 3.0, 0), (1 / 3.0, 2 / 3.0, 128), (2 / 3.0, 1.0, 255)]


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
    ap.add_argument("--hold", action="store_true",
                    help="结束后不切回主页，把探针结果留在屏上供观察")
    ap.add_argument("--draw-wait", type=float, default=0.6)
    args = ap.parse_args()

    lipc("com.lab126.powerd.wakeUp", 1, True)
    lipc("com.lab126.powerd.preventScreenSaver", 1, True)
    atexit.register(lambda: lipc("com.lab126.powerd.preventScreenSaver", 0, True))

    fbfd = FBInk.fbink_open()
    cfg = ffi.new("FBInkConfig *")
    cfg.is_quiet = True
    FBInk.fbink_init(fbfd, cfg)
    st = ffi.new("FBInkState *")
    FBInk.fbink_get_state(cfg, st)
    W, H = st.screen_width, st.screen_height
    print("屏幕 %dx%d" % (W, H))

    frame = np.zeros(H * W, dtype=np.uint8)
    for x0f, x1f, val in BANDS:
        x0, x1 = int(W * x0f), int(W * x1f)
        frame.reshape(H, W)[:, x0:x1] = val
    buf = frame.tobytes()
    print("三竖带：左=黑(0)  中=中灰(128)  右=白(255)")

    # 1) 先用普通 GC16 把三条带画出来（让面板确实显示这个图案）
    print("步骤 1：GC16 画出三条带（正常波形，等待完成）")
    c = ffi.new("FBInkConfig *")
    c.is_quiet = True
    c.wfm_mode = 2
    c.is_flashing = True
    t0 = time.time()
    FBInk.fbink_print_raw_data(fbfd, buf, W, H, len(buf), 0, 0, c)
    FBInk.fbink_wait_for_complete(fbfd, 0)
    print("  完成，耗时 %.0f ms" % ((time.time() - t0) * 1000))
    time.sleep(0.6)

    # 2) 用自造的长 LUT（mxcfb 10）再提交一次同样的内容，不等完成
    print("步骤 2：提交长 LUT 更新（mxcfb 10 = blob mode 7，256 相 ≈3.0 s）")
    print("        注意：这条路径**不等待完成**（驱动自己在 ~7.5 s 才会超时）")
    c2 = ffi.new("FBInkConfig *")
    c2.is_quiet = True
    c2.wfm_mode = WFM
    c2.is_flashing = True
    t0 = time.time()
    rc = FBInk.fbink_print_raw_data(fbfd, buf, W, H, len(buf), 0, 0, c2)
    print("  提交返回 rc=%d（耗时 %.0f ms —— 提交本身很快，说明 LUT 在后台跑）"
          % (rc, (time.time() - t0) * 1000))

    # 3) 等长 LUT 跑完（256 相 * 11.833ms ≈ 3.03 s，留足余量）
    print("步骤 3：等 4.0 秒让 256 相跑完（期间面板正在被自造波形驱动）")
    for i in range(4):
        time.sleep(1.0)
        print("    %d 秒…" % (i + 1))
    print("  完成")

    # 4) 收尾
    if args.hold:
        print("步骤 4：--hold，不切回主页，探针结果留在屏上，请观察当前的画面")
    else:
        print("步骤 4：切回主页重绘")
        lipc("com.lab126.appmgrd.start", "app://com.lab126.booklet.home")
        time.sleep(2)
    FBInk.fbink_close(fbfd)
    atexit.unregister(lipc)
    lipc("com.lab126.powerd.preventScreenSaver", 0, True)
    print("结束")
    return 0


if __name__ == "__main__":
    sys.exit(main())
