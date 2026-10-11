# 17 墨水屏视频播放（fbvideo）

在越狱的 Kindle 上逐帧播放视频。原理是**绕过 X，直接把 1bit 像素写进 framebuffer，并用指定的 EPDC 波形刷屏**。

结论先说：**能播，画面逐像素准确；但帧率被墨水屏硬件锁死在 ~9.9 fps 以内，A2 是唯一快的真实波形。**

**推荐用法**：`800×600 @ 8fps` 是画幅与流畅度的平衡点（占屏 63%×36%，8.05 fps）。
想要满宽就用 `1264×948 @ 6fps`（6.26 fps）。**不要再往大做**——整屏只有 4.87 fps，
而帧率上不去的根因是波形时序，不是软件（见第 8 节，那里也记录了"想突破这个上限该怎么做"
以及已经在真机上验证过的硬件依据）。

## 1 实测数据速览

设备：Kindle Oasis 3（`fsl,imx7d-zelda` / Stinger），FW `005-juno_150101_stinger_zelda-392503`（5.15.1.1），
内核 `4.1.15-lab126`，面板 1264×1680 @ 8bpp（stride 1280）。

**波形（640×480 区域，pcnt 实测）**

| 索引 | 名字 | ms/帧 | fps | 说明 |
| --- | --- | --- | --- | --- |
| **4** | **A2** | **115** | **8.6** | **唯一快的真实波形，1bit 内容的本命** |
| 1 | DU | 208 | 4.8 | 真实，慢 |
| 5 | GL16 | 295 | 3.4 | 真实 |
| 0 | INIT | 323 | 3.1 | 真实 |
| 2 | GC16 | 365 | 2.7 | 真实，最干净 |
| 3 | GC4 | 368 | 2.7 | 真实 |
| **10** | **（FBInk 叫 DU4）** | **37** | **27** | ⚠️ **是真正的 1 相 no-op 波形（什么都不做），不是"驱动丢弃"——见 §7** |

**面积与帧率的取舍（A2 波形，实测拟合）**

```
t ≈ 100.5 ms + 4.938e-5 × 像素数
```

| 尺寸 | 像素 | 预测 ms | fps | 占屏比 |
| --- | --- | --- | --- | --- |
| 320×240 | 76800 | 104 | 9.59 | 25%×14% |
| 640×480 | 307200 | 116 | 8.64 | 51%×29% |
| **800×600** | 480000 | 124 | **8.05** | 63%×36% |
| 1012×759 | 768108 | 139 | 7.22 | 80%×45% |
| **1264×948** | 1198272 | 160 | **6.26** | **100%×56%** |
| 1264×1680 | 2123520 | 205 | 4.87 | 整屏 |

**注意那个 100.5 ms 的常数项**：即使把区域缩到 0 像素也省不掉它，所以**理论天花板约 9.9 fps**。
换尺寸只能在这条线上滑动，换不来数量级。

**播放正确性验证**：把设备截图和本地生成的源帧做逐像素比对，结果全部是 **0.00% 差异**：

| 验证对象 | 匹配到的帧 | 差异 |
| --- | --- | --- |
| 自检动画（640×480） | 第 11 / 32 / 45 帧 | 0.00%（帧号单调递增） |
| Bad Apple（640×480） | 第 307 / 833 帧 | 0.00% |
| Bad Apple 800×600 | 第 7 帧 | 0.00% |

第 3、4 张 Bad Apple 截图都停在第 1219 帧，因为那次播放正好在第 1220 帧崩了
（触摸触发的 `any_input` bug，日志里"共 1220 帧"吻合）——**这个 bug 已修**，
而且它反而成了一次意外的"播放精度证据"。

> **比对时的极性坑**（我在这上面浪费了一轮）：`.ktvid` 里 **1 = 白、0 = 黑**（和 PIL 的 1bit 一致），
> 而截图侧习惯写成 `(像素 < 128)` 得到 **1 = 暗**。两边不统一就会得出"差异 100%"或跨越十几个百分点的假数据，
> 看起来像残影，其实是自己反了。比对前先把两边都统一成"1 = 暗"再算。

**压缩**：1bit 帧冗余度极高，per-frame zlib 后 1bit 画面能压到 **1%~16%**
（Bad Apple 640×480 全长 1755 帧：64.3 MB → 6.3 MB；1264×948：250.7 MB → 21.1 MB）。
设备上解压只花约 3 ms/帧，相对 100+ ms 的刷屏时间可以忽略（实测压缩前后 8.70 vs 8.64 fps）。

## 2 为什么走 fbink，而不是 WAF

