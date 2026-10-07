# -*- coding: utf-8 -*-
# Copyright (c) 2026 kindle-tweaks contributors. GPL-3.0-or-later.
"""
md / docx -> EPUB，再由 mangaconv 交给 boko 转 AZW3（boko 不能读 md、docx）。

    docconv.py <in.md|in.docx> <out.epub>

依赖纯 Python 的 markdown（md）和 mammoth（docx）：
    LD_LIBRARY_PATH=/mnt/us/python3/lib /mnt/us/python3/bin/python3.9 -m pip install markdown mammoth
按最高一级标题拆成章节并生成目录；md 里的本地图片、docx 里的 PNG/JPEG/GIF 图片一起打包，
远程图片和 Word 的 EMF/WMF 矢量图换成替代文字。书名取文件名。
"""
import html
import os
import re
import sys
import uuid
import zipfile
from html.entities import name2codepoint

DOC_EXT = (".md", ".markdown", ".docx")
IMG_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif"}
CSS = """body { margin: 0 2%; }
h1, h2, h3 { line-height: 1.3; }
pre { white-space: pre-wrap; font-family: monospace; font-size: 0.85em; }
code { font-family: monospace; }
blockquote { margin: 0.5em 1.5em; font-style: italic; }
table { border-collapse: collapse; margin: 0.5em 0; }
th, td { border: 1px solid #000; padding: 0.2em 0.4em; }
img { max-width: 100%; }
"""
ZIP_TIME = (2020, 1, 1, 0, 0, 0)    # 固定时间戳：同一份源文件生成的 EPUB 完全相同


def is_doc(path):
    return path.lower().endswith(DOC_EXT)


def _need(module):
    try:
        return __import__(module)
    except ImportError:
        raise RuntimeError("缺少 Python 库 %s，请在 Kindle 上 pip install markdown mammoth" % module)


def _add_image(images, data, ext):
    name = "img%d%s" % (len(images) + 1, ext)
    images[name] = data
    return "images/" + name


def _md_html(src, images):
    markdown = _need("markdown")
    with open(src, encoding="utf-8-sig", errors="replace") as f:
        text = f.read()
    body = markdown.markdown(text, extensions=["extra", "sane_lists"], output_format="xhtml")
    base = os.path.dirname(os.path.abspath(src))

    def img(m):
        tag = m.group(0)
        s = re.search(r'\ssrc="([^"]*)"', tag)
        url = html.unescape(s.group(1)) if s else ""
        ext = os.path.splitext(url.split("?")[0])[1].lower()
        path = os.path.join(base, url)
        if url and not re.match(r"[a-z][a-z0-9+.-]*:", url, re.I) and ext in IMG_MIME and os.path.isfile(path):
            with open(path, "rb") as f:
                new = _add_image(images, f.read(), ext)
            return tag.replace(s.group(0), ' src="%s"' % new)
        alt = re.search(r'\salt="([^"]*)"', tag)
        return "<span>[%s]</span>" % (alt.group(1) if alt and alt.group(1) else "图片")
    return re.sub(r"<img\b[^>]*>", img, body)


def _docx_html(src, images):
    mammoth = _need("mammoth")

    def conv(image):
        ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif"}.get(image.content_type)
        if not ext:
            return {"alt": image.alt_text or "图片"}     # EMF/WMF 等：没有 src，下面换成文字
        with image.open() as f:
            return {"src": _add_image(images, f.read(), ext)}
    with open(src, "rb") as f:
        body = mammoth.convert_to_html(f, convert_image=mammoth.images.img_element(conv)).value

    def drop_srcless(m):
        tag = m.group(0)
        if ' src="' in tag:
            return tag
        alt = re.search(r'\salt="([^"]*)"', tag)
        return "<span>[%s]</span>" % (alt.group(1) if alt else "图片")
    return re.sub(r"<img\b[^>]*>", drop_srcless, body)


def _xhtml(body):
    """HTML 片段 -> 合法的 XHTML 片段：空元素自闭合，XML 不认识的具名实体换成数字。"""
    body = re.sub(r"<(br|hr|img)\b([^>]*?)\s*/?>", r"<\1\2 />", body, flags=re.I)

    def ent(m):
        n = m.group(1)
        if n in ("amp", "lt", "gt", "quot", "apos"):
            return m.group(0)
        return "&#%d;" % name2codepoint[n] if n in name2codepoint else "&amp;" + n + ";"
    return re.sub(r"&([A-Za-z][A-Za-z0-9]*);", ent, body)


