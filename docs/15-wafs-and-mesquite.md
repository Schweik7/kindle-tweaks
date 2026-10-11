# 15 WAF 与 Mesquite

> Kindle 的商店、浏览器、大量设置页面都不是原生程序，而是**跑在 WebKit 外壳里的网页应用（WAF）**。
> 本文讲清它们的目录结构、`config.xml` 规范，以及可以调用的 `window.kindle` JS API。
>
> 内容整理自 [KindleModding Wiki — WAFs & Mesquite](https://kindlemodding.org/wafs-and-mesquite/)（CC BY-NC 4.0）。
> 这一块 wiki 自己标注了大量 `WIP` / `incomplete`，下面凡是不确定的都保留了原作者的保留态度。

## 1 WAF 是什么

**WAF = 一个塞进外壳里的 webapp。** 外壳是 **Mesquite**（Kindle 的 WebKit 封装，`/usr/bin/mesquite`）。
系统上跑的每个 WAF 就是：

- 一个目录，里面有 `config.xml`（元数据 + 权限 + 要开哪些 JS API）、`index.html`（入口）、以及 JS/CSS/图片；
- 在 `appreg.db` 里的一条声明，让它能被 appmgrd 启动。

浏览器本身也是一个 mesquite 实例。本机实测的启动命令存在 `appreg.db` 里（见 [13 第 2.3 节](13-kindle-system-reference.md#23-propertiesbooklet-怎么被启动)）：

```
com.lab126.browser | command | /usr/bin/mesquite -l com.lab126.browser -c file:///var/local/mesquite/browser/ -j
```

> **路径说明**：wiki 写 WAF 放在 `/opt/var/local/mesquite/<名字>/`；
> 本仓库在 Oasis 3 / FW 5.15.1.1 上实测，浏览器的界面文件在 `/var/local/mesquite/browser/`
> （见 [09 第 5 节](09-lab126-internals.md#5-文件和数据库)）。这两个路径在 Kindle 上是两个地方还是同一个，
> 本仓库没有验证——**改之前先 `ls -l` 确认你机器上的实际路径。**

### 1.1 目录结构

以商店 WAF 为例，去掉依赖文件后剩下这些是有意义的：

```
<waf 目录>/
├── config.xml                 元数据（下面整节讲）
├── config_<platform>.xml      按机型/平台分身的配置，如 config_wario.xml、config_zelda.xml
├── index.html                 入口页面（由 config.xml 的 <content src> 指定）
├── store.js / *.js            应用逻辑
├── privateCookies             Cookie 用
├── js/                        第三方库（jquery 等）
├── images/                    图片
├── strings/strings.js         字符串
└── locales/<语言>/strings/strings.js   本地化字符串
```

- `config_<platform>.xml` 的名字（`wario`、`duet`、`zelda`、`bellatrix`…）就是 [13 第 6 节](13-kindle-system-reference.md#6-机型识别) 里的 platform 名。
  **同一份 WAF 按平台分发不同配置**，这是判断「某个界面在不同机型上为什么不一样」的线索。
- `strings/` + `locales/<locale>/strings/` 是亚马逊统一的本地化约定，不是 WAF 框架强制的，但所有官方 WAF 都这么做。

## 2 config.xml

一个 WAF 的全部声明都在这个文件里。这是商店的原文（截取关键部分）：

```xml
<?xml version="1.0"?>
<widget id="com.lab126.store" version="1.0" viewmodes="application"
    xmlns="http://www.w3.org/ns/widgets"
    xmlns:kindle="http://kindle.amazon.com/ns/widget-extensions">
    <name xml:lang="en">Kindle Store</name>
    <description xml:lang="en">Amazon Kindle Store</description>
    <content src="index.html" />
    ...
</widget>
```

下面逐节说明。

### 2.1 根元素 `<widget>`

| 属性 | 含义 |
|---|---|
| `id` | WAF 的 ID，和 Mesquito 应用一样，是任意唯一的「Java 风格命名空间」，通常用反向域名 |
| `version` | 版本号 |
| `viewmodes` | 目前只见过 `application` |
| `xmlns:kindle` | Kindle 扩展的命名空间，下面所有 `kindle:*` 标签都靠它 |

### 2.2 `<name>` / `<description>`

支持 `xml:lang` 做本地化，同一个标签可以重复多次。可以用 unicode 字符（或实体，如 `&#12473;`）。
这两个值会显示在界面的某处。**这些标签里能看到固件源码里的拼写错误**，比如商店 `config.xml` 里的注释
`<!-- Reqeust for localhost access permission -->`。

### 2.3 `<content src>`

**唯一一行指定入口页面的配置。** 这里写 `index.html`。

### 2.4 `<kindle:permissions>`

```xml
<kindle:permissions>
    <kindle:permission name="local-port-access" />
</kindle:permissions>
```

已知的权限只有两个：

| 权限名 | 作用 |
|---|---|
| `local-port-access` | 允许访问 `localhost`，主要是 9101 端口上的数据库接口 |
| `download-allowed` | 允许把文件下载到 Kindle 的 `documents` 目录 |

> `download-allowed` 和本仓库**功能 9（浏览器下载任意文件）**是同一件事的两面：
> 功能 9 改的是 `/usr/bin/mesquite` 二进制里的类型白名单，而这里是 WAF 层面的权限声明。

### 2.5 `<kindle:network>`

设置 User-Agent、额外 HTTP 头、连接数、代理覆盖、错误页：

```xml
<kindle:network>
    <kindle:asset key="user-agent" value="kindle://device-type" />
    <kindle:asset key="user-agent" value="kindle://sw-version" />
    <kindle:asset key="http-header" value="kindle://transport-method" />
    <kindle:asset key="http-header" value="kindle://country-code" />
    <kindle:asset key="initialDNS" value="false" />
    <kindle:asset key="maxConnections" value="6" />
    <kindle:asset key="overrideProxy" value="none" />
    <kindle:asset key="enableCaching" value="false" />
    <kindle:errorPage src="../shared/audibleupsell_error.html" />
</kindle:network>
```

`value` 里 `kindle://…` 形式的占位符会在运行时被替换成真实值（设备型号、固件版本、运营商、国家码）。

浏览器的 `config.xml` 直接写死了一个老 UA：

```xml
<kindle:asset key="user-agent"
  value="Mozilla/5.0 (X11; U; Linux armv7l like Android; en-us) AppleWebKit/531.2+ (KHTML, like Gecko) Version/5.0 Safari/533.2+ Kindle/3.0+" />
<kindle:asset key="enableWrsProxy" value="true" />
<kindle:asset key="allowTlsFallback" value="true" />
```

**想让体验版浏览器伪装成别的浏览器，就是改这一行。** 改完重启对应 mesquite 实例（`restart stored` 或重启浏览器进程）。

> wiki 明确说 `enableCaching` **不管 WAF 自身的缓存**，别指望它。

### 2.6 `<kindle:cookiejar>`

```xml
<kindle:cookiejar>
    <kindle:asset key="persistent" value="true" />
    <kindle:asset key="usePrivateCookies" value="false" />
    <kindle:asset key="useDeviceCookies" value="true" />
    <kindle:asset key="useAccessToken" value="true" />
</kindle:cookiejar>
```

`useDeviceCookies` / `useAccessToken` 就是「带上设备身份和访问令牌」，
也就是 `x-main`、`x-fsn` 这些 Cookie 的来源。

### 2.7 `<kindle:chrome>`

```xml
<kindle:chrome>
    <kindle:asset key="configureSearchBar" value="system" />
</kindle:chrome>
```

配合 [14 第 4.4 节](14-kindle-homebrew-and-dev.md#44-窗口标题awesome-wm-的约定) 的窗口标题一起决定界面上显示哪些常驻元素。
`configureSearchBar` 已知取值 `system` 和 `none`，具体行为不清楚。

### 2.8 `<kindle:gestures>`

```xml
<kindle:gestures>
    <kindle:param name="tap" value="yes" properties="fire_on_tap:1 max_updown_delta:0" />
    <kindle:param name="swipe" value="yes" />
</kindle:gestures>
```

已知的手势名：`tap`、`swipe`、`drag`、`hold`、`multi_tap`、`pinchzoom`（浏览器用的是这一组）。
开启之后 JS 里就能通过 `kindle.gestures.*` 收到回调（见第 4.8 节）。

### 2.9 `<feature name="http://kindle.amazon.com/apis">`

**这一段决定 `window.kindle` 上开放哪些 API。**

```xml
<feature name="http://kindle.amazon.com/apis" required="true">
    <param name="appmgr" value="yes" />
    <param name="net" value="yes" />
    <param name="todo" value="yes" />
    <param name="gestures" value="yes" />
    <param name="chrome" value="yes" />
    <param name="dev" value="yes" />
    <param name="dconfig" value="yes" />
    <param name="download" value="yes" />
    <param name="messaging" value="yes" />
    <param name="uitest" value="yes" />
    <param name="popup" value="yes" />
    <param name="bkgrnd" value="yes" />
    <param name="localprefs" value="yes" />
    <param name="device" value="yes" />
    <param name="winmgrUtils" value="yes" />
    <param name="bluetooth" value="yes" />
</feature>
```

### 2.10 `<kindle:messaging>`

**白名单**：`kindle.messaging` 只能给这里列出的 lipc 服务发消息。

```xml
<kindle:messaging>
    <kindle:app name="com.lab126.pillow" value="yes" />
    <kindle:app name="com.lab126.chromebar" value="yes" />
    <kindle:app name="com.lab126.readnow" value="yes" />
</kindle:messaging>
```

### 2.11 `<kindle:resources>`

```xml
<kindle:resources>
    <kindle:asset key="jquery" value="js/jquery.js" />
    <kindle:asset key="ApplicationCachePath" value="/var/local/mesquite/store/resource/appcache" />
    <kindle:asset key="LocalStorageQuota" value="26214400" />
</kindle:resources>
```

- 声明的资源名就是 `kindle.device.loadResource(frameId, resourceId)` 里的 `resourceId`（见第 4.1 节）。
- 其余的 key 管限额和路径：`LocalStoragePath`、`DatabaseStorageQuota`、`DatabaseStoragePath`、`ApplicationCacheQuota`。

### 2.12 `<kindle:settings>`

杂项开关，各 WAF 差异很大：

| 设置 | 作用 |
|---|---|
| `internetRequired` | 是否要求联网 |
| `saveContext` | 是否由平台保存上下文。商店设成 `no`，因为它自己在 pause 时保存，**避免平台重复保存** |
| `disable-wua-features` | 关掉 WUA 功能 |
| `defaultFontSize` / `defaultFontSize300` / `defaultFontSize212` / `defaultFontSize167` | 按屏幕 DPI 分档的默认字号（浏览器用） |
| `minimumFontSize` | 最小字号 |
| `zoomFactor` | 缩放因子 |
| `flattenFrames` | 是否把 frame 摊平 |
| `enforce96DPI` | 强制 96 DPI |
| `enableW3CStd` | W3C 标准模式 |
| `debug` | 调试开关 |

## 3 和本仓库的关系

| 本仓库功能 | 涉及的层 | 是不是 WAF |
|---|---|---|
| 1 云端不可用弹窗 | `KPPMainApp.js.hbc`（React Native / Hermes） | ❌ 不是 WAF |
| 3 收藏夹视图 | `libKSDKLibrary.so`（原生库） | ❌ 不是 WAF |
| 4 PDF 全屏 | Java 阅读器 jar | ❌ 不是 WAF |
| 8 默认收藏夹视图 | LD_PRELOAD 注入 KPP | ❌ 不是 WAF |
| 9 浏览器下载任意文件 | `/usr/bin/mesquite`（WebKit 外壳本体） | ⚠ 改的是**外壳**，所有 WAF 共用 |
| 2 文件夹收藏夹 | `cc.db` + ccat | ❌ |
| 10 微信传书 | upstart + `com.lab126.cmd` | ❌ |

**结论：本仓库目前没有改任何 WAF 的 `config.xml`。** 但功能 9 改的 `/usr/bin/mesquite`
是所有 WAF 共用的外壳——**这个二进制一旦改坏，商店、浏览器、设置页面会一起坏**。
这也是为什么 [09 第 2 节](09-lab126-internals.md#2-upstart) 特意提醒：替换 `/usr/bin/mesquite` 之后
必须把映射着旧文件的进程找出来重启（`restart stored`），否则 `mntroot ro` 会报 `/ is busy`。

想真正改界面（而不是改外壳），正确的入口是那两处：

- **新版界面（KPP）**：`/app` 下的 React Native bundle，本仓库功能 1 用的就是这条路。
- **老式界面 / WAF**：`/var/local/mesquite/<waf>/` 下的 HTML/JS。**注意 `/mnt/us` 才是升级不丢的分区**，
  改完要么放 `/mnt/us` 再 bind mount，要么接受升级后被还原。

## 4 window.kindle：WAF 能调的 JS API

所有 WAF 都有 `window.kindle` 对象，它是 JS 与系统之间的桥。开放哪些 API 由
[`config.xml` 的 `<feature>`](#29-feature-namehttpkindleamazoncomapis) 决定。

`kindle` 对象本身有一个 `version` 属性（值是 `1`）。本地开发用的 mock 版本里还有 `isMock = 1` 和 `extensions = {}`。

### 4.1 kindle.device / kindle.dev

两者几乎一样，但**有差异**（`kindle.dev` 是本地开发/调试用的变体，wiki 说它「文档不完整，可能不准确」）。

**属性：**

| 名称 | 类型 | 说明 |
|---|---|---|
| `contactInfo` | String | 显示的系统管理员联系方式，默认 `'Your System Administrator'` |
| `eid` | String | 一段 base64 数据，用途未知 |
| `getRegistrationState` | String | 注册状态，如 `'registered'` |
| `hasScreenLight` | Boolean | 是否有阅读灯 |
| `hasKindleStoreAccess` | Boolean | 是否可访问商店，疑似用于家长控制 |
| `isWirelessMenuEnabled` | Boolean | 用户是否开启了无线菜单 |
| `controlStatus` | Int | 控制状态：`1` Device Control、`2` Parental、`3` No Control、`0` 其它 |

**方法：**

| 方法 | 说明 |
|---|---|
| `setSensitivity(useThreshold, threshold)` | 设置墨水屏刷新「灵敏度」。`threshold` 取 0–100，100 会明显更频繁地全刷。`useThreshold = false` 时不要传 `threshold` |
| `setOrientation(orientation)` | 设屏幕方向，取值见 [orientations 枚举](#43-enums)。非法值静默无效 |
| `getDPI()` | 返回设备 DPI |
| `hasWirelessMenu()` | 是否有无线菜单 |
| `log(logEvent, logMsg, logLevel)` | 写系统日志。`logLevel` 取 `info`/`warn`/`error`/`debug`/`perf`。⚠ **Kindle 日志会被上传到亚马逊，别写敏感信息** |
| `getLab126SessionToken()` | 拿访问内部数据库接口所需的会话令牌 |
| `loadResource(frameId, resourceId)` | **把本地 JS 文件注入到任意 frame**，用来绕过 XSS 限制。`frameId` 是 frame 的 DOM id，顶层 frame 用 `_self`；`resourceId` 必须是 `config.xml` 里声明过的资源名。源码在 `/opt/var/local/mesquite/shared/javascripts/userAgent.js` |
| `addDomainToWhitelist(uri, addSubDomains)` | 把域名加入白名单。`addSubDomains` 是字符串 `'true'`/`'false'` |
| `clearCookies()` | 清空本应用的 Cookie jar。⚠ **在 Mesquito 上会清掉所有应用的 Cookie 并被永久拉黑** |
| `clearApplicationCache()` | 清 HTML 缓存。⚠ 同样有被 Mesquito 永久拉黑的风险 |
| `clearCache()` | 清内存缓存 |
| `getMPDomain()` | 市场域名。`kindle.dev` 上疑似失效 |
| `getBaiduSearchURL()` | 返回 `https://www.baidu.com/s?tn=baiduhome_pg&ie=utf-8&rn=4&wd=`，固件里拼在搜索词前面 |
| `disableSecureApis()` | 在非亚马逊 URL 上关掉「安全 API」（`payment` WAF 用） |
| `isInDemoMode()` | 是否在演示模式 |
| `getSoftwareVersionNumber()` | 固件版本号（整数）。例：`5.15.1.1` → `3924990005` |
| `getSoftwareVersionString()` | 固件版本字符串 |
| `getASRMode()` | 自动屏幕旋转模式，返回数字，含义未知 |
| `getCSSPixelsPerInch()` | 每英寸 CSS 像素数 |
| `getRegisteredUserId()` | 注册的 userId（`kindle.dev` 独有） |
| `getDSN()` | 返回一个字符串，含义未知（`kindle.dev` 独有） |
| `getDeviceLocale()` | 设备区域，如 `en_GB`（`kindle.dev` 独有） |
| `getDeviceTypeString()` | 设备代号，如 `malbec`（`kindle.dev` 独有）——**这就是 [13 第 6 节](13-kindle-system-reference.md#6-机型识别) 的 platform 名** |

> **`getSoftwareVersionNumber` 的编码**：wiki 给的是 `5.15.1.1 → 3924990005`。
> 按 Kindle 的惯例这是把各段版本号按位打包成一个整数，写机型判断逻辑时**不要自己算，直接读它的返回值**。

### 4.2 kindle.net

属性：`backgroundRequestHeader`（字符串 `'WAF-HTTP-REQUEST-BACKGROUND-HEADER'`，用途不明）、
`roaming`（3G 机型是否漫游）、`rffSessionId`（不明）。

| 方法 | 说明 |
|---|---|
| `getWirelessState()` | 返回 `'on'` / `'off'` |
| `getActiveInterface()` | 返回 [connectionTypes](#43-enums)：`wifi` / `wan` / `none` |
| `setWirelessPrompt(promptLevel)` | 设置联网提示级别，见 [connectionPromptLevels](#43-enums) |
| `confirmSSLException(confirm, callback)` | 处理无效 SSL 证书。`confirm` 传 `'yes'` / `'no'` |
| `ensureWifiConnection(promptLevel, callback)` | 确保 Wi-Fi 连接。回调拿到 [connectionResults](#43-enums) 字符串 |
| `ensureConnection(promptLevel, forceConnect, callback)` | 确保任意连接。`forceConnect` 是布尔（是否只允许 Wi-Fi） |
| `registerHttpErrorListener(onHttpError)` | 注册 HTTP 错误回调：`onHttpError(internalCode, uri, httpStatus, responseMessage)` |
| `deregisterHttpErrorListener()` | 取消注册 |

**WAF 侧的联网能力对应 `com.lab126.cmd` 这个 lipc 服务**，对照看 [11 第 4.7 节](11-lipc-and-services.md#47-comlab126cmd联网状态)。

### 4.3 enums

这些字符串是很多 API 的参数或返回值，**从 `/opt/var/local/mesquite` 的固件文件里整理出来的**：

| 枚举 | 取值 |
|---|---|
| `connectionPromptLevels` | `all`（所有情况都提示用户）、`never`（不提示，能自动连就自动连）、`nocaptive`（除强制门户外都提示） |
| `connectionResults` | `success`、`failure`、`failure-user-canceled`、`failure-captive-portal` |
| `connectionTypes` | `wifi`、`wan`、`none` |
| `scrollBarStates` | `auto`、`hidden`、`visible` |
| `fileDownloadResults` | `success`、`error`、`canceled`、**`rejected`（文件类型不允许下载）** |
| `eInkRefreshModes` | `auto`、`minimal`、`maximal`、`manual`（不主动刷新，除非 JS 直接调用） |
| `orientations` | `auto`、`portrait`、`portraitUp`、`portraitDown`、`landscape`、`landscapeLeft`、`landscapeRight` |
| `direction` | `up`、`down`、`left`、`right` |
| `alignment` | `top`、**`buttom`**（固件里的拼写错误）、`center`、`left`、`right` |
| `pillow.buttons` | `back`、`store`、`home`、`forward`、`menu`、`refresh`、`cancel`、`discovery`、`KPP_BACK`、`KPP_CLOSE` |
| `pillow.buttonStates` | `enabled`、`disabled`、`false`（这个其实是布尔，不是字符串） |
| `pillow.buttonHandling` | `system`（系统处理）、`notifyapp`（通知 WAF 处理） |
| `pillow.contextMenuIDs` | `browserSettings`、`browserBookmarks`、`browserBookmarkPage`、`browserHistory`、`browserArticleOrWebMode` |
| `pillow.contextMenuStates` | `enabled`、`disabled` |

> `fileDownloadResults.rejected` 就是本仓库**功能 9** 要绕过的那个返回：
> 体验版浏览器只许下载 `.azw`/`.prc`/`.mobi`/`.txt`，其他类型走到这里被拒。

### 4.4 kindle.messaging

Kindle 内部用 **ToDo** 系统与亚马逊通信（下载书、更新屏保、更新商店、遥测）。
`kindle.messaging` 是 WAF 参与这套消息系统的入口。

| 方法 | 说明 |
|---|---|
| `sendMessage(id, eventType, eventData)` | 给指定 lipc 服务发消息，`eventData` 是对象。例：`sendMessage('com.lab126.chromebar', 'configureChrome', { appId: 'com.lab126.store', topNavBar: { template: 'title', title: 'Mesquito Loader' } })` |
| `sendStringMessage(id, eventType, eventData)` | 同上，但 `eventData` 是字符串 |
| `recieveMessage(eventType, callback)` | 注册回调接收发给本 WAF 的 lipc 消息。回调签名 `callback(property, json)`，`property` 是事件名字符串，`json` 是随事件带来的数据。⚠ 注意函数名拼写就是 `recieveMessage` |

**能发给哪些服务由 [`<kindle:messaging>`](#210-kindlemessaging) 白名单决定。**

### 4.5 kindle.todo

| 方法 | 说明 |
|---|---|
| `scheduleItems(items)` | 用一段特定 XML 字符串提交一批 ToDo 项 |

ToDo 文档格式：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<response>
    <total_count>1</total_count>
    <items>
        <item priority="1" type="WISHLIST" action="REFRESH" key="DUMMY"
              is_incremental="false" sequence="0"></item>
    </items>
</response>
```

| 属性 | 说明 |
|---|---|
| `priority` | 整数优先级 |
| `type` | 动作类型 |
| `action` | 具体动作 |
| `key` | 唯一标识这个 ToDo 项，也可以直接写 `DUMMY` |
| 其它 | 任意，原样传给 handler |

`type` 和 `action` 合起来叫 **contentId**，格式是 `action.type`（本例是 `REFRESH.WISHLIST`）。
**这个 contentId 和 `appreg.db` 的 `associations.contentId` 是同一套东西**——
`TP:legacy.SET.PRCH`、`TP:legacy.DOWNLOAD.ADPK` 这类值（见 [13 第 2.2 节](13-kindle-system-reference.md#22-associations谁处理什么)）
就是 ToDo 项的关联键。服务侧的对应接口是 `com.lab126.todo` 的 `scheduleToDoItems`（见 [12](12-lipc-service-catalog.md#comlab126todo)）。

> wiki 说「有效的 ToDo 文档清单待补，需要更多研究」。**想摸清 ToDo 的用法，最好的资料是设备上的
> `/var/local/cc.db` 和 `/var/log/messages` 里的 `ToDo` 日志。**

### 4.6 kindle.chrome

管标题栏和对话框。⚠ wiki 标注为 `WIP` / `incomplete`。

属性：`isDecanterChromeEnabled`（布尔，是否启用「decanter chrome」，疑与固件版本相关）。

| 方法 | 说明 |
|---|---|
| `setTitleBar(centerText, leftText)` | 疑似已废弃 |
| `createHeader(uri, height, tiled)` | 用途不明 |
| `createDialog(uri, width, height, modal)` | 创建对话框，宽高单位为像素 |
| `setSpinnerState(state, timeout, delay)` | 标题栏转圈。`state` 取 `'start'` / `'stop'`。⚠ **即使是 `stop` 也必须传 `timeout` 和 `delay`**，因为 `JSObjectChrome::setSpinnerState` 要求三个参数，虽然会忽略它们 |
| `createContentWindow(uri)` | 返回某种 window 对象/字符串，用途不明 |
| `setContentWinDisplay(displayState)` | `'foreground'` / `'background'` |
| `setJavaScript(enabled)` | `'enabled'` / `'disabled'` |
| `setImageRendering(enabled)` | `'on'` / `'off'`（wiki 原文把它写成「开关 JS 执行」，应该是笔误） |
| `onContentStart()` | 可覆盖的回调：内容开始加载 |
| `onContentProgress(progress)` | 可覆盖的回调：`progress` 是 0–1 的小数 |
| `onContentUrlChanged(url)` | 可覆盖的回调 |
| `onContentTitleChanged(title)` | 可覆盖的回调 |
| `registerWindowOpenEventListener(callback)` | 用途不明，回调收到 `url` |

### 4.7 kindle.dconfig

读 [dconf](13-kindle-system-reference.md#24-dconf藏在-properties-里的配置) 的值：

```js
kindle.dconfig.getValue(key)
```

已知的 key（部分）：`url.store`、`url.website`、`url.kindlestore.kcw.metrics`、`url.cantilever`、
`url.ku.eligible`、`url.ku.landing.page`、`url.mysn.reap`、`url.odac`、`cmd.account.registration`、
`amz.cor`、`marketplace.obfuscated.id`、`mesquite.interceptorIndicator`、`store.disableDiskFileUse`。

> `url.*` 这些值**和 `appreg.db` 的 `dcd` 行是同一批数据**。想改商店指向，改 `appreg.db` 即可，
> 不需要动 WAF 的代码。

### 4.8 kindle.gestures

一组**可覆盖的函数**，是否触发由 [`config.xml` 的 `<kindle:gestures>`](#28-kindlegestures) 决定。

| 回调 | 说明 |
|---|---|
| `onswipe(direction, pageX, pageY)` | 滑动。`direction` 见 [direction 枚举](#43-enums) |
| `ontap(event)` | 点击 |
| `onflick(direction)` | 快速滑动 |
| `onpan(event)` / `onpinch(event)` / `onhold(event)` / `onzoom(event)` | 其余手势，参数含义不明 |

> wiki 提醒：**在 Mesquito 上只有 `onswipe` 和 `ontap` 能用**，因为受商店的 `config.xml` 限制。
> ⚠ 与本仓库相关的一条硬经验：**不要试图模拟触摸事件**——
> 往触摸屏注入事件会导致 Xorg 崩溃、framework 退出，只能重启恢复（[09 第 6 节](09-lab126-internals.md#6-输入设备)）。
> 如果将来要做「自动点击」类的功能，**走 WAF 的 JS 层（就是这一节）比走 `/dev/input` 安全得多**。

### 4.9 kindle.appmgr（本仓库实测，wiki 未记录）

`kindle.appmgr` 是**可覆盖的生命周期回调**（不是拿来调用的函数），名字只有 4 个：

| 回调 | 何时触发 |
|---|---|
| `kindle.appmgr.ongo` | 应用被启动/切入时，参数是上下文串 |
| `kindle.appmgr.onload` | 页面加载完成时 |
| `kindle.appmgr.onpause` | 应用被切到后台时 |
| `kindle.appmgr.onunload` | 应用被卸载时 |

**依据**（Oasis 3 / 5.15.1.1 实测）：

```sh
strings /usr/bin/mesquite | grep -E '^(ongo|onload|onpause|onunload)$'
# 正好这 4 个，且与 /var/log/messages 里的 event->0..3 一一对应
```

**没有 `onback` / `onforward`**（本仓库一开始猜了这两个名字，结果 mesquite 一直报
`W …:JSObjectAppManager::eventsCallbackFunction:cannot find callback function for [0]`）。
系统自带的 adviewer 注册了 `ongo`/`onload`/`onpause`，所以它没有这个警告；注册正确后警告消失（实测 0 次）。

最小写法（放在 `<head>` 里，供参考；完整版见本仓库的 `extensions/kindletweaks/webapp/sample/index.html`）：

```html
<script>
(function () {
  try {
    var k = window.kindle || (window.top && window.top.kindle);
    if (!k || !k.appmgr) { return; }
    k.appmgr.ongo = function (context) { return true; };
    k.appmgr.onload = function () { return true; };
    k.appmgr.onpause = function () { return true; };
    k.appmgr.onunload = function () { return true; };
  } catch (e) {}
})();
</script>
```

想自己确认事件编号与回调名，用 `dbus-monitor --system` 看 `com.lab126.appmgrd` 的信号，
或直接 `grep 'kindletweaks' /var/log/messages`（把应用 ID 换成你自己的）。

## 5 怎么动手改一个 WAF

1. **先定位**。`appreg.db` 的 `properties` 表里搜 `command` 或 `lipcId`，找到目标 WAF 的目录。
   ```sh
   sqlite3 -readonly /var/local/appreg.db \
     "select handlerId, name, value from properties where name in ('command','lipcId') and value like '%mesquite%'"
   ```
2. **先备份**，而且备份到 `/mnt/us`（升级不丢）。
3. **改配置优先，改代码其次**：很多行为（UA、代理、错误页、字号、联网提示、开放哪些 JS API）
   都在 `config.xml` 里，改一行比重打包 JS 稳。
4. **改完重启对应的 mesquite 实例**，不是重启整个界面：
   ```sh
   restart stored          # 商店后台进程也是 mesquite
   lipc-set-prop com.lab126.appmgrd start app://com.lab126.browser    # 重新拉起浏览器
   ```
5. **看日志**：`/var/log/messages`，`grep -i mesquite`。JS 报错也会落到这里。
6. **`/usr/bin/mesquite` 是共用的外壳**。改这个二进制之前先读
   [09 第 2 节](09-lab126-internals.md#2-upstart) 的「替换正在运行的可执行文件」陷阱。

**验证改动是否生效的最快办法**是开 `dbus-monitor --system`（看 WAF 发了哪些消息）+
`/var/log/messages`，而不是猜。

## 6 参考资料

- [KindleModding Wiki — WAFs & Mesquite](https://kindlemodding.org/wafs-and-mesquite/)：
  [Understanding config.xml](https://kindlemodding.org/wafs-and-mesquite/understanding-config-xml.html)、
  [The Kindle Object](https://kindlemodding.org/wafs-and-mesquite/the-kindle-object/)。
  该章节大量标注 `WIP`，引用前建议对照自己机器上的固件文件（`/opt/var/local/mesquite` 下的 `sqsh`）。
- [Mesquito](https://github.com/KindleModding/Mesquito)：社区做的 WAF 运行时，跑自制 WAF 应用。
- [13 Kindle 系统参考资料](13-kindle-system-reference.md)：`appreg.db`、`cc.db`、dconf。
- [14 Kindle 自制软件与原生开发](14-kindle-homebrew-and-dev.md)：窗口标题规范（Awesome WM）。
- [11 lipc 与 com.lab126 服务](11-lipc-and-services.md)：`kindle.messaging` 能触达的那些 lipc 服务。
