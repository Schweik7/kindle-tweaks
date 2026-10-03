package com.amazon.ebook.booklet.pdfreader.impl;

import com.amazon.ebook.booklet.reader.sdk.content.FontPreferences;
import java.awt.Insets;

// kindle-tweaks：PDF 不再沿用普通书的页边距。
// PDFBookMetaData.ns() 里 fontPreferences2.getMargin()（invokevirtual）被换成 invokestatic 本方法，
// 栈效果相同（吃掉一个 FontPreferences，压入一个 Insets）。
public final class PdfZeroMargin {
    private PdfZeroMargin() {
    }

    public static Insets zero(FontPreferences prefs) {
        return new Insets(0, 0, 0, 0);
    }
}
