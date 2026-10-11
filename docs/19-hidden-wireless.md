# 19 隐藏无线界面（nowifi）+ 泡面模式开关

未注册 / fakereg 的机器本来就不该联网，界面上那一排无线入口就变得很碍事：状态栏一直显示
Wi-Fi 或「无服务」的 WAN 条，下拉快捷设置里有飞行模式/同步/全部设置，⋮ 菜单里还有
「网页浏览器」「设置」「Amazon Kids」。这一章记录怎么把这些入口去掉，以及去掉之后
怎么从 KUAL 里开关无线（菜单里叫「泡面模式」）。

涉及两个部件：

| 部件 | 文件 | 作用 |
|---|---|---|
| JS 补丁 | `tools/patch_kpp_nowifi.py` → `/app/KPPMainApp/js/KPPMainApp.js.hbc` | 去掉快捷设置那一排、顶栏购物车、⋮ 菜单里的三项目 |
| 注入库 | `extensions/kindletweaks/nowifi/libkt_nowifi.c` → `libkt_nowifi.so` | 状态栏的 Wi-Fi / 飞行模式 / WAN 图标画成空白 |

菜单里的「泡面模式」开关是纯运行时操作，不碰任何文件，实现在 `tweak.sh` 的 `airplane()`。

验证机型：Oasis 3（10th gen），FW 5.15.1.1，Hermes 字节码版本 84，`KPPMainApp.js.hbc` 2071500 字节。

## 1. JS 补丁的四个锚点

`tools/patch_kpp_nowifi.py` 只认特征，不认偏移；对不上就 assert 失败、不改文件。

### 1.1 下拉快捷设置那一排

画这一排的 `render` 里加载了字符串 `quicksettings.widgetview`，全文件唯一。
把函数第一条指令改成 `return null`（`LoadConstNull r0; Ret r0`，4 字节）。这一排里有
飞行模式、夜间模式、同步、全部设置 —— 连带「全部设置」一起没了，界面上就进不了设置。

### 1.2 顶栏购物车

`RenderTopNavBarButtons` 里找 `GetByIdShort …, KPP_STORE` 后面紧跟 `JStrictEqual` 的那条，
就是 KPP_STORE 分支的入口，把它改成 `return null`。

### 1.3 ⋮ 菜单里的三项（这里踩过坑）

**id 不是语言包键的后缀。** ⋮ 菜单是原生造出来的，链条是：

```
kpp::library::native::KPPChromeConfigUtils::BuildOverflowMenuConfig(bool)   ← 造 items[]
  ├─ 固定顺序循环 kpp::library::native 里的静态 vector<string>：
  │     goodreads / freetime / browser / settings / legal / kindleSpecialOffers
  ├─ 条件加 readingList（书单）、kindleUnlimited
  └─ 再拼上 ksdk::library::ActionSources::CHROME_OVERFLOW_MENU_ACTIONS
        （「新建收藏夹」这类书库动作就是这么来的）
        ↓ 每个动作取 getId() / getLabel()
     KPPNavigation::NavigationActionInterface::getId()   → 构造函数第 2 个字符串
     KPPNavigation::NavigationActionInterface::getLabel()→ 构造函数第 3 个字符串（语言包键）
        ↓ 拼成 {"id":…, "label":…, "group":…, "source":"library", "handling":"system", "state":…, "uri":""}
     KPPChrome::ChromeConfigJsonParserUtils::getContextMenuList() → KPPChrome::ContextMenuItem
        ↓ 送到 JS
     KPPMainApp.js.hbc 的 ContextMenuItem 组件（item.id / item.label，label 再过一次 getText）
```

所以：

| 界面上的字 | 语言包键 | **item.id** |
|---|---|---|
| 网页浏览器 | `chrome.header.overflow.menu.browser` | `browser` |
| 设置 | `chrome.header.overflow.menu.settings` | `settings` |
| Amazon Kids | `chrome.header.overflow.menu.amazon_kids` | **`freetime`** |
| 您的书单 | `chrome.header.overflow.menu.reading_lists` | `readingList` |
| 法律声明 | `chrome.header.overflow.menu.legal` | `legal` |