def _text(fragment):
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def _split(body, title):
    """按出现的最高一级标题（h1 或 h2）拆章；标题之前的内容单独成一章。"""
    level = next((n for n in (1, 2) if re.search(r"<h%d\b" % n, body, re.I)), None)
    if not level:
        return [(title, body)]
    parts = re.split(r"(?=<h%d\b)" % level, body, flags=re.I)
    chapters = []
    for p in parts:
        if not p.strip():
            continue
        m = re.match(r"<h%d\b[^>]*>(.*?)</h%d>" % (level, level), p, re.I | re.S)
        chapters.append((_text(m.group(1)) if m else title, p))
    return chapters


def _lang(body):
    return "zh" if re.search(r"[぀-ヿ一-鿿]", body) else "en"


def _write_epub(dst, title, chapters, images, lang):
    esc = html.escape
    uid = "urn:uuid:%s" % uuid.uuid5(uuid.NAMESPACE_URL, "kindletweaks-doc:" + title)
    files = []
    for i, (name, body) in enumerate(chapters, 1):
        files.append(("c%03d.xhtml" % i, name or title,
                      '<?xml version="1.0" encoding="utf-8"?>\n'
                      '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="%s"><head><title>%s</title>'
                      '<link rel="stylesheet" type="text/css" href="style.css"/></head><body>\n%s\n</body></html>\n'
                      % (lang, esc(name or title), _xhtml(body))))
    manifest = ['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
                '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
                '<item id="css" href="style.css" media-type="text/css"/>']
    manifest += ['<item id="c%d" href="%s" media-type="application/xhtml+xml"/>' % (i, f) for i, (f, _, _) in enumerate(files, 1)]
    manifest += ['<item id="i%d" href="images/%s" media-type="%s"/>' % (i, n, IMG_MIME[os.path.splitext(n)[1]])
                 for i, n in enumerate(images, 1)]
    spine = "".join('<itemref idref="c%d"/>' % i for i in range(1, len(files) + 1))
    opf = ('<?xml version="1.0" encoding="utf-8"?>\n'
           '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
           '<dc:identifier id="uid">%s</dc:identifier><dc:title>%s</dc:title><dc:language>%s</dc:language>'
           '<meta property="dcterms:modified">2020-01-01T00:00:00Z</meta></metadata>'
           '<manifest>%s</manifest><spine toc="ncx">%s</spine></package>\n'
           % (uid, esc(title), lang, "".join(manifest), spine))
    nav = ('<?xml version="1.0" encoding="utf-8"?>\n'
           '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>%s</title></head>'
           '<body><nav epub:type="toc"><ol>%s</ol></nav></body></html>\n'
           % (esc(title), "".join('<li><a href="%s">%s</a></li>' % (f, esc(n)) for f, n, _ in files)))
    ncx = ('<?xml version="1.0" encoding="utf-8"?>\n'
           '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head><meta name="dtb:uid" content="%s"/></head>'
           '<docTitle><text>%s</text></docTitle><navMap>%s</navMap></ncx>\n'
           % (uid, esc(title), "".join('<navPoint id="p%d" playOrder="%d"><navLabel><text>%s</text></navLabel><content src="%s"/></navPoint>'
                                       % (i, i, esc(n), f) for i, (f, n, _) in enumerate(files, 1))))
    container = ('<?xml version="1.0" encoding="utf-8"?>\n'
                 '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                 '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>\n')

    def put(z, name, data, method=zipfile.ZIP_DEFLATED):
        z.writestr(zipfile.ZipInfo(name, ZIP_TIME), data, method)
    with zipfile.ZipFile(dst, "w") as z:
        put(z, "mimetype", "application/epub+zip", zipfile.ZIP_STORED)     # 必须是第一个且不压缩
        put(z, "META-INF/container.xml", container)
        put(z, "OEBPS/content.opf", opf)
        put(z, "OEBPS/nav.xhtml", nav)
        put(z, "OEBPS/toc.ncx", ncx)
        put(z, "OEBPS/style.css", CSS)
        for f, _, data in files:
            put(z, "OEBPS/" + f, data)
        for n, data in images.items():
            put(z, "OEBPS/images/" + n, data, zipfile.ZIP_STORED)


def to_epub(src, dst):
    """md/docx -> EPUB，返回章节数。"""
    title = os.path.splitext(os.path.basename(src))[0]
    images = {}
    body = _docx_html(src, images) if src.lower().endswith(".docx") else _md_html(src, images)
    chapters = _split(body, title)
    _write_epub(dst, title, chapters, images, _lang(body))
    return len(chapters)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    print("%d 章 -> %s" % (to_epub(sys.argv[1], sys.argv[2]), sys.argv[2]))
