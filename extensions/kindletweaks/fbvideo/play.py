#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在 Kindle 墨水屏上播放 .ktvid 帧序列（Python + Pillow + py-fbink，无需编译）。

为什么能跑起来：绕过 X，直接把像素写进 framebuffer 并用选定的波形刷屏。
实测（Oasis 3 / FW 5.15.1.1）：Xorg 在跑的情况下 fbink_write 依然能显示，而且会保持；
但**系统一旦整体重绘就会被冲掉**（`restart kppmainapp` 后实测内容消失），
所以播放期间要自己接管屏幕，并用 preventScreenSaver 压住屏保。

用法：
    python3 play.py video.ktvid                    # 居中播放到结束
    python3 play.py video.ktvid --loops 2          # 循环两遍
    python3 play.py video.ktvid --fps 12           # 覆盖文件里的帧率
    python3 play.py video.ktvid --waveform DU      # 换波形（见下表）
    python3 play.py video.ktvid --gc-every 40      # 每 40 帧做一次全刷去残影
    python3 play.py video.ktvid --x 0 --y 0        # 指定左上角（默认居中）
    python3 play.py video.ktvid --no-restore       # 播完不切回主页（保留最后一帧）

波形（FBInk 头文件给的实测耗时，1bit 内容推荐 A2）：
    A2     黑白->黑白   ~120ms   快，有残影      <- 默认，纯黑白内容最合适
    DU     任意->黑白   ~260ms   较快，轻残影
    GC4    任意->灰阶   ~290ms
    GC16   任意->任意   ~450ms   最干净，慢
    GL16   白->任意     ~450ms

退出：播完 / 播够帧数 / 收到 stop / 按翻页键（默认）/ 点触摸屏（若 `--touch stop`）。

**播放中怎么控制**（两种方式都行）：

1. **在设备上直接操作**（默认行为）：
   - **点一下触摸屏** = 暂停 / 继续（暂停时画面中央显示「暂停 12/1755」）
   - **按翻页键** = 停止播放并回到主页
   - 电源键不抢，交给系统
2. **从 KUAL 菜单或 SSH 控制**（写控制文件，读到就删，一次性）：
   ```sh
   E=/mnt/us/extensions/kindletweaks
   echo toggle > $E/fbvideo/ctl     # pause / resume / toggle / stop / restart
   ```
   播放中还会把状态写到 `$E/fbvideo/state`（status/name/frame/total/fps/waveform/pid），
   KUAL 的菜单标题和「播放状态」靠它显示。
