# -*- coding: utf-8 -*-
# Copyright (c) 2026 kindle-tweaks contributors. GPL-3.0-or-later.
"""
漫画 epub -> Kindle 全屏 PDF（在 Kindle 上跑，也能在电脑上跑，只依赖 Pillow）。

    mangaconv.py convert <in.epub> [out.pdf]   转换一本（不管大小、不管充电）
    mangaconv.py scan                          列出待转换队列
    mangaconv.py run [--force]                 处理队列；不带 --force 时只在充电时干活，拔电就停
    mangaconv.py status                        一行状态（给 KUAL 菜单用）

队列 = documents 下 >= min_size_mb 的 .epub，且看起来是漫画（几乎每个 html 一张图、没什么文字），
且旁边还没有同名 .pdf。转好后原 epub 按 config.json 的 after 处理（默认移到 archive_dir）。
"""
import io
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import time
import zipfile
from urllib.parse import unquote

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kcc_lite  # noqa: E402

CONF = os.path.join(HERE, "config.json")
STATE = os.path.join(HERE, "state.json")
STATUS = os.path.join(HERE, "status.txt")
DEFAULTS = {
    "documents": "/mnt/us/documents",
    "min_size_mb": 50,
    "after": "move",                       # move：移到 archive_dir；keep：留在原处；delete：删除
    "archive_dir": "/mnt/us/epub_converted",
    "tmp_dir": "/mnt/us/.kindletweaks_tmp",
    "screen": [1264, 1680],
    "dpi": 300,
    "jpeg_quality": 80,
    "cropping": 2,
    "cropping_power": 1.0,
    "splitter": 0,
    "upscale": True,
}
ON_KINDLE = os.path.exists("/usr/bin/lipc-get-prop")


def load_conf():
    c = dict(DEFAULTS)
    try:
        with open(CONF, encoding="utf-8") as f:
            c.update(json.load(f))
    except (OSError, ValueError):
        pass
    return c


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(st):
    tmp = STATE + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def log(msg):
    print(time.strftime("%m-%d %H:%M:%S"), msg, flush=True)


