# 04 PDF 全屏：去掉底部百分比和四周白边

> 验证：Kindle Oasis 3，FW 5.15.1.1。代码：[`tools/pdf_fullscreen/`](../tools/pdf_fullscreen/)。
> 效果：打开 PDF 时页面铺满整块屏幕（1264×1680 的测试图 1:1 显示，四边无空白），底部不再显示「13%」之类的阅读进度。普通书（mobi/azw3/kfx）的底栏和页边距不受影响。

适合用 KCC 之类工具做成「一页一图、图片尺寸 = 屏幕分辨率」的漫画 PDF：
- 每页就是一张 JPEG，翻页速度和 mobi 漫画差不多。
- 去掉底栏和边距之后，画面可以完全铺满屏幕。

---

## 1 问题

PDF 阅读器四周有一圈白边，底部还常驻一行阅读进度（右下角「13%」）。
- 点击屏幕、设置、「字体与版式」里都没有关闭它们的选项。
- 浏览器打开同一个 PDF 是没有白边的。

测量方法：做一个和屏幕同样大小的测试 PDF，四周画 6 px 黑框，每 100 px 一个刻度。然后用 `fbgrab` 截屏，量黑框的位置：

| 版本 | 黑框所在区域 | 说明 |
|---|---|---|
| 原版 | x 37–1226，y 32–1615 | 顶部 32 px、底部 64 px（底栏）、左右为等比缩放留下的空白 |
| 去掉底栏 | x 32–1231，y 58–1653 | 左右各 32 px 页边距，宽度被卡住；上下是居中留下的空白 |
| 去掉底栏 + 边距 | x 0–1262，y 0–1679 | 全屏，1:1 |

## 2 底部百分比是谁画的

Java 阅读器框架代码在 `/opt/amazon/ebook/lib/*.jar`（未签名，class 版本 52）。用 CFR 反编译后发现：

- PDF 阅读器自己有一个进度条：`PDFBookView.wa()` 里 `new ProgressBarImpl(sdk, true)`。但它通过 `ReaderUI.k()` 放进的是 **工具栏面板**（`ReaderUIImpl.aRM`）。工具栏是独立窗口，只在点开菜单时才显示。**右下角的百分比不是它画的。**
- 真正画百分比的是阅读器的**通用底栏**：`ReaderUIImpl` 构造函数里 `aRU = new ProgressBarImpl(sdk, false)`，由 `DefaultReaderFooter` 放进内容面板 `JR()` 的 `BorderLayout.SOUTH`。所有格式的书共用这一个对象。

走过的弯路：
1. 只替换 PDF 自己的进度条 → 底部没变化（替换错了对象）。
2. 用定时器反复调用 `ReaderUI.Ix()`（移除底栏）→ 阅读器自己会在翻页、关菜单时调用 `Iw()` 把底栏加回去。两边来回增删，每次都改变 PDF 区域的大小，触发整页重新渲染。
3. 把隐藏逻辑挂在 PDF 进度条的 `addNotify()` 上 → 它在工具栏窗口里，平时根本没有挂上界面，所以从未触发。

**最终做法**：把通用底栏换成子类 `GlobalFooterBar`，在每次布局和绘制时判断：
- 当前书籍控制器 `sdk.IC()` 的类名以 `com.amazon.ebook.booklet.pdfreader.` 开头 → `getPreferredSize()` 返回高度 0，`paint()`/`repaint()` 不画。
- 其他情况 → 完全调用父类，行为不变。

这样不增删任何组件。打开、关闭书时阅读器本来就会重新布局，状态自然跟着走。

## 3 白边从哪里来

资源包里有 `reader.content.{left,right,top}Margin.pdf` 等常量（PDFBookController.vs()），但改成 0 以后白边**没变**。

实际生效的边距来自：
- `PDFBookController.getMargin()`
- → `PDFBookMetaData.ns()`
- → `ReaderSDKImpl.IT().ns().getMargin()`

也就是**全局阅读设置里的边距像素值**。PDF 直接照搬了普通书的「页边距」选项，当前档位约 32 px，上、左、右都是这个值。不能直接改全局值，那样小说的边距也会变。

**做法**：只把 `PDFBookMetaData.ns()` 里那一处 `fontPreferences2.getMargin()` 换成 `PdfZeroMargin.zero(fontPreferences2)`，后者返回 `new Insets(0,0,0,0)`。

## 4 怎么改 class 文件（不重新编译原类）

原类是混淆过的，反编译结果不一定能原样编译回去。所以只做**常量池级别的最小改动**，再加两个新类：

| jar | 改动 |
|---|---|
| `ReaderSDK-impl.jar` | `ReaderUIImpl`：`new ProgressBarImpl` + `invokespecial <init>` 这一处 → `GlobalFooterBar`；新增 `GlobalFooterBar.class`；`ReaderResources` 里 PDF 默认边距常量 6.7925pt → 0 |
| `ReaderSDK-impl-zh.jar` | `ReaderResources_zh` 同上（中文界面读这个） |
| `PDFReader-impl.jar` | `PDFBookMetaData`：`invokevirtual FontPreferences.getMargin()` → `invokestatic PdfZeroMargin.zero(FontPreferences)`；新增 `PdfZeroMargin.class` |

