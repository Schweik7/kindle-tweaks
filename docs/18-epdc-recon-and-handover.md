# 18 EPDC 直驱侦察与工作交接

> **这份文档是写给"接手的 AI / 下一个会话的我自己"的。** 目标：读完这一份就能接着干，
> 不用重新摸索、不用重跑已经做过的实测、不踩已经踩过的坑。
>
> 当前状态一句话：**墨水屏视频播放已经能用（A2 波形 ~8.6 fps）；只读侦察、WB 重采样实验、
> 活跃 WRF/advanced 结构解析、low-first packing 证据链、以及"自造 1023 相长 LUT 上机实测"
> 都已完成 —— 长 LUT 真的能跑（1023 相 = 12.1 秒）。卡点已从"能不能跑"变成两件新事：
> ① mxcfb 索引与 blob mode 是置换表（不能按同名改）；② 驱动有约 7.5 秒完成超时。**
> 下一步要造的是**带真实 action 的长 LUT**（全零 no-op 不驱动像素）。

---

## 1 现状速览

| 工作 | 状态 | 位置 |
| --- | --- | --- |
| 墨水屏视频播放（fbvideo） | ✅ **完成可用**：能转码、能在 KUAL 里选视频播放、能暂停/继续/停止 | [extensions/kindletweaks/fbvideo/](../extensions/kindletweaks/fbvideo/)、[tools/make_ktvid.py](../tools/make_ktvid.py)、[17 墨水屏视频播放](17-fbvideo-eink-video.md) |
| EPDC v2 寄存器/机构调研（纯资料） | ✅ 完成，有完整寄存器表与 LUT 布局 | 本文件第 5 节汇总 |
| EPDC 只读侦察（真机） | ✅ **完成**：寄存器、working buffer、波形 blob 与 TCE 时序均已确认 | 本文件第 4 节 |
| 波形 blob 解码 / 扫描帧率 | ✅ **完成**：10 个标准 mode、14 个温度档；扫描基准 **54.155 Hz（⚠ 但与实测的 84.5 Hz 相位速率不符，见 4.6）** | [extensions/kindletweaks/tools/epdc_recon.py](../extensions/kindletweaks/tools/epdc_recon.py) |
| 判定"EPDC 是否在同一 update 中重采样 WB" | ✅ **真机成立**：在飞更新中改一个像素 target，current 随新 target | 见第 5.3 节与第 6 节 P2 |
| 自造长 LUT 上机实测 | ✅ **完成**：blob mode 7 改 1023 相 → **mxcfb 索引 10 耗时 12.111 秒**（1 相时 17.74 ms）；设备已恢复原厂 | 见第 4.6 节 |
| mxcfb 索引 ↔ blob mode 映射 | ⚠️ **确认是置换表，不是同名对应**（索引 10 → blob mode 7）；完整映射未解 | 见第 4.6 节 |
| 自合成**带 action** 的长 LUT | ⬜ **未开始**（全零 no-op 不驱动像素，这一步才是真正推像素） | 见第 4.6 节"下一步" |
| 写 EPDC 寄存器 | ❌ **仍未碰过，未经用户同意前不要碰** | 见第 7 节 |

**顺带实测确认的两件事**（原先只是文档推断）：
- **WAF 注册熬过了重启**：一次真机重启后，`appreg.db` 里的 `com.kindletweaks` 注册仍在
  （`webapp list` 仍列出 `sample`），`/mnt/us/videos/` 与播放器也都在。详见 [16 常驻网页应用](16-webapp-waf.md)。
- **`preventScreenSaver` / EPDC `power/control` 的 atexit 收尾是有效的**：即使脚本中途被中断，
  重启后复查两者都回到了正常值（`0` / `auto`）。

---

## 2 打印机一次事故：白屏（必读）

**发生过一次白屏，是我造成的，不是硬件损坏。** 复盘：

- 为了"保证读寄存器时 EPDC 处于上电状态"，我让一次显示更新保持"在飞"。
- 我用的是一张 **1264×1680 的整屏纯白图**（`np.full(SH*SW, 255)`）配 GC16 + flashing。
- 脚本被中断（工具调用被中止），进程没来得及执行收尾 → **屏幕就停在那一帧纯白上**。
- 用户看到"白屏"，重启设备后恢复。

**结论与纪律**：
1. **绝对不要用整屏图案做"保活"**。现在的 `epdc_recon.py` 已改成只画 **64×64 在 (8,8)** 的一小块。
2. 任何会改屏幕的脚本都要有 `atexit`/`finally` 收尾：还原 `preventScreenSaver`、
   还原 runtime PM、并**切回主页让系统重绘**（`lipc-set-prop com.lab126.appmgrd.start app://com.lab126.booklet.home`）。
3. fbink 画的内容会一直留在屏上（它就是 framebuffer），**没有任何自动超时**。
   被 kill -9 时收尾不会运行 —— 所以测试图案要小、要可自愈。

---

## 3 Part A：墨水屏视频播放（已完成，可正常使用）

### 3.1 怎么用

KUAL →「墨水屏视频播放」，菜单结构：

```
墨水屏视频播放 [3 个｜未播放]
  暂停 / 继续（点一下切换）        <- 对正在播的那个生效
  停止播放
  播放状态：...
  重新扫描视频目录
  ── 下面点一个就播（自动扫描）──
  badapple_800 (9649 KB)   ›  播放（A2 推荐）/（DU）/（GC16）
  badapple_full (16190 KB) ›  ...
  counter_c (59 KB)        ›  ...
```

SSH：

```sh
E=/mnt/us/extensions/kindletweaks
cd $E/fbvideo
LD_LIBRARY_PATH=/mnt/us/python3/lib /mnt/us/python3/bin/python3 play.py /mnt/us/videos/badapple_800.ktvid
sh $E/tweak.sh fbvideo status      # 在放什么、第几帧、什么波形
sh $E/tweak.sh fbvideo toggle      # 暂停/继续
sh $E/tweak.sh fbvideo stop        # 停止
```

**设备上直接控制**（默认行为）：点触摸屏 = 暂停/继续（暂停时中央显示「暂停 12/1755」）；
按翻页键 = 停止并回主页；电源键不抢。

### 3.2 实测性能（不要重测）

波形耗时（640×480 区域，真机实测）：

| 波形 | ms/帧 | fps | 说明 |
| --- | --- | --- | --- |
| **A2（索引 4）** | **115** | **8.64** | 唯一快的**真实**波形；1bit 内容的本命 |
| DU（1） | 208 | 4.8 | |
| GL16（5） | 295 | 3.4 | |
| GC16（2） | 365 | 2.7 | 最干净 |
| ~~DU4（10）~~ | ~~37~~ | ~~27~~ | ☠️ **假货：驱动丢弃更新，画面一动不动**（肉眼确认） |

面积 vs 帧率（A2，实测拟合）：

```
t ≈ 100.5 ms + 4.938e-5 × 像素数      → 理论上限 ≈ 9.9 fps（区域缩到 0 也省不掉那 100ms）
```

| 尺寸 | fps | 占屏 |
| --- | --- | --- |
| 640×480 | 8.64 | 51%×29% |
| **800×600** | **8.05** | 63%×36%（**推荐**） |
| 1012×759 | 7.22 | 80%×45% |
| 1264×948 | 6.26 | 100%×56% |

**全部 13 个 mxcfb 波形索引都枚举过**：只有索引 10 快得反常（=假货），其它都落在 147~411ms。
**原厂波形里没有更快的模式，A2 就是天花板。**

### 3.3 已验证的坑（都在 docs/17 里）

- **DU4 是陷阱**：截图无法证伪（`/usr/sbin/screenshot` 读的是 framebuffer，而 fbink 就是写 framebuffer，
  framebuffer 里永远是我们刚写的内容）。**唯一裁判是肉眼。**
- **系统重绘会冲掉 fbink 内容**：`restart kppmainapp` 后实测区域墨色 87.3% → 5.1%。
  所以播放器自己压屏保、结束时切回主页。