def set_status(text):
    try:
        with open(STATUS, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass


# ---------------------------------------------------------------- epub

def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def _attr(tag, name):
    m = re.search(r'\s%s\s*=\s*"([^"]*)"' % name, tag) or re.search(r"\s%s\s*=\s*'([^']*)'" % name, tag)
    return m.group(1) if m else None


class Epub:
    IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")

    def __init__(self, path):
        self.z = zipfile.ZipFile(path)
        names = set(self.z.namelist())
        cont = self.z.read("META-INF/container.xml").decode("utf-8", "replace")
        self.opf = unquote(re.search(r'full-path="([^"]+)"', cont).group(1))
        opf = self.z.read(self.opf).decode("utf-8", "replace")
        base = posixpath.dirname(self.opf)

        def meta(tag):
            m = re.search(r"<dc:%s[^>]*>([^<]*)</dc:%s>" % (tag, tag), opf)
            return m.group(1).strip() if m else None
        self.title, self.author = meta("title"), meta("creator")

        manifest = {}
        for tag in re.findall(r"<item\s[^>]*>", opf):
            i, h = _attr(tag, "id"), _attr(tag, "href")
            if i and h:
                manifest[i] = posixpath.normpath(posixpath.join(base, unquote(h)))
        spine_tag = re.search(r"<spine[^>]*>", opf)
        self.rtl = bool(spine_tag and 'page-progression-direction="rtl"' in spine_tag.group(0))
        spine = [manifest.get(_attr(t, "idref")) for t in re.findall(r"<itemref\s[^>]*>", opf)]
        spine = [s for s in spine if s in names]

        # 按阅读顺序取每个 html 里的图；顺便统计正文文字量，判断是不是漫画
        self.images, self.docs, self.docs_with_img, text_chars = [], len(spine), 0, 0
        seen = set()
        for doc in spine:
            if doc.lower().endswith(self.IMG_EXT):
                srcs = [doc]
            else:
                html = self.z.read(doc).decode("utf-8", "replace")
                body = html[html.find("<body"):] if "<body" in html else html
                srcs = []
                for tag in re.findall(r"<(?:img|image)\s[^>]*>", body, re.I):
                    s = _attr(tag, "src") or _attr(tag, "xlink:href") or _attr(tag, "href")
                    if s:
                        srcs.append(posixpath.normpath(posixpath.join(posixpath.dirname(doc), unquote(s.split("#")[0]))))
                text_chars += len(re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", body)))
            srcs = [s for s in srcs if s in names]
            if srcs:
                self.docs_with_img += 1
            for s in srcs:
                if s not in seen:
                    seen.add(s)
                    self.images.append(s)
        self.text_per_doc = text_chars / max(1, self.docs)
        if not self.images:     # spine 里找不到图：退而按文件名排序取所有图片
            self.images = sorted((n for n in names if n.lower().endswith(self.IMG_EXT)), key=natural_key)

    def is_manga(self):
        """几乎每个 html 都只有一张图、几乎没有正文。"""
        if len(self.images) < 10:
            return False, "图片少于 10 张"
        if self.docs and self.docs_with_img / self.docs < 0.9:
            return False, "只有 %d/%d 个页面有图" % (self.docs_with_img, self.docs)
        if self.text_per_doc > 100:
            return False, "每页平均 %d 字正文，像文字书" % self.text_per_doc
        return True, ""

    def read(self, name):
        return self.z.read(name)


# ---------------------------------------------------------------- PDF

def pdf_str(s):
    return "<FEFF" + s.encode("utf-16-be").hex().upper() + ">"


class PdfWriter:
    """边转换边写：每页一张 JPEG（DCTDecode 原样嵌入），页面尺寸 = 图片尺寸 / dpi。"""

    def __init__(self, path, title=None, author=None, dpi=300):
        self.f = open(path, "wb")
        self.dpi = dpi
        self.offsets = {}
        self.pages = []
        self.f.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        self._obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
        info = "<< /Producer (kindle-tweaks mangaconv)"
        if title:
            info += " /Title " + pdf_str(title)
        if author:
            info += " /Author " + pdf_str(author)
        self._obj(3, (info + " >>").encode())
        self.next_id = 4

    def _obj(self, n, body):
        self.offsets[n] = self.f.tell()
        self.f.write(b"%d 0 obj\n" % n + body + b"\nendobj\n")

    def add_jpeg(self, data, w, h):
        p, c, im = self.next_id, self.next_id + 1, self.next_id + 2
        self.next_id += 3
        pw, ph = w * 72.0 / self.dpi, h * 72.0 / self.dpi
        self._obj(p, ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] "
                      "/Resources << /XObject << /I %d 0 R >> >> /Contents %d 0 R >>" % (pw, ph, im, c)).encode())
        stream = ("q %.2f 0 0 %.2f 0 0 cm /I Do Q" % (pw, ph)).encode()
        self._obj(c, b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        self._obj(im, ("<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceGray "
                       "/BitsPerComponent 8 /Filter /DCTDecode /Length %d >>\nstream\n" % (w, h, len(data))).encode()
                  + data + b"\nendstream")
        self.pages.append(p)

    def close(self):
        kids = " ".join("%d 0 R" % p for p in self.pages)
        self._obj(2, ("<< /Type /Pages /Count %d /Kids [%s] >>" % (len(self.pages), kids)).encode())
        xref = self.f.tell()
        total = self.next_id
        self.f.write(b"xref\n0 %d\n0000000000 65535 f \n" % total)
        for n in range(1, total):
            self.f.write(b"%010d 00000 n \n" % self.offsets[n])
        self.f.write(b"trailer\n<< /Size %d /Root 1 0 R /Info 3 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (total, xref))
        self.f.close()


# ---------------------------------------------------------------- 转换

class Aborted(Exception):
    pass


def convert(src, dst, conf, keep_going=None, progress=None):
    """epub -> pdf。keep_going() 返回 False 时中止（删掉半成品）。返回页数。"""
    book = Epub(src)
    opt = kcc_lite.Options(size=tuple(conf["screen"]), cropping=conf["cropping"],
                           croppingp=conf["cropping_power"], splitter=conf["splitter"],
                           righttoleft=book.rtl, upscale=conf["upscale"])
    title = book.title or os.path.splitext(os.path.basename(src))[0]
    tmp = dst + ".part"
    pdf = PdfWriter(tmp, title, book.author, conf["dpi"])
    n = len(book.images)
    try:
        for i, name in enumerate(book.images):
            if keep_going and not keep_going():
                raise Aborted()
            with Image.open(io.BytesIO(book.read(name))) as im:
                im.load()
                for page in kcc_lite.process_page(im, opt, is_cover=(i == 0)):
                    buf = io.BytesIO()
                    page.save(buf, "JPEG", quality=conf["jpeg_quality"], optimize=True)
                    pdf.add_jpeg(buf.getvalue(), *page.size)
            if progress:
                progress(i + 1, n)
        pdf.close()
    except BaseException:
        pdf.f.close()
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    os.replace(tmp, dst)
    return len(pdf.pages)


# ---------------------------------------------------------------- 队列（Kindle 上）

def lipc_get(prop):
    try:
        return subprocess.run(["lipc-get-prop", "com.lab126.powerd", prop],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def charging():
    return lipc_get("isCharging") == "1"


class SuspendBlocker:
    """转换期间不让 Kindle 休眠：屏保状态下 powerd 准备休眠前会发 readyToSuspend 事件，
    收到就回 deferSuspend（只在这个状态下有效，平时设置会报 InvalidState）。屏幕照常显示屏保。"""

    def __init__(self):
        self.p = None
        if not ON_KINDLE:
            return
        import threading
        try:
            self.p = subprocess.Popen(["lipc-wait-event", "-m", "com.lab126.powerd", "readyToSuspend"],
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        except OSError:
            return
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        for _ in self.p.stdout:
            subprocess.run(["lipc-set-prop", "-i", "com.lab126.powerd", "deferSuspend", "300"],
                           capture_output=True, timeout=10)
            log("推迟休眠")

    def close(self):
        if self.p:
            self.p.kill()


def target_pdf(src):
    return os.path.splitext(src)[0] + ".pdf"


def scan(conf, st):
    """返回待转换的 epub 列表（按路径排序）。"""
    out = []
    limit = conf["min_size_mb"] * 1024 * 1024
    for root, dirs, files in os.walk(conf["documents"]):
        dirs[:] = [d for d in dirs if not d.endswith(".sdr")]
        for f in files:
            if not f.lower().endswith(".epub"):
                continue
            p = os.path.join(root, f)
            try:
                s = os.stat(p)
            except OSError:
                continue
            if s.st_size < limit or os.path.exists(target_pdf(p)):
                continue
            rec = st.get(p)
            # 跳过 / 失败过的，文件没变就不再试
            if rec and rec.get("size") == s.st_size and rec.get("mtime") == int(s.st_mtime) and rec["status"] in ("skipped", "failed"):
                continue
            out.append(p)
    return sorted(out, key=natural_key)


def after_convert(src, conf):
    act = conf["after"]
    if act == "delete":
        os.remove(src)
        return "已删除原 epub"
    if act == "move":
        rel = os.path.relpath(src, conf["documents"])
        dst = os.path.join(conf["archive_dir"], rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        return "原 epub 移到 " + dst
    return "原 epub 保留"


def run(force=False):
    """返回码：0 队列已处理完；2 拔电中止；3 没在充电；4 已有一个在跑（后台任务据此决定下次是否重试）。"""
    import fcntl
    conf = load_conf()
    os.makedirs(conf["tmp_dir"], exist_ok=True)
    lock = open(os.path.join(conf["tmp_dir"], "lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 4
    return _run(conf, force)


def _run(conf, force):
    st = load_state()
    queue = scan(conf, st)
    if not queue:
        set_status("队列空")
        return 0
    if not force and not charging():
        set_status("等待充电（%d 本待转）" % len(queue))
        return 3
    last_defer = [0.0]

    def keep_going():
        # 每分钟查一次是否还在充电
        if time.time() - last_defer[0] > 60:
            last_defer[0] = time.time()
            if not force and not charging():
                return False
        return True

    blocker = SuspendBlocker()
    try:
        return _convert_queue(conf, st, queue, keep_going)
    finally:
        blocker.close()


def _convert_queue(conf, st, queue, keep_going):
    done = 0
    for i, src in enumerate(queue):
        name = os.path.basename(src)
        s = os.stat(src)
        rec = {"size": s.st_size, "mtime": int(s.st_mtime)}
        try:
            book = Epub(src)
            ok, why = book.is_manga()
            if not ok:
                rec.update(status="skipped", reason=why)
                log("跳过 %s：%s" % (name, why))
                st[src] = rec
                save_state(st)
                continue
        except Exception as e:  # 坏文件
            rec.update(status="failed", reason="打不开：%s" % e)
            log("失败 %s：%s" % (name, rec["reason"]))
            st[src] = rec
            save_state(st)
            continue

        dst = target_pdf(src)
        work = os.path.join(conf["tmp_dir"], "current.pdf")
        t0 = time.time()
        log("开始 %s（%d 张图）" % (name, len(book.images)))

        def progress(k, n, i=i):
            set_status("转换中 %d/%d 本，第 %d/%d 页" % (i + 1, len(queue), k, n))

        try:
            pages = convert(src, work, conf, keep_going, progress)
        except Aborted:
            log("已拔电，中止 %s，下次充电重新开始" % name)
            set_status("已暂停（拔电），%d 本待转" % (len(queue) - done))
            return 2
        except Exception as e:
            rec.update(status="failed", reason=repr(e))
            log("失败 %s：%r" % (name, e))
            st[src] = rec
            save_state(st)
            continue
        # 写完整后才放进 documents，书库不会索引到半截文件
        shutil.move(work, dst)
        msg = after_convert(src, conf)
        rec.update(status="done", pdf=dst, pages=pages, seconds=int(time.time() - t0),
                   pdf_mb=round(os.path.getsize(dst) / 1048576, 1))
        st[src] = rec
        save_state(st)
        done += 1
        log("完成 %s -> %d 页，%.1f MB，用时 %d 秒；%s" % (name, pages, rec["pdf_mb"], rec["seconds"], msg))
    set_status("完成，本轮转了 %d 本" % done)
    return 0


def main(argv):
    if len(argv) >= 2 and argv[0] == "convert":
        conf = load_conf()
        src = argv[1]
        dst = argv[2] if len(argv) > 2 else target_pdf(src)
        book = Epub(src)
        log("%s | 标题 %s | 作者 %s | rtl=%s | %d 张图 | 漫画判断 %s" %
            (os.path.basename(src), book.title, book.author, book.rtl, len(book.images), book.is_manga()))
        t0 = time.time()
        pages = convert(src, dst, conf, progress=lambda k, n: print("\r%d/%d" % (k, n), end="", flush=True))
        print()
        log("%d 页 -> %s（%.1f MB，%.0f 秒）" % (pages, dst, os.path.getsize(dst) / 1048576, time.time() - t0))
    elif argv[:1] == ["scan"]:
        for p in scan(load_conf(), load_state()):
            print(p)
    elif argv[:1] == ["run"]:
        sys.exit(run(force="--force" in argv))
    elif argv[:1] == ["status"]:
        try:
            print(open(STATUS, encoding="utf-8").read())
        except OSError:
            print("还没运行过")
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