（Amazon Kids 的 id 来自 `NavigationActionFactory::getFreeTimeItem`：它给动作传的是
`freetime`，标签键才是 `…menu.amazon_kids`。上一版补丁按「长度 11、第 0 位 a、第 6 位 _」
猜 `amazon_kids`，永远命不中。）

还有一个容易混的 id 集合：`ChromeConfigDefaultUtils::isAppSwitchMenuItem` 里判的
`goodreads / webBrowser / legal / amazonKids / kindleSpecialOffers / aboutThisBook / xray /
kindleUnlimited` —— 那是**各个 app 自己 configureChrome 时上报的 id**（更多页、商店、
阅读器上下文菜单用），跟书库 ⋮ 菜单不是一套，别照着它写判断。

### 1.4 判断怎么插进 ContextMenuItem

`ContextMenuItem` 前面插一段前导，命中就 `return null`：

```
r1 = props.item.id
r1 == 'browser'  → 返回 null
r1 == 'settings' → 返回 null
'freetime.conditionsofuse.landing.page'.indexOf(r1) == 0 → 返回 null     ← Amazon Kids
```

之所以用 `indexOf` 判前缀：**字符串表里没有 `freetime` 这个字面量**（只有
`freetime.conditionsofuse.landing.page` 之类），而 `LoadConstString` 只能引用已有字符串，
不能凭空造一个。`indexOf(id) === 0` 只对 `freetime` 及其真前缀成立，正好够用。

函数变长了放不回原处，于是把整个函数体搬到文件末尾（footer 前），改函数头里的
偏移与长度、再改 `header.fileLength`，最后重算文件末尾 SHA1。三点前提脚本会检查：
函数头不是 overflowed、没有异常表、没有 switch 表（Hermes 的跳转都是相对地址，
函数体整体平移不影响）。插入的前导必须 < 127 字节，因为 `JStrictEqual` 用的是 Addr8。

## 2. 状态栏图标（LD_PRELOAD）

状态栏进程 `JunoStatusBarDriver` 链接 `libJunoStatusBarShared.so`，图标全部交给 librsvg 渲染。
`libkt_nowifi.c` 拦截 `rsvg_handle_new_from_data` / `rsvg_handle_new_from_file`，命中就换成
同尺寸的空白 SVG（viewBox 不变，所以布局不动，只是那一格画成空白）：

| 图标 | 特征 |
|---|---|
| Wi-Fi 信号 | 现场拼的 SVG，半径 70 的扇形圆弧（`A 70.000000,70.000000`） |
| WAN 信号条 | `width="14.300000" height="20.000000"` |
| WAN 无服务 | `width="16.000000" height="5.000000"` |
| 飞行模式 | 文件 `/app/KPPMainApp/res/core/systemStatus/AirplaneMode.svg` |

电池、锁、音量等一律原样放行。编译（`-z lazy` 必需，zig 默认 BIND_NOW，Kindle 的
glibc 2.20 `ld.so` 会报 `unexpected reloc type 0x24`）：

```sh
python -m ziglang cc -target arm-linux-gnueabi.2.20 -mcpu=cortex_a7 -shared -fPIC -O2 -s \
    -Wl,-z,lazy -o libkt_nowifi.so libkt_nowifi.c
```

## 3. 泡面模式（无线开关）

界面上的无线入口被隐藏之后，系统里就没有开关无线的地方了，所以在 KUAL 里补一个。
走的是系统「飞行模式」小部件**同一条路**（反汇编 `/app/bin/KPPMainAppV2` 确认）：

