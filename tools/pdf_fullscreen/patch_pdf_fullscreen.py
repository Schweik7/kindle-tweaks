"""
让 Kindle 的 PDF 阅读器全屏显示：去掉底部进度条 + 去掉 PDF 四周页边距。

改 3 个 jar（/opt/amazon/ebook/lib/）：
  PDFReader-impl.jar     PDFBookMetaData.ns() 里 FontPreferences.getMargin() -> PdfZeroMargin.zero()
                         （PDF 原本照搬普通书的页边距像素值；改为固定 0，不影响普通书）
  ReaderSDK-impl.jar     ReaderUIImpl 里通用底栏 new ProgressBarImpl -> new GlobalFooterBar
                         （新增子类：当前书籍控制器属于 pdfreader 包时高度 0、不绘制）
                         ReaderResources       里 PDF 页边距常量 6.7925pt -> 0
  ReaderSDK-impl-zh.jar  ReaderResources_zh    同上（中文界面实际读这个）
换类只重定向那一条 new + invokespecial <init>（常量池末尾追加新类引用），
ReaderUIImpl 里其他对底栏的调用仍按 ProgressBarImpl 校验。

用法：python patch_pdf_fullscreen.py <原始 jar 目录> <输出目录> <编译好的 class 目录>
"""
import os
import struct
import sys
import zipfile

OLD_CLS = b"com/amazon/ebook/booklet/reader/impl/ui/ProgressBarImpl"
GLOBAL_CLS = b"com/amazon/ebook/booklet/reader/impl/ui/GlobalFooterBar"
ZERO_CLS = b"com/amazon/ebook/booklet/pdfreader/impl/PdfZeroMargin"
PDF_MARGIN = struct.pack(">f", 6.7925)


def parse_cp(d):
    """返回 (常量池结束偏移, [(tag, start, end)])，按 JVM 规范逐项解析。"""
    n = struct.unpack(">H", d[8:10])[0]
    i, items, k = 10, [], 1
    while k < n:
        tag = d[i]
        if tag == 1:
            ln = struct.unpack(">H", d[i + 1:i + 3])[0]
            end = i + 3 + ln
        elif tag in (3, 4, 9, 10, 11, 12, 18):
            end = i + 5
        elif tag in (5, 6):
            end = i + 9
        elif tag in (7, 8, 16, 19, 20):
            end = i + 3
        elif tag == 15:
            end = i + 4
        else:
            raise ValueError(f"未知常量 tag {tag}")
        items.append((tag, i, end))
        i = end
        k += 2 if tag in (5, 6) else 1
    return i, items


def patch_class(d, utf8_map=None, float_map=None):
    d = bytes(d)
    _, items = parse_cp(d)
    out, last, hits = bytearray(), 0, 0
    for tag, s, e in items:
        if tag == 1 and utf8_map and d[s + 3:e] in utf8_map:
            new = utf8_map[d[s + 3:e]]
            out += d[last:s] + b"\x01" + struct.pack(">H", len(new)) + new
            last, hits = e, hits + 1
        elif tag == 4 and float_map and d[s + 1:e] in float_map:
            out += d[last:s] + b"\x04" + float_map[d[s + 1:e]]
            last, hits = e, hits + 1
    out += d[last:]
    return bytes(out), hits


def redirect_new(d, old_cls, new_cls):
    """只把 `new old_cls` + `invokespecial old_cls.<init>` 这一处换成 new_cls（子类）。
    在常量池末尾追加 Utf8/Class/Methodref，原有常量不动——其他对 old_cls 的方法调用仍按原类型校验，
    否则字段类型是父类、调用点却写子类，会 VerifyError。"""
    d = bytes(d)
    cp_end, items = parse_cp(d)
    idx = {}  # 常量池下标 -> (tag, start, end)
    k = 1
    for it in items:
        idx[k] = it
        k += 2 if it[0] in (5, 6) else 1
    n_next = k

    def utf8(i):
        t, s, e = idx[i]
        return d[s + 3:e] if t == 1 else None

    def u2(off):
        return struct.unpack(">H", d[off:off + 2])[0]

    c_old = [i for i, (t, s, e) in idx.items() if t == 7 and utf8(u2(s + 1)) == old_cls]
    assert len(c_old) == 1, f"Class {old_cls} 命中 {len(c_old)}"
    c_old = c_old[0]
    m_old = [i for i, (t, s, e) in idx.items()
             if t == 10 and u2(s + 1) == c_old and utf8(u2(idx[u2(s + 3)][1] + 1)) == b"<init>"]
    assert len(m_old) == 1, f"{old_cls}.<init> Methodref 命中 {len(m_old)}"
    m_old = m_old[0]
    nat = u2(idx[m_old][1] + 3)

    u_new, c_new, m_new = n_next, n_next + 1, n_next + 2
    added = (b"\x01" + struct.pack(">H", len(new_cls)) + new_cls
             + b"\x07" + struct.pack(">H", u_new)
             + b"\x0a" + struct.pack(">HH", c_new, nat))
    rest = d[cp_end:]
    for op, old, new in ((b"\xbb", c_old, c_new), (b"\xb7", m_old, m_new)):
        pat = op + struct.pack(">H", old)
        assert rest.count(pat) == 1, f"指令 {pat.hex()} 命中 {rest.count(pat)} 处（预期 1）"
        rest = rest.replace(pat, op + struct.pack(">H", new))
    return d[:8] + struct.pack(">H", n_next + 3) + d[10:cp_end] + added + rest


