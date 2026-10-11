# 13 Kindle 系统参考资料

> 改 Kindle 之前先搞清楚「文件放在哪、谁读它、怎么让它重新读」。
> 本文汇总分区布局、`appreg.db` / `cc.db`、搜索栏调试命令、用户态启动流程和机型代号。
>
> 内容整理自 [KindleModding Wiki](https://kindlemodding.org/)（CC BY-NC 4.0）并与本仓库在
> Oasis 3 / FW 5.15.1.1 上的实测经验合并。凡未实测的都以「推测」或「wiki 记录」标出。

## 1 分区与目录

| 路径 | 性质 | 说明 |
|---|---|---|
| `/` | **只读**系统分区 | 升级或重刷固件会**整个替换**。要改先 `mntroot rw`，改完 `mntroot ro`。补丁、upstart 任务都放这儿，所以升级后要重做 |
| `/mnt/us` | 用户分区（vfat 类） | 就是 USB 连电脑看到的那个盘。**没有符号链接、没有执行权限位**。书、KUAL 扩展、自己的脚本放这里，升级不丢 |
| `/var/local` | 可写数据分区 | 数据库和状态：`cc.db`、`appreg.db`、`LIBRARY_CONFIG`、`mesquite/`、`logs/` |
| `/opt/amazon/ebook` | 只读 | Java 框架本体：`booklet/*.jar`、`lib/*.jar`、`config/` |
| `/app` | 只读 | 新版界面：`KPPMainApp`（React Native）、`lib/libKSDKLibrary.so`、`kpp_app_cmds.json` |
| `/etc/upstart` | 系统分区 | 开机任务定义，改前 `mntroot rw`，改完给 init 发 SIGHUP（0.6.6 没有 `initctl`） |

用 USB 存储模式连电脑时 `/mnt/us` 会被**卸载**，在上面跑的程序会出错（[09 第 2 节](09-lab126-internals.md#2-upstart)、
`com.lab126.volumd` 的 `driveModeState` / `userstoreReadyToUnMount` 就是在处理这件事）。

## 2 appreg.db

`/var/local/appreg.db` 是一个 sqlite3 数据库，存的是**「什么文件由什么程序处理」**。
它决定了：新文件用哪个 extractor 索引、点开一本书用哪个应用、一个 booklet 怎么启动。

```sh
sqlite3 -readonly /var/local/appreg.db ".tables"
```

### 2.1 表结构

| 表 | 作用 |
|---|---|
| `associations` | **最重要的一张表**。把 handler 关联到内容类型或接口 |
| `handlerIds` | 所有已注册的 handler（单列） |
| `interfaces` | 接口类型（单列）。已知 8 种：`kaf-service`、`todo`、`application`、`download`、`detail`、`extractor`、`indexer`、`amazon-messaging` |
| `extenstions` | 扩展名 → MIME 类型（**`extenstions` 这个拼写错误是数据库里的原始拼写**） |
| `mimetypes` | 和 `extenstions` 内容相似，用途未知 |
| `properties` | handler 的配置项，**dconf 的值也存在这里** |

> ⚠ 系统里这类拼写错误不止一处：`extenstions`、`enableDispalyEvents`、
> WAF `config.xml` 里的 `Reqeust`。查资料时按固件的原始拼写搜，别「纠正」它。

### 2.2 associations：谁处理什么

四列 `handlerId | interface | contentId | defaultAssoc`。

**内容索引**（`interface='extractor'`）——决定哪些扩展名能被登记进书库：

| contentId | handlerId |
|---|---|
| `GL:*.txt`、`GL:*.run_persistence`、`GL:*.run_hotfix` | `com.lab126.generic.extractor` |
| `GL:*.mobi`、`GL:*.pobi`、`GL:*.prc`、`GL:*.azw` | `com.lab126.mobi.extractor` |
| `GL:*.azw3` | `com.lab126.mobi8.extractor` |
| `GL:*.pdf` | `com.lab126.pdf.extractor` |
| `GL:*.tpz`、`GL:*.azw1` | `com.lab126.topaz.extractor` |
| `GL:*.yj`、`GL:*.azw8`、`GL:*.kfx` | `com.lab126.yj.extractor` |
| `GL:*.aax` | `com.lab126.audible.extractor` |
| `GL:*.sh` | `com.notmarek.shell_integration.extractor` |
| `GL:*.DO_NOT_DELETE` | `org.kindlemodding.hd_extractor` |

**打开文件用哪个应用**（`interface='application'`）：

| contentId | handlerId |
|---|---|
| `MT:application/pdf`、`MT:application/x-mobi8-ebook`、`MT:application/x-mobipocket-ebook`、`MT:application/x-topaz-ebook`、`MT:application/x-kfx-ebook` | `com.lab126.booklet.reader` |
| `MT:application/x-mobipocket-subscription*` | `com.lab126.booklet.periodicals` |
| `MT:application/x-amazon-testrunner` | `com.lab126.booklet.test` |

> 这张表解释了两件事：
> 1. **`.sh` 能被当成书点开运行**，靠的就是 `sh_integration` 注册的 `GL:*.sh` 关联（见 [14 Scriptlets](14-kindle-homebrew-and-dev.md#2-scriptlets)）。
> 2. 本仓库功能 5 把 epub 转成 AZW3 是有道理的：**epub 不在 extractor 表里**，epub 文件丢进 documents 也不会被登记成书。转换后是 `.azw3`，命中 `com.lab126.mobi8.extractor`。

`com.lab126.scanner` 就是读这张表来决定用哪个 extractor 的（见 [11 第 4.8 节](11-lipc-and-services.md#48-内容索引indexer--scanner--ccat)）。

### 2.3 properties：booklet 怎么被启动

`properties` 表存 handler 的配置。以主页 booklet 为例（wiki 记录）：

| name | value |
|---|---|
| `lipcId` | `com.lab126.booklet.home` |
| `jar` | `/opt/amazon/ebook/booklet/home.jar` |
| `default-chrome-style` | `TSB` |
| `maxExecTime` / `maxLoadTime` / `maxGoTime` | `22` / `40` / `30` |
| `supportedOrientation` | `U` |
| `defaultContext` | `context=0` |
| `extend-start` | `Y` |
| `detailFactoryPath` | `/opt/amazon/ebook/booklet/home.jar` |
| `detailFactoryClass` | `com.amazon.kindle.home.detail.HomeDetailViewFactory` |
| `whisper-touch` / `asr` | `supported` |

`lipcId` 就是 appmgrd 用来找这个应用的 lipc 服务名——所以 `app://com.lab126.booklet.home` 这个 URI 能工作。

**extractor 的属性也是在这里注册的**，只有两行：

| handlerId | name | value |
|---|---|---|
| `com.lab126.mobi8.extractor` | `lib` | `/usr/lib/ccat/libmobi8extractorE.so` |
| `com.lab126.mobi8.extractor` | `entry` | `load_mobi8_extractor` |

也就是说，**想给 Kindle 加一种新文件类型，就是往 `appreg.db` 里插一行 associations + 两行 properties**（`lib` + `entry`），再提供一个 `.so`。

而浏览器的启动命令存在同一张表里（本机实测）：

```
com.lab126.browser | command | /usr/bin/mesquite -l com.lab126.browser -c file:///var/local/mesquite/browser/ -j
```

### 2.4 dconf：藏在 properties 里的配置

`properties` 表里 `handlerId` 为 `dcc` / `dcd` 的行就是常说的 **dconf**（`c` = 客户端配置，`d` = 默认值）：

| handlerId | name | value |
|---|---|---|
| `dcc` | `wan.proxy.non_proxy_hosts.http` | `*.amazon.com.au\|*.amazon.com\|…`（一长串直连域名） |
| `dcd` | `url.store` | `https://www.amazon.com/gp/digital/juno/index.html` |
| `dcd` | `url.kindlestore.kcw.metrics` | `/mn/kcw/workflow/log-metrics` |
| `dcd` | `url.unifiedsearch.kindlestore.voltron` | `$WEBSITE/kindle-dbs/ekws/?action=search&…` |

改这些值可以改商店/搜索指向的地址。WAF 里也能通过 `kindle.dconfig` 读（见 [15](15-wafs-and-mesquite.md#47-kindledconfig)）。

## 3 cc.db：书库看到的内容

`/var/local/cc.db` 是内容目录，由 `com.lab126.ccat` 管。书库里出现什么，取决于这张表。

```sh
sqlite3 -readonly /var/local/cc.db \
  "select p_titles_0_nominal, p_location, p_cdeType, p_type from Entries where p_type='Entry:Item' limit 20"
```

| 列 | 含义 |
|---|---|
| `p_location` | 文件路径（`/mnt/us/documents/…`） |
| `p_titles_0_nominal` | 书名 |
| `p_cdeType` | 内容类型，来自 MOBI/AZW3 的 EXTH 记录 501：`EBOK` 电子书 / `PDOC` 文档 / `EBSP` 样章… |
| `p_type` | 条目类型：`Entry:Item`、`Entry:Item:Dictionary`、`Entry:Item:Comic`… |

两个推论（本机实测）：

- **筛选器里的「电子书 / 文档」看的是 `p_cdeType`。** 侧载的书都是 `PDOC`，因为 PDF、TXT 没有 EXTH 501。
- **「漫画」筛选查的是 `p_type = 'Entry:Item:Comic'`**，推测只有商店漫画才有这个值。

文件放进 `documents` 后没被索引时，把它移出再移回来比等 `com.lab126.scanner` 自己扫快。
想要主动触发：

```sh
lipc-set-prop com.lab126.scanner doFullScan 1
lipc-get-prop com.lab126.scanner fullScanStatus
lipc-set-prop com.lab126.scanner reScanFile "/mnt/us/documents/某书.azw3"
```

## 4 搜索栏调试命令

在书库搜索栏输入 `;命令` 回车就能执行。命令不一定以 `;` 开头（`freset` 就没有）。

**定义位置**（三个 JSON 文件）：

| 文件 | 内容 | 备注 |
|---|---|---|
| `/app/kpp_app_cmds.json` | 新版界面的命令 | 其中 `/app/tools/*` **只在内部测试机（prototype Kindle）上存在**，零售机执行会失败 |
| `/usr/share/app/kpp_sys_cmds.json` | 系统级命令 | 零售机可用，下面这张表主要来自这里 |
| `/usr/share/webkit-1.0/pillow/debug_cmds.json` | 旧 pillow 的命令 | **新版固件已经不存在这个文件** |

参数按 shell 的方式传给脚本：`;test 1 2 3` 会把 `$1 $2 $3` 传成 `1 2 3`。

### 4.1 系统命令（零售机可用）

| 命令 | 实际执行 | 说明 |
|---|---|---|
| `;dm` | `/usr/bin/dm.sh` | **把系统日志、消息打包导出到 `/mnt/us/documents`**。排错第一选择 |
| `;711` | `/usr/bin/711.sh` | WiFi 信息 |
| `;611` | `/usr/bin/611.sh` | WAN（3G）信息 |
| `;411` | `/usr/bin/411.sh` | 服务器信息 |
| `;311` | `/usr/bin/311.sh` | 改运营商设置 |
| `;st` | `/usr/bin/dateTime.sh` | 设置时间，等价 `date -D "%F %H:%M" +%s -d "$1 $2"` |
| `;shpm` | `/usr/sbin/shipping_mode` | 进入运输模式 |
| `;un` / `;uns` | `usbnetwork.sh start/stop` | 启停 USBNetwork |
| `;debugOn` / `;debugOff` | `/usr/bin/debugOn.sh` / `debugOff.sh` | 调试开关 |
| `;bsalogon` / `;bsalogoff` | `/usr/bin/bsaLogOn.sh` / `bsaLogOff.sh` | BSA 日志 |
| `;wmtlog` | `/usr/bin/wmtLog.sh` | WMT 日志 |
| `;enter_demo` / `;exit_demo` | `createDemoModeFlagFile.sh` / `deleteDemoModeFlagFile.sh` | 进出演示模式 |
| `;uzb` / `;duzb` | `enableUSBInDemo.sh` / `disableUSBInDemo.sh` | 演示模式下开关 USB 文件管理 |
| `;dsts` | `startSettingsInDemo.sh` | 演示模式下打开设置 |
| `;vfd` | `verifyDemo.sh` | 演示模式校验 |
| `;updateCamp` / `;wwreset` / `;demo` / `;chkup` / `;ledon` | 对应脚本 | 杂项 |
| `freset` | `/bin/sh -c /usr/sbin/factory_reset` | **恢复出厂。没有确认步骤，别手滑** |

### 4.2 `;log` 与热修复

`;log` 是 KUAL / MRPI 的安装入口。早期固件自带这个命令，后来由热修复（hotfix）自己注册（见 [14](14-kindle-homebrew-and-dev.md#1-hotfix)）。

本仓库前置条件里提到的 `;log runme` 就是这一族：以 root 执行 `/mnt/us/RUNME.sh`，
是**没有 SSH 时的救命通道**——白屏也能用，输出重定向到 `/mnt/us/xxx.log` 再用 USB 取回。

### 4.3 内部测试机专属命令（零售机无法使用）

`/app/tools/*` 只在内部机上存在。列几个有代表性的（完整表见 [wiki](https://kindlemodding.org/kindle-hacking/debug-commands.html)）：

| 命令 | 作用 |
|---|---|
| `;term` | 打开终端 |
| `;ui` | 切换 UI 层级 |
| `;kppreader` / `;javareader` / `;defaultreader` | 强制用 KPP 阅读器还是 Java 阅读器 |
| `;kppchrome2` / `;kppstore` | 切换 chrome 样式 |
| `;debugon` / `;debugoff` | 新版界面的调试菜单 |
| `;enable2x` / `;disable2x` / `;default2x` | 2 倍缩放 |
| `;lightbox` / `;odac` / `;kidskpp` / `;kidsjava` | 各种模式切换 |
| `;enableHiddenPDF` / `;disableHiddenPDF` | **PDF 隐藏（非公开）渲染模式**，与功能 4 的 PDF 全屏同一领域 |
| `;framer` / `;launcher` / `;stroke` / `;fabricDemo` | 内部工具 |

> `/app/tools/enableHiddenPDF.sh` 这个命令名值得记一下：固件里本来就有 PDF 相关的实验开关，
> 只是零售机不给这个入口。功能 4 走的是改 jar，而不是这个命令。

### 4.4 用 lipc 触发

不想敲搜索栏（比如脚本里）可以走 `com.lab126.system`：

```sh
lipc-set-prop com.lab126.system executeDebugCommand "711"
```

## 5 越狱到底改了什么

拿到 root 之后，一次越狱做的事情本身很少（wiki 总结）：

1. 把根文件系统挂成可写（`mntroot rw`）。
2. 在 `/etc/uks`（或 `/etc/uks.sqsh` 这个 squashfs）里装上**自制签名公钥**。
   有了它，Kindle 才肯安装自制签名的 OTA 包——这是热修复能装进去的前提。
3. 在根目录创建 `/PRE_GM_DEBUGGING_FEATURES_ENABLED__REMOVE_AT_GMC`，**打开调试功能**。
   （文件名本身就是亚马逊的注释：「发布前删掉」。`/usr/bin/delayShot.sh` 只在存在这个文件时才工作，见 [09 第 7 节](09-lab126-internals.md#7-系统自带的小工具)。）
4. 在根目录创建 `/MNTUS_EXEC`，让 `/mnt/us` 以允许执行的方式挂载（wiki 记录）。
5. 把根文件系统挂回只读。

这几步做完只是「准备好了」，真正的落地由 [hotfix](14-kindle-homebrew-and-dev.md#1-hotfix) 完成。

### 5.1 用户态启动流程

Kindle 的用户态启动用的是 **upstart**（0.6.6，很老）。所有任务定义在 `/etc/upstart/*.conf`。

```
init.exe (upstart)
├─ Xorg                        X 显示服务器
│  ├─ framework（cvm）          Java 框架 com.lab126.kaf
│  ├─ kppmainapp               主页 + 图书馆（React Native / Hermes）
│  ├─ pillow                   系统弹窗、状态栏、快捷设置（WebKit）
│  ├─ stored / 浏览器           都是 mesquite（WebKit 外壳）的实例
│  └─ winmgr                   窗口管理、屏保、标题栏
├─ appmgrd                     应用生命周期
├─ powerd                      电源、屏保、休眠
├─ deviced、btfd、phd …
└─ 你装的 upstart 任务
```

**依赖链很重要**：Xorg 一崩，framework、kppmainapp、pillow、winmgr 全部跟着退出。pillow 会被 upstart 自动拉起，**framework 不会**。症状和恢复见 [09 第 1 节](09-lab126-internals.md#1-进程和它们的依赖)。

常用触发条件：

```sh
start on started framework
start on starting kppmainapp
stop on (stopping framework or ota-update)
respawn
respawn limit 5 300        # 5 分钟内退出超过 5 次就不再拉起
```

**想自己画出完整启动图**：KindleModding 有一份从 `PW6` 的 `/etc/upstart` 生成的流程图，生成脚本在
[`static/kindle-hacking/upstart-diagram.py`](https://github.com/KindleModding/kindlemodding.github.io/blob/main/static/kindle-hacking/upstart-diagram.py)。
它遍历 `.conf` 文件，解析每一行的 `start on …`，把 `emits` / `f_emit` / `initctl emit` 声明的**事件名**映射回发起它的任务，
最后输出 Mermaid `flowchart`。把 Kindle 的 `/mnt` 挂到本地跑一遍，就能得到自己固件版本的启动图。

**本仓库用到的 upstart 知识**：功能 2、5、7、8、10 都是往 `/etc/upstart/` 装任务实现的，所以**升级/重刷固件后要重新开启**（系统分区被整个替换）。

## 6 机型识别

移植补丁时第一件事是确认机型。Kindle 社区用**代号**（nickname）交流，固件内部用
**platform / board**（主板名）和 **device code**（序列号前缀）。

```sh
# 设备类型与 GUID
lipc-get-prop com.lab126.KindleIdentity deviceType
lipc-get-prop com.lab126.KindleIdentity GUID

# USID（就是序列号）、主板、面板、固件版本
lipc-get-prop com.lab126.system usid
lipc-get-prop com.lab126.system boardid
lipc-get-prop com.lab126.system panelCode
lipc-get-prop com.lab126.system version
```

也可以在 设置 → 设备选项 → 设备信息 里看序列号，**前 3 位就是 device code**（老机型是前 2 位十六进制）。

### 6.1 型号表

本仓库验证机是 **KOA3（Kindle Oasis 10th Generation）**。
数据来自 [KindleTool](https://github.com/KindleModding/KindleTool) 的机型表，经 KindleModding Wiki 整理。

| 代号 | Amazon 名称 | 发布 | 出厂固件 | 平台 / 主板 | 序列号前缀 |
|---|---|---|---|---|---|
| K1 | Kindle (1st Generation) | 2007 | ??? | N/A / Fiona | `01` |
| K2 | Kindle (2nd Generation) | 2009 | ??? | Mario/MarioDeprecated / Mario | `02, 03` |
| DX | Kindle DX (2nd Generation) | 2009 | ??? | ??? / Nell/NellSL/NellWW | `04, 05, 09` |
| K3（K3/K3G） | Kindle Keyboard (3rd Generation) | 2010 | ??? | Luigi / Shasta | `06, 08, 0A` |
| K4（K4/K4S） | Kindle (4th Generation) | 2011 | ??? | Yoshi / Tequila | `0E` |
| KT（KT/K5） | Kindle Touch (4th Generation) | 2011 | ??? | Yoshi / Whitney | `0F, 10, 11, 12` |
| PW（PW/PWG） | Kindle Paperwhite (5th Generation) | 2012 | 5.2.0 | Wario / Pinot | `1B, 1C, 1D, 1F, 20, 24` |
| K4（K4/K4B） | Kindle (5th Generation) | 2012 | ??? | Yoshi / Sauza | `23` |
| PW2（PW2/PW2J） | Kindle Paperwhite (6th Generation) | 2013 | 5.4.0 | Wario / Pinot | `17, 5A, 5F, 60, 61, 62, D4, D5, D6, D7, D8, F2, F4, F9` |
| KV | Kindle Voyage (7th Generation) | 2014 | 5.5.0 | Wario / Icewine | `13, 2A, 4F, 52, 53, 54` |
| KT2（KT2/BASIC） | Kindle (7th Generation) | 2014 | 5.5.0 | Wario / Bourbon | `C6, DD` |
| PW3 | Kindle Paperwhite (7th Generation) | 2015 | 5.6.1 | Wario / Muscat | `0G1, 0G2, 0G4, 0G5, 0G6, 0G7, 0KB, 0KC, 0KD, 0KE, 0KF, 0KG, 0LK, 0LL, TTT` |
| KOA | Kindle Oasis (8th Generation) | 2016 | 5.7.1.1 | Duet / Whisky | `0GC, 0GD, 0GR, 0GS, 0GT, 0GU` |
| KT3 | Kindle (8th Generation) | 2016 | 5.8.0 | Heisenberg / Eanab | `0DU, 0K9, 0KA` |
| KM | Kindle x Migu | 2017 | 5.7.2.8 | Heisenberg / Eanab | `0NG` |
| KOA2 | Kindle Oasis (9th Generation) | 2017 | 5.9.0.6 | Zelda / Cognac | `0LM, 0LN, 0LP, 0LQ, 0P1, 0P2, 0P6, 0P7, 0P8, 0S1, 0S2, 0S3, 0S4, 0S7, 0SA` |
| PW4 | Kindle Paperwhite (10th Generation) | 2018 | 5.10.0.1/5.10.0.2 | Rex / Jaeger | `0PL, 0PP, 0T1…0T7, 0TJ…0TN, 102, 103, 16Q…16V` |
| KT4 | Kindle (10th Generation) | 2019 | 5.1x.y | Rex / Moonshine | `0VB, 0WF, 0WG, 0WH, 0WJ, 10L` |
| **KOA3** | **Kindle Oasis (10th Generation)** | **2019** | **5.12.0** | **Zelda / Stinger** | **`0WL, 0WM, 0WN, 0WP, 0WQ, 11L`** |
| PW5（PW5/PW5SE） | Kindle Paperwhite (11th Generation) | 2021 | 5.14.0 | Bellatrix / Malbec | `1LG, 1PX, 1Q0, 1VD, 219, 21A, 2BH, 2BJ, 2DK` |
| KT5 | Kindle (11th Generation) - 2022 Release | 2022 | 5.15.0 | Bellatrix / Cava | `1XH, 22C, 22D, 23A, 25T, 2AP, 2AQ` |
| KS | Kindle Scribe - 2022 Release | 2022 | 5.16.0 | Bellatrix3 / Barolo | `227, 23L, 23M, 263, 270, 27J, 2BL, 2BM` |
| KT6 | Kindle (11th Generation) - 2024 Release | 2024 | 5.16.20 | Bellatrix / Rossini | `3KM, 3L2…3L6, A89` |
| PW6 | Kindle Paperwhite (12th Generation) - 2024 Release | 2024 | 5.17.0 | Bellatrix4 / Sangria | `33W, 33X, 346, 349, 3H3, 3H5, 3H8, 3HA, 3J5, 3JS` |
| KS2 | Kindle Scribe - 2024 Release | 2024 | 5.17.0 | Bellatrix3 / Pisco | `3UV, 3V0, 3V1, 3X3, 3X4, 3X5, 41D, 41E` |
| CS | Kindle Colorsoft (1st Generation) | 2024 | 5.18.0 | Bellatrix4 / Seabreeze | `34X, 3H2…3H9, 3HB, 3J6, 3JT, 455, 456, 4EP` |
| KS3 | Kindle Scribe (3rd Generation) | 2025 | 5.19.x | Platpa6 / Paloma | `454, 4F8, 4FA, 4PE, 4PG, 4PL` |
| KSC | Kindle Scribe Colorsoft (1st Generation) | 2025 | 5.19.x | Platcs8 / Calvados | `46P, 4F9, 4FB, 4PF, 4PH, 4VX` |

**platform 这一列比代号有用**：`duet` / `zelda` / `rex` / `bellatrix` 是固件内部的平台名，
`/app` 目录结构、React Native 界面（KPP）的引入时间都跟它相关。
本仓库补丁的特征码是围绕 **zelda 平台 + FW 5.15.x** 写的。

> PW4 及更早的部分机型序列号前缀很多，上表做了折叠。完整对照（含 KindleTool 名称与 Amazon 型号 ID）
> 见 [wiki 的 Models Table](https://kindlemodding.org/kindle-hacking/models-table.html)，那张表是可交互的。

### 6.2 移植补丁时要看什么

1. **platform / board 是否相同**——决定 `/app`、`/opt/amazon/ebook` 的布局。
2. **固件版本**——决定二进制里的偏移和特征码（本仓库所有 `tools/patch_*.py` 都会先校验，不匹配就不动手）。
3. **是否有 `/app`（KPP 界面）**——PW4 及更早沒有 React Native 界面，功能 1、3、8 不适用。
4. **屏幕分辨率与方向**——`com.lab126.winmgr` 的 `orientation`，功能 4（PDF 全屏）改的边距是按屏算的。

## 7 固件与 OTA

### 7.1 手动下载官方固件

亚马逊没有删除历史固件文件，**改一下链接就能下任意版本**（wiki 记录）。下载后：

1. Kindle 开飞行模式。
2. USB 连电脑，把 `.bin` 拷到 Kindle 根目录（和 `documents` 同级）。
3. 弹出、拔线。
4. 设置 → 右上角菜单 → 更新您的 Kindle。

各机型最后一个「可越狱」固件的链接见
[wiki — Manually Downloading Firmware Update Files](https://kindlemodding.org/firmware-and-flashing/downloading-updates.html)。
KOA3 的对应文件是 `update_kindle_all_new_oasis_v2_5.18.2.bin`（**注意这不是最后一个版本，只是 wiki 认为最后一个可越狱版本**）。

本仓库的定位是 **5.15.1.1 + LanguageBreak**，比这个链接旧。降级见
[wiki — Downgrading Your Kindle](https://kindlemodding.org/firmware-and-flashing/downgrading/)。

### 7.2 别让它自动升级

Kindle 会在这些时机悄悄下载固件：打开商店、注册账号、**短暂连上 Wi-Fi**、联网状态下重启。
升级会换掉整个系统分区，补丁和 upstart 任务全部失效。

已知的抑制手段：

| 手段 | 原理 | 备注 |
|---|---|---|
| 保持磁盘几乎写满（只剩 50–90 MB） | 更新包下不完，装不上 | 社区流行做法，靠 [Kindle-Filler-Disk](https://github.com/bastianmarin/Kindle-Filler-Disk/) 灌垃圾文件。11 代及以后用 MTP 不是 U 盘，脚本无效，得手动拷。越狱并关掉 OTA 后记得删掉 `fill_disk` 目录 |
| 改掉/占住 OTA 二进制 | 让检查更新的程序无法运行 | 即 `renameotabin` 那一类做法，见 [wiki — Disabling OTA Updates](https://kindlemodding.org/jailbreaking/Legacy/post-jailbreak/disable-ota.html) |
| 一直开飞行模式 / 不注册 | 最彻底 | 假注册（fakereg）设备本来就不联网 |

> ⚠ 无论用哪种方法，**每次都去 Kindle 根目录看看有没有 `*.bin` 或 `update.bin.tmp.partial`**，
> 有就删掉。半下载的更新包留在那儿，下次条件满足就会继续。

### 7.3 OTA 包与签名

固件更新包和 hotfix 都是 **OTA 格式（`.bin`）**。它能被安装，是因为 Kindle 校验了包里的签名——
越狱第 2 步装的自制公钥就是干这个的。自制 OTA 的私钥是公开的，包含在
[KindleTool](https://github.com/KindleModding/KindleTool) 里（`KindleTool/create.c`）。

自己打包固件的流程（`kindletool create …`）不在本文范围内，见 KindleTool 仓库。

## 8 参考资料

- [KindleModding Wiki](https://kindlemodding.org/)：本文的主要来源，CC BY-NC 4.0。
  - [Appreg.db](https://kindlemodding.org/kindle-hacking/appreg.html)
  - [Debug Commands](https://kindlemodding.org/kindle-hacking/debug-commands.html)
  - [Usermode Boot Process](https://kindlemodding.org/kindle-hacking/usermode-boot-process.html)
  - [Models Table](https://kindlemodding.org/kindle-hacking/models-table.html)
  - [Manually Downloading Firmware Update Files](https://kindlemodding.org/firmware-and-flashing/downloading-updates.html)
- [KindleTool](https://github.com/KindleModding/KindleTool)：机型表、OTA 打包与解包。
- [09 Kindle 系统内部（com.lab126）笔记](09-lab126-internals.md)：本机实测的进程、upstart、文件与数据库。
- [11 lipc 与 com.lab126 服务](11-lipc-and-services.md)：用 lipc 触发上面这些行为。
