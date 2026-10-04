# 05 epub 自动转换：大漫画 → PDF，文字书 → AZW3

导入 epub 后，文件传输完成便按内容决定怎么转：

| epub 类型 | 转成 | 工具 |
|---|---|---|
| 漫画（几乎每页一张图）且 ≥ `min_size_mb`（默认 50 MB） | 充电时转全屏 PDF | `kcc_lite.py`（KCC 精简移植），见第 1–5 节 |
| 文字书（任意大小） | 传输完成立即转 AZW3（KF8），不要求充电 | 原生 ARM boko；失败时自动回退 Kindling，见第 7 节 |
| 小于 `min_size_mb` 的漫画 | 不自动转 | 在菜单「按目录转换（不限大小）」里选目录，手动转 PDF |

旁边已有同名 `.pdf` / `.mobi` / `.azw3` / `.azw` 的 epub 一律不转。

> 验证：Kindle Oasis 3，FW 5.15.1.1，KUAL python3（Python 3.9 + Pillow 9.0）。代码：[`extensions/kindletweaks/mangaconv/`](../extensions/kindletweaks/mangaconv/)。
> 配合 [04 PDF 全屏](04-pdf-fullscreen.md) 使用：转出来的 PDF 每页正好一屏，阅读器里 1:1 全屏显示。

## 1 为什么

- Kindle 自己打不开 epub。漫画 epub 通常要在电脑上用 KCC 转成 mobi/azw3 再拷进去。
- KCC 的 mobi 输出依赖已经停止维护的 KindleGen；在 32 位 ARM Kindle 上没有原生版本。
- PDF 不需要 KindleGen。每页一张 JPEG 原样嵌进去就是合法的 PDF。去掉底栏和边距之后（功能 4），看漫画的体验和 mobi 差不多，翻页速度也一致。
- 所以思路是：在 Kindle 上解开 epub，用 KCC 的算法处理每一页，直接写成 PDF。

**为什么不用 calibre**：calibre 依赖 Qt 和一大堆原生库，没有能在 Kindle（armel 软浮点、glibc 2.20、约 200 MB 可用内存）上跑的版本，它也不处理漫画的裁边、去页码。

## 2 做了什么

| 文件 | 作用 |
|---|---|
| `kcc_lite.py` | KCC `image.py` / `page_number_crop_alg.py` 的精简移植（GPLv3）。功能：去白边、去页码、跨页拆分/旋转、自动对比度、缩放并补边到屏幕分辨率。 |
| `mangaconv.py` | 解析 epub 阅读顺序、判断是不是漫画、边处理边写 PDF；队列、状态、拔电中止、转换期间防休眠 |
| `mangaconv.conf` | upstart 任务：每 30 秒检查文件是否传输完成，文字书随时转、漫画等充电 |
| `config.json` | 配置（见第 4 节） |
| `../bin/boko` | 文字书 epub → AZW3 的主转换器（原生 ARM 静态版） |
| `../bin/kindling-cli` | boko 失败时的回退转换器（原生 ARM 静态版） |

移植时的改动：
- **去掉 numpy**：Kindle 是 armel，pip 上没有能用的 numpy。
  - 页码检测原来用 `np.where` 找每行的暗像素，改成 `bytes.translate` 加正则找连续段，都在 C 里完成。
  - 合并框的算法原来两两比较，是 O(n²)。改成逐行扫描，只和还没结束的框比较。
- **兼容 Pillow 9.0**：没有 `Image.Resampling`。
- **只输出灰度**：不做彩色检测、量化、彩虹纹消除、webtoon 等。
- **默认放大小图**（`upscale`），每页正好 1264×1680，阅读器不再缩放。

### epub 解析

1. `META-INF/container.xml` → OPF。
2. 按 `<spine>` 顺序取每个 html 里的 `<img src>` / `<image xlink:href>`，同一张图只取一次。
3. `<spine page-progression-direction="rtl">` 决定拆跨页时先放右半边（日漫）。
4. `dc:title` / `dc:creator` 写进 PDF 的 `/Title` `/Author`，书库就显示这个标题。
5. spine 里找不到图时，退而把所有图片按文件名自然排序。

**是不是漫画**：图片 ≥ 10 张，≥ 90% 的 html 有图，平均每个 html 正文 ≤ 100 字。不满足就跳过，记进 `state.json`，文件不变就不再重试。

### 转换流程

1. 先写到 `/mnt/us/.kindletweaks_tmp/current.pdf`，写完整后再移到 epub 旁边（同名 `.pdf`）。书库不会索引到半截文件。
2. 原 epub 按 `after` 处理，默认移到 `/mnt/us/epub_converted/`，并保留原来的相对路径。
3. 输出放在原 epub 所在的文件夹里，所以 [02 文件夹收藏夹](02-folder-collections.md) 会自动把它归进对应收藏夹。

