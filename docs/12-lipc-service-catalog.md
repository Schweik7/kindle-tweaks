# 12 lipc 服务与属性总表

> 本表由真机的 `lipc-probe -a -v` 输出整理而成：属性名、类型、读写权限、示例值都是设备上的事实数据；
> 「职责」和分类是本仓库自行标注的，标「推测」的未逐一实机验证。
>
> 服务是**按需注册**的：没跑的服务不会有，「示例值」列只代表采集那一刻的状态。
>
> 数据来自 [KindleModding Wiki](https://kindlemodding.org/kindle-apps-and-services/) 上的
> `lipc-probe -a -v` 转储（采集自 wiki 作者的测试机，机型与本仓库的验证机不同）。
> 本仓库只在 Oasis 3 / FW 5.15.1.1 上单独核实过 [11](11-lipc-and-services.md) 第 4 节点名的那些属性，
> **本表其余部分未在真机上逐条核对**；换机型或换固件后用
> `python tools/gen_lipc_catalog.py lipc.txt` 重新生成，真机数据才是准的。

读写含义：`r` 只读、`w` 只写（通常是「动作」而非状态）、`rw` 可读可写。
⭐ 表示本仓库（kindle-tweaks）用到的服务。

## 目录

- [系统与框架](#系统与框架)（9）
- [界面与输入](#界面与输入)（13）
- [网络与同步](#网络与同步)（8）
- [内容与索引](#内容与索引)（21）
- [账号与设备身份](#账号与设备身份)（10）
- [电源](#电源)（2）
- [外设](#外设)（5）
- [其他](#其他)（24）

## 系统与框架

### `com.lab126.appmgrd`

应用生命周期管理器：按 URI 启动/切换/暂停应用，维护前台应用状态　⭐ 本仓库用到

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `activeApp` | Str | r | com.lab126.booklet.home |
| `activeAppPid` | Int | r | 3356 |
| `backgroundAppLoaded` | Str | w |  |
| `backgroundAppUnLoaded` | Str | w |  |
| `backward` | Int | w |  |
| `clearAllContext` | Int | w |  |
| `defer` | Str | w |  |
| `forward` | Int | w |  |
| `goresult` | Str | w |  |
| `load` | Str | w |  |
| `loadresult` | Str | w |  |
| `logallapps` | Str | w |  |
| `loghistory` | Str | w |  |
| `logLevel` | Str | rw | info |
| `logMask` | Str | rw | 0x0fff0000 |
| `pauseresult` | Str | w |  |
| `runresult` | Str | w |  |
| `savecontext` | Str | w |  |
| `start` | Str | w |  |
| `startdefault` | Int | w |  |
| `stop` | Str | w |  |
| `unloadresult` | Str | w |  |

### `com.lab126.booklet`

booklet 通用 run/kill 入口

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `kill` | Str | w |  |
| `run` | Str | w |  |

### `com.lab126.cvm`

cvm 进程的日志开关（框架 JVM 的入口）

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `logLevel` | Str | rw | info |
| `logMask` | Str | rw | 0x0fff0000 |

### `com.lab126.kaf`

Java 框架（cvm）本体：注册/商店/设置等所有 booklet 的宿主　⭐ 本仓库用到

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `allocHeap` | Int | w |  |
| `callCVM` | Str | w |  |
| `callInspector` | Str | w |  |
| `delayFrameworkStart` | Int | rw | 0 |
| `dumpHeap` | Str | w |  |
| `dumpHeapUsage` | Str | r |  |
| `dumpHeapWithoutGC` | Str | w |  |
| `dumpNativeHeapStats` | Str | w |  |
| `frameworkStarted` | Int | r | 1 |
| `heapUsed` | Int | r | 20185 |
| `logLevel` | Str | rw | info |
| `logMask` | Str | rw | crit \| error \| warn \| info (0x7800000) |
| `timezoneId` | Str | r | America/Los_Angeles |

### `com.lab126.pmond`

进程/内存监视：超限杀进程、重启

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `heartbeat_start` | Str | w |  |
| `heartbeat_stop` | Str | w |  |
| `kill` | Str | w |  |
| `logLevel` | Str | rw | info |
| `logMask` | Str | rw | 0x0fff0000 |
| `mem_limit` | Str | w |  |
| `mem_warn` | Str | w |  |
| `restart` | Str | w |  |
| `start` | Str | w |  |
| `start_monitoring` | Int | w |  |
| `stop` | Str | w |  |
| `stop_monitoring` | Int | w |  |
| `summary` | Str | r |  |
| `system_memory_status` | Str | r | systemMemoryNormal |

### `com.lab126.system`

系统信息与全局动作：固件版本、面板波形、时间、截图、VoiceView、调试命令入口　⭐ 本仓库用到

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `boardid` | Str | r | xxxxxxxxxxxxxxxx |
| `btDeviceReconfirmed` | Str | w |  |
| `date` | Str | w |  |
| `deleteWaveform` | Str | w |  |
| `deviceLocaleSelected` | Str | w |  |
| `disableASR` | Str | w |  |
| `disableTimeAutoUpdate` | Str | w |  |
| `displayTemperature` | Str | r | 23 |
| `enableTimeAutoUpdate` | Str | w |  |
| `executeDebugCommand` | Str | w |  |
| `guid` | Str | r | xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx |
| `isTimeAutoUpdateEnabled` | Str | r | true |
| `monoTime` | Str | r |  |
| `monoTimeSaved` | Str | r |  |
| `openFeedbackApp` | Str | w |  |
| `orientation` | Str | r |  |
| `panelCode` | Str | r | R060_ED060KD1C1 |
| `panelWaveformversion` | Str | r |  |
| `sendEvent` | Str | w |  |
| `startVoiceView` | Str | w |  |
| `stopVoiceView` | Str | w |  |
| `takeScreenShot` | Str | w |  |
| `updateWaveform` | Str | w |  |
| `usid` | Str | r | xxxxxxxxxxxxxxxx |
| `version` | Str | r | System Software Version: 025-juno_1202_muscat_wario-35696… |
| `waveformversion` | Str | r | 320_R060_AE6C01_ED060KD1C1_TC |

### `com.lab126.todo`

待办队列：系统级异步任务（下载、注册、广告包等）的调度

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `captivePortalResponse` | Str | w |  |
| `demoWifiNotAvailableAlertResponse` | Str | w |  |
| `disableToDo` | Int | w |  |
| `disableToDoForProfileSwitch` | Int | w |  |
| `driveAvailInternally` | Int | r | 1 |
| `enableToDo` | Int | w |  |
| `isToDoAvailable` | Str | w |  |
| `logLevel` | Str | rw | none |
| `logMask` | Str | rw | 0x00000000 |
| `reportStatus` | Str | w |  |
| `scheduleToDo` | Int | w |  |
| `scheduleToDoItems` | Str | w |  |
| `wifiPopupDone` | Str | w |  |
| `wirelessOn` | Str | w |  |

### `com.lab126.todo.kaf`

待办队列在 Java 框架侧的接收端（handleToDoItem）

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `handleToDoItem` | Str | w |  |

### `com.lab126.volumd`

用户分区（/mnt/us）挂载与空间管理　⭐ 本仓库用到

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `driveModeState` | Int | r | 0 |
| `logLevel` | Str | rw | info |
| `logMask` | Str | rw | 0x0fff0000 |
| `recreateUserstoreResponse` | Str | w |  |
| `userstoreDeferUnmountRequest` | Int | w |  |
| `userstoreFreeSpace` | Int | r | 646248 |
| `userstoreIsAvailable` | Int | r | 1 |
| `userstoreReadyToUnMount` | Int | w |  |
| `userstoreTotalSpace` | Int | r | 1042168 |
| `useUsbForNetwork` | Int | rw | 1 |

## 界面与输入

### `com.amazon.kindle.inputMethod`

输入法（IME）与原生层的预编辑接口

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `keyboardCommit` | Str | w |  |
| `keyboardDelete` | Str | w |  |
| `keyboardGetSurround` | Str | w |  |
| `keyboardReplace` | Str | w |  |
| `keyboardSetPreeditString` | Str | w |  |

### `com.lab126.KIWIBridge`

WAF 与原生层之间的 uiQuery 桥

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `uiQuery` | Str | w |  |
| `uiQueryHash` | Has | rw | hash 属性，未展开 |

### `com.lab126.blanket`

全屏「毯子」层：语言选择、USB 提示、广告屏保等覆盖界面　⭐ 本仓库用到

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `load` | Str | rw | langpicker blankwindow ad_screensaver usb |
| `logLevel` | Str | rw | info |
| `logMask` | Str | rw | 0x0fff0000 |
| `uiQuery` | Str | w |  |
| `unload` | Str | rw |  |

### `com.lab126.blanket.ad_screensaver`

广告屏保毯子层的状态查询

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `activeButtonCoordinate` | Str | r |  |
| `screensaver_showing` | Int | r | 0 |

### `com.lab126.booklet.home`

主页/图书馆 booklet 的控制入口

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `deleteOOBE` | Str | w |  |
| `getDisplayOptions` | Str | r |  |
| `go` | Str | w |  |
| `load` | Str | w |  |
| `pause` | Str | w |  |
| `setFilterForGroup` | Str | w |  |
| `setFilterId` | Int | w |  |
| `setSortOrder` | Str | w |  |
| `setViewMode` | Str | w |  |
| `startresult` | Str | w |  |
| `unload` | Str | w |  |
| `validateMerch` | Str | w |  |

### `com.lab126.chromebar`

顶部/底部 chrome 栏（搜索栏、活动指示器）

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `activityIndicator` | Str | w |  |
| `configureChrome` | Str | w |  |
| `searchResults` | Str | w |  |

### `com.lab126.imageViewer`

图片查看器（无 lipc 属性）

`lipc-probe` 没有列出任何属性（服务存在但不用 lipc，或该服务当时未运行）。

### `com.lab126.keyboard`

屏幕键盘：语言、布局、显示/隐藏、预编辑串

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `appID` | Str | r |  |
| `bounds` | Str | r | 0:951:1072:497 |
| `close` | Str | w |  |
| `diacriticalId` | Int | r | 0 |
| `dumpWidget` | Int | rw | 0 |
| `flags` | Int | r | 0 |
| `height` | Int | r | 497 |
| `id` | Int | r | 0 |
| `keyboard_language` | Str | r | en-US |
| `lang` | Int | r | 0 |
| `language` | Str | rw | en_US |
| `languages` | Str | rw | en_US |
| `largeFont` | Str | rw |  |
| `logLevel` | Str | rw | info |
| `logMask` | Str | rw | 0x0fff0000 |
| `open` | Str | w |  |
| `preedit` | Str | r |  |
| `rescan` | Str | r | /var/local/system/keyboard.conf |
| `setSurround` | Str | w |  |
| `show` | Int | r | 0 |
| `uiQueryHash` | Has | rw | hash 属性，未展开 |
| `web` | Int | r | 0 |

### `com.lab126.kwis`

KWIS 小部件守护进程

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `daemon` | Str | w |  |

### `com.lab126.pillow`

系统弹窗、状态栏、快捷设置（WebKit 外壳）　⭐ 本仓库用到

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `activityIndicator` | Str | w |  |
| `applicationWindow` | Str | w |  |
| `customDialog` | Str | w |  |
| `debugInfo` | Str | w |  |
| `disableEnablePillow` | Str | w |  |
| `dismissChrome` | Str | w |  |
| `displayChrome` | Str | w |  |
| `interrogatePillow` | Str | w |  |
| `interrogatePillowHash` | Has | rw | hash 属性，未展开 |
| `logLevel` | Str | rw | info |
| `logMask` | Str | rw | 0x0fff0000 |
| `pillowAlert` | Str | w |  |

### `com.lab126.quickactions`

快捷操作：飞行模式开关、立即同步

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `syncAndCheck` | Str | w |  |
| `toggleAirplaneMode` | Str | w |  |

### `com.lab126.winmgr`

窗口管理器：窗口列表、方向、屏保层、刷新/闪烁控制　⭐ 本仓库用到

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `accelerometer` | Str | r | U |
| `ASRMode` | Int | rw | 0 |
| `chromeState` | Int | rw | 0 |
| `debugInfo` | Str | rw |  |
| `defineWipeCurve` | Str | w |  |
| `eatTapMode` | Int | w |  |
| `enableDispalyEvents` | Int | rw | 0 |
| `epdcMode` | Str | rw | Y8 |
| `extendDamageTimeout` | Int | w |  |
| `fakeKeyEvent` | Str | w |  |
| `fakeTap` | Str | w |  |
| `focusChrome` | Str | w |  |
| `getActiveAppTitle` | Str | r |  |
| `getAllWindows` | Str | w |  |
| `grip_enabled` | Int | rw | 1 |
| `isScreenSaverLayerWindowActive` | Int | r | 0 |
| `liglDebugParams` | Str | w |  |
| `liglFlash` | Str | w |  |
| `liglPause` | Int | rw | 0 |
| `logLevel` | Str | rw | info |
| `logMask` | Str | rw | 0x0fff0000 |
| `orientation` | Str | r | U |
| `orientationLock` | Str | rw | U |
| `pageTurnkeyConfig` | Str | rw | Normal |
| `passwordDialogEnabled` | Int | rw | 0 |
| `refreshOnTurn` | Str | w |  |
| `setAccOrientation` | Str | rw | 0 |
| `setPreference` | Str | w |  |
| `visibleWindows` | Str | w |  |
| `winmgrReady` | Int | r | 1 |

### `com.lab126.winmgr.ligl`

winmgr 的 LIGL（墨水屏刷新算法）日志开关

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `logMask` | Str | w |  |

## 网络与同步

### `com.amazon.ebook.util.net.certmanutilities`

证书管理工具（无 lipc 属性）

`lipc-probe` 没有列出任何属性（服务存在但不用 lipc，或该服务当时未运行）。

### `com.lab126.cmd`

网络连接管理：可用接口、当前接口、强制联网　⭐ 本仓库用到

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `activeInterface` | Str | r | wifi |
| `availableInterfaces` | Has | rw | hash 属性，未展开 |
| `disableInterfaces` | Has | rw | hash 属性，未展开 |
| `ensureConnection` | Str | w |  |
| `interfaceProperties` | Has | rw | hash 属性，未展开 |
| `logLevel` | Str | rw | none |
| `logMask` | Str | rw | 0x00000000 |
| `smsRecvRequired` | Int | rw | 0 |
| `wirelessEnable` | Int | rw | 1 |

### `com.lab126.dynconfig`

动态配置下发

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `handleToDoItem` | Str | w |  |
| `logLevel` | Str | rw | info |
| `logMask` | Str | rw | 0x0fff0000 |
| `transferProgressNotification` | Has | rw | hash 属性，未展开 |

### `com.lab126.linux.arm.connectionutilities`

连接工具：WiFi 弹窗/飞行模式的响应入口

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `captivePortalResponse` | Str | w |  |
| `demoWifiNotAvailableAlertResponse` | Str | w |  |
| `wifiPopupDone` | Str | w |  |
| `wirelessOn` | Str | w |  |

### `com.lab126.refreshCache`

定期刷新各类缓存（联网后触发）

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `captivePortalResponse` | Str | w |  |
| `demoWifiNotAvailableAlertResponse` | Str | w |  |
| `logLevel` | Str | rw | info |
| `logMask` | Str | rw | 0x0fff0000 |
| `refreshCacheFailure` | Str | w |  |
| `refreshCachePrintClients` | Int | w |  |
| `refreshCacheReady` | Str | w |  |
| `refreshCacheRun` | Int | w |  |
| `refreshCacheSuccess` | Str | w |  |
| `updateRefreshTime` | Has | rw | hash 属性，未展开 |
| `wifiPopupDone` | Str | w |  |
| `wirelessOn` | Str | w |  |

### `com.lab126.transfer`

传输队列：下载/上传请求入队与查询

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `captivePortalResponse` | Str | w |  |
| `demoWifiNotAvailableAlertResponse` | Str | w |  |
| `dequeue` | Has | rw | hash 属性，未展开 |
| `dump_queues` | Has | rw | hash 属性，未展开 |
| `get_info` | Has | rw | hash 属性，未展开 |
| `logLevel` | Str | rw | info |
| `logMask` | Str | rw | 0x0fff0000 |
| `modify` | Has | rw | hash 属性，未展开 |
| `obliterate` | Has | rw | hash 属性，未展开 |
| `request_download` | Has | rw | hash 属性，未展开 |
| `request_upload` | Has | rw | hash 属性，未展开 |
| `send_status` | Has | rw | hash 属性，未展开 |
| `wifiPopupDone` | Str | w |  |
| `wirelessOn` | Str | w |  |

### `com.lab126.transferService`

传输进度通知

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `transferProgressNotification` | Has | rw | hash 属性，未展开 |

### `com.lab126.wifid`

WiFi 管理守护进程：扫描、配置文件（profile）、证书、信号强度

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `711` | Str | r | ********* 2- Connection ********* 2.1 MAC: 74:C2:46:FC:4D… |
| `certificateData` | Has | rw | hash 属性，未展开 |
| `cmCheckConnection` | Str | w |  |
| `cmConnect` | Str | w |  |
| `cmConnMode` | Str | w |  |
| `cmDisconnect` | Str | w |  |
| `cmIntfInfo` | Has | rw | hash 属性，未展开 |
| `cmIntfInUse` | Int | r | 1 |
| `cmNWProperties` | Has | rw | hash 属性，未展开 |
| `cmState` | Str | r | CONNECTED |
| `createNetConfig` | Has | rw | hash 属性，未展开 |
| `createProfile` | Has | rw | hash 属性，未展开 |
| `currentEssid` | Has | rw | hash 属性，未展开 |
| `deleteCertificate` | Str | w |  |
| `deleteProfile` | Str | w |  |
| `enable` | Int | rw | 1 |
| `feelingLuckyProfile` | Str | r | HOME_021850_2G |
| `hotSpotDBDownloadStatus` | Int | w |  |
| `installCertificate` | Has | rw | hash 属性，未展开 |
| `logLevel` | Str | rw | info |
| `logMask` | Str | rw | 0x0fff0000 |
| `macAddress` | Str | r | xx:xx:xx:xx:xx:xx |
| `macSecret` | Str | r | xxxxxxxxxxxxxxxxxxxx |
| `manufacturerCode` | Str | r | xxxxxxxxxxxxxxxxxxxx |
| `netConfig` | Has | rw | hash 属性，未展开 |
| `profileCount` | Int | r | 1 |
| `profileData` | Has | rw | hash 属性，未展开 |
| `resetSavePasswordPreference` | Int | w |  |
| `scan` | Str | w |  |
| `scanList` | Has | rw | hash 属性，未展开 |
| `scanListCount` | Int | r | 2 |
| `scanState` | Str | r | idle |
| `signalStrength` | Str | r | 5/5 |

## 内容与索引

### `DeviceMessaging.LanguageLayer.MessageResponse`

语言层消息响应

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `adm_message` | Str | w |  |
| `adm_registration` | Str | w |  |
| `s2dm_message` | Str | w |  |

### `com.lab126.LocalizationServices`

本地化：词典、内容包语言

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `kllDictionary` | Str | w |  |
| `newItemLanguage` | Str | w |  |
| `refreshCache` | Str | w |  |
| `updateContentPack` | Int | w |  |

### `com.lab126.archive`

云端文档（Archive）同步与待办处理

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `handleToDoItem` | Str | w |  |
| `logLevel` | Str | rw | info |
| `logMask` | Str | rw | 0x0fff0000 |
| `refreshCache` | Str | w |  |
| `s2dm_message` | Str | w |  |
| `transferProgressNotification` | Has | rw | hash 属性，未展开 |

### `com.lab126.bookcacher`

按需缓存书本资源

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `cacheBook` | Has | rw | hash 属性，未展开 |

### `com.lab126.ccat`

内容目录（cc.db / ccat）服务

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `logLevel` | Str | rw | info |
| `logMask` | Str | rw | 0x0fff0000 |
| `setActiveProfile` | Str | w |  |

### `com.lab126.contentpackd`

内容包（字体、键盘布局）的安装与挂载

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `fontsMountedState` | Int | r | 1 |
| `fontUpdateCallback` | Str | w |  |
| `installKeyboard` | Str | w |  |
| `logLevel` | Str | rw | info |
| `logMask` | Str | rw | 0x0fff0000 |
| `rebootDevice` | Str | w |  |
| `scanFont` | Str | w |  |

### `com.lab126.coverArtService`

封面提取与缓存

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `downloadCoverArt` | Has | rw | hash 属性，未展开 |
| `downloadCoverArtBatch` | Has | rw | hash 属性，未展开 |
| `getCoverDimensions` | Has | rw | hash 属性，未展开 |
| `refreshCoverArt` | Int | w |  |

### `com.lab126.extractor.java`

Java 提取器的注册与删除

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `add` | Str | w |  |
| `delete` | Str | w |  |
| `logExtractors` | Str | w |  |
| `update` | Str | w |  |

### `com.lab126.grokservice`

全文检索（grokservice）

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `flushCache` | Str | w |  |
| `isLinked` | Str | r | linked |
| `searchRequest` | Str | w |  |

### `com.lab126.indexer`

内容索引器：扫描 documents、生成 cc.db 条目　⭐ 本仓库用到

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `debugTextDumpCount` | Int | rw | 0 |
| `dumpIndexerState` | Int | w |  |
| `indexAndSearchContent` | Str | w |  |
| `numberOfItemsToBeIndexed` | Int | r | 0 |
| `pauseIndexerMilliseconds` | Int | w |  |
| `pauseIndexerSourceMilliseconds` | Str | w |  |
| `pauseIndexerTillTimeMilliseconds` | Str | r | -1 |
| `updateIndexerState` | Int | w |  |

### `com.lab126.instantSearch`

即时搜索与搜索建议

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `handleSearchItem` | Str | w |  |
| `initializeSearch` | Int | w |  |
| `searchRequest` | Str | w |  |
| `storeSuggestionsRequest` | Str | w |  |

### `com.lab126.reader.languagelayer`

语言层（生词提示/词典）重置

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `reset` | Str | w |  |

### `com.lab126.reader.languagelayer.pinyin`

拼音语言层重置

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `reset` | Str | w |  |

### `com.lab126.reader.qa`

阅读器字体/行距的快捷设置（QA 用）

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `fontBoldness` | Int | rw | 0 |
| `fontSize` | Int | rw | 3 |
| `fontStyle` | Str | rw | bookerly |
| `getFontStyles` | Str | r | "amazon ember","condensed","amazon ember bold","futura","… |
| `lineSpacing` | Int | rw | 1 |

### `com.lab126.reader.readingtimer`

阅读计时统计

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `getReadingProgressTypes` | Str | r |  |
| `readingProgressType` | Str | rw | location |

### `com.lab126.readingstreams`

阅读会话流（阅读进度上报）

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `hideContext` | Has | rw | hash 属性，未展开 |
| `openContext` | Has | rw | hash 属性，未展开 |
| `performAction` | Has | rw | hash 属性，未展开 |
| `recordSetting` | Has | rw | hash 属性，未展开 |
| `showContext` | Has | rw | hash 属性，未展开 |

### `com.lab126.readnow`

「立即阅读」入口：直接打开一本书

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `openBook` | Str | w |  |

### `com.lab126.scanner`

内容扫描器：按 appreg.db 的 extractor 关联识别并登记新文件　⭐ 本仓库用到

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `doFullScan` | Int | w |  |
| `fullScanStatus` | Int | r | 0 |
| `logLevel` | Str | rw | info |
| `logMask` | Str | rw | 0x0fff0000 |
| `reScanFile` | Str | w |  |
| `triggerUpdate` | Int | w |  |

### `com.lab126.stored`

商店后台进程（mesquite 实例）

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `kill` | Str | w |  |
| `logLevel` | Str | rw | info |
| `logMask` | Str | rw | 0x0fff0000 |
| `processRestart` | Str | w |  |
| `ready` | Str | r | 1 |
| `refreshCache` | Str | w |  |
| `run` | Str | w |  |
| `transferProgressNotification` | Has | rw | hash 属性，未展开 |

### `com.lab126.yjff`

YJ 相关（无 lipc 属性）

`lipc-probe` 没有列出任何属性（服务存在但不用 lipc，或该服务当时未运行）。

### `com.lab126.yjlipclistener`

YJ（KFX）索引开关

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `disableYJIndexer` | Str | w |  |

## 账号与设备身份

### `AssetOwnership.DeviceSharingUpdated`

设备共享状态变更消息

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `adm_message` | Str | w |  |
| `adm_registration` | Str | w |  |
| `s2dm_message` | Str | w |  |

### `AssetOwnership.SMD.Poll`

资产归属轮询（借阅/共享）

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `handleToDoItem` | Str | w |  |
| `logLevel` | Str | rw | info |
| `logMask` | Str | rw | 0x0fff0000 |
| `refreshCache` | Str | w |  |
| `s2dm_message` | Str | w |  |
| `transferProgressNotification` | Has | rw | hash 属性，未展开 |

### `HouseholdMessage.Updates`

Household 更新消息

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `adm_message` | Str | w |  |
| `adm_registration` | Str | w |  |
| `s2dm_message` | Str | w |  |

### `com.amazon.java.messagingservice`

Amazon 消息服务（s2dm/adm 下行消息）

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `adm_message` | Str | w |  |
| `adm_registration` | Str | w |  |
| `s2dm_message` | Str | w |  |

### `com.lab126.DeviceAuthenticationService`

设备认证 Cookie 的获取与安装

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `authcookies` | Str | r | session-id=135-5025856-4810245; expires="23 Feb 2043 23:5… |
| `cookies` | Str | r |  |
| `fetchAuthCookies` | Int | w |  |
| `fetchAuthCookiesForRegionalStack` | Int | w |  |
| `installCredentials` | Int | w |  |

### `com.lab126.IdentityService`

身份令牌（accessToken）的获取与失效

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `accessToken` | Has | rw | hash 属性，未展开 |
| `invalidateAccessToken` | Str | w |  |
| `refreshCache` | Str | w |  |

### `com.lab126.KindleIdentity`

设备类型与 GUID

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `deviceType` | Str | r | A21RY355YUXQAF |
| `GUID` | Str | r | xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx |

### `com.lab126.amazonRegistrationService`

注册状态：isRegistered、注册/注销令牌　⭐ 本仓库用到

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `deregister` | Int | w |  |
| `isRegistered` | Int | r | 1 |
| `primaryUserId` | Str | r |  |
| `registerPrimaryUser` | Has | rw | hash 属性，未展开 |
| `registerSecondaryUser` | Has | rw | hash 属性，未展开 |
| `registerWithPreAuthorizedCode` | Str | w |  |
| `registerWithToken` | Str | w |  |

### `com.lab126.freetime`

Amazon Kids+（FreeTime）订阅状态

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `refreshCache` | Str | w |  |
| `rejectSubscriptionOffer` | Str | w |  |
| `subscriptionStatus` | Int | r | 0 |
| `updateChildrenSubscriptionStatus` | Str | w |  |

### `com.lab126.household`

家庭/多用户档案（Household & Profiles）

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `activeAdultProfile` | Str | r |  |
| `activeProfile` | Str | r |  |
| `activeProfileRole` | Str | r | ADULT |
| `linkSecondaryAdultToHousehold` | Str | w |  |

## 电源

### `com.lab126.phd`

电源/健康相关的计划任务（SPH 调度）

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `logLevel` | Str | rw | info |
| `logMask` | Str | rw | 0x0fff0000 |
| `newSPHSchedule` | Str | w |  |

### `com.lab126.powerd`

电源管理：屏保、休眠、充电、电源键、前光　⭐ 本仓库用到

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `abortSuspend` | Int | w |  |
| `addSuspendLevels` | Int | w |  |
| `battLevel` | Int | r | 51 |
| `battStateInfo` | Str | r |  |
| `battTemperature` | Int | r | 73 |
| `deferRestart` | Int | w |  |
| `deferSuspend` | Int | w |  |
| `flAuto` | Int | rw | 0 |
| `flIntensity` | Int | rw | 24 |
| `flMaxIntensity` | Int | r | 25 |
| `flRawIntensity` | Int | r | 3280 |
| `flStartup` | Int | w |  |
| `flTurboBrightnessIntensity` | Int | r | 1 |
| `isCharging` | Int | r | 0 |
| `isLowTempState` | Int | r | 0 |
| `logLevel` | Str | rw | none |
| `logMask` | Str | rw | 0x00000000 |
| `powerButton` | Int | w |  |
| `preventScreenSaver` | Int | rw | 0 |
| `rtcWakeup` | Int | w |  |
| `rtcWakeup2` | Str | w |  |
| `sendPendingResume` | Int | w |  |
| `shutdownAlertResponse` | Str | w |  |
| `state` | Str | r | active |
| `status` | Str | r | Powerd state: Active Remaining time in this state: 588.59… |
| `suspendGrace` | Int | w |  |
| `touchScreenSaverTimeout` | Int | w |  |
| `wakeUp` | Int | w |  |

## 外设

### `com.lab126.btService`

蓝牙音频可用性查询

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `isAudibleAvailable` | Int | r | 0 |
| `isAudibleContentAvailable` | Int | r | 0 |
| `isPfmAudibleSupported` | Int | r | 0 |

### `com.lab126.btfd`

蓝牙：配对、连接、A2DP、BLE

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `BLEdisable` | Str | w |  |
| `BLEenable` | Str | w |  |
| `Bond` | Str | w |  |
| `BTconnectedDevName` | Str | r |  |
| `BTenable` | Str | w |  |
| `BTflightMode` | Int | w |  |
| `BTmetadata` | Has | rw | hash 属性，未展开 |
| `BTplaybackData` | Has | rw | hash 属性，未展开 |
| `btPopupDone` | Str | w |  |
| `BTstate` | Int | r | 1 |
| `Connect` | Str | w |  |
| `currentBTOperatingMode` | Int | r | 2 |
| `Disconnect` | Str | w |  |
| `DiscoverA2DP` | Int | w |  |
| `DumpStateInfo` | Int | w |  |
| `ensureBTconnection` | Str | w |  |
| `hasNeverPaired` | Int | r | 1 |
| `isAudibleAvailable` | Int | r | 1 |
| `isBtchQueuedOrRunning` | Int | r | 0 |
| `isBtchRunning` | Int | r | 0 |
| `ListConnected` | Has | rw | hash 属性，未展开 |
| `ListDiscovered` | Has | rw | hash 属性，未展开 |
| `ListPaired` | Has | rw | hash 属性，未展开 |
| `logLevel` | Str | rw | info |
| `logMask` | Str | rw | 0x0fff0000 |
| `PairUserConfirmation` | Int | w |  |
| `triggerBTscan` | Int | w |  |
| `Unbond` | Str | w |  |

### `com.lab126.deviced`

设备抽象层：触摸开关、USB 音频等硬件事件

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `enable_touch` | Int | w |  |
| `usbaudioConnected` | Int | rw | 0 |
| `usbaudioSendEvent` | Int | w |  |

### `com.lab126.odot`

ODOT 消息队列（推测与 OTG/配件有关）

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `queueMessage` | Str | w |  |

### `com.lab126.tphv3`

TPH v3（推测与触控/手势处理有关）

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `debugTphv3SessionCount` | Int | r | 1 |
| `debugTphv3SessionTimeout` | Int | r | 28 |
| `debugTphv3SilentPeriod` | Int | r | 27 |
| `debugTphv3State` | Int | r | 2 |
| `debugTphv3StillHereCount` | Int | r | 6 |
| `debugTphv3Supported` | Int | r | 1 |
| `debugTphv3UdpTphCount` | Int | r | 0 |

## 其他

### `CampaignSync.Invalidate`

营销活动缓存失效（无 lipc 属性）

`lipc-probe` 没有列出任何属性（服务存在但不用 lipc，或该服务当时未运行）。

### `CampaignSync.Update`

营销活动更新消息

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `adm_message` | Str | w |  |
| `adm_registration` | Str | w |  |
| `s2dm_message` | Str | w |  |

### `DPCService.SettingChanged`

DPC 设置变更消息

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `adm_message` | Str | w |  |
| `adm_registration` | Str | w |  |
| `s2dm_message` | Str | w |  |

### `com.lab126.JournalingService`

日志/日记服务开关

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `isEnabled` | Int | r | 1 |

### `com.lab126.adManager`

广告（Special Offers）管理

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `adImpression` | Str | w |  |
| `adViewerMessage` | Str | w |  |
| `buttonClicked` | Str | w |  |
| `forceVisibleAdId` | Str | rw | {"adId":"null"} |
| `ingestAdFile` | Str | w |  |
| `isAdUnitDevice` | Int | r | 1 |
| `restart` | Str | w |  |

### `com.lab126.adRotationManager`

屏保广告轮播

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `currentAd` | Str | r |  |
| `nextAd` | Str | r |  |
| `peekNextAd` | Str | r |  |
| `restart` | Str | w |  |
| `startRotationController` | Str | r |  |

### `com.lab126.bev`

（无 lipc 属性，作用未知）

`lipc-probe` 没有列出任何属性（服务存在但不用 lipc，或该服务当时未运行）。

### `com.lab126.demd`

设备指标（metrics）上报

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `demAppMetricsEmissionStatus` | Int | rw | 2 |
| `demOsMetricsEmissionStatus` | Int | rw | 2 |
| `logDemAppMetric` | Has | rw | hash 属性，未展开 |
| `logDemOsMetric` | Has | rw | hash 属性，未展开 |
| `logLevel` | Str | rw | info |
| `logMask` | Str | rw | 0x0fff0000 |

### `com.lab126.demoservice`

演示模式（无 lipc 属性）

`lipc-probe` 没有列出任何属性（服务存在但不用 lipc，或该服务当时未运行）。

### `com.lab126.devicemetrics`

设备指标按类上报

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `captivePortalResponse` | Str | w |  |
| `demoWifiNotAvailableAlertResponse` | Str | w |  |
| `handleToDoItem` | Str | w |  |
| `logLevel` | Str | rw | info |
| `logMask` | Str | rw | 0x0fff0000 |
| `pushAllMetrics` | Int | w |  |
| `pushClickstreamMetrics` | Int | w |  |
| `pushHighPriorityMetrics` | Int | w |  |
| `pushMetricsByClass` | Str | w |  |
| `refreshCache` | Str | w |  |
| `transferProgressHandler` | Has | rw | hash 属性，未展开 |
| `wifiPopupDone` | Str | w |  |
| `wirelessOn` | Str | w |  |

### `com.lab126.dpm.apps`

按应用维度的策略开关（注释/公开笔记等）

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `disableAnnotationsBackup` | Int | w |  |
| `disablePopularHighlights` | Int | w |  |
| `disablePublicNotes` | Int | w |  |

### `com.lab126.dpmManager`

设备策略管理：家长控制、限制项、设备密码

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `contactInfo` | Str | r | Your System Administrator |
| `devicePolicyId` | Str | r |  |
| `getControlStatus` | Int | r | 0 |
| `isActiveContentDisabled` | Int | r | 0 |
| `isAnnotationsBackupDisabled` | Int | r | 0 |
| `isArchivedItemsDisabled` | Int | rw | 0 |
| `isBrowserDisabled` | Int | rw | 0 |
| `isChangeDictionaryDisabled` | Int | r | 0 |
| `isChangeLanguageDisabled` | Int | r | 0 |
| `isDeregisterDisabled` | Int | r | 0 |
| `isDiscoveryDisabled` | Int | rw | 0 |
| `isEditDeviceNameDisabled` | Int | r | 0 |
| `isEditPasscodeDisabled` | Int | r | 0 |
| `isEditPersonalInfoDisabled` | Int | r | 0 |
| `isExperimentalMenuDisabled` | Int | r | 0 |
| `isFactoryResetDisabled` | Int | r | 0 |
| `isKindleStoreDisabled` | Int | rw | 0 |
| `isManageWifiSettingsDisabled` | Int | r | 0 |
| `isMinPasscodeLengthEnabled` | Int | r | 0 |
| `isMp3PlayerDisabled` | Int | r | 0 |
| `isParentalPasswordSet` | Int | r | 0 |
| `isPopularHighlightsDisabled` | Int | r | 0 |
| `isPublicNotesDisabled` | Int | r | 0 |
| `isSettingsMenuDisabled` | Int | r | 0 |
| `isSocialNetworksDisabled` | Int | r | 0 |
| `isToggleAnnotationsBackupDisabled` | Int | r | 0 |
| `isTogglePopularHighlightsDisabled` | Int | r | 0 |
| `isTogglePublicNotesDisabled` | Int | r | 0 |
| `isToggleWirelessDisabled` | Int | r | 0 |
| `isTurnOffPasscodeDisabled` | Int | r | 0 |
| `isTurnOnPasscodeDisabled` | Int | r | 0 |
| `isWikipediaLookupDisabled` | Int | rw | 0 |
| `logLevel` | Str | rw | info |
| `logMask` | Str | rw | 0x0fff0000 |
| `maxPasscodeAttempts` | Int | r | -1 |
| `minPasscodeLength` | Int | r | 1 |
| `notifyDeviceControlsStateChange` | Str | w |  |
| `parentalControlsHint` | Str | rw |  |
| `secondaryProxyExcludedHosts` | Str | r |  |
| `secondaryProxyHost` | Str | r |  |
| `secondaryProxyPort` | Str | r |  |
| `setParentalControlsPassword` | Has | rw | hash 属性，未展开 |
| `showAppLockedAlert` | Has | rw | hash 属性，未展开 |
| `validateParentalControlsPassword` | Has | rw | hash 属性，未展开 |
| `wipeAfterMaxPasscodeAttempts` | Int | r | 0 |

### `com.lab126.dsus`

设备软件更新服务（DSUS）版本上报

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `reportVersion` | Str | w |  |

### `com.lab126.fastMetrics`

高优先级指标快报

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `captivePortalResponse` | Str | w |  |
| `demoWifiNotAvailableAlertResponse` | Str | w |  |
| `logLevel` | Str | rw | info |
| `logMask` | Str | rw | 0x0fff0000 |
| `wifiPopupDone` | Str | w |  |
| `wirelessOn` | Str | w |  |

### `com.lab126.kindleStatusService`

设备状态日志上报

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `log` | Str | w |  |
| `logToFile` | Str | w |  |
| `recordConfigMetrics` | Str | w |  |

### `com.lab126.kwis.weblabTreatments`

Weblab 实验开关（KWIS 侧）

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `experiments` | Has | rw | hash 属性，未展开 |

### `com.lab126.legalComplianceService`

GDPR/合规提示状态

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `gdprValue` | Int | r | 1 |

### `com.lab126.linux.arm.metrics`

指标上报（无 lipc 属性）

`lipc-probe` 没有列出任何属性（服务存在但不用 lipc，或该服务当时未运行）。

### `com.lab126.lxinit`

（无 lipc 属性，作用未知）

`lipc-probe` 没有列出任何属性（服务存在但不用 lipc，或该服务当时未运行）。

### `com.lab126.merchant`

商户/推荐位（shuffle、removeAll）

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `remove` | Str | w |  |
| `removeAll` | Str | w |  |
| `shuffle` | Str | rw | true |

### `com.lab126.sharing`

分享到社交网络

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `isSharingEnabled` | Int | r | 0 |
| `shareBookEvent` | Str | w |  |
| `shareBookText` | Str | w |  |
| `shareMessageAboutBook` | Str | w |  |

### `com.lab126.sph`

（无 lipc 属性，作用未知）

`lipc-probe` 没有列出任何属性（服务存在但不用 lipc，或该服务当时未运行）。

### `com.lab126.tutorialService`

新手引导状态

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `clearAllTutorialStatus` | Str | w |  |

### `com.lab126.wishlist`

心愿单缓存刷新

| 属性 | 类型 | 读/写 | 示例值 |
|---|---|---|---|
| `refreshCache` | Str | w |  |

---

生成方式：`python tools/gen_lipc_catalog.py <lipc-probe 转储>`。
属性名与类型是设备上的事实数据；「职责」等描述为本仓库撰写。
参考资料：[KindleModding Wiki — Kindle Apps & Services](https://kindlemodding.org/kindle-apps-and-services/)（CC BY-NC 4.0）。