```
KPPSettings::QuickSettings::AirplaneWidgetController::execute
  → KPPSettings::ServiceProvider::ConnectionManagerServiceProvider::toggleWirelessConnection
  → KindleIpc::LipcWrapper::setProperty<int>(com.lab126.cmd, wirelessEnable, …)
```

* 状态：`lipc-get-prop -i com.lab126.cmd wirelessEnable`（1 = 无线开，0 = 无线关）
* 开关：`lipc-set-prop -i com.lab126.cmd wirelessEnable 0|1`

系统里还有个 `com.lab126.quickactions toggleAirplaneMode`（只写、只能翻转），
`tweak.sh` 没用它，因为直接写属性才能「指定开还是关」，也才能先比状态再决定要不要动。

菜单项显示成「泡面模式 [已开启/已关闭] → 开启 / 关闭」，SSH 里的命令名仍是
`tweak.sh airplane on|off`，`tweak.sh status` 里有一行 `airplane:`。

### 实测（Oasis 3 / 5.15.1.1）

| wirelessEnable | 实测结果 |
|---|---|
| 0（泡面模式开） | `iwconfig wlan0` → **No such device**，`cmState=NA`，`scanState=idle` |
| 1（泡面模式关） | 5 秒后 `cmState=CONNECTED`，IP 回来，SSH 恢复 |

⚠ 关无线会一并断掉 **WiFi 上的 SSH**；USB 网的 SSH 不受影响。真机验证时先布置看门狗
（`setsid sh -c 'sleep 30; lipc-set-prop -i com.lab126.cmd wirelessEnable 1'`），
否则 SSH 断了没法自己开回来。

## 4. 怎么部署（现在就是固化在设备上的）

这一功能有两半，分别落在两处，都在 KUAL 的「Kindle Tweaks」里开关，**重启不受影响**：

| 半 | 落在哪 | 谁管 | KUAL 菜单项 |
|---|---|---|---|
| hbc 三处界面 | `/app/KPPMainApp/js/KPPMainApp.js.hbc`（系统分区） | 功能 1 的补丁单元（`files/KPPMainApp.js.hbc.patched`） | 「去除「云端不可用」弹窗 + 隐藏无线界面」 |
| 状态栏图标 | `/etc/upstart/statusbar.conf` 的 exec 行（系统分区）+ `nowifi/libkt_nowifi.so`（用户分区） | `tweak.sh nowifi on\|off` | 「隐藏状态栏无线图标（nowifi）」 |

### 4.1 hbc：popup 打底，nowifi 叠加

`patch_kpp.py`（去弹窗）和 `patch_kpp_nowifi.py`（隐藏无线界面）打的是**同一个** hbc，
而「去弹窗」是必备的，所以就让 popup 的 `.patched` 直接做成叠加版，一个开关带两半：

```sh
python tools/patch_kpp.py        KPPMainApp.js.hbc.orig KPPMainApp.js.hbc.patched
python tools/patch_kpp_nowifi.py KPPMainApp.js.hbc.patched KPPMainApp.js.hbc.patched   # 就地叠加
scp KPPMainApp.js.hbc.* root@<kindle-ip>:/mnt/us/extensions/kindletweaks/files/
```

两个补丁改的区域不重叠，先后顺序无所谓，但 `.patched` 必须是「先 popup 再 nowifi」的结果。
只想留去弹窗、不要隐藏无线界面时，跳过第二条命令，重新生成 `.patched` 后再点一次 `popup on`
即可（`set_unit` 按 md5 判断要不要写）。

写入靠 `tweak.sh popup on`（`set_unit`）：先 `mntroot rw`，`cp .patched 目标`，再 `mntroot ro`，
最后 `restart kppmainapp`。`tweak.sh status` 里的 `popup:` 就是拿目标文件的 md5 和
`.orig` / `.patched` 比出来的，所以固化以后它显示 `on`。

### 4.2 状态栏：LD_PRELOAD 注入 statusbar 任务