## 3 什么时候转

- 后台任务 `mangaconv` 每 30 秒计算一次 epub 列表签名（路径、大小、时间）。连续两次签名相同才启动 Python，所以 scp 还在写入的半截文件不会被误判为坏书；USB 模式下则在弹出设备、`/mnt/us` 重新挂载后处理。
- **文字书不检查充电状态**：传输完成后等待一次稳定确认，通常 30–60 秒内开始转换。转换器是原生 ARM 程序，通常只需数秒。
- **自动漫画转换仍要求充电**：未充电时只标记为等待；接上电源后电源状态令队列签名变化，自动开始。转换过程中每分钟确认一次仍在充电，拔电就删掉半成品并暂停。
- 列表、电源和配置签名没变且上一轮已处理后，不再启动 Python；平时只有一次轻量 `find` 和电源查询。
- 进程用 `nice -n 19` + `ionice -c 3`，不影响翻页。
- **防休眠**：
  - 进入屏保一段时间后，powerd 会发 `readyToSuspend` 事件，然后深度休眠，CPU 会停。
  - 转换期间用 `lipc-wait-event -m com.lab126.powerd readyToSuspend` 监听这个事件，收到就回 `lipc-set-prop -i com.lab126.powerd deferSuspend 300`。屏幕照常显示屏保。
  - `deferSuspend` 只在这个状态下有效。平时设置会报 `lipcPropErrInvalidState`；不加 `-i` 会报 `NoSuchProperty`。

KUAL 菜单：「Kindle Tweaks」→「epub 自动转换」

- 第一行显示进度，比如「转换中 1/3 本，第 57/197 页」，点它就刷新。
- **开启自动转换（文字书传完即转）** / **关闭自动转换**：安装或移除 `/etc/upstart/mangaconv.conf`。升级固件后需要重新开启。
- **立即转换（不等充电）**：后台处理一次队列，不检查充电。
- **规则：…**：显示当前规则和可用后端，如「boko→Kindling 回退」或「缺 boko/Kindling」。
- **按目录转换（不限大小）**：
  - 列出 documents 里所有含待转换 epub 的目录和本数，选一个就在后台转那个目录（含子目录），不限大小、不等充电。
  - 如果别的转换正在进行，会排队，等它结束再开始。
  - KUAL 的参数里不能直接放带空格、中文的路径，所以菜单生成时把目录写进 `mangaconv/dirs.txt`，菜单项只传行号。

## 4 配置 `mangaconv/config.json`

| 键 | 默认 | 说明 |
|---|---|---|
| `min_size_mb` | 50 | 只转这么大以上的 epub（大的基本都是漫画） |
| `after` | `move` | 转好后原 epub：`move` 移到 `archive_dir`，`keep` 留在原处，`delete` 删除 |
| `archive_dir` | `/mnt/us/epub_converted` | 不在 documents 里，书库看不到 |
| `jpeg_quality` | 80 | 每页 JPEG 质量 |
| `cropping` | 2 | 0 不裁，1 裁白边，2 裁白边 + 页码 |
| `cropping_power` | 1.0 | 裁切力度 0~3，越大越敢裁 |
| `splitter` | 0 | 跨页：0 拆成两页（特别宽的旋转），1 只旋转，2 两种都要 |
| `upscale` | true | 小图放大到一屏 |
| `text_to_azw3` | true | 是否自动转换文字书；可在配置里显式关闭 |
| `boko` | `../bin/boko` | boko 路径 |
| `kindling` | `../bin/kindling-cli` | Kindling CLI 路径 |
| `text_timeout` | 1800 | 单个转换器的超时秒数；boko 超时后仍会尝试 Kindling |

## 5 实测（Oasis 3）

| 书 | 源 | 页数 | 用时 | PDF |
|---|---|---|---|---|
| 魔王 JuvenileRemix 卷05（Kmoe） | 156 MB，RGB JPEG 约 1340×2160 | 197 | 458 秒（约 2.3 秒/页） | 91 MB（q85） |

- Python 进程约 34 MB 内存，CPU 用的是最低优先级。
- 电脑上转同一本只要 20 秒。在电脑上跑也行：`python mangaconv.py convert 输入.epub 输出.pdf`，只需要 Pillow。

## 6 常用命令

