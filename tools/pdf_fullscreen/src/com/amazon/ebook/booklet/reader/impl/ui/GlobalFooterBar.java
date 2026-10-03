package com.amazon.ebook.booklet.reader.impl.ui;

import com.amazon.ebook.booklet.reader.sdk.ReaderSDK;
import java.awt.Dimension;
import java.awt.Graphics;

// kindle-tweaks：阅读器通用底栏（右下角百分比/页码）。
// ReaderUIImpl 里 new ProgressBarImpl(sdk,false) 被换成本类。
// 当前打开的是 PDF（书籍控制器属于 pdfreader 包）时高度为 0、不绘制；其他书籍行为不变。
public class GlobalFooterBar extends ProgressBarImpl {
    private static final String PDF_PKG = "com.amazon.ebook.booklet.pdfreader.";
    private final ReaderSDK sdk;

    public GlobalFooterBar(ReaderSDK sdk, boolean showPageNumber) {
        super(sdk, showPageNumber);
        this.sdk = sdk;
    }

    private boolean hidden() {
        try {
            Object c = sdk == null ? null : sdk.IC();
            return c != null && c.getClass().getName().startsWith(PDF_PKG);
        } catch (Throwable t) {
            return false;
        }
    }

    public Dimension getPreferredSize() {
        Dimension d = super.getPreferredSize();
        return hidden() ? new Dimension(d.width, 0) : d;
    }

    public Dimension getMinimumSize() {
        Dimension d = super.getMinimumSize();
        return hidden() ? new Dimension(d.width, 0) : d;
    }

    public void paint(Graphics g) {
        if (!hidden()) {
            super.paint(g);
        }
    }

    public void repaint() {
        if (!hidden()) {
            super.repaint();
        }
    }
}