- **比对极性**：`.ktvid` 里 **1=白**，截图侧 `(px<128)` 是 **1=暗**。搞反会得出"差异 13~30%"的假数据
  （我曾据此误判"有残影"，实际是 **0.00% 逐像素一致**）。
- **帧率要和尺寸匹配**，否则播放时长会失真（800×600 用 `--fps 8`，1264×948 用 `--fps 6`）。

---

## 4 Part B：EPDC 只读侦察（已完成的部分）

### 4.1 方法（怎么在安全的条件下读寄存器）

驱动 `pwrdown_delay = 0`：**没有排队更新时它立刻 `EPDC_CTRL.CLKGATE` + 断 VCOM/display/3p3**。
而 `CLKGATE` 置位时读任何 EPDC 寄存器都无意义（可能总线错误）。所以：

1. `echo on > .../306f0000.epdc/power/control`（内核正规 runtime PM 接口，用完还原 `auto`）
2. **触发一次小区域 fbink 更新并让它"在飞"**，在读之前确认 `EPDC_CTRL.CLKGATE == 0`
3. 只读"基寄存器"白名单（见第 5 节），**避开所有 `+4/+8/+0xC` 的 `_SET/_CLEAR/_TOGGLE` 别名**（写语义）
4. 读 DDR（working buffer、波形 blob）完全安全

脚本已固化：[extensions/kindletweaks/tools/epdc_recon.py](../extensions/kindletweaks/tools/epdc_recon.py)

```sh
LD_LIBRARY_PATH=/mnt/us/python3/lib PYTHONIOENCODING=utf-8 \
  /mnt/us/python3/bin/python3.9 /mnt/us/extensions/kindletweaks/tools/epdc_recon.py
```

### 4.2 真机读到的寄存器（📌 这是已确证的数据）

读的时候正在跑一次 `(40,40) 320×240` 的 GC16 更新，所以 `UPD_CORD/UPD_SIZE/LUT_SEL`
正好对得上，可以交叉验证读到的值是真的。

| 寄存器 | 读到的值 | 含义 |
| --- | --- | --- |
| `EPDC_VERSION` (0x7F0) | **0x03000000** → rev **30** | **EPDC v2，64 个 LUT 槽**。公开源码查不到这个数值，是实读出来的 |
| `EPDC_CTRL` (0x000) | 0x00000040 | bit6 = `UPD_DATA_SWIZZLE_ALL_BYTES_SWAP`；**SFTRST=0 CLKGATE=0**（已上电） |
| **`EPDC_WB_ADDR`** (0x030) | **0x9c000000** | **= 设备树 `reserved-working-buffer` 那块 5MB** ✅ 完全对上 |
| `EPDC_WB_ADDR_TCE` (0x010) | 0x9c000000 | TCE 扫描用同一地址（驱动写同一个值） |
| **`EPDC_WVADDR`** (0x020) | **0x92800000** | **波形/LUT blob 在 DDR 里的真实地址** |
| `EPDC_RES` (0x040) | 0x069004f0 | HORIZONTAL=**1264** VERTICAL=**1680** ✅ |
| `EPDC_FORMAT` (0x050) | 0x00002000 | [13:12]=0b10 → **`WB_TYPE_WB_EXTERNAL16`**（WB 在外部 DDR、16 位/槽） |
| `EPDC_TEMP` (0x1A0) | 8 | 当前温度档索引 |
| `EPDC_UPD_CTRL` (0x160) | 0x80180201 / 0x801a0201 | USE_FIXED=1、**LUT_SEL=24 / 26**、**WAVEFORM_MODE=2(GC16)**、FULL=1 |
| `EPDC_UPD_CORD` (0x120) | 0x00280028 | X=40 Y=40 ✅ 正是我们画的位置 |
| `EPDC_UPD_SIZE` (0x140) | 0x00f00140 | W=**320** H=**240** ✅ |
| `EPDC_UPD_ADDR`/`UPD_STRIDE` | 0 / 0 | standard mode 下恒为 0（EPDC 直接从外部 WB 取像素） |
| `EPDC_IRQ` (0x420) | 0x00280000 | bit21 `TCE_IDLE`=1, bit19 `FRAME_END`=1 |
| **`EPDC_STATUS_LUTS`** (0x440) | **0x04000000** | **bit26 正在跑** —— 与 `LUT_SEL=26` 吻合 ✅ |
| `EPDC_STATUS_NEXTLUT` (0x460) | 0x0000013f | NEXT_LUT_VALID=1, NEXT_LUT=**63** |
| `EPDC_STATUS` (0x4A0) | 0x00000008 | UPD_VOID=1 |
| `EPDC_DEBUG_LUT` (0x530) | 0x00000000 | 没在用（要先用 `EPDC_DEBUG.DEBUG_LUT_SEL` 选 LUT） |

### 4.3 working buffer 已独立证实（另一条证据链）

只读 DDR 做的事（**零风险**）：dump `0x9c000000` → 画一个已知矩形 → 再 dump → 对比。

- 画 500×320 矩形 → **恰好 160000 个 16 位单元变化**（一个不多）
- 变化范围**正好是行 700..1019、列 260..759**，**stride = 1264 单元/行**（紧排）
- 内层白框 420×240 → 值 `0x60f0` 出现 **100800 次**；外层黑底 → `0x6000` 出现 **59200 次**
- 位域与 K4 文档一致：bit15:12=LUT 号，bit11=partial，**bit7:4=目标灰度，bit3:0=当前灰度**
- 驱动初始化写的是 `0x00F0`（白），与读到的稳态值一致

`/proc/iomem` 也印证：`80000000-9bffffff` 和 `9c500000-9fffffff` 是 System RAM，
**中间 `9c000000-9c4fffff` 被挖掉**（5MB，`working_buffer_size = xres*yres*2 = 4250400` 字节，还剩 ~0.95MB）。

### 4.4 原厂波形 blob 已解出（P0 完成）

先纠正一个很容易混淆的层次：**`EPDC_WVADDR` 指向的活跃 DMA blob 不是根文件系统里的
`epdc_ED070KC1.fw`**。启动日志明确记录：

```
waveform=400_A053_HE2901_ED070KC3U1_TC.wrf.gz
read_mnt_wfm_v2: /mnt/wfm/waveform_to_use/400_A053_...wrf.gz
allocate 2475341 byte ... for waveform
Waveform file supports advanced algorithms
```

这个临时目录在开机完成后已经消失；`/proc/eink/waveform/source` 报 `built-in`，`info` 报
`bit depth=0x05`、原始文件大小 `0x00076163`，模块里导出的 `panel_get_waveform*` 符号也表明
源数据来自面板内置 flash。根文件系统的 `/lib/firmware/imx/epdc/epdc_ED070KC1.fw`
（3,624,948 字节，SHA-256 `7013686a...c9f23`）是 fallback；它与活跃 blob 的前 4096 字节
实比不相同。

已经从 `/dev/mmcblk2p4` **只读挂载**并复制出原始活跃文件，复制后立刻卸载：

- `400_A053_HE2901_ED070KC3U1_TC.wrf.gz`：101,625 B，SHA-256
  `e97cd46ac87310f3ed24fd5a82642d7365c04ec81b6baaada43bced4d4783020`；
- 解压后的 WRF：2,475,404 B，SHA-256
  `6daf8d6373002e12240d52c3ec45ee32ea96e4f7e85d0fdeb66805f1d1224b0d`；
- 其 payload 起点是 `48-byte header + 14-byte temperature table + 1-byte padding = 0x3f`；
- **`WRF[0x3f:]` 与 2,475,341 B 活跃 DMA blob 逐字节完全相等**。

这把“loader 如何转换 WRF”的问题收紧为：gzip 解压后只剥去 63 B 文件前缀，标准波形、VCD、
ACD 与 XSWI 均按原字节进入 DMA；没有额外的 phase 解压或 nibble 重排。

fallback `.fw` 的 48 字节文件头是：

```
luts=0x04  mc=9  trc=13
温度边界：0 3 6 9 12 15 18 21 24 27 30 33 38 43
```

