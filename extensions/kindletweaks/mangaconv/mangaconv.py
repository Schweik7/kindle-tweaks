# -*- coding: utf-8 -*-
# Copyright (c) 2026 kindle-tweaks contributors. GPL-3.0-or-later.
"""
漫画 epub -> Kindle 全屏 PDF（在 Kindle 上跑，也能在电脑上跑，只依赖 Pillow）。

    mangaconv.py convert <in.epub> [out.pdf]   转换一本（不管大小、不管充电）
    mangaconv.py scan                          列出待转换队列
    mangaconv.py run [--force] [--dir 目录]     处理队列；不带 --force 时只在充电时干活，拔电就停；
                                               --dir 只处理该目录里的 epub，不限大小、不等充电
    mangaconv.py status                        一行状态（给 KUAL 菜单用）

队列 = documents 下旁边还没有同名 pdf/mobi/azw3 的 .epub，按内容决定怎么转：
  漫画（几乎每个 html 一张图、没什么文字）且 >= min_size_mb → PDF（kcc_lite 处理每页）；
  文字书（任意大小）→ mobi（KindleGen 经 qemu-i386 运行，需要 ../bin/ 里的两个文件）；
  小漫画 → 不自动转，留给菜单里「按目录转换」手动转 PDF。
转好后原 epub 按 config.json 的 after 处理（默认移到 archive_dir）。
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
    # 文字书 epub -> mobi：KindleGen（x86 静态版）经 qemu-i386 用户态模拟运行
    "text_to_mobi": True,
    "kindlegen": os.path.join(os.path.dirname(HERE), "bin", "kindlegen"),
    "qemu": os.path.join(os.path.dirname(HERE), "bin", "qemu-i386-static"),
    "kindlegen_compress": 0,
    "kindlegen_timeout": 3600,
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


def target_mobi(src):
    return os.path.splitext(src)[0] + ".mobi"


def has_output(src):
    """旁边已经有同名的 pdf/mobi/azw3，就不再转（也不会覆盖用户自己的文件）。"""
    base = os.path.splitext(src)[0]
    return any(os.path.exists(base + e) for e in (".pdf", ".mobi", ".azw3", ".azw"))


def kindlegen_ready(conf):
    return conf["text_to_mobi"] and all(os.path.isfile(conf[k]) for k in ("kindlegen", "qemu"))


def scan(conf, st, only_dir=None):
    """返回待转换的 epub 列表（按路径排序），具体转成什么在 _convert_queue 里看内容决定。
    自动模式：>= min_size_mb 的都算；小的只在启用了 epub->mobi 时才算（小漫画会被标成 manual 留给手动）。
    only_dir：只看这个目录（含子目录），不限大小，manual 的也转。"""
    out = []
    limit = conf["min_size_mb"] * 1024 * 1024
    mobi = kindlegen_ready(conf)
    for root, dirs, files in os.walk(only_dir or conf["documents"]):
        dirs[:] = [d for d in dirs if not d.endswith(".sdr")]
        for f in files:
            if not f.lower().endswith(".epub"):
                continue
            p = os.path.join(root, f)
            try:
                s = os.stat(p)
            except OSError:
                continue
            if has_output(p):
                continue
            if not only_dir and s.st_size < limit and not mobi:
                continue
            rec = st.get(p)
            # 跳过 / 失败过 / 等手动的，文件没变就不再试
            if rec and rec.get("size") == s.st_size and rec.get("mtime") == int(s.st_mtime):
                if rec["status"] in ("skipped", "failed") or (rec["status"] == "manual" and not only_dir):
                    continue
            out.append(p)
    return sorted(out, key=natural_key)


def to_mobi(src, dst, conf, keep_going=None):
    """用 KindleGen（x86，经 qemu-i386 用户态模拟运行）把 epub 编译成 mobi（含 KF8）。"""
    work = os.path.join(conf["tmp_dir"], "kindlegen")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    ep = os.path.join(work, "book.epub")
    shutil.copyfile(src, ep)
    logf = os.path.join(work, "kindlegen.log")
    # KindleGen 会把 epub 解压到 $TMPDIR，默认 /tmp 在内存里，改到 U 盘区
    env = dict(os.environ, TMPDIR=work)
    cmd = [conf["qemu"], conf["kindlegen"], ep, "-c%d" % conf["kindlegen_compress"], "-dont_append_source", "-o", "book.mobi"]
    with open(logf, "w") as lf:
        p = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, env=env, cwd=work)
    t0 = time.time()
    try:
        while p.poll() is None:
            time.sleep(5)
            if keep_going and not keep_going():
                raise Aborted()
            if time.time() - t0 > conf["kindlegen_timeout"]:
                raise RuntimeError("kindlegen 超时（%d 秒）" % conf["kindlegen_timeout"])
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
    out = os.path.join(work, "book.mobi")
    # 返回码 0 成功、1 成功但有警告、2 失败
    if p.returncode not in (0, 1) or not os.path.exists(out):
        try:
            errs = [l.strip() for l in open(logf, encoding="utf-8", errors="replace") if "Error" in l][-2:]
        except OSError:
            errs = []
        raise RuntimeError("kindlegen rc=%s %s" % (p.returncode, " | ".join(errs)))
    shutil.move(out, dst)
    shutil.rmtree(work, ignore_errors=True)


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


def run(force=False, only_dir=None):
    """返回码：0 队列已处理完；2 拔电中止；3 没在充电；4 已有一个在跑（后台任务据此决定下次是否重试）。
    only_dir：手动指定目录（不限大小、不等充电）；有别的转换在跑就排队等它结束。"""
    import fcntl
    conf = load_conf()
    os.makedirs(conf["tmp_dir"], exist_ok=True)
    lock = open(os.path.join(conf["tmp_dir"], "lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        if not only_dir:
            return 4
        set_status("排队中：等当前转换结束")
        fcntl.flock(lock, fcntl.LOCK_EX)
    return _run(conf, force or bool(only_dir), only_dir)


def _run(conf, force, only_dir=None):
    st = load_state()
    queue = scan(conf, st, only_dir)
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
        return _convert_queue(conf, st, queue, keep_going, only_dir)
    finally:
        blocker.close()


def _convert_queue(conf, st, queue, keep_going, only_dir=None):
    done = 0
    limit = conf["min_size_mb"] * 1024 * 1024
    for i, src in enumerate(queue):
        name = os.path.basename(src)
        s = os.stat(src)
        rec = {"size": s.st_size, "mtime": int(s.st_mtime)}

        def remember(status, reason):
            rec.update(status=status, reason=reason)
            log("%s %s：%s" % ({"skipped": "跳过", "failed": "失败", "manual": "留给手动"}[status], name, reason))
            st[src] = rec
            save_state(st)

        try:
            book = Epub(src)
            manga, why = book.is_manga()
        except Exception as e:  # 坏文件
            remember("failed", "打不开：%s" % e)
            continue
        if manga and (s.st_size >= limit or only_dir):
            kind = "pdf"
        elif not manga and kindlegen_ready(conf):
            kind = "mobi"
        elif manga:
            remember("manual", "小于 %d MB 的漫画，在菜单「按目录转换」里手动转 PDF" % conf["min_size_mb"])
            continue
        else:
            remember("skipped", "%s；epub→mobi 未启用或缺 kindlegen" % why)
            continue

        t0 = time.time()
        try:
            if kind == "pdf":
                dst = target_pdf(src)
                work = os.path.join(conf["tmp_dir"], "current.pdf")
                log("开始 %s -> PDF（%d 张图）" % (name, len(book.images)))

                def progress(k, n, i=i):
                    set_status("转换中 %d/%d 本，第 %d/%d 页" % (i + 1, len(queue), k, n))
                pages = convert(src, work, conf, keep_going, progress)
                # 写完整后才放进 documents，书库不会索引到半截文件
                shutil.move(work, dst)
                rec.update(pages=pages)
            else:
                dst = target_mobi(src)
                log("开始 %s -> mobi（kindlegen）" % name)
                set_status("转换中 %d/%d 本：%s -> mobi" % (i + 1, len(queue), name[:20]))
                to_mobi(src, dst, conf, keep_going)
        except Aborted:
            log("已拔电，中止 %s，下次充电重新开始" % name)
            set_status("已暂停（拔电），%d 本待转" % (len(queue) - done))
            return 2
        except OSError as e:
            # 多半是切到了 USB 存储模式、/mnt/us 被卸载：不记失败，下次重来
            log("读写出错，中止 %s：%r" % (name, e))
            set_status("读写出错已中止，%d 本待转" % (len(queue) - done))
            return 2
        except Exception as e:
            remember("failed", repr(e))
            continue
        msg = after_convert(src, conf)
        rec.update(status="done", out=dst, seconds=int(time.time() - t0),
                   out_mb=round(os.path.getsize(dst) / 1048576, 1))
        st[src] = rec
        save_state(st)
        done += 1
        log("完成 %s -> %s，%.1f MB，用时 %d 秒；%s" % (name, os.path.basename(dst), rec["out_mb"], rec["seconds"], msg))
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
        d = argv[argv.index("--dir") + 1] if "--dir" in argv else None
        sys.exit(run(force="--force" in argv, only_dir=d))
    elif argv[:1] == ["status"]:
        try:
            print(open(STATUS, encoding="utf-8").read())
        except OSError:
            print("还没运行过")
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