```sh
E=/mnt/us/extensions/kindletweaks
sh $E/tweak.sh manga now                      # 立即处理队列
cat $E/mangaconv/status.txt                   # 当前进度
tail $E/mangaconv/convert.log                 # 日志
cat $E/mangaconv/state.json                   # 每本书的结果（done / skipped / failed 和原因）
LD_LIBRARY_PATH=/mnt/us/python3/lib /mnt/us/python3/bin/python3.9 $E/mangaconv/mangaconv.py scan   # 看队列
```

## 7 文字书 epub → AZW3：boko + Kindling fallback

**为什么不直接搬 calibre**：格式转换本身不难，难在运行环境。
- epub 是 zip 包里的 HTML/CSS/图片，azw3（KF8）是把差不多的内容装进亚马逊的 PalmDB 二进制容器。
- calibre 的转换流程依赖 lxml、html5-parser、css-parser 等一堆 C 扩展。它官方只有 x86 / arm64 版本，而 Kindle 是 32 位 armel 软浮点、glibc 2.20、可用内存约 200 MB，装不上。
- 抽取 calibre 的转换器还会带出它的 OEB 文档模型、CSS/HTML 清理流水线、元数据和 MOBI writer；维护成本明显高于使用专门的 Rust 实现。

现在的方案完全不使用 qemu：

1. 优先调用 [boko](https://github.com/zacharydenton/boko)。它对 Kindle 元数据处理更完整，速度和内存占用也更好。
2. boko 0.5.0 会给所有 AZW3 写入固定 ASIN `EBOK000000`，多本书导入 Kindle 后会共享 `cdeKey`，甚至令内容数据库拒绝后续写入。因此转换后把这个 EXTH 值等长替换为原 EPUB 的 SHA-256 前 10 位；同一本书 ID 稳定，不同书不会冲突，也不改变 PalmDB 偏移。
3. boko 启动失败、返回非零、超时或生成的文件没有合法 `BOOKMOBI` 头时，自动调用 [Kindling](https://github.com/CuteLicense/kindling-epub-to-mobi)。
4. 只有两个后端都失败才把该书记为 `failed`；成功时在 `state.json` 的 `backend` 字段记录实际使用者。
5. 输出先写在 `/mnt/us/.kindletweaks_tmp/ebook-convert/`，校验完整后再移到 epub 旁边，命名为同名 `.azw3`。

### 构建与安装

电脑装好 rustup 和 Rust 1.91+ 后，在仓库根目录运行：

```sh
python tools/build_ebook_converters.py extensions/kindletweaks/bin
scp extensions/kindletweaks/bin/boko extensions/kindletweaks/bin/kindling-cli \
  root@<kindle-ip>:/mnt/us/extensions/kindletweaks/bin/
```

脚本固定到实测过的源码提交，自动添加 `armv7-unknown-linux-musleabi` target，并使用 Rust 自带的 `rust-lld`。产物是 ARMv7、静态链接、soft-float ELF，不依赖 Kindle 陈旧的 glibc，也不需要交叉 GCC。Windows 可直接构建；需要 Linux 时建议用 WSL Arch。源码版本与许可证见 [third-party.md](third-party.md)。

### Oasis 3 实测

同一本 459,174 字节的 Standard Ebooks《Epictetus》epub，在 Kindle Oasis 3 上转换：

| 后端 | release 二进制 | 用时 | 峰值 RSS | AZW3 输出 |
|---|---:|---:|---:|---:|
| boko 0.5.0 | 4,937,504 B（4.71 MiB） | 0.26 s | 12.5 MB | 514,859 B |
| Kindling 0.27.0 | 10,821,184 B（10.32 MiB） | 3.35 s | 47.4 MB | 551,497 B |

构建脚本对 release 产物剥离符号并使用 `panic=abort`，两个二进制合计 15.03 MiB。两份输出都在 Kindle 上生成成功，并通过 calibre 解析和往返转换；boko 输出的元数据更完整，因此作为主路径。

另用 8 本中文书做了实机导入回归：大义觉迷录、西域四百年、骑鹅旅行记、贞德两次审判记录、猎人笔记、唐诗鉴赏辞典、漫长的余生、百年战争。8/8 由 boko 转换并进入 Oasis 3 内容库，calibre 解析 8/8 成功；强制 boko 返回失败时 Kindling 回退也成功。图片较多的《漫长的余生》用时 4 秒（输出 8.6 MB），有 219 张图的《百年战争》用时 35 秒（输出 20.4 MB），两本都因正文密度足够而正确识别为文字书。

## 8 杂项

- 想重新转某本被跳过或失败的书：从 `state.json` 里删掉它那一条，或者改一下文件（mtime 变了就会重试）。
- 已经有同名 `.pdf` / `.mobi` / `.azw3` / `.azw` 的 epub 不会转，不会覆盖你自己的文件。
