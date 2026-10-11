# kindle-tweaks

让越狱 Kindle 更好用的一组小改造，主要针对**未注册 / fakereg 假注册**的机器。所有功能集中在一个 KUAL 菜单「Kindle Tweaks」里，可以单独开关。

*A collection of tweaks for jailbroken Kindles (especially unregistered / fake-registered ones), managed from a single KUAL menu: remove the "cloud unavailable" nag, auto-build collections from folders, unlock the Collections view, and full-screen PDF (no footer, no margins). Docs are in Chinese; scripts are self-explanatory.*

> 验证设备：Kindle Oasis 3（10th gen），FW **5.15.1.1**，LanguageBreak 越狱 + KUAL + [fakereg](https://www.mobileread.com/forums/showpost.php?p=4122357&postcount=125)。
> 其他机型和固件的原理大概率相同，但偏移和特征码可能不同。脚本都会先校验，不匹配就不动。

## 功能

| # | 功能 | 解决的问题 | 文档 |
|---|---|---|---|
| 1 | 去掉「云端不可用」弹窗 | 假注册后每次进书库都弹「云端不可用，您必须注册 kindle…」；功能 13 的界面隐藏也叠加在这一份 `KPPMainApp.js.hbc.patched` 上（popup 打底，再打 nowifi） | [docs/01-cloud-popup.md](docs/01-cloud-popup.md) |
| 2 | 文件夹 → 收藏夹自动同步 | Kindle 不认文件夹；未注册时「新建收藏夹」是灰色的 | [docs/02-folder-collections.md](docs/02-folder-collections.md) |
| 3 | 解锁「查看选项 → 收藏夹」视图 | 收藏夹里的书仍在书库第一层平铺；该视图在未注册时是灰色的 | [docs/03-collections-view.md](docs/03-collections-view.md) |
| 4 | PDF 全屏 | PDF 底部常驻阅读百分比、四周有白边，设置里关不掉 | [docs/04-pdf-fullscreen.md](docs/04-pdf-fullscreen.md) |
| 5 | epub/md/docx 自动转换 | Kindle 打不开 epub。文字书传输完成后立即用原生 ARM boko 转成 AZW3，失败时回退 Kindling；大漫画充电时用精简移植的 KCC 转成全屏 PDF；md、docx 先生成 EPUB 再转 AZW3 | [docs/05-manga-convert.md](docs/05-manga-convert.md) |
| 6 | 屏保开机随机排序开关 | linkss 开机时重排所有屏保，图多时开机很慢 | （菜单里直接切换） |
| 7 | 调试模式 | Kindle 进入深度休眠会断开 Wi-Fi/SSH；可选始终不深度休眠、仅充电时不深度休眠或关闭，屏保始终照常 | [docs/06-debug-awake.md](docs/06-debug-awake.md) |
| 8 | 默认收藏夹视图 | Home 固定网格、图书馆筛选等操作会让界面回到「全部 + 网格」；进入屏保后，下次进入图书馆由注入 KPP 的小库瞬间恢复收藏夹视图（不重启、不白屏） | [docs/07-default-collections.md](docs/07-default-collections.md) |
| 9 | 浏览器下载任意文件 | 体验版浏览器只许下载 .azw/.prc/.mobi/.txt，下载 epub、pdf 弹「文件类型无效」；放开后照常存到 documents，epub 由功能 5 自动转换 | [docs/08-browser-download.md](docs/08-browser-download.md) |
| 10 | 微信传书 | 假注册设备用不了亚马逊的推送；在微信里把书发给 ClawBot 或企业微信「微信客服」，自建 VPS 收下，Kindle 亮屏联网时自动取走放进 documents，取走后微信回「已送达」；支持好友和多台 Kindle，在网页管理页上绑定 | [docs/10-wechat-send.md](docs/10-wechat-send.md) |
| 11 | 常驻网页应用（WAF） | 越狱后能用 HTML+JS 写界面，但自己写的网页默认不是系统应用。把 `/mnt/us/webapps/<名字>/` 注册进 `appreg.db`，就成了能被启动器/脚本随时拉起的一等 WAF，拿到完整 `window.kindle`（开书、联网、发 lipc）；注册信息在持久分区，不依赖任何缓存，比 Mesquito 覆盖商店缓存的做法耐久 | [docs/16-webapp-waf.md](docs/16-webapp-waf.md) |
| 12 | 墨水屏视频播放 | 绕开 X 直接写 framebuffer 逐帧刷屏，能在墨水屏上放视频（Bad Apple 实测可播）。A2 波形实测 8.6 fps（640×480）～6.3 fps（满宽 1264×948），**硬件天花板约 9.9 fps**；1bit 帧 + zlib 压缩，全长 Bad Apple 只有 9～16 MB | [docs/17-fbvideo-eink-video.md](docs/17-fbvideo-eink-video.md) |
| 13 | 隐藏无线界面 + 泡面模式开关 | 未注册的机器本来就不该联网，界面上那一排无线入口很碍事：KPP 里的三处（下拉快捷设置那一排、顶栏购物车、⋮ 菜单里的「网页浏览器」「设置」「Amazon Kids」）**叠加在功能 1 的 hbc 补丁上**，状态栏的 Wi-Fi / 飞行模式 / WAN 图标由 `nowifi` 注入小库换成同尺寸空白；无线开关放进 KUAL（菜单里叫「泡面模式」，走系统飞行模式小部件同一个 lipc 属性 `com.lab126.cmd wirelessEnable`，1 = 无线开，0 = 无线关） | [docs/19-hidden-wireless.md](docs/19-hidden-wireless.md) |

## KUAL 菜单

```
Kindle Tweaks
├─ 去除「云端不可用」弹窗 + 隐藏无线界面 [已开启] → 开启 / 关闭（还原原版）
├─ 解锁「查看选项→收藏夹」 [已开启] → 开启 / 关闭（还原原版）
├─ PDF 全屏（无底栏无边距） [已开启] → 开启 / 关闭（还原原版）
├─ 浏览器可下载任意文件（存到 documents） [已开启] → 开启 / 关闭（还原原版）
├─ 文件夹收藏夹 [自动同步已开启]     → 立即同步 / 开启自动同步 / 关闭自动同步 / 删除所有自动生成的收藏夹
├─ epub/md/docx 自动转换 [已开启]   → 进度 / 开启 / 关闭 / 立即转换 / 规则 / 按目录转换（动态列出目录）
├─ 屏保开机随机排序（linkss） [已关闭] → 开启 / 关闭
├─ 默认收藏夹视图 [已开启]             → 开启 / 关闭（保留当前视图）
├─ 调试模式 [已关闭]                   → 查看当前状态 / 不深度休眠 / 充电时不深度休眠 / 关闭调试模式
├─ 微信传书 [已开启]                   → 上次同步结果 / 立即同步 / 开启 / 关闭
├─ 常驻网页应用（WAF） [0 个已常驻]     → 自检 doctor / 重新安装全部 / 候选应用（安装并常驻 / 立即打开 / 卸载）
├─ 墨水屏视频播放 [0 个视频｜off]       → 停止播放 / 视频列表（选波形：A2 推荐 / DU / GC16）
├─ 泡面模式 [已关闭]                     → 开启 / 关闭
├─ 隐藏状态栏无线图标（nowifi） [已开启]   → 开启 / 关闭（显示图标）
├─ 升级固件后：全部补丁重新开启（并重装常驻网页应用）
└─ 全部补丁还原原版
```

菜单项里的 `[状态]` 是按系统文件实际的 md5 算出来的，每次操作后自动刷新。缺补丁文件的功能会显示「缺补丁文件」，不影响其他功能。

## 目录

```
extensions/kindletweaks/    KUAL 扩展，整个目录拷到 Kindle 的 extensions/ 下
  tweak.sh                  所有开关的实现（KUAL 和 SSH 共用），生成 menu.json
  foldercoll/               文件夹 → 收藏夹（sync.py + upstart 任务模板）
  mangaconv/                漫画 epub → PDF、文字书 epub/md/docx → AZW3（mangaconv.py + docconv.py + upstart 任务模板）
  debugawake/               调试模式：充电时推迟深度休眠的 upstart 任务模板
  libraryview/              恢复收藏夹视图：upstart 任务模板 + 注入 KPP 的 libkt_libview.c
  nowifi/                   隐藏状态栏的无线图标：注入 JunoStatusBarDriver 的 libkt_nowifi.c
  wxsend/                   微信传书：拉取用的 upstart 任务模板 + config.example
  webapp/                   常驻网页应用（WAF）：config.template.xml + sample/ 自检示例
  fbvideo/                  墨水屏视频播放：play.py（Pillow + py-fbink 逐帧刷屏）
  tools/epdc_recon.py       EPDC v2 只读侦察（寄存器 / 扫描帧率 / 波形 blob 解码；危险操作已按事故加固）
  files/                    补丁用的系统文件 *.orig / *.patched（自己生成，不进 git）
server/wxsend/              微信传书的 VPS 端（wxsend.py + systemd 单元 + nginx location）
tools/                      在电脑上生成 .patched
  patch_kpp.py              KPPMainApp.js.hbc（功能 1，需要 hermes-dec）
  patch_kpp_nowifi.py       KPPMainApp.js.hbc：隐藏无线相关界面（快捷设置那一排、顶栏购物车、⋮ 菜单里的网页浏览器/设置/Amazon Kids），需要 hermes-dec
  patch_ksdk.py             libKSDKLibrary.so（功能 3，纯 Python）
  patch_mesquite.py         /usr/bin/mesquite（功能 9，纯 Python）
  pdf_fullscreen/build.py   3 个 Java jar（功能 4，需要 JDK 9+）
  build_ebook_converters.py 从固定源码构建 boko + Kindling ARMv7 静态版（功能 5）
  gen_lipc_catalog.py       从 `lipc-probe -a -v` 的转储重新生成 docs/11 的服务索引与 docs/12
  make_ktvid.py             视频/GIF/图片序列 → .ktvid 帧序列（缩放 + 抖动成 1bit + zlib 压缩）
  analyze_epdc_waveform.py  EPDC 波形 blob 解析（32×32 state / 每相 512 B / 双 nibble order）
  build_epdc_noop_waveform.py  离线生成"1023 相全零 no-op"WRF（纯离线，不连设备）
  verify_noop_wrf.py        上机前验穿自造 WRF：确认除该改的地方外逐字节不变
docs/                       原理、排查过程、新固件上怎么重做
  01..08、10、19            每个功能的实现与排查记录
  09-lab126-internals.md    在真机上摸清的系统结构（进程、upstart、lipc、文件、注入）
  11-lipc-and-services.md   lipc 规则 + 92 个 com.lab126 服务索引 + 常用服务详解
  12-lipc-service-catalog.md 全部服务的完整属性表
  13-kindle-system-reference.md  appreg.db / cc.db / 调试命令 / 启动流程 / 机型代号 / 固件
  14-kindle-homebrew-and-dev.md  hotfix / Scriptlets / KPM / 原生开发 / 窗口标题
  15-wafs-and-mesquite.md   WAF、config.xml 规范与 window.kindle API
  16-webapp-waf.md         常驻网页应用（WAF）功能；Mesquito/KWebBrew 对比与 UI 方案选型
  17-fbvideo-eink-video.md  墨水屏视频播放：.ktvid 格式、波形与帧率实测、屏幕适配取舍、为什么不能更快
  18-epdc-recon-and-handover.md  EPDC v2 侦察（含**自造 1023 相长 LUT 上机实测 = 12.1 秒**）+ **工作交接**（现状、待办、雷区）
  19-hidden-wireless.md     隐藏无线界面（nowifi）：JS 补丁的四个锚点、⋮ 菜单条目 id 的原生出处、状态栏图标注入、泡面模式开关
```

> ⚠ 本仓库**不包含任何亚马逊的原始文件或补丁后的文件**。补丁都是从你自己机器上提取的文件生成的。

## 前置条件

- 已越狱，装好 KUAL 和 MRPI。
- 能在 Kindle 上以 root 执行命令，二选一：
  - [USBNetwork](https://www.mobileread.com/forums/showthread.php?t=225030) 开启 SSH over WiFi（推荐，下文用 `ssh root@<kindle-ip>`）。
  - hotfix 自带的 `;log runme`：在书库搜索栏输入，会以 root 执行根目录的 `RUNME.sh`。
- 功能 2、5 需要 Kindle 上有 Python 3（例如 KUAL 的 python3 扩展，装在 `/mnt/us/python3`，自带 Pillow）。功能 5 转换 md/docx 还要在 Kindle 上 `pip install markdown mammoth`（见 [docs/05](docs/05-manga-convert.md) 第 8 节）。
- 生成补丁需要电脑上有 Python 3；功能 1 还要 [hermes-dec](https://github.com/P1sec/hermes-dec)（`pip install git+https://github.com/P1sec/hermes-dec`），功能 4 还要 JDK 9+；功能 5 的文字书转换器需要 rustup + Rust 1.91+ 构建一次。

## 快速开始

```sh
# 0. 如需文字书转换，先构建 Kindle 原生 ARM 转换器
python tools/build_ebook_converters.py extensions/kindletweaks/bin

# 0b. 免重启注入库（需要 pip install ziglang；不编译也能用，退回屏保时重载 KPP）
#     默认收藏夹视图
python -m ziglang cc -target arm-linux-gnueabi.2.20 -mcpu=cortex_a7 -shared -fPIC -O2 -s -Wl,-z,lazy \
    -o extensions/kindletweaks/libraryview/libkt_libview.so extensions/kindletweaks/libraryview/libkt_libview.c
#     隐藏状态栏的无线图标（功能 13 的状态栏部分）
python -m ziglang cc -target arm-linux-gnueabi.2.20 -mcpu=cortex_a7 -shared -fPIC -O2 -s -Wl,-z,lazy \
    -o extensions/kindletweaks/nowifi/libkt_nowifi.so extensions/kindletweaks/nowifi/libkt_nowifi.c

# 1. 装扩展
scp -r extensions/kindletweaks root@<kindle-ip>:/mnt/us/extensions/
F=/mnt/us/extensions/kindletweaks/files

# 2. 从 Kindle 提取原始文件
scp root@<kindle-ip>:/app/KPPMainApp/js/KPPMainApp.js.hbc KPPMainApp.js.hbc.orig
scp root@<kindle-ip>:/app/lib/libKSDKLibrary.so          libKSDKLibrary.so.orig
scp -r root@<kindle-ip>:/opt/amazon/ebook/lib            ebook-lib
scp root@<kindle-ip>:/usr/bin/mesquite                   mesquite.orig

# 3. 在电脑上生成补丁版（需要哪个功能就生成哪个）
python tools/patch_kpp.py  KPPMainApp.js.hbc.orig KPPMainApp.js.hbc.patched
#    「隐藏无线界面」（功能 13）是在上一个补丁上**叠加**的：popup 打底，再打一遍 nowifi
python tools/patch_kpp_nowifi.py KPPMainApp.js.hbc.patched KPPMainApp.js.hbc.patched
python tools/patch_ksdk.py libKSDKLibrary.so.orig libKSDKLibrary.so.patched
python tools/patch_mesquite.py mesquite.orig mesquite.patched
python tools/pdf_fullscreen/build.py ebook-lib pdf-out     # 生成 3 对 jar 的 .orig/.patched

# 4. 传到扩展的 files/
scp *.orig *.patched pdf-out/* root@<kindle-ip>:$F/
```

然后打开 KUAL →「Kindle Tweaks」→「首次使用：刷新状态」，菜单就会列出全部功能。

- 建议每个补丁第一次用时先临时试用（bind mount，重启即失效），方法见各功能文档。
- SSH 等价命令：`sh /mnt/us/extensions/kindletweaks/tweak.sh status`、`tweak.sh pdffull on`、`tweak.sh all off` 等。不带参数运行会显示用法。

## SSH 常用命令

### 先读：Kindle 上的 Linux 和普通 Linux 不一样的地方

- **怎么开 SSH**：用 [USBNetwork](https://www.mobileread.com/forums/showthread.php?t=225030)（KUAL 的 MRInstaller 装）。
  - 在 U 盘区的 `usbnet/etc/config` 里设 `USE_WIFI="true"`、`USE_WIFI_SSHD_ONLY="true"`，表示只在 WiFi 上开 SSH，不把 USB 切成网卡。
  - `usbnet/` 下放一个名为 `auto` 的空文件，开机就会自动启动 SSH。
  - **公钥**放在 `usbnet/etc/authorized_keys`。它自带的 dropbear 读的是这个路径，不是 `~/.ssh`。
  - **密码登录**用 root 密码。没设过可以用 `passwd` 设，或者改 `/etc/shadow`。它在系统分区，升级固件后会被还原。
- **IP 地址**：在路由器里看，或者 SSH 上去后执行 `ifconfig wlan0`。建议在路由器里给它固定 IP。
- **休眠时连不上**：Kindle 进屏保约 1 分钟后深度休眠，WiFi 会断。按一下电源键唤醒就能连。调试期间可以用 `lipc-set-prop com.lab126.powerd preventScreenSaver 1` 禁止进屏保，用完改回 0。
- **PATH 不全**：非交互的 `ssh root@<ip> '命令'` 找不到 `lipc-*`、`mntroot`、`start`/`stop` 等命令。先执行：
  ```sh
  export PATH=/usr/sbin:/sbin:$PATH
  ```
- **两个分区**：
  - `/` 是系统分区，平时只读。要改的话先 `mntroot rw`，改完 `mntroot ro`。升级或重刷固件会整个替换它。
  - `/mnt/us` 是用户分区，就是 USB 连电脑时看到的那个盘（vfat 类文件系统，没有符号链接和执行权限位）。书、扩展、自己的脚本都放这里，升级不会丢。
  - 用 USB 存储模式连电脑时，`/mnt/us` 会被卸载，在上面跑的程序会出错。
- **busybox 的坑**：
  - 系统命令大多是 busybox 版，功能比 GNU 版少，比如 `find -size` 只认 `k`、不认 `M`。
  - 变量后面紧跟中文时要写成 `${N}`，否则中文会被当成变量名的一部分。
- **脚本必须 LF 换行**：在 Windows 上写的 `.sh` 如果是 CRLF，会出现莫名其妙的「not found」。拷上去后可以执行 `sed -i 's/\r$//' 脚本.sh`。
- **改坏了怎么办**：
  - 用 bind mount 临时试的改动：长按电源键约 40 秒强制重启，自动恢复。
  - 写进系统分区的改动：只要 SSH 还能连就能救，usbnet 不依赖界面，白屏也能连。
  - 实在不行，就重刷同版本官方固件，书不会丢。
- **没有 SSH 时的替代**：在书库搜索栏输入 `;log runme`，会以 root 执行 U 盘区根目录的 `RUNME.sh`（需要 LanguageBreak 的 hotfix）。输出可以重定向到 `/mnt/us/xxx.log`，再通过 USB 查看。
- **发现更多接口**：
  - 系统服务之间通过 lipc 通信。`lipc-probe -l` 列出所有服务；`lipc-probe -v com.lab126.powerd` 列出某个服务的属性和当前值（r 可读 / w 可写）。`lipc-probe -a` 会探测全部服务，输出很长。
  - 系统日志在 `/var/log/messages`。
  - 进程依赖、lipc 服务、appmgrd、关键文件、输入设备等系统内部知识见 [docs/09](docs/09-lab126-internals.md)。
  - lipc 的规则、92 个 `com.lab126.*` 服务的索引和常用服务详解见 [docs/11](docs/11-lipc-and-services.md)，逐个服务的完整属性表见 [docs/12](docs/12-lipc-service-catalog.md)。
  - `appreg.db`（什么文件由什么程序处理）、搜索栏调试命令、开机流程、机型代号见 [docs/13](docs/13-kindle-system-reference.md)。

### 常用命令

**截屏**

```sh
/mnt/us/usbnet/bin/fbgrab /tmp/shot.png    # 读 /dev/fb0，生成 PNG（1264×1680）
scp root@<kindle-ip>:/tmp/shot.png .        # 在电脑上取回
```
- /usr/sbin/screenshot 同样也可以进行截屏

**打开书、回主页、电源**

```sh
# 直接打开一本书（文件必须已被书库索引；没索引好就把文件移出 documents 再移回来）
lipc-set-prop com.lab126.appmgrd start "app://com.lab126.booklet.reader/mnt/us/documents/某书.pdf"
lipc-set-prop com.lab126.appmgrd start app://com.lab126.booklet.home    # 回主页
lipc-get-prop com.lab126.appmgrd activeApp                              # 当前前台应用

lipc-set-prop com.lab126.powerd wakeUp 1               # 唤醒
lipc-set-prop -i com.lab126.powerd powerButton 1       # 模拟按电源键（进/出屏保）；整数属性要加 -i
lipc-set-prop com.lab126.powerd preventScreenSaver 1   # 调试时禁止进屏保，用完改回 0
lipc-get-prop com.lab126.powerd isCharging             # 是否在充电（1/0）
lipc-get-prop com.lab126.powerd status                 # 电源状态、休眠倒计时、电量
```

**重启界面进程**

```sh
restart kppmainapp          # 只重启书库/主页界面（改了 KPPMainApp.js.hbc、libKSDKLibrary.so 后）
stop framework; while pidof cvm >/dev/null; do sleep 1; done; start framework   # 重启 Java 框架（改了 jar 后）
# framework 重启后会回到上次的应用；若停在 KUAL 会是一片白屏，执行上面的「回主页」即可
```

**书库数据库（只读）**

```sh
sqlite3 -readonly /var/local/cc.db "select p_titles_0_nominal, p_location from Entries where p_type='Entry:Item' limit 20"
```

**Python 3（KUAL 的 python3 扩展，装在 `/mnt/us/python3`）**

它的动态库不在系统路径里，直接运行会找不到 `libpython3.9.so`，需要带上环境变量：

```sh
LD_LIBRARY_PATH=/mnt/us/python3/lib PYTHONIOENCODING=utf-8 /mnt/us/python3/bin/python3.9 脚本.py
```

可以写两个包装脚本省掉这些。

`/mnt/us/python3/bin/python3`：

```sh
#!/bin/sh
# Kindle 上的 python3 包装：自动带上库路径和 CA 证书
export LD_LIBRARY_PATH=/mnt/us/python3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
export SSL_CERT_FILE=${SSL_CERT_FILE:-/mnt/us/python3/lib/python3.9/site-packages/certifi/cacert.pem}
export PYTHONIOENCODING=${PYTHONIOENCODING:-utf-8}
exec /mnt/us/python3/bin/python3.9 "$@"
```

`/mnt/us/python3/bin/pip`：

```sh
#!/bin/sh
export PIP_ROOT_USER_ACTION=ignore PIP_DISABLE_PIP_VERSION_CHECK=1
exec /mnt/us/python3/bin/python3 -m pip "$@"
```

- **装 pip**：`/mnt/us/python3/bin/python3 -m ensurepip`，再 `pip install certifi`。装完 certifi 后，HTTPS 才能验证证书。
- **能装哪些包**：只有纯 Python 包，或者自带 armel 编译产物的包。numpy 这类没有软浮点 ARM 版本。
- **想直接敲 `python3` / `pip`**：在 `/usr/local/bin/` 里放两个转发脚本。它们在系统分区，要先 `mntroot rw`，升级固件后会丢。
- ⚠ **不要**把 `LD_LIBRARY_PATH=/mnt/us/python3/lib` 设成全局变量。系统自带的 `sqlite3` 等程序会加载到 Python 带的库，报 `SQLite header and source version mismatch`。

**本项目的日志**

```sh
E=/mnt/us/extensions/kindletweaks
sh $E/tweak.sh status                   # 所有功能的状态
cat $E/tweak.log                        # 开关操作记录
tail $E/foldercoll/sync.log             # 文件夹收藏夹
tail $E/mangaconv/convert.log           # epub 转换
cat $E/wxsend/status.txt                # 微信传书上次同步结果
grep -iE "VerifyError|NoClassDef|NoSuchMethod" /var/log/messages   # Java 补丁出错时
```

## 升级 / 重刷固件之后

系统分区会被整个替换，所以补丁和自动同步的开机任务都会失效。`extensions/kindletweaks/` 在用户分区，不受影响。

- **固件版本不变**：KUAL →「升级固件后：全部补丁重新开启（并重装常驻网页应用）」，再在「文件夹收藏夹」里重新「开启自动同步」、在「大漫画 epub 转 PDF」里重新「开启」。
  常驻网页应用的**安装清单在 `/mnt/us/extensions/kindletweaks/webapp/installed.txt`**，固件更新不会丢，所以那一步会自动把它们重装回 `appreg.db`；也可以单独点「常驻网页应用」→「重新安装全部常驻应用」。
  隐藏无线界面（功能 13）的两半也都在这一步里：hbc 那半随功能 1 的 `.patched` 一起写回，状态栏那半由「隐藏状态栏无线图标（nowifi）」重新改一遍 `/etc/upstart/statusbar.conf`。
- **固件版本变了**：菜单里会显示「文件不匹配」，脚本不会写入。
  1. 用新固件的文件重新生成 `.orig` / `.patched`。
  2. 如果生成脚本找不到特征，按 docs 里的手动方法重新定位。
  3. 新版固件可能改动了 `appreg.db` 的结构或 WAF 的加载方式，常驻网页应用若失效，先跑「常驻网页应用」→「自检 doctor」。

## 风险与救砖

补丁改的是书库界面程序（功能 1、3）和 Java 阅读器框架（功能 4）。万一改坏，可能出现白屏：

- **临时试用阶段**：长按电源键约 40 秒强制重启，自动恢复。
- **已永久写入**：
  - 能 SSH 就执行 `sh /mnt/us/extensions/kindletweaks/tweak.sh all off`。usbnet 的 SSH 不依赖界面，白屏时一样能连。
  - 不能 SSH 就重刷同版本官方固件（书不会丢）。
- 白屏也可能只是 framework 重启后停在了 KUAL 的空白页，见 [docs/04 第 6 节](docs/04-pdf-fullscreen.md#6-排错笔记)。

请自行承担风险。

## 参考文档

`docs/` 里的 01–10、19 是每个功能的实现与排查记录；09 和 11–15 是系统性参考资料，改新功能时先查这几篇。

| 文档 | 内容 |
|---|---|
| [09 系统内部笔记](docs/09-lab126-internals.md) | 在 Oasis 3 / 5.15.1.1 真机上摸清的进程、upstart、lipc、文件与数据库、输入设备、LD_PRELOAD |
| [11 lipc 与 com.lab126 服务](docs/11-lipc-and-services.md) | lipc 与 DBus 的对应、`get/set/Int/Str/Has` 命名规则、事件发现方法、92 个服务索引、常用服务详解 |
| [12 lipc 服务与属性总表](docs/12-lipc-service-catalog.md) | 全部服务逐个列出属性、类型、读写权限与示例值 |
| [13 系统参考资料](docs/13-kindle-system-reference.md) | 分区布局、`appreg.db`、`cc.db`、搜索栏调试命令、越狱改了什么、upstart 启动流程、机型代号表、固件与 OTA |
| [14 自制软件与原生开发](docs/14-kindle-homebrew-and-dev.md) | hotfix、Scriptlets、KPM 打包、koxtoolchain + Kindle SDK + Meson、Awesome WM 窗口标题规范 |
| [15 WAF 与 Mesquite](docs/15-wafs-and-mesquite.md) | WAF 目录结构、`config.xml` 逐节规范、`window.kindle` JS API 与枚举 |
| [16 常驻网页应用与 UI 选型](docs/16-webapp-waf.md) | 怎么让 HTML+JS 应用永久常驻（`appreg.db` 注册机制、实测证据、排错），以及 Mesquito/KWebBrew 对比和「越狱 Kindle 上写 UI 该选哪条路」的实测数据 |
| [17 墨水屏视频播放](docs/17-fbvideo-eink-video.md) | `.ktvid` 帧序列格式与转码、A2/DU4 波形实测（含 DU4 这个坑）、面积与帧率的取舍模型、与 K4 逐像素直驱方案的对比 |
| [18 EPDC 只读侦察与交接](docs/18-epdc-recon-and-handover.md) | EPDC v2 寄存器表与 LUT/DDR 布局、真机只读侦察结果（working buffer、波形 blob 地址）、**下一步待办与雷区**（接手前必读） |
| [19 隐藏无线界面 + 泡面模式](docs/19-hidden-wireless.md) | JS 补丁的四个锚点、⋮ 菜单条目 id 的原生出处（`BuildOverflowMenuConfig` / `NavigationActionFactory`）、状态栏图标的 rsvg 注入、`com.lab126.cmd wirelessEnable` 的开关与实测、坑位清单 |

11–15 是参考 [KindleModding Wiki](https://kindlemodding.org/)（CC BY-NC 4.0）整理并**重新撰写**的，不是逐字复制。
其中的事实数据（服务名、属性、机型表）都来自设备取证——服务与属性出自 wiki 作者机器上的 `lipc-probe -a -v` 转储，
机型表出自 KindleTool；本仓库在 Oasis 3 / 5.15.1.1 上实测过的部分都单独标注了「本机实测」。
换机型或换固件后，用 `tools/gen_lipc_catalog.py` 重新生成 11、12 两篇。

## 致谢

- [KindleModding Wiki](https://github.com/KindleModding/kindlemodding.github.io)：docs/11–15 的资料主要来源，CC BY-NC 4.0。
- [KindleTool](https://github.com/KindleModding/KindleTool)：docs/13 的机型表与 OTA 知识。
- [LibrarianSync](https://github.com/NiLuJe/librariansync)：ccat `/change` 接口与 AuthToken。
- [kindle-auto-collections](https://github.com/poketjomon/kindle-auto-collections)：cc.db 结构。
- MobileRead [t=357149](https://www.mobileread.com/forums/showthread.php?t=357149)：「云端不可用」弹窗的来源分析。
- [hermes-dec](https://github.com/P1sec/hermes-dec)、[CFR](https://www.benf.org/other/cfr/)。
- [Kindle Comic Converter (KCC)](https://github.com/ciromattia/kcc)：`mangaconv/kcc_lite.py` 的裁边、去页码、跨页拆分算法移植自 KCC。

## License

GPL-3.0-or-later（见 [LICENSE](LICENSE)）。`kcc_lite.py` 移植自 KCC 的 GPLv3 代码，所以整个仓库从 MIT 改为 GPL。

> ⚠ `docs/11`–`docs/15` 是对 [KindleModding Wiki](https://kindlemodding.org/)（**CC BY-NC 4.0**）的
> 整理与重新表述，内容为事实性的技术资料，未逐字复制原文。若要把这几篇文档单独再分发或用于商业用途，
> 需同时遵守 CC BY-NC 4.0 的署名与非商业条款。