"""
import argparse
import os
import struct
import subprocess
import sys
import time
import zlib

import numpy as np

MAGIC = b"KTVID1\x00\x00"
HEADER_SIZE = 48
FLAG_MSB = 0x01
FLAG_ZLIB = 0x02


class _Done(Exception):
    """内部用：跳出播放循环（停止播放）"""
    pass

WAVEFORMS = ["A2", "DU", "GC16", "GC4", "GL16", "DU4", "AUTO"]
# 按键/触摸设备（Oasis 3）：0 电源键、3 翻页键、8 触摸屏
INPUT_DEVS = ["/dev/input/event0", "/dev/input/event3", "/dev/input/event8"]
INPUT_EVENT_SIZE = 16  # 32 位 ARM：tv_sec(4) tv_usec(4) type(2) code(2) value(4)


def lipc_set(prop, value, intval=False):
    """prop 形如 com.lab126.powerd.preventScreenSaver。

    坑：lipc-set-prop 带 -i/-s 时要求 **publisher 和属性名分开传**
    （`lipc-set-prop -i -- <publisher> <属性名> <值>`）。
    传成点号合并的单个参数会直接报 usage 错、rc=1、**静默失败** ——
    这里曾经因此让 wakeUp 和 preventScreenSaver 全都没生效。
    不带 -i 时它自己会"smartly try"，反而能容忍合并写法，所以别依赖那个。
    """
    pub, _, name = prop.rpartition(".")
    if not pub:
        pub, name = prop, ""
    cmd = ["lipc-set-prop"]
    if intval:
        cmd.append("-i")
    cmd += ["--", pub, name, str(value)]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except Exception:
        pass


def read_header(path):
    with open(path, "rb") as f:
        head = f.read(HEADER_SIZE)
        if len(head) < HEADER_SIZE:
            raise SystemExit("文件太小，不是 .ktvid")
        if head[:8] != MAGIC:
            raise SystemExit("magic 不对，不是 .ktvid（用 tools/make_ktvid.py 生成）")
        w, h, bpp, flags, _rsv, count, fps100, fbytes = struct.unpack_from("<HHBBHIII", head, 8)
        title = head[28:48].split(b"\x00")[0].decode("utf8", "replace")
    return dict(width=w, height=h, bpp=bpp, flags=flags, count=count,
                fps=fps100 / 100.0, frame_bytes=fbytes, title=title,
                compressed=bool(flags & FLAG_ZLIB))


def open_inputs():
    fds = []
    for p in INPUT_DEVS:
        try:
            fds.append(os.open(p, os.O_RDONLY | os.O_NONBLOCK))
        except OSError:
            pass
    return fds


BTN_TOUCH = 330
KEY_POWER = 116


def read_inputs(fds):
    """读掉输入事件，返回动作集合：'touch'（触摸屏）/'key'（翻页键等实体键）。
       电源键不算 —— 那个交给 powerd，别抢。"""
    acts = set()
    for fd in fds:
        try:
            data = os.read(fd, INPUT_EVENT_SIZE * 64)
        except (BlockingIOError, OSError):
            continue
        n = len(data)
        if not n:
            continue
        # 一次 read 可能把事件从中间切开，这里只判断"有没有动静"，够用
        for off in range(0, n - INPUT_EVENT_SIZE + 1, INPUT_EVENT_SIZE):
            etype, code, value = struct.unpack_from("<HHi", data, off + 8)
            if etype == 3:                      # EV_ABS：触摸坐标
                acts.add("touch")
            elif etype == 1 and value == 1:     # EV_KEY：按下
                if code == BTN_TOUCH:
                    acts.add("touch")
                elif code != KEY_POWER:
                    acts.add("key")
    return acts


def write_state(path, **kw):
    """写状态文件，供 KUAL/SSH 查在放什么、第几帧、暂停没有。
       用 temp + rename，避免读到写了一半的内容。"""
    if not path:
        return
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            for k, v in kw.items():
                f.write("%s=%s\n" % (k, v))
        os.replace(tmp, path)
    except OSError:
        pass


def read_ctl(path):
    """读控制命令（读到就删掉，一次性）。返回 'pause'/'resume'/'toggle'/'stop'/'restart' 或 None。"""
    if not path:
        return None
    try:
        with open(path, "r") as f:
            cmd = f.read().strip()
    except (IOError, OSError):
        return None
    if not cmd:
        return None
    try:
        os.unlink(path)
    except OSError:
        pass
    return cmd.split()[0].lower()


def make_banner(w, text, font_size=46):
    """渲染一块提示条（Pillow 不在就返回 None）。返回 (buf, bw, bh)。"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    bw = min(w, 560)
    bh = 100
    img = Image.new("L", (bw, bh), 0)                 # 黑底
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, bw - 1, bh - 1], outline=255, width=3)
    f = None
    for p in ("/usr/java/lib/fonts/STHeitiMedium.ttf",
              "/usr/java/lib/fonts/STHeiti-Regular.ttf"):
        if os.path.exists(p):
            try:
                f = ImageFont.truetype(p, font_size)
                break
            except Exception:
                pass
    if f is None:
        try:
            f = ImageFont.load_default()
        except Exception:
            return None
    try:
        tw, th = d.textsize(text, font=f)
    except Exception:
        tw, th = (bw, bh)
    d.text((max(0, (bw - tw) // 2), max(0, (bh - th) // 2)), text, font=f, fill=255)
    return img.tobytes(), bw, bh


def main():
    ap = argparse.ArgumentParser(description="Kindle 墨水屏 .ktvid 播放器")
    ap.add_argument("file")
    ap.add_argument("--fps", type=float, default=0, help="覆盖文件里的帧率")
    ap.add_argument("--loops", type=int, default=1, help="循环次数（0=无限）")
    ap.add_argument("--frames", type=int, default=0, help="最多播多少帧（0=全部）")
    ap.add_argument("--waveform", choices=WAVEFORMS, default="A2")
    ap.add_argument("--gc-every", type=int, default=60,
                    help="每 N 帧用 GC16 全刷一次去残影（0=不去残影）")
    ap.add_argument("--x", type=int, default=-1, help="左上角 X（默认居中）")
    ap.add_argument("--y", type=int, default=-1, help="左上角 Y（默认居中）")
    ap.add_argument("--no-restore", action="store_true", help="播完不切回主页")
    ap.add_argument("--no-sleep-guard", action="store_true", help="不设 preventScreenSaver")
    ap.add_argument("--frame-log", default="", help="每帧写「时间戳 帧号 总毫秒 解码毫秒 刷屏毫秒」到该文件")
    ap.add_argument("--ctl", default="", help="控制文件：写入 pause/resume/toggle/stop/restart 即可控制播放")
    ap.add_argument("--state", default="", help="状态文件：把 在放什么/第几帧/是否暂停 写到这里供 KUAL 查")
    ap.add_argument("--touch", choices=["toggle", "stop", "restart", "none"], default="toggle",
                    help="点触摸屏的动作（默认 暂停/继续）")
    ap.add_argument("--key", choices=["stop", "toggle", "restart", "none"], default="stop",
                    help="按翻页键等的动作（默认 停止播放；电源键不抢）")
    ap.add_argument("--no-pause-banner", action="store_true", help="暂停时不显示提示条")
    ap.add_argument("--flip", choices=["none", "v", "h"], default="none", help="翻转画面")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    from _fbink import ffi, lib as FBInk

    info = read_header(args.file)
    W, H, COUNT = info["width"], info["height"], info["count"]
    fps = args.fps or info["fps"] or 8.0
    fb_bytes = info["frame_bytes"]
    if fb_bytes != (W + 7) // 8 * H:
        raise SystemExit("头部里的 frame_bytes(%d) 与尺寸(%dx%d)不符" % (fb_bytes, W, H))
    if COUNT == 0:
        raise SystemExit("文件里没有帧")

    log = (lambda *a: None) if args.quiet else (lambda *a: print(*a, flush=True))

    fbfd = FBInk.fbink_open()
    if fbfd == -1:
        raise SystemExit("fbink_open 失败")
    cfg = ffi.new("FBInkConfig *")
    cfg.is_quiet = True
    if FBInk.fbink_init(fbfd, cfg) < 0:
        raise SystemExit("fbink_init 失败")

    st = ffi.new("FBInkState *")
    FBInk.fbink_get_state(cfg, st)
    SW, SH = st.screen_width, st.screen_height
    x = args.x if args.x >= 0 else max(0, (SW - W) // 2)
    y = args.y if args.y >= 0 else max(0, (SH - H) // 2)

    wfm = getattr(FBInk, "WFM_" + args.waveform, None)
    if wfm is None:
        raise SystemExit("这个 FBInk 构建里没有 WFM_" + args.waveform)

    log("FBInk %s" % ffi.string(FBInk.fbink_version()).decode("ascii"))
    log("屏幕 %dx%d   画面 %dx%d @ (%d,%d)   共 %d 帧 @ %.2f fps   波形 %s   %s"
        % (SW, SH, W, H, x, y, COUNT, fps, args.waveform,
           "zlib 压缩" if info["compressed"] else "未压缩"))

    # 先唤醒，播放期间再压住屏保（别让系统把画面盖掉）
    lipc_set("com.lab126.powerd.wakeUp", 1, intval=True)
    if not args.no_sleep_guard:
        lipc_set("com.lab126.powerd.preventScreenSaver", 1, intval=True)

    fds = open_inputs()
    row_bits = (W + 7) // 8 * 8

    def draw_at(buf, bw, bh, bx, by, use_flash=False, use_waveform=None):
        c = ffi.new("FBInkConfig *")
        c.is_quiet = True
        c.wfm_mode = use_waveform if use_waveform is not None else wfm
        if use_flash:
            c.is_flashing = True
        # 返回的是这次更新的 marker；0 = LAST_MARKER，可以直接拿去 wait
        return FBInk.fbink_print_raw_data(fbfd, buf, bw, bh, len(buf), bx, by, c)

    def draw(buf, use_flash=False, use_waveform=None):
        return draw_at(buf, W, H, x, y, use_flash, use_waveform)

    name = os.path.basename(args.file)

    def st(**kw):
        """把状态写给 KUAL 看（在放什么、第几帧、暂停没有）"""
        kw.setdefault("file", args.file)
        kw.setdefault("name", name)
        kw.setdefault("total", COUNT)
        kw.setdefault("fps", "%.2f" % fps)
        kw.setdefault("waveform", args.waveform)
        kw.setdefault("pid", os.getpid())
        write_state(args.state, **kw)

    frames_done = 0
    t0 = time.time()
    t_last = t0
    shown = 0
    paused = False
    pause_total = 0.0
    t_pause_start = 0.0
    last_buf = None
    stop_reason = "播放完毕"

    def set_paused(p, frame_no):
        nonlocal paused, t_pause_start, pause_total
        if p:
            if paused:
                return
            paused = True
            t_pause_start = time.time()
            if last_buf is not None and not args.no_pause_banner:
                b = make_banner(W, "暂停  %d/%d" % (frame_no, COUNT))
                if b:
                    bb, bw2, bh2 = b
                    draw_at(bb, bw2, bh2, x + max(0, (W - bw2) // 2),
                            y + max(0, (H - bh2) // 2), use_flash=True,
                            use_waveform=getattr(FBInk, "WFM_GC16", wfm))
                    FBInk.fbink_wait_for_complete(fbfd, 0)
            st(status="paused", frame=frame_no)
            log("[暂停] 第 %d/%d 帧（点屏幕继续，点翻页键停止）" % (frame_no, COUNT))
        else:
            if not paused:
                return
            pause_total += time.time() - t_pause_start
            paused = False
            # 用 GC16 重画当前帧，把暂停提示条彻底清干净（A2 会留残影）
            if last_buf is not None:
                draw(last_buf, use_flash=True, use_waveform=getattr(FBInk, "WFM_GC16", wfm))
                FBInk.fbink_wait_for_complete(fbfd, 0)
            st(status="playing", frame=frame_no)
            log("[继续] 第 %d/%d 帧" % (frame_no, COUNT))

    def handle(cmd, frame_no):
        """处理一个控制命令，返回 'cont' / 'stop' / 'restart'"""
        if cmd == "pause":
            set_paused(True, frame_no)
        elif cmd == "resume":
            set_paused(False, frame_no)
        elif cmd == "toggle":
            set_paused(not paused, frame_no)
        elif cmd == "stop":
            return "stop"
        elif cmd == "restart":
            return "restart"
        return "cont"

    st(status="playing", frame=0)
    flog = open(args.frame_log, "w") if args.frame_log else None
    try:
        with open(args.file, "rb") as f:
            f.seek(HEADER_SIZE)
            loops = 0
            while True:
                if args.loops and loops >= args.loops:
                    break
                loops += 1
                for i in range(COUNT):
                    # ---- 先响应控制文件与按键，暂停时就不会白解码 ----
                    r = "cont"
                    cmd = read_ctl(args.ctl) if args.ctl else None
                    if cmd:
                        r = handle(cmd, i + 1)
                    if r == "cont":
                        acts = read_inputs(fds)
                        if acts:
                            for kind, action in (("touch", args.touch), ("key", args.key)):
                                if kind in acts and action != "none":
                                    r = handle(action, i + 1)
                                    if r != "cont":
                                        break
                    if r == "stop":
                        stop_reason = "手动停止"
                        raise _Done()
                    if r == "restart":
                        loops = 0
                        f.seek(HEADER_SIZE)
                        shown = frames_done = 0
                        pause_total = 0.0
                        t0 = time.time()
                        st(status="playing", frame=0)
                        log("[重播] 从头开始")
                        break
                    if paused:
                        time.sleep(0.04)
                        continue

                    t_dec = time.time()
                    if info["compressed"]:
                        lb = f.read(4)
                        if len(lb) < 4:
                            break
                        (clen,) = struct.unpack("<I", lb)
                        raw = zlib.decompress(f.read(clen))
                    else:
                        raw = f.read(fb_bytes)
                    if len(raw) < fb_bytes:
                        break
                    bits = np.unpackbits(np.frombuffer(raw, dtype=np.uint8))
                    bits = bits.reshape(H, row_bits)[:, :W]
                    if args.flip == "v":
                        bits = bits[::-1, :]
                    elif args.flip == "h":
                        bits = bits[:, ::-1]
                    buf = (bits * 255).astype(np.uint8).tobytes()
                    last_buf = buf          # 暂停时要靠它重画/清提示条，别漏了这句
                    t_dec = (time.time() - t_dec) * 1000.0

                    # 每隔 gc_every 帧用 GC16 全刷一次，压掉 A2/DU 的残影
                    t_frame = time.time()
                    if args.gc_every and frames_done and frames_done % args.gc_every == 0:
                        draw(buf, use_flash=True, use_waveform=getattr(FBInk, "WFM_GC16", wfm))
                        FBInk.fbink_wait_for_complete(fbfd, 0)
                    else:
                        draw(buf)
                    FBInk.fbink_wait_for_complete(fbfd, 0)   # 等面板刷完，自我限速
                    t_draw = (time.time() - t_frame) * 1000.0
                    frames_done += 1
                    shown += 1
                    if flog:
                        flog.write("%.3f %d %.1f %.1f %.1f\n"
                                   % (time.time(), i, t_dec + t_draw, t_dec, t_draw))
                        flog.flush()

                    # 按帧率补齐剩余时间（暂停耗时不算进去）
                    target = t0 + pause_total + shown / fps
                    now = time.time()
                    if target > now:
                        time.sleep(target - now)

                    if not args.quiet and now - t_last >= 2.0:
                        el = now - t0 - pause_total
                        log("  %d 帧 / %.1f 秒 = %.2f fps" % (shown, el, shown / el if el else 0))
                        t_last = now

                    if frames_done % 8 == 0:
                        st(status="playing", frame=i + 1)

                    if args.frames and frames_done >= args.frames:
                        stop_reason = "达到帧数上限"
                        break
            f.seek(HEADER_SIZE)
    except _Done:
        pass
    finally:
        FBInk.fbink_close(fbfd)
        if flog:
            flog.close()
        for fd in fds:
            try:
                os.close(fd)
            except OSError:
                pass
        if not args.no_sleep_guard:
            lipc_set("com.lab126.powerd.preventScreenSaver", 0, intval=True)
        # 状态文件删掉 = 没在播（KUAL 靠进程 + 这个文件判断状态）
        if args.state:
            try:
                os.unlink(args.state)
            except OSError:
                pass

    el = time.time() - t0 - pause_total
    log("%s：播了 %d 帧，用时 %.1f 秒，平均 %.2f fps"
        % (stop_reason, shown, el, shown / el if el else 0))

    if not args.no_restore:
        # 让 X 重绘一遍，否则屏幕上留着一帧和系统状态不一致的画面
        lipc_set("com.lab126.appmgrd.start", "app://com.lab126.booklet.home")
    return 0


if __name__ == "__main__":
    sys.exit(main())
