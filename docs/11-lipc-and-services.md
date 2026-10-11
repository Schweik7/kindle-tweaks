# 11 lipc 与 com.lab126 服务

> 系统里所有「进程之间说话」都走 lipc。本仓库的功能 1、3、6、7、8 都是靠 lipc 或改 lipc 对端的行为实现的。
> 本文讲清 lipc 的规则和排查手法，并给出 92 个 `com.lab126.*` 服务的索引；
> 每个服务的完整属性表在 [12 lipc 服务与属性总表](12-lipc-service-catalog.md)。
>
> 服务名、属性名、类型、读写权限来自 [KindleModding Wiki](https://kindlemodding.org/kindle-apps-and-services/) 的 `lipc-probe -a -v` 记录；
> 标注「本机实测」的条目在本仓库的 Oasis 3 / FW 5.15.1.1 上验证过，其余为参考资料，用前请在真机上确认。

## 1 lipc 是什么

`com.lab126.*` 是亚马逊做 Kindle 的部门（Lab126）给系统服务起的名字，所以系统服务和应用的 ID 大多以 `com.lab126.` 开头。

lipc 是 Kindle 自己的进程间通信机制，**建在 DBus system bus 之上**。它只有两种对象：

| lipc 概念 | DBus 里的等价物 |
|---|---|
| 属性（property） | 方法调用（method call），path 固定 `/default` |
| 事件（event） | 信号（signal），path 固定 `/default` |

接口名固定是**服务名本身**，成员名是属性名或事件名。也就是说，一次属性读写落到 DBus 上就是：

```
path=/default  interface=com.lab126.powerd  member=getflIntensityInt
```

### 1.1 属性名的命名规则

`get` / `set` + 属性名 + 类型后缀，具体是读还是写由服务自己注册：

| 后缀 | 含义 | 参数 |
|---|---|---|
| `Int` | 32 位整数属性 | 值直接作为参数 |
| `Str` | 字符串属性 | 值直接作为参数 |
| `Has` | 哈希属性（hasharray） | 基于共享内存里的 GLib `GHashTable`，未完全逆向 |

最后还有一个可选的「调用者名字」参数（比如 `com.lab126.kppsettings`）。

返回值：所有 get/set 都会先返回一个 `uint32` 状态码；get 还会再返回属性值。用 `lipc-get-prop` / `lipc-set-prop` 时这层是透明的。

举两个 `dbus-monitor --system` 抓到的例子（wiki 记录）：

```
method call sender=:1.179 -> dest=com.lab126.powerd serial=1498 path=/default; interface=com.lab126.powerd; member=getflIntensityInt
   string "com.lab126.kppsettings"
method return sender=:1.5 -> dest=:1.179 reply_serial=1498
   uint32 0
   int32 10
```

```
signal sender=:1.21 -> dest=(null destination) serial=4453 path=/default; interface=com.lab126.cmd; member=connectionAvailable
   string "wifi"
   string "internet"
```

后一个就是**事件**：`com.lab126.cmd` 广播「Wi-Fi 已连上，而且能出网」，带两个字符串参数。

### 1.2 发现事件

`lipc-probe` 只列属性和当前值，**不列事件**。找事件有三个办法：

```sh
export PATH=/usr/sbin:/sbin:$PATH

dbus-monitor --system                       # 看所有信号；interface.member 就是「服务.事件」
lipc-wait-event com.lab126.powerd goingToScreenSaver    # 猜一个名字直接等
grep -o 'lipc-wait-event [^ ]* [^ ]*' /app/bin/* 2>/dev/null   # 看程序自己等了什么
```

`lipc-wait-event -m`（持续输出）接管道时输出有缓冲，事件不能及时处理，脚本里要用循环 + 单次等待。

## 2 命令速查

```sh
export PATH=/usr/sbin:/sbin:$PATH     # 非交互 ssh 必须先补 PATH，见 09

lipc-probe -l                       # 列出所有已注册的服务
lipc-probe -v com.lab126.powerd     # 某个服务的属性、类型、当前值（r 可读 / w 可写）
lipc-probe -a                       # 探测全部服务（输出很长，可能要跑一会儿）
lipc-probe -a -v                    # 全部服务 + 全部属性，文档 12 就是这么来的

lipc-get-prop com.lab126.powerd state
lipc-get-prop -i com.lab126.powerd isCharging      # Int 属性建议加 -i

lipc-set-prop    com.lab126.powerd preventScreenSaver 1
lipc-set-prop -i com.lab126.powerd powerButton 1   # Int 属性必须加 -i，否则静默失败

lipc-wait-event    com.lab126.powerd goingToScreenSaver
lipc-wait-event -s 40 com.lab126.appmgrd historyChange     # 最多等 40 秒
lipc-wait-event -m com.lab126.powerd readyToSuspend        # 持续输出
```

**踩坑**（本机实测，另见 [09 第 3 节](09-lab126-internals.md#3-lipc服务之间的通信)）：

- `lipc-set-prop` 对 `Int` 属性**不加 `-i` 会静默失败**，不报错也不生效。这是最容易浪费时间的一个。
- 错误码：`lipc_status=8` / `0x8` 表示服务存在但还没准备好（应用刚启动、未注册）；`0x3 lipcErrNoSuchSource` 表示服务不存在（进程没在跑）。
- 值里带 `[]` 只是 `lipc-probe` 的显示习惯，**读写时不要带方括号**。

### 2.1 把属性和事件用在自己程序里

简单用途直接 fork `lipc-get-prop` / `lipc-set-prop` 最省事。需要频繁读写或者要收事件，就链 `liblipc.so`：

- [openlipc](https://github.com/notmarek/openlipc)：逆向出来的 C 头文件
- [openlipclua](https://github.com/NiLuJe/openlipclua)：Lua 封装

### 2.2 查某个服务是哪个进程

```sh
# 两种写法等价，gdbus 短一些
dbus-send --system --print-reply --dest=org.freedesktop.DBus / org.freedesktop.DBus.GetConnectionUnixProcessID string:com.lab126.btService
gdbus call -y -d org.freedesktop.DBus -o / -m org.freedesktop.DBus.GetConnectionUnixProcessID com.lab126.btService

ps u -p <pid>          # 拿完整命令行
```

## 3 服务索引

92 个服务，按用途分组。⭐ 是本仓库（kindle-tweaks）实际用到的。
换机型或换固件后，用 `python tools/gen_lipc_catalog.py lipc.txt` 重新生成本节和 [文档 12](12-lipc-service-catalog.md)。

<!-- 服务索引：由 tools/gen_lipc_catalog.py 生成，改结构请同步改脚本 -->

### 系统与框架

| 服务 | 职责 | 属性数 |
|---|---|---|
| [`com.lab126.appmgrd`](12-lipc-service-catalog.md#comlab126appmgrd) ⭐ | 应用生命周期管理器：按 URI 启动/切换/暂停应用，维护前台应用状态 | 22 |
| [`com.lab126.booklet`](12-lipc-service-catalog.md#comlab126booklet) | booklet 通用 run/kill 入口 | 2 |
| [`com.lab126.cvm`](12-lipc-service-catalog.md#comlab126cvm) | cvm 进程的日志开关（框架 JVM 的入口） | 2 |
| [`com.lab126.kaf`](12-lipc-service-catalog.md#comlab126kaf) ⭐ | Java 框架（cvm）本体：注册/商店/设置等所有 booklet 的宿主 | 13 |
| [`com.lab126.pmond`](12-lipc-service-catalog.md#comlab126pmond) | 进程/内存监视：超限杀进程、重启 | 14 |
| [`com.lab126.system`](12-lipc-service-catalog.md#comlab126system) ⭐ | 系统信息与全局动作：固件版本、面板波形、时间、截图、VoiceView、调试命令入口 | 26 |
| [`com.lab126.todo`](12-lipc-service-catalog.md#comlab126todo) | 待办队列：系统级异步任务（下载、注册、广告包等）的调度 | 14 |
| [`com.lab126.todo.kaf`](12-lipc-service-catalog.md#comlab126todokaf) | 待办队列在 Java 框架侧的接收端（handleToDoItem） | 1 |
| [`com.lab126.volumd`](12-lipc-service-catalog.md#comlab126volumd) ⭐ | 用户分区（/mnt/us）挂载与空间管理 | 10 |

### 界面与输入

| 服务 | 职责 | 属性数 |
|---|---|---|
| [`com.amazon.kindle.inputMethod`](12-lipc-service-catalog.md#comamazonkindleinputmethod) | 输入法（IME）与原生层的预编辑接口 | 5 |
| [`com.lab126.KIWIBridge`](12-lipc-service-catalog.md#comlab126kiwibridge) | WAF 与原生层之间的 uiQuery 桥 | 2 |
| [`com.lab126.blanket`](12-lipc-service-catalog.md#comlab126blanket) ⭐ | 全屏「毯子」层：语言选择、USB 提示、广告屏保等覆盖界面 | 5 |
| [`com.lab126.blanket.ad_screensaver`](12-lipc-service-catalog.md#comlab126blanketad_screensaver) | 广告屏保毯子层的状态查询 | 2 |
| [`com.lab126.booklet.home`](12-lipc-service-catalog.md#comlab126booklethome) | 主页/图书馆 booklet 的控制入口 | 12 |
| [`com.lab126.chromebar`](12-lipc-service-catalog.md#comlab126chromebar) | 顶部/底部 chrome 栏（搜索栏、活动指示器） | 3 |
| [`com.lab126.imageViewer`](12-lipc-service-catalog.md#comlab126imageviewer) | 图片查看器（无 lipc 属性） | 0 |
| [`com.lab126.keyboard`](12-lipc-service-catalog.md#comlab126keyboard) | 屏幕键盘：语言、布局、显示/隐藏、预编辑串 | 22 |
| [`com.lab126.kwis`](12-lipc-service-catalog.md#comlab126kwis) | KWIS 小部件守护进程 | 1 |
| [`com.lab126.pillow`](12-lipc-service-catalog.md#comlab126pillow) ⭐ | 系统弹窗、状态栏、快捷设置（WebKit 外壳） | 12 |
| [`com.lab126.quickactions`](12-lipc-service-catalog.md#comlab126quickactions) | 快捷操作：飞行模式开关、立即同步 | 2 |
| [`com.lab126.winmgr`](12-lipc-service-catalog.md#comlab126winmgr) ⭐ | 窗口管理器：窗口列表、方向、屏保层、刷新/闪烁控制 | 30 |
| [`com.lab126.winmgr.ligl`](12-lipc-service-catalog.md#comlab126winmgrligl) | winmgr 的 LIGL（墨水屏刷新算法）日志开关 | 1 |

### 网络与同步

| 服务 | 职责 | 属性数 |
|---|---|---|
| [`com.amazon.ebook.util.net.certmanutilities`](12-lipc-service-catalog.md#comamazonebookutilnetcertmanutilities) | 证书管理工具（无 lipc 属性） | 0 |
| [`com.lab126.cmd`](12-lipc-service-catalog.md#comlab126cmd) ⭐ | 网络连接管理：可用接口、当前接口、强制联网 | 9 |
| [`com.lab126.dynconfig`](12-lipc-service-catalog.md#comlab126dynconfig) | 动态配置下发 | 4 |
| [`com.lab126.linux.arm.connectionutilities`](12-lipc-service-catalog.md#comlab126linuxarmconnectionutilities) | 连接工具：WiFi 弹窗/飞行模式的响应入口 | 4 |
| [`com.lab126.refreshCache`](12-lipc-service-catalog.md#comlab126refreshcache) | 定期刷新各类缓存（联网后触发） | 12 |
| [`com.lab126.transfer`](12-lipc-service-catalog.md#comlab126transfer) | 传输队列：下载/上传请求入队与查询 | 14 |
| [`com.lab126.transferService`](12-lipc-service-catalog.md#comlab126transferservice) | 传输进度通知 | 1 |
| [`com.lab126.wifid`](12-lipc-service-catalog.md#comlab126wifid) | WiFi 管理守护进程：扫描、配置文件（profile）、证书、信号强度 | 33 |

### 内容与索引

| 服务 | 职责 | 属性数 |
|---|---|---|
| [`DeviceMessaging.LanguageLayer.MessageResponse`](12-lipc-service-catalog.md#devicemessaginglanguagelayermessageresponse) | 语言层消息响应 | 3 |
| [`com.lab126.LocalizationServices`](12-lipc-service-catalog.md#comlab126localizationservices) | 本地化：词典、内容包语言 | 4 |
| [`com.lab126.archive`](12-lipc-service-catalog.md#comlab126archive) | 云端文档（Archive）同步与待办处理 | 6 |
| [`com.lab126.bookcacher`](12-lipc-service-catalog.md#comlab126bookcacher) | 按需缓存书本资源 | 1 |
| [`com.lab126.ccat`](12-lipc-service-catalog.md#comlab126ccat) | 内容目录（cc.db / ccat）服务 | 3 |
| [`com.lab126.contentpackd`](12-lipc-service-catalog.md#comlab126contentpackd) | 内容包（字体、键盘布局）的安装与挂载 | 7 |
| [`com.lab126.coverArtService`](12-lipc-service-catalog.md#comlab126coverartservice) | 封面提取与缓存 | 4 |
| [`com.lab126.extractor.java`](12-lipc-service-catalog.md#comlab126extractorjava) | Java 提取器的注册与删除 | 4 |
| [`com.lab126.grokservice`](12-lipc-service-catalog.md#comlab126grokservice) | 全文检索（grokservice） | 3 |
| [`com.lab126.indexer`](12-lipc-service-catalog.md#comlab126indexer) ⭐ | 内容索引器：扫描 documents、生成 cc.db 条目 | 8 |
| [`com.lab126.instantSearch`](12-lipc-service-catalog.md#comlab126instantsearch) | 即时搜索与搜索建议 | 4 |
| [`com.lab126.reader.languagelayer`](12-lipc-service-catalog.md#comlab126readerlanguagelayer) | 语言层（生词提示/词典）重置 | 1 |
| [`com.lab126.reader.languagelayer.pinyin`](12-lipc-service-catalog.md#comlab126readerlanguagelayerpinyin) | 拼音语言层重置 | 1 |
| [`com.lab126.reader.qa`](12-lipc-service-catalog.md#comlab126readerqa) | 阅读器字体/行距的快捷设置（QA 用） | 5 |
| [`com.lab126.reader.readingtimer`](12-lipc-service-catalog.md#comlab126readerreadingtimer) | 阅读计时统计 | 2 |
| [`com.lab126.readingstreams`](12-lipc-service-catalog.md#comlab126readingstreams) | 阅读会话流（阅读进度上报） | 5 |
| [`com.lab126.readnow`](12-lipc-service-catalog.md#comlab126readnow) | 「立即阅读」入口：直接打开一本书 | 1 |
| [`com.lab126.scanner`](12-lipc-service-catalog.md#comlab126scanner) ⭐ | 内容扫描器：按 appreg.db 的 extractor 关联识别并登记新文件 | 6 |
| [`com.lab126.stored`](12-lipc-service-catalog.md#comlab126stored) | 商店后台进程（mesquite 实例） | 8 |
| [`com.lab126.yjff`](12-lipc-service-catalog.md#comlab126yjff) | YJ 相关（无 lipc 属性） | 0 |
| [`com.lab126.yjlipclistener`](12-lipc-service-catalog.md#comlab126yjlipclistener) | YJ（KFX）索引开关 | 1 |

### 账号与设备身份

| 服务 | 职责 | 属性数 |
|---|---|---|
| [`AssetOwnership.DeviceSharingUpdated`](12-lipc-service-catalog.md#assetownershipdevicesharingupdated) | 设备共享状态变更消息 | 3 |
| [`AssetOwnership.SMD.Poll`](12-lipc-service-catalog.md#assetownershipsmdpoll) | 资产归属轮询（借阅/共享） | 6 |
| [`HouseholdMessage.Updates`](12-lipc-service-catalog.md#householdmessageupdates) | Household 更新消息 | 3 |
| [`com.amazon.java.messagingservice`](12-lipc-service-catalog.md#comamazonjavamessagingservice) | Amazon 消息服务（s2dm/adm 下行消息） | 3 |
| [`com.lab126.DeviceAuthenticationService`](12-lipc-service-catalog.md#comlab126deviceauthenticationservice) | 设备认证 Cookie 的获取与安装 | 5 |
| [`com.lab126.IdentityService`](12-lipc-service-catalog.md#comlab126identityservice) | 身份令牌（accessToken）的获取与失效 | 3 |
| [`com.lab126.KindleIdentity`](12-lipc-service-catalog.md#comlab126kindleidentity) | 设备类型与 GUID | 2 |
| [`com.lab126.amazonRegistrationService`](12-lipc-service-catalog.md#comlab126amazonregistrationservice) ⭐ | 注册状态：isRegistered、注册/注销令牌 | 7 |
| [`com.lab126.freetime`](12-lipc-service-catalog.md#comlab126freetime) | Amazon Kids+（FreeTime）订阅状态 | 4 |
| [`com.lab126.household`](12-lipc-service-catalog.md#comlab126household) | 家庭/多用户档案（Household & Profiles） | 4 |

### 电源

| 服务 | 职责 | 属性数 |
|---|---|---|
| [`com.lab126.phd`](12-lipc-service-catalog.md#comlab126phd) | 电源/健康相关的计划任务（SPH 调度） | 3 |
| [`com.lab126.powerd`](12-lipc-service-catalog.md#comlab126powerd) ⭐ | 电源管理：屏保、休眠、充电、电源键、前光 | 28 |

### 外设

| 服务 | 职责 | 属性数 |
|---|---|---|
| [`com.lab126.btService`](12-lipc-service-catalog.md#comlab126btservice) | 蓝牙音频可用性查询 | 3 |
| [`com.lab126.btfd`](12-lipc-service-catalog.md#comlab126btfd) | 蓝牙：配对、连接、A2DP、BLE | 28 |
| [`com.lab126.deviced`](12-lipc-service-catalog.md#comlab126deviced) | 设备抽象层：触摸开关、USB 音频等硬件事件 | 3 |
| [`com.lab126.odot`](12-lipc-service-catalog.md#comlab126odot) | ODOT 消息队列（推测与 OTG/配件有关） | 1 |
| [`com.lab126.tphv3`](12-lipc-service-catalog.md#comlab126tphv3) | TPH v3（推测与触控/手势处理有关） | 7 |

### 其他

| 服务 | 职责 | 属性数 |
|---|---|---|
| [`CampaignSync.Invalidate`](12-lipc-service-catalog.md#campaignsyncinvalidate) | 营销活动缓存失效（无 lipc 属性） | 0 |
| [`CampaignSync.Update`](12-lipc-service-catalog.md#campaignsyncupdate) | 营销活动更新消息 | 3 |
| [`DPCService.SettingChanged`](12-lipc-service-catalog.md#dpcservicesettingchanged) | DPC 设置变更消息 | 3 |
| [`com.lab126.JournalingService`](12-lipc-service-catalog.md#comlab126journalingservice) | 日志/日记服务开关 | 1 |
| [`com.lab126.adManager`](12-lipc-service-catalog.md#comlab126admanager) | 广告（Special Offers）管理 | 7 |
| [`com.lab126.adRotationManager`](12-lipc-service-catalog.md#comlab126adrotationmanager) | 屏保广告轮播 | 5 |
| [`com.lab126.bev`](12-lipc-service-catalog.md#comlab126bev) | （无 lipc 属性，作用未知） | 0 |
| [`com.lab126.demd`](12-lipc-service-catalog.md#comlab126demd) | 设备指标（metrics）上报 | 6 |
| [`com.lab126.demoservice`](12-lipc-service-catalog.md#comlab126demoservice) | 演示模式（无 lipc 属性） | 0 |
| [`com.lab126.devicemetrics`](12-lipc-service-catalog.md#comlab126devicemetrics) | 设备指标按类上报 | 13 |
| [`com.lab126.dpm.apps`](12-lipc-service-catalog.md#comlab126dpmapps) | 按应用维度的策略开关（注释/公开笔记等） | 3 |
| [`com.lab126.dpmManager`](12-lipc-service-catalog.md#comlab126dpmmanager) | 设备策略管理：家长控制、限制项、设备密码 | 45 |
| [`com.lab126.dsus`](12-lipc-service-catalog.md#comlab126dsus) | 设备软件更新服务（DSUS）版本上报 | 1 |
| [`com.lab126.fastMetrics`](12-lipc-service-catalog.md#comlab126fastmetrics) | 高优先级指标快报 | 6 |
| [`com.lab126.kindleStatusService`](12-lipc-service-catalog.md#comlab126kindlestatusservice) | 设备状态日志上报 | 3 |
| [`com.lab126.kwis.weblabTreatments`](12-lipc-service-catalog.md#comlab126kwisweblabtreatments) | Weblab 实验开关（KWIS 侧） | 1 |
| [`com.lab126.legalComplianceService`](12-lipc-service-catalog.md#comlab126legalcomplianceservice) | GDPR/合规提示状态 | 1 |
| [`com.lab126.linux.arm.metrics`](12-lipc-service-catalog.md#comlab126linuxarmmetrics) | 指标上报（无 lipc 属性） | 0 |
| [`com.lab126.lxinit`](12-lipc-service-catalog.md#comlab126lxinit) | （无 lipc 属性，作用未知） | 0 |
| [`com.lab126.merchant`](12-lipc-service-catalog.md#comlab126merchant) | 商户/推荐位（shuffle、removeAll） | 3 |
| [`com.lab126.sharing`](12-lipc-service-catalog.md#comlab126sharing) | 分享到社交网络 | 4 |
| [`com.lab126.sph`](12-lipc-service-catalog.md#comlab126sph) | （无 lipc 属性，作用未知） | 0 |
| [`com.lab126.tutorialService`](12-lipc-service-catalog.md#comlab126tutorialservice) | 新手引导状态 | 1 |
| [`com.lab126.wishlist`](12-lipc-service-catalog.md#comlab126wishlist) | 心愿单缓存刷新 | 1 |

## 4 常用服务详解

只挑改 Kindle 时真正会碰到的几个。「推测」表示按属性名推断、本仓库没实测。

### 4.1 com.lab126.powerd（电源）

功能 6（屏保随机排序）、功能 7（调试模式不深度休眠）都靠它。

| 属性 | 类型 | 读/写 | 说明 |
|---|---|---|---|
| `state` | Str | r | 当前状态，`active` / `screenSaver` / … 本机实测 |
| `isCharging` | Int | r | 是否在充电（1/0）。本机实测 |
| `battLevel` | Int | r | 电量百分比。本机实测 |
| `battTemperature` | Int | r | 电池温度原始值（wiki 记录里是 `73`，单位未确认） |
| `battStateInfo` | Str | r | JSON 格式的完整电池信息：`cap`、`charging`、`usb`、`state` |
| `status` | Str | r | 多行状态摘要：当前状态、在该状态停留秒数、`defer_suspend`、`prevent_screen_saver`、电量、是否充电。排查休眠问题先看这个 |
| `preventScreenSaver` | Int | rw | `1` = 禁止进屏保。调试期间保持 SSH 用，用完改回 `0`。本机实测 |
| `powerButton` | Int | w | 模拟按电源键（进/出屏保）。**Int 属性，set 时必须 `-i`**。本机实测 |
| `wakeUp` | Int | w | 唤醒。本机实测 |
| `deferSuspend` | Int | w | 推迟深度休眠，参数是秒数。**只在屏保状态下有效**。功能 7 用的就是它。本机实测 |
| `suspendGrace` | Int | w | 屏保之后允许进入休眠的宽限期（推测） |
| `abortSuspend` / `sendPendingResume` / `addSuspendLevels` / `deferRestart` | Int | w | 休眠流程的几个干预点，未实测 |
| `shutdownAlertResponse` | Str | w | 关机提示弹窗的应答 |
| `touchScreenSaverTimeout` | Int | w | 触摸后重新进屏保的等待时间（推测） |
| `rtcWakeup` / `rtcWakeup2` | Int / Str | w | 定时唤醒（推测） |
| `flIntensity` | Int | rw | 前光亮度 |
| `flAuto` | Int | rw | 自动亮度开关 |
| `flMaxIntensity` / `flRawIntensity` / `flTurboBrightnessIntensity` | Int | r | 前光上限 / 原始 ADC 值 / 瞬时增亮 |
| `flStartup` | Int | w | 开机时套用的前光设置 |
| `isLowTempState` | Int | r | 是否处于低温保护状态 |
| `logLevel` / `logMask` | Str | rw | 日志级别 / 掩码，几乎所有 `com.lab126.*` 服务都有这两个 |

**已确认的事件**（本机实测）：`goingToScreenSaver`、`outOfScreenSaver`、`readyToSuspend`、`suspending`、`resuming`。
功能 7 的循环就是「收到 `readyToSuspend` → 需要保活就发 `deferSuspend 300`」，见 [06](06-debug-awake.md)。

```sh
lipc-get-prop com.lab126.powerd status
lipc-set-prop com.lab126.powerd preventScreenSaver 1     # 调试时
lipc-set-prop com.lab126.powerd preventScreenSaver 0     # 用完改回
```

### 4.2 com.lab126.appmgrd（应用生命周期）

打开书、回主页、查前台应用全靠它。

| 属性 | 类型 | 读/写 | 说明 |
|---|---|---|---|
| `start` | Str | w | 启动/切换应用，参数是 URI。本机实测 |
| `activeApp` | Str | r | 当前前台应用，如 `com.lab126.booklet.home`。本机实测 |
| `activeAppPid` | Int | r | 前台应用的 pid |
| `forward` / `backward` | Int | w | 前进/后退（推测） |
| `stop` / `load` / `savecontext` / `clearAllContext` / `defer` | Str/Int | w | 生命周期控制 |
| `goresult` / `loadresult` / `runresult` / `pauseresult` / `unloadresult` | Str | w | **应用回报**执行结果，不是给你用的 |

常用 URI（本机实测）：

```sh
lipc-set-prop com.lab126.appmgrd start app://com.lab126.booklet.home      # 回主页
lipc-set-prop com.lab126.appmgrd start "app://com.lab126.booklet.reader/mnt/us/documents/某书.pdf"
lipc-set-prop com.lab126.appmgrd start "app://com.lab126.KPPMainApp/?view=KPP_LIBRARY"   # 图书馆
```

**已确认的事件**：`historyChange`、`appStateChange`、`appActivating`。状态机（日志 `appmgr_history:app_state_change`）：

```
EXECUTED → REGISTERED → LOAD_SENT → LOADED → GO_SENT → STARTED      暂停时：PAUSE_SENT → PAUSED
```

**重启前台应用后不要马上发 `start`**：`restart kppmainapp` 之后新进程约 7 秒才注册 lipc 服务，这之前 appmgrd 的 `go` 会失败（`lipc_status=8`），pillow 会弹「应用程序错误：无法启动选定的应用程序」（`appmgrAppFailedFatal`），而且这个弹窗会一直留在屏幕上、跨过屏保和休眠。等 `historyChange` 就行，appmgrd 会自动恢复原来的视图。详见 [09 第 4 节](09-lab126-internals.md#4-appmgrd应用生命周期)。

### 4.3 com.lab126.pillow（弹窗）

| 属性 | 类型 | 读/写 | 说明 |
|---|---|---|---|
| `pillowAlert` | Str | w | 显示系统弹窗。排错时用来确认「谁弹的窗」 |
| `customDialog` | Str | w | 自定义对话框 |
| `displayChrome` / `dismissChrome` | Str | w | 显示/隐藏状态栏与 chrome |
| `applicationWindow` / `activityIndicator` | Str | w | 应用窗口、转圈指示器 |
| `debugInfo` | Str | w | 打印调试信息 |
| `interrogatePillow` / `interrogatePillowHash` | Str | w | 自检 |

### 4.4 com.lab126.winmgr（窗口）

30 个属性，改界面/刷新相关时有用。

| 属性 | 类型 | 读/写 | 说明 |
|---|---|---|---|
| `getAllWindows` / `visibleWindows` | Str | w | 列出全部 / 可见窗口（写入即查询，结果进日志） |
| `winmgrReady` | Int | r | winmgr 是否就绪 |
| `isScreenSaverLayerWindowActive` | Int | r | 屏保层是否在前（推测） |
| `getActiveAppTitle` | Str | r | 当前窗口标题 |
| `orientation` | Str | r | 当前方向 |
| `orientationLock` / `setAccOrientation` | rw | rw | 方向锁定 / 加速度计方向（推测） |
| `chromeState` | Str | rw | chrome（状态栏/搜索栏）当前状态 |
| `ASRMode` | Int | rw | 自动屏幕旋转（Auto Screen Rotation）模式 |
| `epdcMode` | Str | rw | EPDC（墨水屏控制器）模式 |
| `grip_enabled` / `pageTurnkeyConfig` | rw | rw | 防误触握持检测 / 翻页键配置 |
| `liglFlash` / `liglDebugParams` / `liglPause` / `defineWipeCurve` | w/w/rw/w | | LIGL 墨水屏刷新算法的调试入口 |
| `refreshOnTurn` / `extendDamageTimeout` | Int | w | 翻页刷新控制（推测） |
| `eatTapMode` / `fakeTap` / `fakeKeyEvent` / `focusChrome` | w | w | 事件注入与拦截。**注意 [09 第 6 节](09-lab126-internals.md#6-输入设备)：不要往触摸屏注入事件** |
| `passwordDialogEnabled` | Int | rw | 密码对话框 |
| `debugInfo` | Str | rw | 调试信息 |
| `enableDispalyEvents` | Int | rw | 属性名里的 `Dispaly` 是**固件自带的拼写错误**，照抄即可。这类拼写错误在 Kindle 上很常见（WAF 的 `config.xml` 里也有 `Reqeust`、`extenstions`） |

### 4.5 com.lab126.system（系统信息）

| 属性 | 类型 | 读/写 | 说明 |
|---|---|---|---|
| `version` | Str | r | 固件版本字符串 |
| `boardid` / `panelCode` / `panelWaveformversion` / `waveformversion` | Str | r | 主板与墨水屏面板信息。做显示相关改动前先记下来 |
| `displayTemperature` | Str | r | 面板温度（波形补偿用） |
| `guid` / `usid` | Str | r | 设备唯一 ID |
| `monoTime` / `monoTimeSaved` | Str | r | 单调时钟 |
| `orientation` | Str | r | 方向 |
| `takeScreenShot` | Str | w | 截屏（等价于 `/usr/sbin/screenshot`，见 [09 第 7 节](09-lab126-internals.md#7-系统自带的小工具)） |
| `executeDebugCommand` | Str | w | **执行搜索栏调试命令**，见 [13 Kindle 系统参考资料](13-kindle-system-reference.md#4-搜索栏调试命令) |
| `date` | Str | w | 设置时间 |
| `isTimeAutoUpdateEnabled` / `enableTimeAutoUpdate` / `disableTimeAutoUpdate` | r/w/w | | 自动校时 |
| `disableASR` / `startVoiceView` / `stopVoiceView` | w | w | 无障碍功能 |
| `updateWaveform` / `deleteWaveform` | w | w | 面板波形更新 |
| `sendEvent` / `deviceLocaleSelected` / `openFeedbackApp` / `btDeviceReconfirmed` | w | w | 杂项事件入口 |

### 4.6 com.lab126.volumd（用户分区）

`/mnt/us` 就是这一层管的。用 USB 存储模式连电脑时它会被卸载，在上面跑的程序会出错（见 README）。

| 属性 | 类型 | 读/写 | 说明 |
|---|---|---|---|
| `userstoreIsAvailable` | Int | r | 用户分区是否可用 |
| `userstoreTotalSpace` / `userstoreFreeSpace` | Int | r | 总空间 / 剩余空间（字节） |
| `driveModeState` | Int | r | 当前是 U 盘模式还是主机模式 |
| `useUsbForNetwork` | Int | rw | 是否把 USB 口当网卡（USBNetwork 用的就是这个） |
| `userstoreReadyToUnMount` / `userstoreDeferUnmountRequest` / `recreateUserstoreResponse` | w | w | 卸载流程的握手 |

### 4.7 com.lab126.cmd（联网状态）

| 属性 | 类型 | 读/写 | 说明 |
|---|---|---|---|
| `activeInterface` | Str | r | 当前出网接口（`wifi` / `wan` / `none`） |
| `availableInterfaces` | Str | r | 可用接口列表 |
| `wirelessEnable` / `disableInterfaces` / `interfaceProperties` | rw | rw | 无线开关与接口属性（哈希属性） |
| `ensureConnection` | Str | w | 强制建立连接 |
| `smsRecvRequired` | Str | rw | 短信接收（3G 机型） |

**已确认的事件**：`connectionAvailable`，带两个字符串参数（接口名 + 是否能出网），也就是 `connectionAvailable("wifi", "internet")`。微信传书这类「亮屏联网时再取件」的逻辑可以等它。

### 4.8 内容索引：indexer / scanner / ccat

往 `documents` 里丢文件之后，是这三个服务把它变成书库里的一本书：

| 服务 | 用途 |
|---|---|
| `com.lab126.scanner` | 扫描 `documents`，按 [appreg.db](13-kindle-system-reference.md#2-appregdb) 里 `interfaces=extractor` 的关联挑出对应 extractor。`doFullScan`、`reScanFile`、`triggerUpdate` 可以手动触发；`fullScanStatus` 查询进度 |
| `com.lab126.indexer` | 真正建索引。`numberOfItemsToBeIndexed` 看还有多少没处理，`pauseIndexerMilliseconds` / `pauseIndexerTillTimeMilliseconds` 暂停索引，`dumpIndexerState` 打状态 |
| `com.lab126.ccat` | 内容目录服务，管 `/var/local/cc.db` |
| `com.lab126.extractor.java` | 注册/删除 Java 提取器（`add` / `update` / `delete`） |

**实践**：`documents` 里的文件没被索引时，把它移出 `documents` 再移回来比等它自己扫快。

### 4.9 com.lab126.amazonRegistrationService（注册状态）

假注册（fakereg）机器上判断「系统认为自己注册了没有」就看它。

| 属性 | 类型 | 读/写 | 说明 |
|---|---|---|---|
| `isRegistered` | Int | r | 是否已注册。**由 framework（cvm）提供**，framework 没起来时查不到，症状就是设置打不开、显示「需要注册 Kindle」 |
| `primaryUserId` | Str | r | 主账号 ID（`amzn1.account.…`） |
| `registerWithToken` / `registerWithPreAuthorizedCode` / `deregister` | Str/Int | w | 注册、注销 |
| `registerPrimaryUser` / `registerSecondaryUser` | Has | rw | 哈希属性，`lipc-probe` 不展开 |

### 4.10 com.lab126.kaf（Java 框架）

| 属性 | 类型 | 读/写 | 说明 |
|---|---|---|---|
| `frameworkStarted` | Int | r | 框架是否已启动。功能 4 改 jar 后重启 framework，等这个变 1 |
| `heapUsed` | Int | r | 堆占用（KB） |
| `timezoneId` | Str | r | 时区 |
| `delayFrameworkStart` | Int | rw | 延迟框架启动 |
| `callCVM` / `callInspector` / `dumpHeap` / `dumpHeapWithoutGC` / `dumpNativeHeapStats` / `allocHeap` | Str/Int | w | 调试入口 |

### 4.11 其他值得知道的

| 服务 | 关键属性 | 用途 |
|---|---|---|
| `com.lab126.blanket` | `load` / `unload` / `uiQuery` | 「毯子」是全屏覆盖界面。wiki 记录里 `load` 的当前值是 `langpicker blankwindow ad_screensaver usb`，也就是这几个已知的毯子 |
| `com.lab126.blanket.ad_screensaver` | `screensaver_showing` / `activeButtonCoordinate` | 广告屏保当前是否在显示、按钮坐标。想判断「屏幕上是广告还是普通屏保」用这个 |
| `com.lab126.wifid` | `scan` / `scanList` / `scanState` / `signalStrength` / `currentEssid` / `createProfile` / `cmConnect` / `cmDisconnect` | 最全的 WiFi 控制面（33 个属性）。`711` 这个属性名就是搜索栏命令 `;711` 的来源 |
| `com.lab126.btfd` | `BTenable` / `BTstate` / `Bond` / `Connect` / `listConnected`… | 蓝牙。KUAL 的蓝牙开关背后就是它。Oasis 3 没蓝牙，属性按机型注册 |
| `com.lab126.dpmManager` | 45 个属性，全是家长控制/限制项（`isBrowserDisabled`、`isKindleStoreDisabled`、`setParentalControlsPassword`…） | 想知道「某个菜单为什么是灰的」，先来这里查一遍。功能 2、3 遇到的「新建收藏夹/收藏夹视图是灰的」性质不同（是未注册导致），但排查思路一样 |
| `com.lab126.keyboard` | `open` / `close` / `language` / `languages` / `bounds` | 屏幕键盘 |
| `com.lab126.deviced` | `enable_touch` | 开关触摸屏。**比往触摸屏注入事件安全得多** |
| `com.lab126.stored` | `run` / `kill` / `processRestart` / `ready` | 商店后台进程，也是 mesquite 实例。替换过 `/usr/bin/mesquite` 之后要重启它（见 [09 第 2 节](09-lab126-internals.md#2-upstart)） |

## 5 在自己机器上重新 dump

固件、机型不同，服务和属性都会不一样。**本文档的索引只是路标，真机数据才是准的。**

```sh
export PATH=/usr/sbin:/sbin:$PATH
lipc-probe -a -v > /mnt/us/lipc.txt        # 全部服务 + 全部属性
scp root@<kindle-ip>:/mnt/us/lipc.txt .
```

只想看某一个服务：

```sh
lipc-probe -v com.lab126.powerd
```

想对比「某项功能打开前后哪些属性和事件动了」：

```sh
# 终端 A：抓 DBus 信号（事件）。默认只能看到信号，看不到方法调用。
dbus-monitor --system | grep -E 'interface=com\.lab126|member='

# 终端 B：抓属性快照，然后在 Kindle 上操作，再抓一次，diff
lipc-probe -a -v > /mnt/us/lipc.before.txt
# … 操作 …
lipc-probe -a -v > /mnt/us/lipc.after.txt
diff /mnt/us/lipc.before.txt /mnt/us/lipc.after.txt
```

想把 dump 转成新的 [文档 12](12-lipc-service-catalog.md)（同时刷新第 3 节的索引）：

```sh
python tools/gen_lipc_catalog.py lipc.txt
```

想让 `dbus-monitor` **也能看到方法调用**（也就是谁读了谁的属性），要给它加 eavesdrop 权限：编辑 `/etc/dbus-1/system-local.conf`（先 `mntroot rw`），保留原有内容并加上

```xml
<policy user="root">
  <allow eavesdrop="true"/>
  <allow eavesdrop="true" send_destination="*"/>
</policy>
```

改完确认 XML 合法，然后重启 Kindle 才生效。⚠ 这是在改操作系统的核心组件，改坏了界面起不来；调试完建议还原。详见 [09 第 3 节](09-lab126-internals.md#3-lipc服务之间的通信) 的风险说明。

## 6 参考资料

- [KindleModding Wiki — Kindle Apps & Services](https://kindlemodding.org/kindle-apps-and-services/)：本文档 12 的数据来源，也讲了 lipc 与 DBus 的对应细节。CC BY-NC 4.0。
- [openlipc](https://github.com/notmarek/openlipc) / [openlipclua](https://github.com/NiLuJe/openlipclua)：在 C / Lua 里直接用 lipc。
- [09 Kindle 系统内部（com.lab126）笔记](09-lab126-internals.md)：本机实测的进程、upstart、lipc 踩坑记录。