两条路线的差别是「谁控制刷新」：

| | WAF（mesquite/WebKit） | fbvideo（Pillow + py-fbink） |
| --- | --- | --- |
| 刷新时机 | 系统管（`lab126_ligl.lua`），拿不到 | **自己指定波形，逐帧控制** |
| 帧率 | 不可控 | **A2 实测 8.6 fps** |
| 语言 | 只能用 ES5 | Python + numpy + Pillow |
| 适合 | 表单、阅读、列表、常驻面板 | **动画、视频、需要精确刷新的东西** |

所以本仓库里 `webapp`（WAF）和 `fbvideo` 是互补的：**静态/交互界面用 WAF，动画用 fbvideo**。
选型依据见 [16 常驻网页应用（WAF）](16-webapp-waf.md#8-附录ui-选型的实测数据)。

## 3 怎么用

### 3.1 设备上

```sh
# KUAL 菜单：墨水屏视频播放 -> 选视频 -> 选波形
# 或 SSH：
cd /mnt/us/extensions/kindletweaks/fbvideo
LD_LIBRARY_PATH=/mnt/us/python3/lib /mnt/us/python3/bin/python3 play.py /mnt/us/videos/badapple.ktvid
```

常用参数：

| 参数 | 作用 |
| --- | --- |
| `--waveform A2\|DU\|GC16` | 选波形，默认 A2 |
| `--fps N` | 覆盖文件头里的帧率 |
| `--loops N` | 循环次数（0=无限） |
| `--frames N` | 最多播多少帧 |
| `--x/--y` | 指定左上角，默认居中 |
| `--gc-every N` | 每 N 帧用 GC16 全刷一次去残影（默认 60，`0` 关闭） |
| `--flip v\|h` | 翻转画面 |
| `--frame-log FILE` | 每帧记「时间戳 帧号 总ms 解码ms 刷屏ms」，用来量性能 |
| `--exit-on-input` | 按键/触摸就停（默认**不响应**，避免误触中断播放） |
| `--no-restore` | 播完不切回主页（保留最后一帧） |

停止播放：KUAL 里「停止播放」，或 `pkill -f play.py`。

### 3.2 电脑上转码

```sh
# 视频（需要本机有 ffmpeg）
python tools/make_ktvid.py badapple.mp4 -o badapple.ktvid --fps 8 --width 800 --height 600
# 只取一段试水
python tools/make_ktvid.py badapple.mp4 -o t.ktvid --start 100 --duration 20
# GIF / PNG 序列（只用 Pillow，不需要 ffmpeg）
python tools/make_ktvid.py anim.gif -o anim.ktvid --fps 10
python tools/make_ktvid.py frames_dir -o out.ktvid --fps 12
# A/B 对比时把标签烧进每帧，一眼看出在放哪段
python tools/make_ktvid.py in.mp4 -o ab.ktvid --label "A2"
```

**帧率要和尺寸匹配**，否则播放时长会失真：`--fps` 设成目标尺寸能达到的帧率
（800×600 用 8，1264×948 用 6）。设高了播放器只能按面板速度走，视频会被拖长。

> **下载素材的坑（实测）**：用 `yt-dlp` 抓 YouTube 时，DASH 格式（`bv*`/`-f 18`）经常返回
> `HTTP Error 403: Forbidden`。加上 `--extractor-args "youtube:player_client=android"` 就能正常下载
> （其它 client 如 `web_safari`/`tv` 也可能行，但 `android` 是实测成功的那个）。

**给 Bad Apple 用的推荐参数**（已转好放在设备的 `/mnt/us/videos/`）：

| 文件 | 尺寸 | fps | 大小 | 定位 |
| --- | --- | --- | --- | --- |
| `badapple_800.ktvid` | 800×600 | 8 | 9.4 MB | **流畅优先**（63% 宽） |
| `badapple_full.ktvid` | 1264×948 | 6 | 15.8 MB | **满宽优先** |
| `counter_c.ktvid` | 640×480 | 10 | 59 KB | 自检用：帧号 + 弹跳球 + 进度条 |

## 4 .ktvid 格式

小端。

| 偏移 | 长度 | 内容 |
| --- | --- | --- |
| 0 | 8B | magic `"KTVID1\0\0"` |
| 8 | 2B | width |
| 10 | 2B | height |
| 12 | 1B | bpp（固定 1） |
| 13 | 1B | flags：bit0=位序 MSB-first，bit1=每帧带 zlib |
| 14 | 2B | 保留 |
| 16 | 4B | frame_count |
| 20 | 4B | fps × 100 |
| 24 | 4B | frame_bytes = ceil(width/8) × height（解压后大小） |
| 28 | 20B | 标题（UTF-8，NUL 补齐） |
| 48 | … | 帧数据 |

帧数据：未压缩时每帧 `frame_bytes` 字节；压缩时每帧 `[uint32 压缩长度][zlib 数据]`。
每行按字节对齐（`ceil(w/8)` 字节），位序 MSB-first，**1=白、0=黑**，
所以设备端 `unpackbits` 后 `reshape(h, ceil(w/8)*8)[:, :w] * 255` 就能直接喂给 framebuffer。

## 5 fbink 的两种形态（容易踩）

设备上同时存在**两个不同的 fbink 构建**，能力不一样：

| | `/mnt/us/libkh/bin/fbink`（CLI） | `/mnt/us/python3/lib/libfbink.so.1`（py-fbink 自带） |
| --- | --- | --- |
| 版本 | v1.25.0 | v1.24.0-78 |
| 特性 | `Fonts=No Image=No` | **有字体**（`fbink_print` 返回 1，内置 32×32 字体，39 列×52 行） |
| 用途 | 命令行写字/清屏 | Python 里画图 |

所以要**打印文字**得用 py-fbink（`FBInk.fbink_print`），CLI 那个 `Fonts=No` 打不了字。
但**画图像**两条路都行：本方案不走 fbink 的图片解码，而是用 Pillow 渲染成 8bpp 灰度再
`fbink_print_raw_data(data, w, h, len, x_off, y_off, cfg)`，所以 `Image=No` 不影响我们。

关键 API 位置：

```python
from _fbink import ffi, lib as FBInk          # 不是 import fbink
cfg = ffi.new("FBInkConfig *")
cfg.is_quiet = True
cfg.wfm_mode = FBInk.WFM_A2                   # 波形在这里，不是 FBInkConfig.waveform
FBInk.fbink_print_raw_data(fbfd, buf, W, H, len(buf), x, y, cfg)
FBInk.fbink_wait_for_complete(fbfd, 0)        # marker=0 表示「本会话最后一次更新」
```

`cfg` 的字段名要对：`wfm_mode`（不是 `waveform`）、`no_refresh`、`is_flashing`、`dithering_mode`。

## 6 屏幕的归属：画上去会显示，但会被系统冲掉

实测（这一点决定了播放器要有哪些行为）：

- Xorg（PID 4739）、awesome、blanket 都持有 `/dev/fb0`，但**直接写 framebuffer 依然能显示并保持**
  （画一块黑底白框，区域墨色 5.7% → 87.3%，等 10 秒后完全没有变化）。
- 但 `restart kppmainapp` 触发系统整体重绘后，**同样的区域从 87.3% 掉回 5.1%** —— 内容被冲掉了。

所以：

- 播放期间播放器会自己设 `preventScreenSaver 1` 压住屏保，播完再放开；
- 停止播放后切回主页让 X 重绘，否则屏幕上留着一帧和系统状态不一致的画面；
- **不要指望 fbink 画的东西能长期驻留**。要常驻的界面走 WAF（见 [15](15-wafs-and-mesquite.md) / [16](16-webapp-waf.md)）。

## 7 索引 10 这个坑（重要；2026-10-11 已查明真正原因）

`WFM_DU4`（FBInk 的枚举值 = mxcfb 波形索引 10）测出来只要 **37 ms/帧（640×480）、
79 ms/帧（1264×948）**，看起来比 A2 快 3 倍，非常诱人。而且**肉眼确认：画面一动不动**。

> ⚠️ **本节原先的解释是错的**，这里保留纠错过程，因为教训比结论更值钱。

**原先（错误）的解释**：说它是"不被支持的索引"，"驱动把更新合并/丢弃了"，
证据是内核 `SW mitigation` 日志间隔 ~125 ms 与提交节奏对不上。

**真正的原因**（靠自造波形 + 上机实测查清，详见 [18 §4.6](18-epdc-recon-and-handover.md)）：
**mxcfb 的 `waveform_mode` 索引并不等于波形 blob 里的 mode 序号**，两者是一张置换表。
实测 **mxcfb 索引 10 → blob mode 7**，而原厂 blob 的 mode 7 恰好是一个
**合法的「1 相、512 字节 action 全零」no-op** —— 也就是硬件收到的指令字面意思就是
"这一个相位不对任何像素施加电压"。

所以：驱动**没有**丢弃更新，面板**如实地什么都不做**，18 ms 就干完了。
这不是一个"更快的波形"，确实不能用来放视频 —— **但结论对、理由错**。

**决定性证据**：把 blob mode 7 从 1 相改成 **1023 相**（内容仍是全零）后：

| blob mode 7 的相数 | mxcfb 索引 10 的耗时 |
| ---: | ---: |
| 1（原厂） | 17.74 ms |
| 1023（自造） | **12111.2 ms** |

而同一轮里其它索引耗时**完全不受影响**（索引 2 始终 353 ms）。这既证明了
"索引 10 = blob mode 7"，也证明了那张长 LUT **真的被硬件执行了**。

**教训**：
1. **不要用"耗时反常"来推断"波形不被支持"** —— 先怀疑索引映射。
2. 判断面板有没有真刷新，**唯一的裁判仍然是肉眼**：`/usr/sbin/screenshot` 读的是
   framebuffer，而 framebuffer 里永远是我们刚写进去的内容，无论面板刷没刷。
   （本次结论之所以能推翻旧说法，靠的是"改波形内容 → 耗时跟着变"这个**因果实验**，
   而不是看截图。）

## 8 为什么不能再快：与 K4 直驱方案的对比

社区里 [qwert-Xx/kindle4nt-eink-video](https://github.com/qwert-Xx/kindle4nt-eink-video)
把 Kindle 4 的播放推到了 **84.6 次/秒（= 面板扫描帧率）、0 漏帧**，是 8 fps 的十倍。
它的做法和本方案**根本不同**：

| | 本方案（Oasis 3，原厂栈） | k4-eink-video（Kindle 4，内核补丁） |
| --- | --- | --- |
| 刷新单元 | 一次 `mxcfb` 区域更新 = 一帧 | **一个 EPDC 扫描帧** |
| 波形 | 只能用 Amazon 波形文件里的 A2 | **驱动现场合成 1023 帧长 LUT** |
| 像素控制 | 整块 buffer 覆盖 | **working buffer 逐像素**：驱动按 `(目标<<4)\|当前` 查动作表，每扫描帧推一步 |
| 控制通道 | `/dev/fb0` + mxcfb ioctl | 补丁新增 `/dev/k4-epdc-wb`（START / WAIT_FRAME / STOP + mmap） |
| 需要什么 | 越狱 + KUAL python3 | **匹配的 EPDC 补丁、面板波形、自定义内核** |

**能不能搬到 Oasis 3？** 关键障碍是硬件不同代：

| | Kindle 4 NT | Oasis 3 |
| --- | --- | --- |
| SoC | i.MX50 | **i.MX7D**（`fsl,imx7d-zelda`） |
| EPDC | EPDC v1 | **EPDC v2**（驱动 `imx_epdc_v2_fb`，`fsl,imx7d-epdc`） |
| 内核 | 主线 6.6.157 | **Amazon 4.1.15-lab126** |
| LUT / 寄存器 | 按 i.MX50 RM 24.3.8 | **布局不同，要按 i.MX7D RM 重写** |

也就是说，那个补丁是给**另一代 EPDC、另一个内核**写的。搬过来不是改几个宏，
而是**针对 Amazon 的 4.1.15 内核给 EPDC v2 重写一套补丁**，然后**给 Oasis 3 编一个自定义内核并刷进去**。
这是另一个量级的工程（需要 Amazon 的 GPL 内核源码 + 匹配的工具链 + 刷机风险）。

**一个可能的中间路线**（**已经在真机上验证了前半段**）：这台机器的 `/dev/mem` 存在且
**`CONFIG_STRICT_DEVMEM` 没有开**，EPDC 寄存器块在物理地址 `0x306f0000`（size `0x10000`）。

更要紧的是：**Oasis 3 的 EPDC v2 本身就有 working buffer，而且和 K4 是同一套结构**。
下面是真机只读验证的结果（读 DDR 不碰控制器，零风险）：

| 项 | 实测值 |
| --- | --- |
| 设备树 | `epdc@306f0000` 节点里有 `reserved-working-buffer = <&epdc_reserved>` |
| 预留区 | `epdc_reserved`：**物理 `0x9c000000`，大小 `0x500000`（5 MB）** |
| `/proc/iomem` | `80000000-9bffffff` 和 `9c500000-9fffffff` 是 System RAM，**中间 `9c000000-9c4fffff` 被挖掉** |
| 是否真在用 | 画一个 500×320 的矩形后，该区域**恰好 160000 个 16 位单元变化**（= 500×320，一个不多） |
| 内存布局 | **stride = 1264 单元/行**（紧排），变化范围正好是所画矩形的行列范围 |
| 值格式 | `0x60f0` 出现 **100800 次**（= 内层白框 420×240），`0x6000` **59200 次**（= 外层黑底） |

值格式与 K4 文档一致（bit15:12 = LUT 号，bit11 = partial 标记，bit7:4 = 目标灰度，bit3:0 = 当前灰度）：
`0x60f0` 就是「LUT6 / 目标 15（白）/ 当前 0（黑）」，正是那圈白框。
5 MB 减去 `1264×1680×2 = 4250400` 字节，**还剩约 0.95 MB 空闲**，足够放一张自合成 LUT
（K4 用 1023 帧 × 256 字节 ≈ 262 KB）。

另外，K4 文档提到"读寄存器前必须保持 EPDC 上电"——这台机器有正规解法：
EPDC 的 **runtime PM 控制接口**是 `/sys/devices/platform/soc/30400000.aips-bus/306f0000.epdc/power/control`，
默认 `auto` / 当前 `runtime_status = suspended`，把它写成 `on` 就能强制常供电再做寄存器操作。

**结论**：K4 那套"思想"的**硬件基础在 Oasis 3 上确实存在**，缺的只有最后一块——
一张**常驻的长 LUT** + 一个**不随每帧结束的会话**。补齐它有两条路：

1. **内核补丁**：像 K4 那样新增一个字符设备暴露会话接口。要针对 Amazon 4.1.15 + EPDC v2 重写，
   且要给 Oasis 3 编自定义内核并刷入 —— 工程量最大，但最稳。
2. **用户态 `/dev/mem`**：自己把合成的 LUT 写进 EPDC（或指向 DDR 里的自建表）、编程相关寄存器、
   然后靠 WB 逐帧喂目标值。**不需要编内核**，但要逆向 EPDC v2 的 LUT 格式与寄存器，
   而且驱动才是控制器的主人，并发访问会打架。

> 📌 **后续进展已经单独成文**：[18 EPDC 只读侦察与交接](18-epdc-recon-and-handover.md)。
> 那里有完整的 EPDC v2 寄存器表、LUT/波形在 DDR 里的布局、**真机只读侦察的结果**
> （`EPDC_WB_ADDR = 0x9c000000`、`EPDC_WVADDR = 0x92800000`、`EPDC_VERSION` 实测 rev=30 等），
> 以及"要接着往下做该从哪一步开始"。**想推进这条路，看 18 而不是这一节。**

⚠️ 无论哪条路，都不建议在主力机上盲试：寄存器盲读有读清（read-clear）风险，
盲写可能把显示控制器搞挂；而且 K4 文档自己就写了合成 LUT **没有直流平衡，
长期残影和面板寿命影响未验证**。真要推进，**第一步必须是只读侦察**（先 `power/control = on` 保持上电，
再按已知寄存器表读，不写任何一个寄存器）。

## 9 已知限制

- **有上限就是有上限**：A2 的 ~100 ms 固定开销决定了 ~9.9 fps 天花板，换尺寸只能在线内滑动。
- **无声**。这台 Oasis 3 没有声卡（`/dev/snd` 不存在，`com.lab126.btService isAudibleAvailable = 0`），
  Bad Apple 只能静音播放。要和外部音频对齐，用 `--fps` 控制节奏后手动同步起播。
- **残影**：A2/DU 会累积残影，靠 `--gc-every` 定期 GC16 全刷压掉（默认每 60 帧，一次约 365 ms）。
  间隔越小越干净、越慢。
- **会丢掉按键/触摸打断**：默认不响应输入（避免误触中断），需要打断加 `--exit-on-input`。
- **不要同时开两个播放器**：会互相抢屏幕。`fbvideo_play` 会先停掉已有进程。
- **系统重绘会冲掉画面**，见第 6 节。

## 10 参考

- [FBInk](https://github.com/NiLuJe/FBInk)（本方案用的底层库；波形耗时与 API 定义见 `fbink.h`）
- [py-fbink](https://github.com/NiLuJe/py-fbink)（Python cffi 绑定，设备上已随 KUAL python3 扩展安装）
- [qwert-Xx/kindle4nt-eink-video](https://github.com/qwert-Xx/kindle4nt-eink-video)（K4 的 WB 逐像素直驱，第 8 节的对比对象）
- [qwert-Xx/kindle4nt-linux](https://github.com/qwert-Xx/kindle4nt-linux)（K4 的主线 Linux 移植与其补丁系列）
- 本仓库 [15 WAF 与 mesquite](15-wafs-and-mesquite.md)、[16 常驻网页应用](16-webapp-waf.md)（另一条 UI 路线）
