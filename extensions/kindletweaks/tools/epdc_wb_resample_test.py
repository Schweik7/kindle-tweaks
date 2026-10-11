#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KOA3 EPDC P2：验证同一 update 运行中是否重采样 working buffer。

安全边界：
  * 不映射、不读取、更不写入 EPDC 寄存器。控制器 CLKGATE 后读寄存器可能挂总线。
  * --setup-only 只初始化 FBInk，不映射 working buffer，也不提交刷新。
  * --control-only 只读 working buffer，通过驱动提交两个 64x64 GC16 更新。
  * 只有 --execute 才把一个像素的 target gray(bit7:4) 改写一次。
  * 不调用 WAIT_FOR_UPDATE_COMPLETE；完成状态只由安全的 reserved WB 内容判断。

设备端运行时必须提供 FBInk 动态库路径：
  LD_LIBRARY_PATH=/mnt/us/python3/lib PYTHONIOENCODING=utf-8 \
    /mnt/us/python3/bin/python3.9 -u epdc_wb_resample_test.py --setup-only
"""
import argparse
import mmap
import os
import signal
import struct
import subprocess
import sys
import time

EXPECTED_COMPATIBLE = b"fsl,imx7d-zelda"
EXPECTED_WIDTH = 1264
EXPECTED_HEIGHT = 1680
WB_PHYS = 0x9C000000
WB_MAP_SIZE = 0x500000
PM_DIR = "/sys/devices/platform/soc/30400000.aips-bus/306f0000.epdc/power"

REG_X = REG_Y = 8
REG_W = REG_H = 64
PIXEL_X = PIXEL_Y = 40
WFM_GC16 = 2
SCAN_PERIOD_S = 1.0 / 54.1551009
SETTLE_TIMEOUT_S = 3.0


def lipc(prop, value, intval=False):
    pub, _, name = prop.rpartition(".")
    cmd = ["lipc-set-prop"] + (["-i"] if intval else []) + ["--", pub, name, str(value)]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except Exception:
        pass


def fields(word):
    return {
        "word": word,
        "lut": (word >> 12) & 0xF,
        "partial": (word >> 11) & 1,
        "target": (word >> 4) & 0xF,
        "current": word & 0xF,
    }


def fmt_word(word):
    f = fields(word)
    return "0x%04x lut=%x partial=%d target=%x current=%x" % (
        f["word"], f["lut"], f["partial"], f["target"], f["current"])


def main():
    ap = argparse.ArgumentParser()
    modes = ap.add_mutually_exclusive_group()
    modes.add_argument("--setup-only", action="store_true",
                       help="只初始化 FBInk，不映射 WB、不刷新")
    modes.add_argument("--control-only", action="store_true",
                       help="通过驱动刷新并只读 WB，不直接写 WB")
    modes.add_argument("--execute", action="store_true",
                       help="执行一次单像素 WB target 写入实验")
    args = ap.parse_args()
    if not (args.setup_only or args.control_only or args.execute):
        print("拒绝执行：请显式传 --setup-only、--control-only 或 --execute。")
        return 2

    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass

    def timeout_handler(_signum, _frame):
        raise TimeoutError("实验总时长超过 15 秒")

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(15)

    fd = None
    wb = None
    fbfd = None
    FBInk = None
    original_word = None
    pixel_off = None
    did_write = False

    try:
        print("启动：参数检查通过，准备加载 FBInk。")
        from _fbink import ffi, lib as FBInk

        compatible = open("/proc/device-tree/compatible", "rb").read()
        if EXPECTED_COMPATIBLE not in compatible:
            raise RuntimeError("设备 compatible 不匹配: %r" % compatible)

        pm_control = open(PM_DIR + "/control").read().strip()
        pm_status = open(PM_DIR + "/runtime_status").read().strip()
        print("设备指纹通过；EPDC PM=%s/%s（不修改）" % (pm_control, pm_status))
        lipc("com.lab126.powerd.wakeUp", 1, True)
        lipc("com.lab126.powerd.preventScreenSaver", 1, True)

        fbfd = FBInk.fbink_open()
        cfg = ffi.new("FBInkConfig *")
        cfg.is_quiet = True
        if FBInk.fbink_init(fbfd, cfg) < 0:
            raise RuntimeError("fbink_init 失败")
        state = ffi.new("FBInkState *")
        FBInk.fbink_get_state(cfg, state)
        if (state.screen_width, state.screen_height) != (EXPECTED_WIDTH, EXPECTED_HEIGHT):
            raise RuntimeError("屏幕尺寸不匹配: %dx%d" %
                               (state.screen_width, state.screen_height))
        print("FBInk 初始化通过：%dx%d" % (state.screen_width, state.screen_height))

        if args.setup_only:
            print("SETUP PASS：未映射 WB，未提交刷新。")
            return 0

        mem_mode = os.O_RDWR if args.execute else os.O_RDONLY
        fd = os.open("/dev/mem", mem_mode | os.O_SYNC)
        wb_prot = mmap.PROT_READ | mmap.PROT_WRITE if args.execute else mmap.PROT_READ
        wb = mmap.mmap(fd, WB_MAP_SIZE, mmap.MAP_SHARED, wb_prot, offset=WB_PHYS)

        # EPDC working buffer 没有 stride 寄存器；硬件按 EPDC_RES.width 紧密排列。
        pixel_off = (PIXEL_Y * EXPECTED_WIDTH + PIXEL_X) * 2

        def rd_word():
            return struct.unpack_from("<H", wb, pixel_off)[0]

        def wr_target(target):
            nonlocal did_write
            before = rd_word()
            after = (before & ~0x00F0) | ((target & 0xF) << 4)
            struct.pack_into("<H", wb, pixel_off, after)
            did_write = True
            return before, rd_word()

        white = bytes([255]) * (REG_W * REG_H)
        black = bytes(REG_W * REG_H)

        def draw(pixels):
            draw_cfg = ffi.new("FBInkConfig *")
            draw_cfg.is_quiet = True
            draw_cfg.wfm_mode = FBInk.WFM_GC16 if hasattr(FBInk, "WFM_GC16") else WFM_GC16
            draw_cfg.is_flashing = True
            rc = FBInk.fbink_print_raw_data(fbfd, pixels, REG_W, REG_H, len(pixels),
                                             REG_X, REG_Y, draw_cfg)
            if rc < 0:
                raise RuntimeError("fbink_print_raw_data 失败: %d" % rc)
            return rc

        def wait_gray(gray, timeout=SETTLE_TIMEOUT_S):
            deadline = time.monotonic() + timeout
            last = rd_word()
            while time.monotonic() < deadline:
                last = rd_word()
                f = fields(last)
                if f["target"] == gray and f["current"] == gray:
                    return last
                time.sleep(0.005)
            raise TimeoutError("WB 未在 %.1fs 内稳定到灰度%x: %s" %
                               (timeout, gray, fmt_word(last)))

        def settle(pixels, gray):
            marker = draw(pixels)
            word = wait_gray(gray)
            print("  settle gray=%x marker=%s: %s" % (gray, marker, fmt_word(word)))
            return word

        original_word = rd_word()
        print("WB 单元 (%d,%d) 初值: %s" % (PIXEL_X, PIXEL_Y, fmt_word(original_word)))

        settle(white, 0xF)
        if args.control_only:
            settled = settle(black, 0x0)
            print("CONTROL PASS：两次 GC16 更新完成；WB 始终只读: %s" %
                  fmt_word(settled))
            return 0

        print("\nA: 白底 -> 黑；运行中把单像素 target 改回白")
        t_submit = time.monotonic()
        marker = draw(black)
        # 白色基线本身可能仍在驱动队列中；给后续黑更新最多 3 秒开始，
        # 真正的写入时刻仍以捕获到 target=0/current=f 为准。
        deadline = t_submit + SETTLE_TIMEOUT_S
        armed_word = None
        while time.monotonic() < deadline:
            word = rd_word()
            f = fields(word)
            if f["target"] == 0x0 and f["current"] == 0xF:
                armed_word = word
                break
            time.sleep(0.001)
        if armed_word is None:
            raise RuntimeError("未捕获到白->黑的在飞状态: %s" % fmt_word(rd_word()))

        time.sleep(SCAN_PERIOD_S * 1.25)
        before, after = wr_target(0xF)
        t_write = time.monotonic()
        print("  marker=%s armed@%.2fms: %s" %
              (marker, (t_write - t_submit) * 1000.0, fmt_word(armed_word)))
        print("  WRITE target 0 -> f: %s => %s" %
              (fmt_word(before), fmt_word(after)))

        samples = []
        end = t_write + SETTLE_TIMEOUT_S
        while time.monotonic() < end:
            samples.append(((time.monotonic() - t_write) * 1000.0, rd_word()))
            time.sleep(0.005)
        final_word = rd_word()
        final = fields(final_word)
        saw_target_f = any(fields(word)["target"] == 0xF for _, word in samples)
        saw_current_0 = any(fields(word)["current"] == 0x0 for _, word in samples)
        print("  complete@%.2fms: %s" %
              ((time.monotonic() - t_submit) * 1000.0, fmt_word(final_word)))
        print("  samples=%d target曾保持f=%s current曾到黑=%s" %
              (len(samples), saw_target_f, saw_current_0))

        if final["target"] != 0xF:
            print("INCONCLUSIVE：硬件/驱动覆盖了写入的 target nibble。")
            return 1
        if final["current"] == 0xF and not saw_current_0:
            print("PASS：同一 update 采用了中途改回的白 target，未完成黑转换。")
            return 0
        print("FAIL：current gray 仍完成黑转换；本次未观察到同一 update 重采样。")
        return 1

    finally:
        signal.alarm(0)
        # 不读取任何 EPDC 寄存器。只在确实写过时恢复原 target nibble。
        if did_write and wb is not None and pixel_off is not None and original_word is not None:
            try:
                current_word = struct.unpack_from("<H", wb, pixel_off)[0]
                restored = (current_word & ~0x00F0) | (original_word & 0x00F0)
                struct.pack_into("<H", wb, pixel_off, restored)
                print("已恢复原 target nibble: %s" % fmt_word(restored))
            except Exception as exc:
                print("!! 恢复原 WB 单元失败: %s" % exc)
        if wb is not None:
            wb.close()
        if fd is not None:
            os.close(fd)
        if fbfd is not None and FBInk is not None:
            FBInk.fbink_close(fbfd)
        lipc("com.lab126.powerd.preventScreenSaver", 0, True)
        lipc("com.lab126.appmgrd.start", "app://com.lab126.booklet.home")
        print("收尾完成：未触碰 EPDC 寄存器；屏保已恢复，已请求主页重绘。")


if __name__ == "__main__":
    sys.exit(main())
