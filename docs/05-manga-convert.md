# 05 大漫画 epub 充电时自动转 PDF

> 验证：Kindle Oasis 3，FW 5.15.1.1，KUAL python3（Python 3.9 + Pillow 9.0）。代码：[`extensions/kindletweaks/mangaconv/`](../extensions/kindletweaks/mangaconv/)。
> 配合 [04 PDF 全屏](04-pdf-fullscreen.md) 使用：转出来的 PDF 每页正好一屏，阅读器里 1:1 全屏显示。

## 1 为什么

- Kindle 自己打不开 epub。漫画 epub 通常要在电脑上用 KCC 转成 mobi/azw3 再拷进去。
- KCC 的 mobi 输出依赖 KindleGen，而 KindleGen 只有 x86 版，Kindle 上跑不了。
- PDF 不需要 KindleGen。每页一张 JPEG 原样嵌进去就是合法的 PDF。去掉底栏和边距之后（功能 4），看漫画的体验和 mobi 差不多，翻页速度也一致。
- 所以思路是：在 Kindle 上解开 epub，用 KCC 的算法处理每一页，直接写成 PDF。

**为什么不用 calibre**：calibre 依赖 Qt 和一大堆原生库，没有能在 Kindle（armel 软浮点、glibc 2.20、约 200 MB 可用内存）上跑的版本，它也不处理漫画的裁边、去页码。

## 2 做了什么

| 文件 | 作用 |
|---|---|
| `kcc_lite.py` | KCC `image.py` / `page_number_crop_alg.py` 的精简移植（GPLv3）。功能：去白边、去页码、跨页拆分/旋转、自动对比度、缩放并补边到屏幕分辨率。 |
| `mangaconv.py` | 解析 epub 阅读顺序、判断是不是漫画、边处理边写 PDF；队列、状态、拔电中止、转换期间防休眠 |
| `mangaconv.conf` | upstart 任务：充电时每分钟检查一次队列 |
| `config.json` | 配置（见第 4 节） |

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

- 后台任务 `mangaconv` 每分钟查一次 `lipc-get-prop com.lab126.powerd isCharging`。只有在充电时才继续往下检查。
- 充电时先用 `find -size +10240k` 粗筛大于 10 MB 的 epub 列表。列表签名没变、而且上一轮已经处理完，就不再启动 Python。平时几乎不耗电。
- 转换过程中每分钟确认一次还在充电，拔电就中止（删掉半成品）。下次充电时这本从头开始。
- 进程用 `nice -n 19` + `ionice -c 3`，不影响翻页。
- **防休眠**：
  - 进入屏保一段时间后，powerd 会发 `readyToSuspend` 事件，然后深度休眠，CPU 会停。
  - 转换期间用 `lipc-wait-event -m com.lab126.powerd readyToSuspend` 监听这个事件，收到就回 `lipc-set-prop -i com.lab126.powerd deferSuspend 300`。屏幕照常显示屏保。
  - `deferSuspend` 只在这个状态下有效。平时设置会报 `lipcPropErrInvalidState`；不加 `-i` 会报 `NoSuchProperty`。

KUAL 菜单：「Kindle Tweaks」→「大漫画 epub 转 PDF」

- **开启：充电时自动转换** / **关闭自动转换**：安装或移除 `/etc/upstart/mangaconv.conf`。升级固件后需要重新开启。
- **立即转换（不等充电）**：后台处理一次队列，不检查充电。
- **刷新进度**：菜单标题里会显示进度，比如「转换中 1/3 本，第 57/197 页」。

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

- 想重新转某本被跳过或失败的书：从 `state.json` 里删掉它那一条，或者改一下文件（mtime 变了就会重试）。
- 已经有同名 `.pdf` 的 epub 不会转，不会覆盖你自己的 PDF。
