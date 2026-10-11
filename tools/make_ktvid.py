#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把视频 / GIF / 图片序列转成 Kindle 墨水屏播放器能吃的紧凑帧序列（.ktvid）。

为什么不用 mp4/gif 直接播：设备上没有 ffmpeg、没有 opencv，Python 里解 mp4 不现实；
GIF 能解但体积大、解码慢。所以这里在电脑上先把帧处理成「1bit 黑白、按行打包」，
设备端只要 unpackbits + 贴到 framebuffer，几乎零解码开销。

用法：
    # 视频（需要本机有 ffmpeg）
    python tools/make_ktvid.py input.mp4 -o badapple.ktvid --fps 8 --width 640 --height 480
    # 只取前 20 秒试水
    python tools/make_ktvid.py input.mp4 -o test.ktvid --start 0 --duration 20
    # GIF（只用 Pillow，不需要 ffmpeg）
    python tools/make_ktvid.py anim.gif -o anim.ktvid --fps 10
    # 图片序列
    python tools/make_ktvid.py frames_dir -o out.ktvid --fps 12

.ktvid 格式（小端）：
    0   8B   magic  "KTVID1\\0\\0"
    8   2B   width
    10  2B   height
    12  1B   bpp（固定 1）
    13  1B   flags（bit0 = 位序 MSB-first；bit1 = 每帧前带 uint32 压缩长度、内容为 zlib）
    14  2B   reserved
    16  4B   frame_count
    20  4B   fps x 100
    24  4B   frame_bytes = ceil(width/8) * height（解压后的原始大小）
    28  20B  title（UTF-8，NUL 补齐）
    48  ...  帧数据
             未压缩：每帧 frame_bytes 字节
             压缩：  每帧 [uint32 压缩后长度][zlib 数据]

    1bit 帧冗余度很高，zlib 通常能压到 1/5 ~ 1/15，所以默认开压缩。