活跃 blob 自身仍可独立推出 **10 个标准 mode × 14 个温度档**：开头第一个 `uint64` 为
112，即一共有 14 个顶层指针；mode 表从 `0x70` 开始并以 `0x70 = 14×8` 连续递增到
mode 9。多出的 4 个不是 mode 10..13，而是
**advanced algorithm 指针**。早先把 112/8 直接解释成“14 个 mode”是错的，会沿着非 mode
数据继续解析并越界。

各标准 mode 的 `frame_count` 如下；这是每个 `(mode,temp)` 数据块开头的 `uint64`，读取它
不依赖后续 LUT 项的具体编码：

| mode | 常见名字 | 14 个温度档的 `frame_count` |
| ---: | --- | --- |
| 0 | INIT | 109 93 81 71 61 111 95 83 75 67 63 59 55 51 |
| 1 | DU | 53 45 39 34 29 25 21 18 16 14 13 12 11 10 |
| 2 | GC16 | 103 87 75 65 56 47 39 34 29 29 29 29 29 29 |
| 3 | GC4 | 80 68 58 51 43 37 31 26 23 23 23 23 23 23 |
| 4 | A2 / GLR16 | 80 68 58 51 43 37 31 26 23 23 23 23 23 23 |
| 5 | GL16 / GLD16 | 103 87 75 65 56 47 39 34 29 29 29 29 29 29 |
| 6 | 未命名 | 28 25 23 20 17 14 12 10 8 8 8 8 8 8 |
| 7 | 未命名 | 1 1 1 1 1 1 1 1 1 1 1 1 1 1 |
| 8 | 未命名 | 103 87 75 65 56 47 39 34 29 29 29 29 29 29 |
| 9 | 未命名 | 103 87 75 65 56 47 39 34 29 29 29 29 29 29 |

标准 mode 中最长的是 **111**（mode 0、温度档 5）。一次测试时 `EPDC_TEMP=9`，对应
INIT/DU/GC16/GC4/A2/GL16/mode6 的表头值依次为 67/14/29/23/23/29/8。

活跃 blob 的 107 组相邻唯一数据块全部严格满足 **`span = 8 + frame_count × 512`**。
512 B 正好容纳 `32×32` 个 4-bit action，因此与 `/proc` 报告的 5-bit/32-state 波形完全吻合：
这里的“5-bit”是 current/target **状态数**，每个电压 action 本身仍占一个 nibble。