两个关键点：

- **不能直接改共享的类名常量。**
  - 最初把 `ReaderUIImpl` 常量池里 `ProgressBarImpl` 的类名整个改成 `GlobalFooterBar`。
  - 结果对底栏的其他调用（`setName`、`addMouseListener`……）也跟着变成了 `GlobalFooterBar.xxx`。但字段 `aRU` 的声明类型还是 `ProgressBarImpl`，校验器报 `VerifyError: Bad type on operand stack`，阅读器打不开。
  - 正确做法：在常量池**末尾追加**新的 Class/Methodref，只把那条 `new`（`bb`）和 `invokespecial`（`b7`）指令的操作数指过去。
- **`invokevirtual` → `invokestatic` 要栈效果相同**：
  - 原调用吃掉一个 `FontPreferences`、压入一个 `Insets`。
  - 新静态方法签名 `(FontPreferences)Insets`，效果一样，指令长度也都是 3 字节，字节码偏移和 StackMapTable 都不用动。

**上机前先在电脑上校验**：`build.py` 会用本机 JVM 以 `-Xverify:all` 加载改过的类，复现了 Kindle 上的 VerifyError，确认修复后才上机。

## 5 生成与安装

```sh
# 1. 把 Kindle 的整个 jar 目录拷回电脑（编译需要整套 classpath）
scp -r root@<kindle-ip>:/opt/amazon/ebook/lib ./ebook-lib

# 2. 生成 .orig / .patched（需要 JDK 9+，例如 IntelliJ/CLion 自带的 jbr；用 JAVA_HOME 指定）
python tools/pdf_fullscreen/build.py ./ebook-lib ./out

# 3. 传到 Kindle
scp out/* root@<kindle-ip>:/mnt/us/extensions/kindletweaks/files/
```

然后在 KUAL →「Kindle Tweaks」→「PDF 全屏」→「开启」。

- 脚本会把 3 个 jar 写进系统分区，然后**重启整个 Java 框架**。屏幕会刷新一阵，约 1 分钟后回到主页。
- 关闭（还原原版）的流程相同。

### 临时试用（不动系统分区）

```sh
export PATH=/usr/sbin:/sbin:$PATH
F=/mnt/us/extensions/kindletweaks/files
stop framework
while pidof cvm >/dev/null; do sleep 1; done     # 等 cvm 真正退出，否则 umount/mount 会 busy
for j in PDFReader-impl.jar ReaderSDK-impl.jar ReaderSDK-impl-zh.jar; do
  mount --bind $F/$j.patched /opt/amazon/ebook/lib/$j
done
start framework
```

出问题时长按电源键 40 秒强制重启，bind mount 失效，系统恢复原样。

## 6 排错笔记

- **重启 framework 后一片白屏，不一定是崩溃。** framework 启动后会恢复上次的前台应用。如果上次停在 KUAL，它会显示成一片空白。
  - 判断：`lipc-get-prop com.lab126.appmgrd activeApp`。
  - 恢复：`lipc-set-prop com.lab126.appmgrd start app://com.lab126.booklet.home`。
  - `tweak.sh` 重启 framework 后会自动执行这一步。
- **从 SSH 直接打开一本书**：`lipc-set-prop com.lab126.appmgrd start "app://com.lab126.booklet.reader/mnt/us/documents/xxx.pdf"`。
  - 前提：这本书已被书库正确索引（`cc.db` 里 `p_type='Entry:Item'`）。没索引好的，把文件移出 documents 再移回来，就会重新索引。
- **测试时防止休眠**：`lipc-set-prop com.lab126.powerd preventScreenSaver 1`（测完改回 0）。
- **截屏**：`/mnt/us/usbnet/bin/fbgrab /tmp/shot.png`（读 `/dev/fb0`），scp 回电脑后用 PIL 测量。
- 看类加载错误：`grep -iE "VerifyError|NoClassDef|NoSuchMethod" /var/log/messages`。

## 7 新固件上怎么重做

1. 拷出新固件的 `/opt/amazon/ebook/lib`，用 CFR 反编译 `ReaderSDK-impl.jar` 和 `PDFReader-impl.jar`。
2. 确认这几处还在：
   - `ReaderUIImpl` 构造函数里只有一处 `new ProgressBarImpl(..., false)`。
   - `PDFBookMetaData.ns()` 里只有一处 `getMargin()`。
   - `ReaderSDK` 接口里还有 `IC()`。
3. 混淆名（`IC`、`ns` 等）每个固件都可能变：
   - 改 `GlobalFooterBar.java` 里的 `sdk.IC()`。
   - 改 `patch_pdf_fullscreen.py` 里的类名和方法名。
   - 脚本对每处改动都断言「恰好命中 1 处」，对不上会直接报错，不会生成坏文件。
4. 用 `build.py` 生成（会自动做字节码校验）。先按第 5 节临时试用，再在 KUAL 里开启。