"""
import argparse
import os
import shutil
import struct
import subprocess
import sys
import zlib

import numpy as np
from PIL import Image

HEADER_SIZE = 48
MAGIC = b"KTVID1\x00\x00"
FLAG_MSB = 0x01
FLAG_ZLIB = 0x02


def die(msg):
    print("错误：" + msg, file=sys.stderr)
    sys.exit(1)


def fit_size(src_w, src_h, box_w, box_h):
    """等比缩放到 box 内，返回 (w, h)"""
    if src_w <= 0 or src_h <= 0:
        return box_w, box_h
    s = min(box_w / src_w, box_h / src_h)
    return max(1, int(round(src_w * s))), max(1, int(round(src_h * s)))


def to_1bit(img, dither):
    """转成 1bit 黑白；返回 (h, w) 的 0/1 uint8 数组"""
    if img.mode != "L":
        img = img.convert("L")
    if dither == "none":
        # 纯阈值：文字/剪影更锐利，但灰阶会断层
        arr = np.asarray(img, dtype=np.uint8)
        bits = (arr < 128).astype(np.uint8)
    else:
        # Floyd–Steinberg 抖动：灰阶观感更好
        one = img.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
        bits = (np.asarray(one, dtype=np.uint8) > 0).astype(np.uint8)
    return bits


def pad_to(bits, w, h):
    """把 (h,w) 的 0/1 数组放进更大的白底画布并居中"""
    out = np.ones((h, w), dtype=np.uint8)
    bh, bw = bits.shape
    y0 = (h - bh) // 2
    x0 = (w - bw) // 2
    out[y0:y0 + bh, x0:x0 + bw] = bits
    return out


def find_label_font(size):
    for c in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              r"C:\Windows\Fonts\arialbd.ttf",
              r"C:\Windows\Fonts\ARIALBD.TTF",
              r"C:\Windows\Fonts\seguisb.ttf"):
        if os.path.exists(c):
            try:
                from PIL import ImageFont
                return ImageFont.truetype(c, size)
            except Exception:
                pass
    return None


def burn_label(bits, text, font_size=44):
    """在左上角烧一个白底黑字的标签（只用于对比，正常视频不用）。
       注意本工程里 bits 的约定是 1=白、0=黑（和 PIL 的 1bit 一致）。"""
    bh, bw = bits.shape
    f = find_label_font(font_size)
    if f is None:
        return bits
    from PIL import ImageDraw
    tmp = Image.new("L", (bw, 90), 255)          # 白底
    ImageDraw.Draw(tmp).text((16, 14), text, font=f, fill=0)   # 黑字
    lab = (np.asarray(tmp, dtype=np.uint8) >= 128).astype(np.uint8)   # 1=白 0=字
    out = bits.copy()
    h, w = lab.shape
    out[0:h, 0:w] = lab                            # 整块贴上去，白底盖住原画面
    return out


def pack_frame(bits, width):
    """(h,w) 0/1 -> 每行 MSB-first、按字节对齐的 bytes（设备端 unpackbits 后 reshape 即可）"""
    per_row = (width + 7) // 8 * 8
    h, w = bits.shape
    if w != per_row:
        padded = np.zeros((h, per_row), dtype=np.uint8)
        padded[:, :w] = bits
        bits = padded
    return np.packbits(bits, axis=1).tobytes()


# --------------------------------------------------------------------------- 帧来源

def frames_from_video(path, fps, width, height, start, duration):
    """用 ffmpeg 解码成 gray rawvideo，逐帧 yield (H,W) 的 PIL 图"""
    if not shutil.which("ffmpeg"):
        die("PATH 里没有 ffmpeg，无法读视频。装一个，或者改用 GIF/图片序列输入。")
    vf = ("fps=%g,scale=%d:%d:force_original_aspect_ratio=decrease,"
          "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=white" % (fps, width, height, width, height))
    cmd = ["ffmpeg", "-v", "error", "-nostdin"]
    if start:
        cmd += ["-ss", str(start)]
    cmd += ["-i", path]
    if duration:
        cmd += ["-t", str(duration)]
    cmd += ["-vf", vf, "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=width * height)
    fsz = width * height
    count = 0
    try:
        while True:
            buf = proc.stdout.read(fsz)
            if not buf or len(buf) < fsz:
                break
            count += 1
            yield Image.frombytes("L", (width, height), buf)
    finally:
        proc.stdout.close()
        err = proc.stderr.read().decode("utf8", "replace").strip()
        proc.stderr.close()
        proc.wait()
        if err:
            print("ffmpeg: " + err[:400], file=sys.stderr)
        if count == 0:
            die("ffmpeg 没吐出一帧，检查输入文件和参数")


def frames_from_image_file(path, fps, width, height):
    """GIF / APNG 等多帧图片，用 Pillow 逐帧解"""
    im = Image.open(path)
    n = getattr(im, "n_frames", 1)
    for i in range(n):
        im.seek(i)
        yield im.convert("L")


def frames_from_dir(path, fps, width, height):
    exts = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")
    names = sorted(f for f in os.listdir(path) if f.lower().endswith(exts))
    if not names:
        die("目录里没有图片：" + path)
    for f in names:
        yield Image.open(os.path.join(path, f)).convert("L")


# --------------------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="视频/GIF/图片序列 -> .ktvid（Kindle 墨水屏帧序列）")
    ap.add_argument("input", help="视频文件 / GIF / 图片目录")
    ap.add_argument("-o", "--output", required=True, help="输出的 .ktvid")
    ap.add_argument("--fps", type=float, default=8.0, help="目标帧率（默认 8）")
    ap.add_argument("--width", type=int, default=640, help="画面宽（默认 640）")
    ap.add_argument("--height", type=int, default=480, help="画面高（默认 480）")
    ap.add_argument("--start", type=float, default=0, help="从第几秒开始（仅视频）")
    ap.add_argument("--duration", type=float, default=0, help="取多少秒（仅视频，0=全部）")
    ap.add_argument("--title", default="", help="标题（最多 20 字节，写进头部）")
    ap.add_argument("--dither", choices=["fs", "none"], default="fs",
                    help="fs=Floyd-Steinberg 抖动（默认），none=纯阈值（剪影更锐利）")
    ap.add_argument("--fit", action="store_true",
                    help="不拉满画布，等比缩小后居中（默认就是等比缩放+白底居中）")
    ap.add_argument("--no-compress", action="store_true",
                    help="不做 zlib 压缩（默认压缩，1bit 帧通常能小 5~15 倍）")
    ap.add_argument("--label", default="",
                    help="在每帧左上角烧进一行标签（用于 A/B 对比，一眼看出在放哪一段）")
    args = ap.parse_args()

    W, H = args.width, args.height
    if W % 8:
        W = (W + 7) // 8 * 8
        print("提示：宽度按 8 对齐到 %d" % W)
    frame_bytes = (W + 7) // 8 * H

    src = args.input
    if os.path.isdir(src):
        gen = frames_from_dir(src, args.fps, W, H)
    else:
        ext = os.path.splitext(src)[1].lower()
        if ext in (".gif", ".png", ".webp", ".apng") and ext != ".png":
            gen = frames_from_image_file(src, args.fps, W, H)
        elif ext == ".gif":
            gen = frames_from_image_file(src, args.fps, W, H)
        else:
            gen = frames_from_video(src, args.fps, W, H, args.start, args.duration)

    title = args.title or os.path.splitext(os.path.basename(src))[0]
    tb = title.encode("utf8")[:20]

    compress = not args.no_compress
    flags = FLAG_MSB | (FLAG_ZLIB if compress else 0)

    tmp = args.output + ".part"
    n = 0
    raw_total = 0
    with open(tmp, "wb") as out:
        out.write(b"\x00" * HEADER_SIZE)          # 先占位，最后回填
        for img in gen:
            # 等比缩放到画布内，再白底居中
            sw, sh = fit_size(img.width, img.height, W, H)
            if (sw, sh) != img.size:
                img = img.resize((sw, sh), Image.LANCZOS)
            bits = to_1bit(img, args.dither)
            bits = pad_to(bits, W, H)
            if args.label:
                bits = burn_label(bits, args.label)
            packed = pack_frame(bits, W)
            raw_total += len(packed)
            if compress:
                comp = zlib.compress(packed, 6)
                out.write(struct.pack("<I", len(comp)))
                out.write(comp)
            else:
                out.write(packed)
            n += 1
            if n % 200 == 0:
                print("  ... %d 帧" % n)
        # 回填头部
        out.seek(0)
        out.write(MAGIC)
        out.write(struct.pack("<HHBBHIII", W, H, 1, flags, 0, n, int(round(args.fps * 100)), frame_bytes))
        out.write(tb.ljust(20, b"\x00"))
        assert out.tell() == HEADER_SIZE

    os.replace(tmp, args.output)
    size = os.path.getsize(args.output)
    print()
    print("完成：%s" % args.output)
    print("  画面      %dx%d  1bit" % (W, H))
    print("  帧数      %d  @ %.2f fps  -> 时长约 %.1f 秒" % (n, args.fps, n / args.fps if args.fps else 0))
    print("  每帧      %d 字节（解压后）" % frame_bytes)
    print("  压缩      %s" % ("zlib" if compress else "无"))
    print("  文件大小  %.1f MB%s" % (size / 1048576.0,
          ("（原始 %.1f MB，压缩到 %.0f%%）" % (raw_total / 1048576.0, 100.0 * size / raw_total)) if raw_total else ""))
    if n == 0:
        die("一帧都没有，检查输入")


if __name__ == "__main__":
    main()
