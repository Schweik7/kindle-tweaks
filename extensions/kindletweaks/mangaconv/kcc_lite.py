# -*- coding: utf-8 -*-
#
# kcc_lite：Kindle Comic Converter (KCC) 图像处理部分的精简移植，只保留输出 Kindle PDF 用到的功能。
# 来源：https://github.com/ciromattia/kcc  kindlecomicconverter/image.py、page_number_crop_alg.py、common_crop.py
#
# Copyright (C) 2010  Alex Yatskov
# Copyright (C) 2011  Stanislav (proDOOMman) Kosolapov <prodoomman@gmail.com>
# Copyright (c) 2016  Alberto Planas <aplanas@gmail.com>
# Copyright (c) 2012-2014 Ciro Mattia Gonano <ciromattia@gmail.com>
# Copyright (c) 2013-2019 Pawel Jastrzebski <pawelj@iosphe.re>
# Copyright (c) 2026 kindle-tweaks contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# 与 KCC 的差别：
#   - 去掉 numpy（Kindle 是 armel 软浮点，没有可用的 numpy 轮子），页码检测改成纯 Python + bytes 运算；
#   - 兼容 Pillow 9.0（没有 Image.Resampling）；
#   - 只做灰度输出；不做彩色检测、量化、彩虹纹消除、面板间裁切、webtoon、Kindle Scribe 等。
import re

from PIL import Image, ImageChops, ImageFile, ImageFilter, ImageOps