`JunoStatusBarDriver` 由 upstart 任务 `/etc/upstart/statusbar.conf` 拉起，改它的 exec 行
（和 `libraryview` 改 `kppmainapp.conf` 一个套路，见 docs/07）：

```sh
tweak.sh nowifi on     # = mntroot rw + sed 改 statusbar.conf 的 exec 行 + kill -HUP 1
                       #   + 重启 JunoStatusBarDriver（upstart 的 respawn 不会换环境）
tweak.sh status        # nowifi(statusbar icons): on（状态栏已注入）
```

改完的那一行长这样：

```
exec env LD_PRELOAD=/mnt/us/extensions/kindletweaks/nowifi/libkt_nowifi.so /app/bin/JunoStatusBarDriver
```

`.so` 在用户分区（`extensions/kindletweaks/nowifi/`），不进 git，要在电脑上编译后 scp 过去。

### 4.3 升级固件后

系统分区被替换，两半都会没：`tweak.sh all on`（KUAL 里的「升级固件后：全部补丁重新开启」）
会把 hbc 写回去、也会重新给 statusbar.conf 加注入行。

### 4.4 临时试用（调试时才用）

不想写系统分区时，可以用 tmpfs 盖住 hbc，重启即恢复：

```sh
export PATH=/usr/sbin:/sbin:$PATH
mount -t tmpfs -o size=64m tmpfs /app/KPPMainApp/js/KPPMainApp.js.hbc
cat /mnt/us/kt-nowifi-both.hbc > /app/KPPMainApp/js/KPPMainApp.js.hbc
restart kppmainapp
```

注意 tmpfs 是**叠**上去的（`/proc/mounts` 里会有多行），重启就没了；这时 `tweak.sh status`
里 `popup:` 会显示「文件不匹配」（既不是 `.orig` 也不是 `.patched` 的 md5），属正常现象。
状态栏那半同理：临时用可以 `kill` 掉状态栏进程，再用
`LD_PRELOAD=/tmp/libkt_nowifi.so /app/bin/JunoStatusBarDriver &` 手工起一个（重启即恢复）。

## 5. 换固件后怎么重做

1. 重新跑 `python tools/patch_kpp_nowifi.py <hbc> <out>`。脚本对不上任何一处都会直接
   assert 报错，不会写坏文件。
2. 报「字符串表里没有 xxx」/「找到 0 个 ContextMenuItem」/「找到 N 个 …」时，用
   `hermes-dec` 重新定位：`LoadConstString 'quicksettings.widgetview'` 的 render、
   `RenderTopNavBarButtons` 的 KPP_STORE 分支、`ContextMenuItem`（名字在函数表的
   `functionName` 里）。
3. 若 `item.id` 那套判断失效，重新反汇编 `/app/bin/KPPMainAppV2`，按第 1.3 节那条链
   找 `BuildOverflowMenuConfig` 用的 id（`strings` 里搜 `chrome.header.overflow.menu.`
   能一次看到所有标签键）。
4. 状态栏图标特征（半径 70、14.3/16 宽、AirplaneMode.svg）在新固件上可能变，先
   `rsvg` 钩子只打印不替换跑一遍，把实际 SVG 打出来再改特征。

## 6. 坑位清单

* **字符串表里没有的字符串不能直接比较**：`freetime`、`amazon_kids` 都不在表里，
  要么用前缀判断（第 1.4 节），要么改字符串表（工作量不划算）。
* **`⋮` 在 GBK 控制台会抛 `UnicodeEncodeError`**：Windows 上跑补丁脚本时对 stdout 设
  `errors="replace"`（脚本里已经加了），否则打印到一半就崩，且崩在写文件之前。
* **Addr8 跳转**：前导超过 127 字节就跳不过去，脚本里有 `assert off_null < 127`。
* **tmpfs 挂载重启失效**，`.patched` 也不是「装了就一直生效」——升级固件后系统分区整个被替换。
* **关无线＝断 SSH**，调试时先布置看门狗或用 USB 网。