def redirect_call(d, owner, name, desc, new_owner, new_name, new_desc):
    """把唯一一条 invokevirtual owner.name desc 换成 invokestatic new_owner.new_name new_desc（栈效果须相同）。
    新 Methodref/NameAndType/Class/Utf8 追加在常量池末尾，原常量不动。"""
    d = bytes(d)
    cp_end, items = parse_cp(d)
    idx = {}
    k = 1
    for it in items:
        idx[k] = it
        k += 2 if it[0] in (5, 6) else 1
    n_next = k

    def u2(off):
        return struct.unpack(">H", d[off:off + 2])[0]

    def utf8(i):
        t, s, e = idx[i]
        return d[s + 3:e] if t == 1 else None

    def mref(i):
        t, s, e = idx[i]
        cls = utf8(u2(idx[u2(s + 1)][1] + 1))
        nat = idx[u2(s + 3)][1]
        return cls, utf8(u2(nat + 1)), utf8(u2(nat + 3))

    old = [i for i, (t, s, e) in idx.items() if t == 10 and mref(i) == (owner, name, desc)]
    assert len(old) == 1, f"Methodref {owner}.{name}{desc} 命中 {len(old)}"
    pat = b"\xb6" + struct.pack(">H", old[0])
    rest = d[cp_end:]
    assert rest.count(pat) == 1, f"invokevirtual {pat.hex()} 命中 {rest.count(pat)} 处（预期 1）"

    def u8(s):
        return b"\x01" + struct.pack(">H", len(s)) + s
    i_owner, i_cls, i_name, i_desc, i_nat, i_m = range(n_next, n_next + 6)
    added = (u8(new_owner) + b"\x07" + struct.pack(">H", i_owner) + u8(new_name) + u8(new_desc)
             + b"\x0c" + struct.pack(">HH", i_name, i_desc) + b"\x0a" + struct.pack(">HH", i_cls, i_nat))
    rest = rest.replace(pat, b"\xb8" + struct.pack(">H", i_m))
    return d[:8] + struct.pack(">H", n_next + 6) + d[10:cp_end] + added + rest


def rewrite_jar(src, dst, changes, extra=None):
    """changes: {entry: func(bytes)->bytes}; extra: {entry: bytes} 新增文件"""
    zin = zipfile.ZipFile(src)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename in changes:
                data = changes[info.filename](data)
            zout.writestr(info, data)
        for name, data in (extra or {}).items():
            zout.writestr(name, data)


def classes_under(cls_dir, pkg, prefix):
    """cls_dir 里某个包下以 prefix 开头的 .class（含内部类），返回 {jar 内路径: bytes}"""
    d = os.path.join(cls_dir, *pkg.split("/"))
    names = sorted(f for f in os.listdir(d) if f.startswith(prefix) and f.endswith(".class"))
    assert names, f"{d} 里没有 {prefix}*.class"
    return {f"{pkg}/{f}": open(os.path.join(d, f), "rb").read() for f in names}


def main():
    src_dir, out_dir, cls_dir = sys.argv[1:4]
    os.makedirs(out_dir, exist_ok=True)
    report = []

    def pdfmeta(d):
        nd = redirect_call(d, b"com/amazon/ebook/booklet/reader/sdk/content/FontPreferences", b"getMargin",
                           b"()Ljava/awt/Insets;", ZERO_CLS, b"zero",
                           b"(Lcom/amazon/ebook/booklet/reader/sdk/content/FontPreferences;)Ljava/awt/Insets;")
        report.append("PDFBookMetaData.ns(): 页边距 -> PdfZeroMargin.zero()（PDF 不再沿用普通书边距）")
        return nd

    rewrite_jar(os.path.join(src_dir, "PDFReader-impl.jar"), os.path.join(out_dir, "PDFReader-impl.jar"),
                {"com/amazon/ebook/booklet/pdfreader/impl/PDFBookMetaData.class": pdfmeta},
                classes_under(cls_dir, "com/amazon/ebook/booklet/pdfreader/impl", "PdfZeroMargin"))

    def readerui(d):
        nd = redirect_new(d, OLD_CLS, GLOBAL_CLS)
        report.append("ReaderUIImpl: ProgressBarImpl -> GlobalFooterBar")
        return nd

    def margins_for(cls):
        def margins(d):
            nd, h = patch_class(d, float_map={PDF_MARGIN: struct.pack(">f", 0.0)})
            assert h == 1, f"{cls} 里 6.7925 常量命中 {h} 处（预期 1）"
            report.append(f"{cls}: PDF 页边距 6.7925pt -> 0")
            return nd
        return margins

    res = "com/amazon/ebook/booklet/reader/resources/"
    rewrite_jar(os.path.join(src_dir, "ReaderSDK-impl.jar"), os.path.join(out_dir, "ReaderSDK-impl.jar"),
                {"com/amazon/ebook/booklet/reader/impl/ReaderUIImpl.class": readerui,
                 res + "ReaderResources.class": margins_for("ReaderResources")},
                classes_under(cls_dir, "com/amazon/ebook/booklet/reader/impl/ui", "GlobalFooterBar"))
    rewrite_jar(os.path.join(src_dir, "ReaderSDK-impl-zh.jar"), os.path.join(out_dir, "ReaderSDK-impl-zh.jar"),
                {res + "ReaderResources_zh.class": margins_for("ReaderResources_zh")})

    for r in report:
        print(r)


if __name__ == "__main__":
    main()