ImageFile.LOAD_TRUNCATED_IMAGES = True
Image.MAX_IMAGE_PIXELS = int(2048 * 2048 * 2048 // 4 // 3)
_R = getattr(Image, "Resampling", Image)
LANCZOS, BICUBIC = _R.LANCZOS, _R.BICUBIC

AUTO_CROP_THRESHOLD = 0.015

# 页码尺寸的假设（相对图片尺寸），与 KCC 相同
MAX_SHAPE = (0.015 * 3, 0.02)
MIN_SHAPE = (0.003, 0.006)
WINDOW_H = MAX_SHAPE[1] * 1.25
MAX_DIST = (0.01, 0.002)


class Options:
    """对应 KCC 的命令行选项（默认值 = KCC 默认 + Kindle Oasis 2/3 profile）。"""

    def __init__(self, **kw):
        self.size = (1264, 1680)      # 屏幕分辨率
        self.cropping = 2             # 0 不裁，1 裁白边，2 裁白边 + 页码
        self.croppingp = 1.0          # 裁切力度 0~3
        self.croppingm = 0.0          # 裁后面积至少占原图比例，否则不裁
        self.splitter = 0             # 跨页：0 拆成两页（太宽则旋转），1 只旋转，2 拆 + 旋转都要
        self.righttoleft = True       # 拆跨页时先放右半边（日漫）
        self.rotateright = False
        self.upscale = True           # 小图也放大到屏幕尺寸（KCC 默认不放大；PDF 里放大后阅读器就是 1:1）
        self.gamma = 1.0
        self.autocontrast = True
        for k, v in kw.items():
            if not hasattr(self, k):
                raise TypeError("未知选项 " + k)
            setattr(self, k, v)


def threshold_from_power(power):
    return 240 - (power * 64)


def fill_check(image):
    """判断页面背景是白还是黑（KCC fillCheck）。"""
    bw = image.convert("L").point(lambda x: 0 if x < 128 else 255, "1")
    box_a = bw.getbbox()
    box_b = ImageChops.invert(bw).getbbox()
    if box_a is None or box_b is None:
        diff = 0
    else:
        surf_b = (box_a[2] - box_a[0]) * (box_a[3] - box_a[1])
        surf_w = (box_b[2] - box_b[0]) * (box_b[3] - box_b[1])
        diff = ((max(surf_b, surf_w) - min(surf_b, surf_w)) / min(surf_b, surf_w)) * 100
    if diff > 0.5:
        if surf_w < surf_b:
            return "white"
        if surf_w > surf_b:
            return "black"

    def hist_sign(im):
        h = im.histogram()
        if h[0] == 0:
            return -1
        if h[255] == 0:
            return 1
        return 0

    fill = 0
    w, h = bw.size
    y = 0
    while y < h:
        if y + 5 > h:
            y = h - 5
        fill += hist_sign(bw.crop((0, y, w, y + 5)))
        y += 5
    x = 0
    while x < w:
        if x + 5 > w:
            x = w - 5
        fill += hist_sign(bw.crop((x, 0, x + 5, h)))
        x += 5
    return "black" if fill > 0 else "white"


def _prepare_bw(img, power, background):
    if img.mode != "L":
        img = ImageOps.grayscale(img)
    if background != "white":
        img = ImageOps.invert(img)
    img = ImageOps.autocontrast(img, 1).filter(ImageFilter.BoxBlur(1))
    threshold = threshold_from_power(power)
    bw = img.point(lambda p: 255 if p <= threshold else 0)
    ignore_pixels_near_edge(bw)
    return img, bw, threshold


def ignore_pixels_near_edge(bw):
    w, h = bw.size
    if int(0.02 * h) == int(0.025 * h) or int(0.02 * w) == int(0.025 * w):
        return
    edges = [(0, 0, w, int(0.02 * h)), (0, int(0.98 * h), w, h),
             (0, 0, int(0.02 * w), h), (int(0.98 * w), 0, w, h)]
    inners = [(int(0.02 * w), int(0.02 * h), int(0.98 * w), int(0.025 * h)),
              (int(0.02 * w), int(0.975 * h), int(0.98 * w), int(0.98 * h)),
              (int(0.02 * w), int(0.02 * h), int(0.025 * w), int(0.98 * h)),
              (int(0.975 * w), int(0.02 * h), int(0.98 * w), int(0.98 * h))]
    for edge_box, inner_box in zip(edges, inners):
        inner = bw.crop(inner_box)
        imperfections = inner.histogram()[255] / (inner.height * inner.width)
        if 0 < imperfections < .001:
            bw.paste(0, inner_box)
        if imperfections < .001 and bw.crop(edge_box).histogram()[-1] != 0:
            bw.paste(0, edge_box)


def bbox_crop_margin(img, power=1, background="white"):
    return _prepare_bw(img, power, background)[1].getbbox()


def _row_groups(row, lut, max_dist):
    """一行里所有「暗像素」按间距 <= max_dist 分组，返回 [(x0, x1)]。"""
    groups = []
    for m in re.finditer(b"\x01+", row.translate(lut)):
        s, e = m.start(), m.end() - 1
        if groups and s - groups[-1][1] <= max_dist:
            groups[-1][1] = e
        else:
            groups.append([s, e])
    return groups


def _merge_boxes(boxes, dx, dy):
    """把距离不超过 (dx, dy) 的框合并（框 = [x0, x1, y0, y1]），直到不再变化。"""
    boxes = [list(b) for b in boxes]
    changed = True
    while changed:
        changed = False
        out = []
        for b in boxes:
            for o in out:
                if not (b[0] - dx > o[1] or b[1] + dx < o[0] or b[2] - dy > o[3] or b[3] + dy < o[2]):
                    o[0], o[1] = min(o[0], b[0]), max(o[1], b[1])
                    o[2], o[3] = min(o[2], b[2]), max(o[3], b[3])
                    changed = True
                    break
            else:
                out.append(b)
        boxes = out
    return boxes


def bbox_crop_margin_page_number(img, power=1, background="white"):
    """在裁白边的基础上，再把底部单独的页码裁掉（KCC get_bbox_crop_margin_page_number）。"""
    gray, bw, threshold = _prepare_bw(img, power, background)
    bb = bw.getbbox()
    if not bb:
        return None
    left, top, right, bot = bb
    W, H = gray.size
    window_h = int(H * WINDOW_H)
    part = gray.crop((left, bot - window_h, right, bot))
    pw, ph = part.size
    data = part.tobytes()
    lut = bytes(1 if v <= threshold else 0 for v in range(256))
    dx, dy = W * MAX_DIST[0], H * MAX_DIST[1]

    # 逐行分组后按行累积合并；只和「还没结束」的框比较，比 KCC 的两两合并快得多
    done, active = [], []
    for i in range(ph):
        still = []
        for b in active:
            (still if b[3] + dy >= i else done).append(b)
        active = still
        for x0, x1 in _row_groups(data[i * pw:(i + 1) * pw], lut, dx):
            for b in active:
                if not (x0 - dx > b[1] or x1 + dx < b[0]):
                    b[0], b[1], b[3] = min(b[0], x0), max(b[1], x1), i
                    break
            else:
                active.append([x0, x1, i, i])
    # 一行里的一组可能同时连到两个框，最后再整体合并一次（此时框已经很少）
    boxes = _merge_boxes(done + active, dx, dy)

    boxes = [b for b in boxes if b[1] - b[0] >= W * MIN_SHAPE[0] and b[3] - b[2] >= H * MIN_SHAPE[1]]
    lowest = [b for b in boxes if b[3] == window_h - 1]
    min_y = min(b[2] for b in lowest) if lowest else 0
    same_range = [b for b in boxes if b[3] >= min_y]
    max_shape = (W * MAX_SHAPE[0], max(H * MAX_SHAPE[1], 3))
    crop = (0, 0, W, H)
    if (len(same_range) == 1 and same_range[0][1] - same_range[0][0] <= max_shape[0]
            and same_range[0][3] - same_range[0][2] <= max_shape[1]):
        crop = (0, 0, W, bot - (window_h - same_range[0][2] + 1))
    return bw.crop(crop).getbbox()


def _maybe_crop(image, bbox, minimum):
    w, h = image.size
    left, upper, right, lower = bbox
    # 最多裁掉每边 10%
    box = (min(0.1 * w, left), min(0.1 * h, upper), max(0.9 * w, right), max(0.9 * h, lower))
    if (box[2] - box[0]) * (box[3] - box[1]) / (w * h) >= minimum:
        return image.crop(tuple(int(v) for v in box))
    return image


def split_pages(image, opt):
    """跨页处理（KCC splitCheck），返回 [(模式, 图)]。"""
    width, height = image.size
    dw, dh = opt.size
    out = []
    if (width > height) != (dw > dh) and width / height > 1.16:
        bisect = 1.8
        if opt.splitter != 1 and width / height < bisect:
            if width > height:
                lbox, rbox = (0, 0, width // 2, height), (width // 2, 0, width, height)
            else:
                lbox, rbox = (0, 0, width, height // 2), (0, height // 2, width, height)
            first, second = (rbox, lbox) if opt.righttoleft else (lbox, rbox)
            out += [("S1", image.crop(first)), ("S2", image.crop(second))]
        if opt.splitter > 0 or (opt.splitter == 0 and width / height >= bisect):
            out.append(("R", image.rotate(-90 if opt.rotateright else 90, BICUBIC, True)))
        return out
    return [("N", image)]


def autocontrast(image, opt):
    if not opt.autocontrast:
        return image
    lo, hi = image.convert("L").getextrema()
    if hi - lo < (255 - 32 * 3):    # 本来就很低对比度的页，多半是刻意的
        return image
    return ImageOps.autocontrast(image, preserve_tone=True)


def resize(image, opt, fill):
    size = opt.size
    if image.size[0] <= size[0] and image.size[1] <= size[1]:
        if not opt.upscale:
            return image
        method = BICUBIC
    else:
        method = LANCZOS
    ratio_dev = size[1] / size[0]
    ratio_img = image.size[1] / image.size[0]
    if abs(ratio_img - ratio_dev) < AUTO_CROP_THRESHOLD:
        return ImageOps.fit(image, size, method=method)
    # PDF：补边到正好一屏，阅读器就会 1:1 显示
    return ImageOps.pad(image, size, method=method, color=fill)


def process_page(image, opt, is_cover=False):
    """一张源图 -> [灰度页面图]（跨页可能拆成多张）。"""
    image = image.convert("L") if image.mode not in ("L", "RGB") else image
    background = fill_check(image)
    if not is_cover:
        if opt.cropping == 2:
            bbox = bbox_crop_margin_page_number(image, opt.croppingp, background)
        elif opt.cropping == 1:
            bbox = bbox_crop_margin(image, opt.croppingp, background)
        else:
            bbox = None
        if bbox:
            image = _maybe_crop(image, bbox, opt.croppingm)
    pages = []
    for _, img in split_pages(image, opt):
        img = img.convert("L")
        if opt.gamma != 1.0:
            g = opt.gamma
            img = img.point(lambda a: int(255 * (a / 255.) ** g))
        img = autocontrast(img, opt)
        img = resize(img, opt, 255 if background == "white" else 0)
        pages.append(img)
    return pages
