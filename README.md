# kindle-tweaks

让越狱 Kindle 更好用的一组小改造，主要针对**未注册 / fakereg 假注册**的机器。所有功能集中在一个 KUAL 菜单「Kindle Tweaks」里，可以单独开关。

*A collection of tweaks for jailbroken Kindles (especially unregistered / fake-registered ones), managed from a single KUAL menu: remove the "cloud unavailable" nag, auto-build collections from folders, unlock the Collections view, and full-screen PDF (no footer, no margins). Docs are in Chinese; scripts are self-explanatory.*

> 验证设备：Kindle Oasis 3（10th gen），FW **5.15.1.1**，LanguageBreak 越狱 + KUAL + [fakereg](https://www.mobileread.com/forums/showpost.php?p=4122357&postcount=125)。
> 其他机型和固件的原理大概率相同，但偏移和特征码可能不同。脚本都会先校验，不匹配就不动。

## 功能

| # | 功能 | 解决的问题 | 文档 |
|---|---|---|---|
| 1 | 去掉「云端不可用」弹窗 | 假注册后每次进书库都弹「云端不可用，您必须注册 kindle…」 | [docs/01-cloud-popup.md](docs/01-cloud-popup.md) |
| 2 | 文件夹 → 收藏夹自动同步 | Kindle 不认文件夹；未注册时「新建收藏夹」是灰色的 | [docs/02-folder-collections.md](docs/02-folder-collections.md) |
| 3 | 解锁「查看选项 → 收藏夹」视图 | 收藏夹里的书仍在书库第一层平铺；该视图在未注册时是灰色的 | [docs/03-collections-view.md](docs/03-collections-view.md) |
| 4 | PDF 全屏 | PDF 底部常驻阅读百分比、四周有白边，设置里关不掉 | [docs/04-pdf-fullscreen.md](docs/04-pdf-fullscreen.md) |
| 5 | epub 充电时自动转换 | Kindle 打不开 epub。大漫画用精简移植的 KCC 转成全屏 PDF；文字书用 KindleGen（经 qemu 在 Kindle 上运行）转成 mobi；小漫画可按目录手动转 | [docs/05-manga-convert.md](docs/05-manga-convert.md) |
| 6 | 屏保开机随机排序开关 | linkss 开机时重排所有屏保，图多时开机很慢 | （菜单里直接切换） |

## KUAL 菜单

```
Kindle Tweaks
├─ 去除「云端不可用」弹窗 [已开启]   → 开启 / 关闭（还原原版）
├─ 解锁「查看选项→收藏夹」 [已开启] → 开启 / 关闭（还原原版）
├─ PDF 全屏（无底栏无边距） [已开启] → 开启 / 关闭（还原原版）
├─ 文件夹收藏夹 [自动同步已开启]     → 立即同步 / 开启自动同步 / 关闭自动同步 / 删除所有自动生成的收藏夹
├─ epub 自动转换 [已开启]           → 进度 / 开启 / 关闭 / 立即转换 / 规则 / 按目录转换（动态列出目录）
├─ 屏保开机随机排序（linkss） [已关闭] → 开启 / 关闭
├─ 升级固件后：全部补丁重新开启
└─ 全部补丁还原原版
```

菜单项里的 `[状态]` 是按系统文件实际的 md5 算出来的，每次操作后自动刷新。缺补丁文件的功能会显示「缺补丁文件」，不影响其他功能。

## 目录

```
extensions/kindletweaks/    KUAL 扩展，整个目录拷到 Kindle 的 extensions/ 下
  tweak.sh                  所有开关的实现（KUAL 和 SSH 共用），生成 menu.json
  foldercoll/               文件夹 → 收藏夹（sync.py + upstart 任务模板）
  mangaconv/                漫画 epub → PDF（kcc_lite.py 移植自 KCC，mangaconv.py + upstart 任务模板）
  files/                    补丁用的系统文件 *.orig / *.patched（自己生成，不进 git）
tools/                      在电脑上生成 .patched
  patch_kpp.py              KPPMainApp.js.hbc（功能 1，需要 hermes-dec）
  patch_ksdk.py             libKSDKLibrary.so（功能 3，纯 Python）
  pdf_fullscreen/build.py   3 个 Java jar（功能 4，需要 JDK 9+）
  fetch_kindlegen.py        下载 KindleGen + qemu-i386-static（功能 5 的 epub→mobi，拷到扩展的 bin/）
docs/                       原理、排查过程、新固件上怎么重做
```

> ⚠ 本仓库**不包含任何亚马逊的原始文件或补丁后的文件**。补丁都是从你自己机器上提取的文件生成的。

## 前置条件

- 已越狱，装好 KUAL 和 MRPI。
- 能在 Kindle 上以 root 执行命令，二选一：
  - [USBNetwork](https://www.mobileread.com/forums/showthread.php?t=225030) 开启 SSH over WiFi（推荐，下文用 `ssh root@<kindle-ip>`）。
  - hotfix 自带的 `;log runme`：在书库搜索栏输入，会以 root 执行根目录的 `RUNME.sh`。
- 功能 2、5 需要 Kindle 上有 Python 3（例如 KUAL 的 python3 扩展，装在 `/mnt/us/python3`，自带 Pillow）。
- 生成补丁需要电脑上有 Python 3；功能 1 还要 [hermes-dec](https://github.com/P1sec/hermes-dec)（`pip install git+https://github.com/P1sec/hermes-dec`），功能 4 还要 JDK 9+。

## 快速开始

```sh
# 0. 装扩展
scp -r extensions/kindletweaks root@<kindle-ip>:/mnt/us/extensions/
F=/mnt/us/extensions/kindletweaks/files

# 1. 从 Kindle 提取原始文件
scp root@<kindle-ip>:/app/KPPMainApp/js/KPPMainApp.js.hbc KPPMainApp.js.hbc.orig
scp root@<kindle-ip>:/app/lib/libKSDKLibrary.so          libKSDKLibrary.so.orig
scp -r root@<kindle-ip>:/opt/amazon/ebook/lib            ebook-lib

# 2. 在电脑上生成补丁版（需要哪个功能就生成哪个）
python tools/patch_kpp.py  KPPMainApp.js.hbc.orig KPPMainApp.js.hbc.patched
python tools/patch_ksdk.py libKSDKLibrary.so.orig libKSDKLibrary.so.patched
python tools/pdf_fullscreen/build.py ebook-lib pdf-out     # 生成 3 对 jar 的 .orig/.patched

# 3. 传到扩展的 files/
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

### 常用命令

**截屏**

```sh
/mnt/us/usbnet/bin/fbgrab /tmp/shot.png    # 读 /dev/fb0，生成 PNG（1264×1680）
scp root@<kindle-ip>:/tmp/shot.png .        # 在电脑上取回
```

**打开书、回主页、电源**

```sh
# 直接打开一本书（文件必须已被书库索引；没索引好就把文件移出 documents 再移回来）
lipc-set-prop com.lab126.appmgrd start "app://com.lab126.booklet.reader/mnt/us/documents/某书.pdf"
lipc-set-prop com.lab126.appmgrd start app://com.lab126.booklet.home    # 回主页
lipc-get-prop com.lab126.appmgrd activeApp                              # 当前前台应用

lipc-set-prop com.lab126.powerd wakeUp 1               # 唤醒
lipc-set-prop com.lab126.powerd powerButton 1          # 模拟按电源键（进/出屏保）
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
grep -iE "VerifyError|NoClassDef|NoSuchMethod" /var/log/messages   # Java 补丁出错时
```

## 升级 / 重刷固件之后

系统分区会被整个替换，所以补丁和自动同步的开机任务都会失效。`extensions/kindletweaks/` 在用户分区，不受影响。

- **固件版本不变**：KUAL →「升级固件后：全部补丁重新开启」，再在「文件夹收藏夹」里重新「开启自动同步」、在「大漫画 epub 转 PDF」里重新「开启」。
- **固件版本变了**：菜单里会显示「文件不匹配」，脚本不会写入。
  1. 用新固件的文件重新生成 `.orig` / `.patched`。
  2. 如果生成脚本找不到特征，按 docs 里的手动方法重新定位。

## 风险与救砖

补丁改的是书库界面程序（功能 1、3）和 Java 阅读器框架（功能 4）。万一改坏，可能出现白屏：

- **临时试用阶段**：长按电源键约 40 秒强制重启，自动恢复。
- **已永久写入**：
  - 能 SSH 就执行 `sh /mnt/us/extensions/kindletweaks/tweak.sh all off`。usbnet 的 SSH 不依赖界面，白屏时一样能连。
  - 不能 SSH 就重刷同版本官方固件（书不会丢）。
- 白屏也可能只是 framework 重启后停在了 KUAL 的空白页，见 [docs/04 第 6 节](docs/04-pdf-fullscreen.md#6-排错笔记)。

请自行承担风险。

## 致谢

- [LibrarianSync](https://github.com/NiLuJe/librariansync)：ccat `/change` 接口与 AuthToken。
- [kindle-auto-collections](https://github.com/poketjomon/kindle-auto-collections)：cc.db 结构。
- MobileRead [t=357149](https://www.mobileread.com/forums/showthread.php?t=357149)：「云端不可用」弹窗的来源分析。
- [hermes-dec](https://github.com/P1sec/hermes-dec)、[CFR](https://www.benf.org/other/cfr/)。
- [Kindle Comic Converter (KCC)](https://github.com/ciromattia/kcc)：`mangaconv/kcc_lite.py` 的裁边、去页码、跨页拆分算法移植自 KCC。

## License

GPL-3.0-or-later（见 [LICENSE](LICENSE)）。`kcc_lite.py` 移植自 KCC 的 GPLv3 代码，所以整个仓库从 MIT 改为 GPL。