[Glider/e-ink](https://github.com/qubitops/e-ink) 项目里的 `wbf_waveform_dump` 已经支持 5-bit 的
32×32 表和 4-bit action；它按“target 外层、source 内层”展开，并把第一个/偶数 source state
放在**低 nibble**、下一个放在高 nibble。`mxc_waveform_dump` 也按低 nibble 在先读取。旧的
16×16 `mxc_waveform_asm` 确实反向打包，但它不支持本机的 5-bit/32-state 格式，不能作为本机
编码器。结合原始 WRF payload 与 DMA blob 逐字节相等、驱动设置 `LUT_DATA_SWIZZLE=NO_SWAP`，
当前选择 **low-first** 作为 5-bit WRF 的格式结论；`high-first` 仅保留为诊断对照。这个结论尚未
通过加载自合成波形做硬件注入验证。

### 4.5 面板扫描基准已确定（P1 完成）

`FRAME_END` 是会被内核 ISR 清除的中断状态位，不是用户态可可靠计数的边沿；Amazon/NXP 的
EPDC v2 驱动也没有实现 `MXCFB_WAIT_FOR_VSYNC`。可靠方法是按 i.MX7D Reference Manual
13.6.4.22/25/26/27，从 pixel clock 与 TCE 时序直接计算：

```
epdc_pixel_root_clk = 160,000,000 Hz
H = LINE_SYNC 86 + LINE_BEGIN 33 + active 1264 + LINE_END 358 = 1741 pixel clocks
V = FRAME_SYNC 1 + FRAME_BEGIN 4 + active 1680 + FRAME_END 12 = 1697 lines
scan = 160,000,000 / (1741 × 1697) = 54.1551009 Hz
period = 18.46548 ms
```

用 64×64 黑白交替块分别跑原厂 mode，完成时间都落在整数个扫描周期附近，交叉验证了这个结果：

| mode | 表头 `frame_count` | 完成时间 | 折合扫描场 |
| ---: | ---: | ---: | ---: |
| INIT | 67 | 463.00 ms | 25 |
| DU | 14 | 166.19 ms | 9 |
| GC16 | 29 | 342.63 ms | 19 |
| GC4 | 23 | 342.78 ms | 19 |
| A2 | 23 | 95.64 ms | 5 |
| GL16 | 29 | 272.06 ms | 15 |
| mode6 | 8 | 272.30 ms | 15 |

这也证明：在 advanced/AF 固件里，数据块开头的 `frame_count` **不能当作等时扫描场数**。
曾做过的 `完成时间 ~ frame_count` 线性拟合得出 225.8 Hz，是错误方法，已经从脚本删除。

### 4.6 自造长 LUT 已上机实测（P3 前半段完成）

**做法：走官方安装路径 + 完整可回滚备份**

- 波形分区 `/dev/mmcblk2p4`，**FAT32，4 MB**，目录：`waveform_to_use/`（活跃波形）、
  `waveform_storage/`（**空**）、`images/`（开机图 / hibernation 图）
- 活跃波形文件名 = 驱动模块参数 `waveform` 的值：`400_A053_HE2901_ED070KC3U1_TC.wrf.gz`
- 备份三件套（都在设备 `/mnt/us/waveform_backup/`）：**整分区镜像** `mmcblk2p4.orig.img`
  （4194304 B，sha256 `3140c8ee…`）、原文件 `….wrf.gz.orig`（sha256 `e97cd46a…`，与本地提取副本三方一致）、
  一键回滚脚本 `rollback.sh`
- 安装步骤（等价于 `/usr/sbin/wfm_update` 的做法，但绕开它的 **Amazon 签名校验**）：
  挂载 p4 → 清空 `waveform_to_use/` → 拷入**同名**文件 → `sync` → 卸载
- ⚠️ **不要用 `/usr/sbin/wfm_mount`**：它挂载失败时会 `mkdosfs -F 32` **直接格式化分区**。
  自己 `mount /dev/mmcblk2p4 /mnt/wfm` 更安全。
- ⚠️ `/usr/sbin/wfm_forceupdate` 把文件拷到 `/mnt/wfm/waveform_to_use.gz`（**分区根目录的单个文件**），
  而 v2 loader 读的是 `/mnt/wfm/waveform_to_use/<名字>`（**目录**）—— 两者不通，别指望它。
- 重启后内核日志确认新波形被采纳：
  `open file … ok size=95974`（原 101625）、`allocate 2999128 byte @ …`（原 2475341）、
  `Waveform file supports advanced algorithms`（解析无报错）

**实测结果**

| blob mode 7 的相数 | mxcfb 索引 10 的耗时 | 同轮其它索引 |
| ---: | ---: | --- |
| 1（原厂） | **17.74 ms** | 索引 2 = 353 ms |
| 1023（自造） | **12111.2 ms** | 索引 2 = 353 ms（**完全不受影响**） |

两点拟合：**`t ≈ 5.9 ms + 11.833 ms × 相数`**

**🔴 重大纠正一：mxcfb 的 `waveform_mode` 索引 ≠ blob 里的 mode 序号**

§4.4 / §4.5（以及更早的资料调研）都假设"用户态 `waveform_mode` 原样就是 blob mode 索引"。
**这是错的，两者之间是一张置换表。** 实测扫描 mxcfb 0..17（64×64 块，逐个计时）：

| mxcfb 索引 | 耗时 | | mxcfb 索引 | 耗时 |
| ---: | ---: | --- | ---: | ---: |
| 0 / 1 / 16 / 17 | ~177 ms | | 9 | 282 ms |
| 2 / 3 / 7 / 8 / 13 / 14 | ~353 ms | | **10** | **12111 ms ← 就是 blob mode 7** |
| 4 | 106 ms | | 11 / 12 | 282 ms |
| 6 | 282 ms | | 15 | 800 ms |

**后果**：§4.5 那张"各 mode 的 `frame_count` ↔ 完成时间"表是**按同名索引硬配出来的，不能采信**
（例如 mxcfb 4 只有 106 ms，若它真是 blob mode 4 的 23 相就该是 ~280 ms）。
**任何"改某个 mode 看效果"的实验，都必须先确定索引映射。**

**🔴 重大纠正二：驱动有约 7.5 秒的完成超时**

12.1 秒的长 LUT 触发了超时与恢复流程：

```
[FBInk] [wait_for_complete_kindle] MXCFB_WAIT_FOR_UPDATE_COMPLETE: Connection timed out!
imx_epdc_v2_fb: Timed out waiting for update completion
imx_epdc_v2_fb: In epdc_recover routine.
imx_epdc_v2_fb:  LUT_status=0x00000000/0x00000000
```

设备**没有坏**（恢复流程跑完即恢复正常，之后索引 2 仍是干净的 353 ms），但这意味着：
**走正常 mxcfb 路径时，单张 LUT 最多只能跑到约 7.5 秒。** 想要更长的连续会话，只有两条路：
绕过驱动直接操作 `/dev/mem`（危险），或把相数压到超时以内。

**❓ 未解：实测相位速率 84.5 Hz 与算出的扫描率 54.155 Hz 差 1.5625 倍**

- 实测（本次唯一一次**干净的**索引↔mode 配对）：**11.833 ms/相 → 84.51 Hz**
- §4.5 按 160 MHz 像素时钟算出的是 **54.155 Hz（18.465 ms/场）**
- 内核时钟框架确认 `epdc_pixel_root_clk = 160000000`（`epdc_pixel_post_div` = 480/3），
  所以 160 MHz 这个数**是对的**
- 两者之比恰好 **1.5625 = 250/160**。物理上"1 相 = 1 个扫描场"更合理，
  如果这样，则扫描率应是 ~84.5 Hz，说明 §4.5 算式里 H 或 V 的总数被高估了 1.5625 倍
  （或 `PIXELS_PER_SDCLK` 也参与行时间计算，而非只影响像素打包）
- **84.6 Hz 与 K4 项目报的 84.6 fps 完全一致**，这不像巧合，值得优先查清

**运维要点（本轮新增）**

- **`EPDC_WVADDR` 每次启动都会变**：观察到 `0x92800000` 和 `0xa3793000`。
  所以 `epdc_blob_dump.py` 里硬编码的 `0x92800000` **在别的启动里会读错内存**。
  正确做法：从 dmesg 的 `allocate N byte @ XXXXXXXX for waveform` 取真实地址
  （或按第 4.1 节的窗口式方法读寄存器）。
- `/proc/eink/waveform/working_buffer_addr` = 2617245696 = **`0x9C000000`** —— 官方接口，
  可用来确认 WB 地址而不用碰 MMIO。
- `/proc/eink/waveform/record` 记录格式
  `timestamp: [top left width height] wave upda temp flag dither marker`；
  长 LUT 期间读它会返回 `try again after update done`（`wave` 列的确切含义待查）。
- `/proc/eink/waveform/info` 里的 `tuning bias` 会变（实测 0x04 → 0x05），
  但它**不是**文件头字段 —— 文件头 63 字节逐字节相同，`tuning bias` 是驱动运行时算的。

**本轮结束时设备状态**：已完整恢复原厂波形（`open file size=101625`、`allocate 2475341`、
索引 10 回到 17.74 ms）并重启验证；`preventScreenSaver=0`、EPDC `auto/suspended`、无遗留进程。
备份与回滚脚本保留在 `/mnt/us/waveform_backup/`。

**下一步（P3 后半段）**

1. **补相数-时长曲线**：1 / 256 / 512 / 1023 相各测一次，确认线性与截距，
   并定出"安全相数上限"（对应驱动 7.5 s 超时 → 约 630 相）
2. **造一张带真实 action 的长 LUT**：全零 no-op 只证明"能跑很久"，但它**不驱动像素**。
   要真正逐帧推像素，表里必须有 VPOS/VNEG
   （第三方资料：`1`=推向黑、`2`=推向白、`0/3`=不驱动；**NXP 原文未取得**），
   并且整段必须**净直流为零**（K4 作者自己都没验证长期残影与面板寿命）
3. 然后才能做 P2 的完整版：**在长 LUT 运行期间改 WB 的 target**，看像素是否真的跟着走
   （P2 已证明硬件会重采样 WB，但那张表有真实 action；全零表下改 target 不会有任何效果）

---

## 5 EPDC v2 机构（纯资料调研结论，省得重查）

### 5.1 寄存器表（偏移相对 `0x306f0000`）

来源：NXP `linux-imx` 分支 `imx_4.9.11_1.0.0_ga` 的 `drivers/video/fbdev/mxc/epdc_v2_regs.h`
（与 Kindle 的 4.1.15-lab126 同代，两个分支的该头文件字节完全相同）。
**EPDC v2 从未进入 mainline，mainline 只有 EPDC v1。**

| 宏 | 偏移 | 关键位域 | 用途 |
| --- | --- | --- | --- |
| `EPDC_CTRL` | 0x000 | [31]SFTRST [30]**CLKGATE** [8]SRAM_POWERDOWN [7:6]UPD_DATA_SWIZZLE | 全局控制 |
| `EPDC_WB_ADDR_TCE` | 0x010 | 32 位物理地址 | TCE 扫描用 WB 地址（v2 特有） |
| `EPDC_WVADDR` | 0x020 | 32 位物理地址 | **波形/LUT blob 的 DDR 基址** |
| `EPDC_WB_ADDR` | 0x030 | 32 位物理地址 | **working buffer 基址** |
| `EPDC_RES` | 0x040 | [28:16]VERTICAL [12:0]HORIZONTAL | 面板分辨率 |
| `EPDC_FORMAT` | 0x050 | [13:12]WB_TYPE [10:8]BUF_PIXEL_FORMAT [2:0]TFT_PIXEL_FORMAT | WB 类型/像素格式 |
| `EPDC_WB_FIELD0..3` | 0x060/0x070/0x080/0x090 | [17:16]USE_FIXED [12:8]FROM [7:4]TO [3:0]LEN | 局部刷新域 |
| `EPDC_UPD_ADDR`/`STRIDE`/`CORD`/`SIZE` | 0x100/0x110/0x120/0x140 | — | 更新源/区域 |
| **`EPDC_UPD_CTRL`** | **0x160** | **[31]USE_FIXED [21:16]LUT_SEL [15:8]WAVEFORM_MODE [2]AUTOWV [1]DRY_RUN [0]FULL** | **★ 写它 = 启动一次面板更新** |
| `EPDC_TEMP` | 0x1A0 | 温度档索引 | 选温度档 |
| `EPDC_AUTOWV_LUT` | 0x1C0 | [23:16]DATA [2:0]ADDR | 8 项自动波形表（写端口） |
| `EPDC_TCE_*` | 0x200~0x320 | HSCAN/VSCAN/CTRL/SDCFG… | 时序控制器（决定帧率） |
| `EPDC_IRQ1`/`IRQ2` | 0x3E0/0x3F0 | 每 LUT 一位（完成） | RO；**仅在时钟明确开启时读** |
| `EPDC_IRQ` | 0x420 | [23]PWR [22]UPD_DONE [21]TCE_IDLE [20]BUS_ERR **[19]FRAME_END** [16]WB_CMPLT | RO；**仅在时钟明确开启时读** |
| `EPDC_STATUS_LUTS`/`LUTS2` | 0x440/0x450 | bit n = LUT n 正在跑（bit0 恒 1） | RO；**仅在时钟明确开启时读** |
| `EPDC_STATUS_NEXTLUT` | 0x460 | [8]VALID [5:0]NEXT_LUT | RO |
| `EPDC_STATUS` | 0x4A0 | [3]UPD_VOID [2]LUTS_UNDERRUN [1]LUTS_BUSY [0]WB_BUSY | RO |
| **`EPDC_DEBUG_LUT`** | **0x530** | **[25:16]LUTADDR [14:5]FRAME [4:0]STATEMACHINE** | **★ 唯一能观察 LUT 运行的口子** |
| `EPDC_GPIO` | 0x700 | [8]PWRSTAT [6]PWRCOM [5:2]PWRCTRL | 面板电源/VCOM（**写可能真伤屏**） |
| `EPDC_VERSION` | 0x7F0 | [31:24]MAJOR [23:16]MINOR [15:0]STEP | RO |

**明确不存在**：`EPDC_LUT_CTRL`、`EPDC_LUT_STATUS`、`EPDC_LUTn_ADDR`、`EPDC_LUT_DATA`、`EPDC_UPD_DATA`。
→ **EPDC v1/v2 都没有"LUT 数据写入端口"寄存器。**

每个基寄存器在 `+4/+8/+0xC` 都有 `_SET`/`_CLEAR`/`_TOGGLE` 别名 —— **那是写语义，别读。**
此外，寄存器本身标成 RO 不代表控制器关钟后仍可安全访问；本机已经两次复现疑似在
`CLKGATE` 后读取 EPDC MMIO 导致整机总线等待。离线/收尾阶段不要映射这段 MMIO。

### 5.2 LUT/波形怎么进 EPDC

驱动**不给 EPDC 写任何 LUT 数据**：整个 `.fw` 经 firmware loader 读入，去掉头 48 字节 + 温度区间表
+ 1 字节 padding 后**整块 memcpy 到一块 DMA 内存**，然后把首地址写进 `EPDC_WVADDR`。
运行时只写三个东西：

| 寄存器 | 写什么 |
| --- | --- |
| `EPDC_WVADDR` (0x020) | 波形 DDR 缓冲区物理基址 |
| `EPDC_TEMP` (0x1A0) | 温度档索引 |
| `EPDC_UPD_CTRL` (0x160) | `LUT_SEL[21:16]` 选硬件 LUT 槽；`WAVEFORM_MODE[15:8]` 选波形 mode |

`(温度, mode) → mode 偏移表 → 温度偏移表 → 波形块 frame_count(uint64) → 逐帧 LUT`
**这套寻址是 EPDC 硬件做的**，驱动把 blob 当不透明数据。

**本机波形 blob 在 DDR 里的已验证布局**（`EPDC_WVADDR` 指向的起点）：

```
+0x00   top_offset_table : 14 × uint64 LE
        前 mc+1=10 项是标准 mode；后 4 项是 advanced algorithm 入口
        每个标准 mode 指向 temp_offset_table : (trc+1)=14 × uint64 LE
        然后每个 (mode,temp) 波形块：
            uint64 LE  frame_count
            紧跟 advanced/AF 编码的数据
```

- 启动日志与 `/proc/eink/waveform/info` 已确认 active WRF 是 advanced、bit depth 5；不能把普通
  v2 的 16×16 / 128 B-per-phase 规则硬套到本机。
- `frame_count`、mode/temp 指针以及 **512 B/phase** 已由活跃 DMA blob 的块跨度交叉验证；这对应
  32×32 个 4-bit action。5-bit WRF 的 nibble 顺序已由格式工具、原始 WRF/DMA 同一性和
  `NO_SWAP` 三条证据确定为 low-first；仍未确定的是 advanced algorithm 各字段的完整运行时语义。
- 根文件系统 `.fw` 是 fallback，与 active WRF 转换出的 DMA blob 不同；分析和自合成必须以
  `EPDC_WVADDR` 的实际布局为准。
- 寄存器里没有独立的 LUT 长度字段；`EPDC_DEBUG_LUT.FRAME` 为 10 bit，因此“单 LUT 最多
  1024 个硬件 frame”目前仍只是上限推测，不能从 `frame_count` 直接换算时长。

### 5.3 TCE 如何读取 WB，以及更新跑完之后会发生什么

i.MX7D Reference Manual 已给出比寄存器名更直接的证据：

- 13.6.3.11.2 明确说 EPDC 有 **WB latency FIFO**，它加载供 TCE 面板刷新使用的 WB pixel data；
  这些像素值被 TCE 用于 LUT lookup。
- 总线请求源表单列 `WB pixel read FIFO0 (refresh)` 与 `FIFO1 (refresh)`；refresh 带宽公式按
  **完整 working buffer × frame rate** 计算。
- FIFO prefill 发生在开始处；手册特别注明顺序 frame-scan 时该预填设置“不起作用”，符合扫描过程
  持续取数而不是一次性锁存整帧。
- `AUTOWV_PAUSE` 的说明还允许软件在 WB processing 之后、LUT loading / panel scan 之前修改 WB。

所以“**TCE 每个扫描场会从外部 WB 读取像素**”已有很强的官方资料支持。P2 真机实验又进一步确认：
同一个 update 已经进入 `target=0/current=f` 的在飞状态后，CPU 把该像素 target 改回 `f`，最终
current 保持 `f`，而不做改写的控制组会正常完成到 `0`。也就是说硬件没有在 update 开始时一次性
锁存整个 WB，扫描期间的后续场仍会采用被改过的像素状态。

- **触发 = 写 `EPDC_UPD_CTRL` (0x160)**，这是唯一的面板动作启动点。
- LUT 跑完：`EPDC_STATUS_LUTS` 对应位清 0、`EPDC_IRQ1/IRQ2` 对应位置 1、槽回收。
- **没有任何 LUT 循环 / 自动重提交机制**：硬件无 loop/repeat 位、无 LUT 重装入口；
  驱动全文只有 3 处 `queue_work`，唯一会"重新提交"的是碰撞重试（且强制改成 `WAVEFORM_MODE_AUTO`）。
- **★ 队列一空驱动就把 EPDC 整个关掉**：`epdc_intr_work_func()` 结尾在队列空时
  `schedule_delayed_work(epdc_done_work, pwrdown_delay)` → `epdc_powerdown()`：
  ```c
  regulator_disable(vcom); regulator_disable(display);
  __raw_writel(EPDC_CTRL_CLKGATE, EPDC_CTRL_SET);
  clk_disable_unprepare(epdc_clk_pix); clk_disable_unprepare(epdc_clk_axi);
  regulator_disable(v3p3);
  ```
  probe 里 `pwrdown_delay = 0` → **立刻掉电**。用户态可用 `MXCFB_SET_PWRDOWN_DELAY` 改，
  `FB_POWERDOWN_DISABLE = -1` 可禁用。**所以"长 LUT 常驻"必须表现为"更新队列永不空"，
  或先禁用自动掉电。**
- **LUT0 是保留槽**（开机 INIT 用），实际可用 **1..63**；**64 个槽可同时跑**。
- WB 不是 CPU 直接写的：standard mode 下由 **PxP 的 WFE-A 引擎**从 framebuffer 算出来写进去
  （`epdc_working_buffer_update()` → `pxp_wfe_a_process()`）。
- advanced 模式初始化时，驱动只额外把 `EPDC_WB_FIELD3` 配成
  `USAGE=PTS, FROM=8, TO=8, LEN=1`；结合实测 WB 的 bit11 `PARTIAL` 标记，这支持“32 个状态由
  4-bit 灰度再加一个上下文位构成”的方向，但目前还不足以证明具体状态编号。nibble packing
  已由 WBF 工具和本机 WRF/DMA 同一性确定为 low-first。

### 5.4 与 K4 方案（qwert-Xx/kindle4nt-eink-video）的对比

| | K4（Kindle 4 NT, i.MX50） | Oasis 3（i.MX7D） |
| --- | --- | --- |
| EPDC | v1 | **v2**（驱动从未进 mainline） |
| 内核 | 主线 6.6.157 | **Amazon 4.1.15-lab126** |
| 长 LUT 常驻 | 补丁新增 `/dev/k4-epdc-wb`，驱动合成 1023 帧 LUT + 自动重启 | **无此机制**，要自己造 |
| 成果 | **84.6 次/秒（= 扫描帧率），0 漏帧** | 目前 8.6 fps |

---

## 6 下一步待办（按优先级）

### P0 —— ✅ 波形 blob 结构与帧数

已完成，结果见 4.4。关键纠错：**112/8 是顶层指针数，不是 mode 数**；活跃 blob 中连续的
`0x70` 温度表步长证明标准 mode 为 10、温度档为 14。原厂最长标准表头为 111，但
advanced/AF 的 `frame_count` 不等于等时扫描场数。

复查命令：

```sh
LD_LIBRARY_PATH=/mnt/us/python3/lib PYTHONIOENCODING=utf-8 \
  /mnt/us/python3/bin/python3.9 /mnt/us/extensions/kindletweaks/tools/epdc_recon.py --no-fps
```

### P1 —— ✅ 扫描帧率

已完成，结果见 4.5：**54.1551009 Hz / 18.46548 ms**。不要再轮询 `FRAME_END`，也不要做
`elapsed ~ frame_count` 拟合；前者会被 ISR 清除，后者不适用于 advanced/AF 数据。

### P2 —— ✅ 最小真机写入实验：同一 update 中会重采样 WB

用户授权后已用独立工具 `epdc_wb_resample_test.py` 完成。实验只在左上角 64×64 测试块中改
`(40,40)` 一个像素的 WB `target gray`（bit7:4），没有写任何 EPDC 寄存器：

1. **只读控制组**：白色 GC16 稳定到 `0x3cff (target=f,current=f)`；随后黑色 GC16 正常稳定到
   `0x4c00 (target=0,current=0)`，证明同一坐标、波形和更新路径确实能完成白→黑。
2. **实验组**：白基线后提交黑更新，捕获到明确的在飞状态
   `0x800f (target=0,current=f)`；再等待 **1.25 个扫描场（约 23.08 ms）**，只把 target 改回白，
   读回 `0x80ff (target=f,current=f)`。
3. 写入发生在黑更新提交后 **378.08 ms**。之后连续观察约 3 秒、573 个 WB 样本：target 一直为
   `f`，current 从未到 `0`；最终仍为 `0x80ff`。
4. 结论：**PASS**。若 update 起始时锁存了目标灰度，控制组证明该像素应该最终变黑；实际它采用
   中途写回的白 target，说明同一 update 的后续扫描会重新取 WB 状态。

实验完成后只恢复原 target nibble，并请求主页重绘；复查为 `power/control=auto`、
`runtime_status=suspended`、`preventScreenSaver=0`，无遗留进程。

实验过程中还定位了一个重要安全问题：旧版脚本在 update 结束后继续轮询 EPDC 寄存器，两次出现
“屏幕亮着但全机卡住、只能重启”；pstore/dmesg 没有 panic、OOM 或 watchdog 证据。结合已知的
`CLKGATE` 约束，高度怀疑是在控制器关钟后读寄存器导致总线等待。最终版因此**完全不映射 EPDC
寄存器**，只读 reserved WB 判断状态，并按 `setup-only → control-only → execute` 分阶段验证。

### P3 —— ✅ 自造 1023 相 LUT 已上机实测（结果见 4.6）

- P2 已成立。K4 的 v1 “每帧 256 B”布局不能直接复制到本机；当前路径使用本机原始 WRF 作为
  容器，只替换一个已验证的标准 mode 指针，不假定 reserved WB 尾部能够承载 waveform blob。
- 已核对 Glider/e-ink：5-bit `wbf_waveform_dump` 的 32×32 解析为 low-first；旧 MXC assembler
  仍固定 16×16/128 B 且打包相反，不能直接复用。本地工具按本机 512 B/phase 布局实现。

已完成第一段离线工具链：

- `epdc_blob_dump.py` 不访问 EPDC MMIO，只从此前确认的普通 DDR `0x92800000` 只读导出活跃 blob；
  导出前校验 KOA3 compatible、顶层表大小及全部顶层指针范围。
- 2026-10-11 重启后再次导出 **2,475,341 B**，SHA-256 为
  `2af3c1fb87d05b553ba6cd434be0bcb0a3ecdc341a1f9d78e7a9a569a741a37a`；14 个顶层指针与
  重启前完全一致，说明当前地址和内容稳定。
- `analyze_epdc_waveform.py` 已实现 32×32 state、4-bit action、**512 B/phase** 的离线解析、反向
  打包 round-trip 和 CSV 导出；显式保留 `low/high` 两种 nibble order。选择 mode/temp 时现在必须
  显式传 `--nibble-order`；`low` 是现有格式证据支持的顺序，`high` 仅作诊断对照。
- 原厂 mode 7 的 14 个温区全部是 **1 phase 且 512 B action 全零**，可作为不施加正/负电压的
  no-op 模板。`build_epdc_noop_waveform.py` 会先验证这一条件，再在 blob 末尾 8-byte 对齐地追加
  `uint64 frame_count + frame_count × 512 B zero actions`，并仅把 mode 7 的 14 个温区指针改到新块。
- 以 `--frames 1023` 构建的离线 WRF：追加块位于 payload `0x25c550`，对齐填充 3 B，输出
  2,999,191 B，SHA-256
  `0bab8a716b57b3057690d540ee2377804b2be1210cb8ebddf8050bebb4530c1a`。独立回读确认 14 个指针、
  1023 相计数和 523,776 B phase 数据全部正确；四个 advanced 指针保持
  `0x25b830 0x25c0f0 0x75f55 0x25c52e`。确定性 gzip 往返也逐字节通过。
- 生成器是**纯离线工具**。该 WRF 已在用户授权后**上机实测完毕**：1023 相 = **12.111 秒**，
  1 相 = 17.74 ms，并因此查明了"mxcfb 索引 ≠ blob mode"与"驱动 7.5 秒超时"两件事。
  完整过程、备份方式、安装路径与结论都在 **4.6**。设备事后已完整恢复原厂波形。
- 对全部标准表复核：**108 个唯一数据块，107/107 个相邻跨度都严格等于
  `8 + frame_count × 512`**。这把 512 B/phase 从抽样推断提升为全表结构验证。
- 顶层额外四个值再次确认为 `0x25b830 0x25c0f0 0x75f55 0x25c52e`，并已部分解码：
  - `0x25b830..0x25c0f0` 是 **VCD**：2240 B，正好为 `10 modes × 14 temps × 16 B`；
    140/140 条记录的末字节加和校验均正确。只有两种唯一记录：mode 0..7 的 112 条是 version 1，
    mode 8..9 的 28 条是 version 4。IDA 反编译 `fetch_epdc_vdc_04_data()` 已确认 v1 字段为
    `vpos/vneg/vddh/vee/vcom_offset/...`，v4 字段为
    `vddh_ext/vee_ext/xon_len/xon_delay/vddh/vee/vcom_offset/v_l/vpdd_len`。
  - `0x25c0f0..0x25c52e` 是 **ACD**：1086 B。前 560 B 正好是
    `10 modes × 14 temps × 4 B` 的一级表，每项为“24-bit 小端源文件偏移 + 1-byte 加和校验”，
    140/140 项校验正确。mode 0/1/2/3/6/7/8 全零；mode 4、5、9 各有 14 个非零项，步长分别为
    8、12、12 B。
  - ACD 余下 526 B 可继续精确分块：mode 4 为 `14×8 B` descriptor，mode 5 与 mode 9 各为
    `14×12 B` descriptor，最后共享 78 B 数据。三组 descriptor 各自 14 条完全相同，内部校验指针
    指向 `0x76115`、`0x76119`、`0x7615f`。
  - 顶层第三个值 `0x75f55` 与一级表第一个非零源偏移一致；共享数据的推导末端
    `0x76115 + 78 = 0x76163` 又与 `/proc/eink/waveform/info` 报告的原始文件大小完全一致。因此这些
    指针属于**转换前 WRF/WBF 的源文件地址空间**。活跃 blob 已把标准波形展开，数值上落入其 mode 0
    payload 只是地址碰撞，不能在那里解引用 ACD 数据；loader 已把 ACD/VCD 另行复制到 blob 尾部。
  - IDA 反编译 `eink_get_wfm_voltage_control()` 与 `fetch_epdc_adc_06_data()` 后，重定位规则也已确认：
    ACD 一级表之后的 526 B 映射为源地址 `0x75f55..0x76163`，读取时使用
    `relocated_tail + (source_pointer - 0x75f55)`。descriptor 头是
    `u16 version + u8 parameter_count + u8 checksum`，随后每个参数是带校验的 24-bit 源指针；参数记录是
    `u16 payload_len + payload + u8 checksum`。
  - 驱动的 ACD 默认值为 `SFT=3, ASV=21`；只有 descriptor version 1 或 6 且参数数不超过 2 时，
    才用第 1/2 个参数 payload 的首字节覆盖。当前 mode 4（v1/1 参数）、mode 5（v2/2 参数）、
    mode 9（v6/2 参数）最终都得到 **SFT=3、ASV=21**；全部 descriptor、参数记录校验均通过。
  - `0x25c52e` 是 **XSWI**：长度 29 的字符串 `400_A053_HE2901_ED070KC3U1_TC`，尾部校验和
    `0x5d` 与长度+正文之和一致。
- ACD 的物理分组、重定位规则以及 SFT/ASV 读取逻辑已经确定。尚缺 67-byte 参数 payload 的完整语义；
  low-first packing 已有格式证据，离线 no-op WRF 已生成，但尚未加载到真机。

本轮 IDA 输入是设备端只读复制的 `mxc_epdc_v2_fb.ko`（190,040 B，SHA-256
`dae99e489a9d47d224d30729f913edbcd756e45d6da37c7654c2cbf530052a17`）。模块自身只负责把已经生成的
WRF payload 复制到 DMA，并设置 `LUT_DATA_SWIZZLE=NO_SWAP`；没有发现逐 phase 的 nibble 重排代码。

### P4 —— 工程化（如果决定往下走）

- 必须先和用户确认"写寄存器"的授权；建议先在**只读侦察脚本基础上单独写一个实验脚本**，
  与正式功能隔离。
- 必须处理与驱动的互斥（驱动才是控制器主人，并发写会错乱 IRQ/队列状态机，可能整屏花/挂）。
- 必须考虑 **DC 平衡**：K4 作者自己写了合成 LUT **没有直流平衡，长期残影和面板寿命影响未验证**。
  在一台 Oasis 3 上这个代价比在 K4 上贵得多。

---

## 7 雷区清单（每条都踩过）

| 坑 | 事实 | 应对 |
| --- | --- | --- |
| **读寄存器** | `CLKGATE` 置位时读任何 EPDC 寄存器都无意义/可能总线错误 | 保持一次更新在飞 + 先验 `CLKGATE==0` |
| **完成后轮询 EPDC 寄存器** | 旧 P2 脚本两次令设备亮屏卡死；无 panic/OOM 证据，高度怀疑关钟后的寄存器读 | 实验工具完全不映射 EPDC；完成状态改从 reserved WB 观察 |
| **别名寄存器** | `+4/+8/+0xC` 的 `_SET/_CLEAR/_TOGGLE` 是写语义 | 只读基偏移 |
| **`EPDC_IRQ_CLEAR`(0x428)** | 写它 / 写 `IRQ_MASK*` 会让驱动状态机卡死（`WAIT_FOR_UPDATE_COMPLETE` 永久挂起） | 绝对不写 |
| **`EPDC_GPIO`(0x700)** | `PWRCTRL`/`PWRCOM` 是面板电源/VCOM | 绝对不写 |
| **整屏测试图案** | 会导致"白屏"（第 2 节） | 只用小块保活 + atexit 切回主页 |
| **`lipc-set-prop -i`** | 带 `-i/-s` 时要求 **publisher 和属性名分开传**；传点号合并写法会**静默失败**（rc=1） | 用 `lipc-set-prop -i -- <publisher> <名字> <值>`；不带 flag 时它自己能容忍合并写法 |
| **`/mnt/us` 大小写** | 是 Amazon **fsp(FUSE)** 层，**大小写不敏感**（`videos` 与 `Videos` 同一目录），但 **FUSE 对两种拼写返回不同 inode** | 只用一个规范目录名；**别按 inode 去重** |
| **busybox `sleep`** | 不支持小数（`sleep 0.8` 报错） | 只用整数 |
| **PowerShell + scp** | `.work\file` 里的反斜杠会被吞（变成 `.workfile`） | 用 `Get-ChildItem` 取 `FullName` 再传 |
| **PowerShell 控制台** | 是 GBK，中文/`✓` 输出乱码 | 写文件再用 read 工具看；或设 `PYTHONIOENCODING=utf-8` |
| **`%b` 格式符** | Python 的 `%` 格式化不支持二进制 | 用 `"{:02b}".format()` |
| **两个 fbink 构建** | `/mnt/us/libkh/bin/fbink`（CLI，`Fonts=No`）与 `/mnt/us/python3/lib/libfbink.so.1`（py-fbink 自带，**有字体**）能力不同 | 打字要用 py-fbink |
| **截图无法证伪刷新** | `screenshot` 读 framebuffer，而 fbink 写 framebuffer | 判断"面板有没有真刷"只能靠**肉眼** |
| **`_fbink` 的 cfg** | 波形字段叫 **`wfm_mode`**（不是 `waveform`） | 见 play.py |
| **`FRAME_END`** | 中断位会被内核 ISR 清除/锁存，用户态轮询抓不到可靠边沿 | 用 pixel clock + TCE 时序计算，见 4.5 |

---

## 8 环境与访问

| 项 | 值 |
| --- | --- |
| Kindle | Oasis 3（KOA3），`root@192.168.31.55`，免密 SSH |
| SoC / 平台 | i.MX7D，`fsl,imx7d-zelda`，板 `stinger` |
| 内核 | `4.1.15-lab126`（Amazon，2023-02-10） |
| 固件 | `005-juno_150101_stinger_zelda-392503`（5.15.1.1） |
| 面板 | 1264×1680 @ 8bpp，stride 1280，300dpi |
| EPDC | `imx_epdc_v2_fb`，寄存器块 **`0x306f0000`**（size 0x10000） |
| WB | **`0x9c000000`**，5MB（设备树 `reserved-working-buffer`） |
| 波形 blob | **`0x92800000`**（真机读到的 `EPDC_WVADDR`） |
| `/dev/mem` | 存在，**`CONFIG_STRICT_DEVMEM` 未开** |
| 设备 python3 | `/mnt/us/python3/bin/python3`（3.9.8）+ numpy 1.21.4 + Pillow 9.0.0 + `_fbink`（cffi） |
| runtime PM | `/sys/devices/platform/soc/30400000.aips-bus/306f0000.epdc/power/control` |
| 活跃波形 | 面板内置 `400_A053_HE2901_ED070KC3U1_TC.wrf.gz`；解压 WRF 为 2,475,404 B，`WRF[0x3f:]` 与 2,475,341 B DMA blob 完全相等；根文件系统 `epdc_ED070KC1.fw` 是不同的 fallback |
| **波形分区** | **`/dev/mmcblk2p4`，FAT32，4 MB**，挂载点 `/mnt/wfm`；活跃波形在 `waveform_to_use/<模块参数 waveform 的值>` |
| 波形安装（官方脚本） | `/usr/sbin/wfm_update`（**要 Amazon 签名 bundle**，自定义文件走不通）、`/usr/sbin/wfm_forceupdate`（拷到分区根、与 v2 loader 路径不符）、`/usr/sbin/wfm_delete`、`/usr/sbin/wfm_mount`（**挂载失败会 `mkdosfs` 格式化**，慎用） |
| 内核时钟 | `epdc_pixel_root_clk = 160000000`（`epdc_pixel_post_div` = 480/3；可在 `/sys/kernel/debug/clk/` 查） |
| 本机工具 | ffmpeg/ffprobe、`D:\py313\Scripts\yt-dlp.exe`、代理 `127.0.0.1:7890` |
| 下载注意 | YouTube 的 DASH 格式常 `403`，加 `--extractor-args "youtube:player_client=android"` 可解 |

后端进程与服务的细节见 [09 lab126 内部结构](09-lab126-internals.md)、[13 系统参考](13-kindle-system-reference.md)。

---

## 9 文件地图（本次新增/改动）

| 文件 | 作用 |
| --- | --- |
| [tools/make_ktvid.py](../tools/make_ktvid.py) | PC 端：视频/GIF/图片序列 → `.ktvid`（缩放 + 抖动成 1bit + per-frame zlib；`--label` 可烧标签做 A/B） |
| [extensions/kindletweaks/fbvideo/play.py](../extensions/kindletweaks/fbvideo/play.py) | 设备端播放器：波形选择、帧率匹配、去残影、**控制文件（pause/resume/toggle/stop/restart）**、状态文件、触屏/按键控制、暂停提示条 |
| [extensions/kindletweaks/tools/epdc_recon.py](../extensions/kindletweaks/tools/epdc_recon.py) | **EPDC v2 只读侦察**：寄存器 dump、TCE 扫描率、active/fallback 比对、10×14 指针/帧数与 512 B/phase 解码 |
| [extensions/kindletweaks/tools/epdc_wb_resample_test.py](../extensions/kindletweaks/tools/epdc_wb_resample_test.py) | **P2 独立实验**：分阶段初始化/只读控制/单像素 WB 改写；不映射 EPDC 寄存器，带超时与收尾 |
| [extensions/kindletweaks/tools/epdc_blob_dump.py](../extensions/kindletweaks/tools/epdc_blob_dump.py) | 从已确认的普通 DDR 地址只读导出活跃 waveform blob；不访问 EPDC MMIO，并校验设备/指针指纹 |
| [tools/analyze_epdc_waveform.py](../tools/analyze_epdc_waveform.py) | PC 端 32×32/512 B phase 解析器：全表校验、双 nibble order、round-trip 与 CSV 导出 |
| [tools/build_epdc_noop_waveform.py](../tools/build_epdc_noop_waveform.py) | PC 端纯离线生成器：验证 mode 7 全零模板，追加最长 1023 相 no-op 块并保持 advanced 数据不变；不连接设备 |
| [tools/verify_noop_wrf.py](../tools/verify_noop_wrf.py) | PC 端**上机前验穿**：确认自造 WRF 只改了 mode 7 的 14 个指针 + 末尾追加块，其余逐字节不变；并解释"跨度不符"的两个正常例外 |
| [extensions/kindletweaks/tools/measure_mode7.py](../extensions/kindletweaks/tools/measure_mode7.py) | 设备端：分模式计时（含自造长 LUT 的耗时判定），只用 64×64 小块，不碰 EPDC 寄存器 |
| [extensions/kindletweaks/tools/sweep_modes.py](../extensions/kindletweaks/tools/sweep_modes.py) | 设备端：扫描 mxcfb 索引 0..17 的耗时，用来**反推 mxcfb 索引 ↔ blob mode 的置换表** |
| [extensions/kindletweaks/tweak.sh](../extensions/kindletweaks/tweak.sh) | KUAL 菜单「墨水屏视频播放」（自动扫描 + 暂停/继续/停止 + 状态）；`fbvideo play/stop/toggle/state/status/menujson` |
| [docs/17-fbvideo-eink-video.md](17-fbvideo-eink-video.md) | 功能正文档：`.ktvid` 格式、全部实测数据、索引 10 陷阱（§7 已在 2026-10-11 纠正）、面积/帧率模型、K4 对比 |
| 本文件 | 交接 + EPDC 侦察记录 |

设备上：视频放 `/mnt/us/videos/*.ktvid`（现有 `badapple_800`、`badapple_full`、`counter_c`）。
**波形备份与一键回滚**在 `/mnt/us/waveform_backup/`（整分区镜像 + 原文件 + `rollback.sh`）。
`*.ktvid`、`*.mp4`、`fbvideo/play.log`、`fbvideo/ctl`、`fbvideo/state`、`*.wrf(.gz)`、`.work/`
以及 IDA 的 `Hook.log`/`IDAHook.log` 都在 `.gitignore` 里。

---

## 10 仍未解 / 查不到的（别当成已知）

1. **`EPDC_VERSION` 在别的 i.MX7D 机器上是不是也 0x03000000** —— 只有这一台的实测值。
2. **本机 advanced/AF 的剩余格式细节** —— 32×32×4-bit action、512 B/phase、low-first packing、
   VCD/ACD/XSWI 的物理分块、ACD 重定位与 SFT/ASV 读取已确认；尚缺 67-byte ACD 参数 payload 的
   完整语义，以及它们与 `BUF_PIXEL_FORMAT`/PTS 状态位的关系。low-first 尚未经自合成波形硬件注入验证。
3. **mxcfb 索引 ↔ blob mode 的完整置换表** —— 只确定了 **索引 10 → blob mode 7**（靠"改相数看谁变慢"）。
   其余 9 个 mode 的对应关系未知。**任何"改某个 mode"的实验都必须先做这个映射。**
4. **相位速率 84.5 Hz vs 算出的扫描率 54.155 Hz（差 1.5625 倍）** —— 见 4.6 末尾。
   若"1 相 = 1 场"成立，则 §4.5 的算式需要修正（且 84.6 Hz 与 K4 的实测完全吻合）。
5. **驱动的 7.5 秒完成超时** —— 已观测到触发与 `epdc_recover`，但**恢复流程到底做了什么、
   长 LUT 被中断时面板处于什么状态，没有查清**。走正常 mxcfb 路径时这是硬上限。
6. **带真实 action 的长 LUT 尚未构造** —— 全零 no-op 只证明"能跑很久"；真正推像素需要
   VPOS/VNEG action 且整段净直流为零。**action 数值语义仍只有第三方资料**（`1`=推向黑、`2`=推向白），
   NXP 原文未取得。
7. **单 LUT 硬件 frame 是否真的上限 1024** —— 1023 相能跑通（12.1 秒），所以上限 ≥1023；
   更长的（如 2048）未测。
8. **`EPDC_LUT_STANDBY1/2`(0x1E0/0x1F0) 语义** —— 头文件有、驱动从不碰。
9. **WB 重采样的精确截止点与粒度** —— P2 已证明等待 1.25 个扫描场后改 target 仍会生效，但
   尚未测出每个场的采样相位、FIFO 预取深度及“离扫描到该像素多近”才来不及生效。
10. **Amazon 的 `reserved-working-buffer` 私有补丁** —— 公开树里没有。

---

## 11 给接手者的忠告

1. **先确认设备状态再动手**：`preventScreenSaver`、EPDC `power/control`、有没有遗留的
   `/mnt/us/_*` 临时文件、`fbvideo state`。测试脚本一定要有 atexit 收尾。
2. **改屏幕的测试只用小块**，并且**在用户看着的时候做**（判断"面板到底刷没刷"只有肉眼可靠）。
3. **纯只读的部分可以放心做**；一旦要越过"写寄存器/写 WB"这条线，**先问用户**，
   并把实验脚本与正式功能隔离 —— 这台是用户的日常机。
4. **改波形前先做三件备份**：`dd` 整个 `/dev/mmcblk2p4` 做镜像、把活跃 `.wrf.gz` 复制出来、
   写一个一键回滚脚本放 `/mnt/us`。原文件 sha256 要和你本地副本对得上再动手。
5. **别按"同名 mode"改波形** —— mxcfb 索引与 blob mode 是置换表（第 4.6 节）。
   改之前先用 `sweep_modes.py` 建立映射，否则你会像我们一样白改一轮。
6. **不要用 `wfm_mount`**（挂载失败会格式化分区）；自己 `mount /dev/mmcblk2p4 /mnt/wfm` 并检查返回值。
7. **耗时反常不等于"波形不被支持"** —— 单张 LUT 超过约 7.5 秒会触发驱动的
   `Timed out waiting for update completion` + `epdc_recover`，实验设计要把这点算进去。
8. **别忘了物理约束**：DC 平衡。K4 作者自己就写明合成 LUT 没有直流平衡、长期残影与面板寿命未验证。
   在一台 Oasis 3 上这个代价比在 Kindle 4 上贵得多 —— 造带 action 的长 LUT 之前想清楚。
