# 16 常驻网页应用（WAF）与 UI 方案选型

> 这篇解决两件事：
> 1. **怎么让 HTML+JS 应用在越狱 Kindle 上永久常驻** —— 本仓库的「常驻网页应用（WAF）」功能；
> 2. **越狱 Kindle 上写 UI 到底该选哪条路** —— 附在 Oasis 3 / FW 5.15.1.1 上的实测数据。
>
> 文中标「实测」的都在本仓库的验证机上跑过；标「文档证据」的是读设备上的启动脚本/配置得出的结论。

## 1 结论速览

| 路线 | 本机可用性 | 最适合的 UI |
|---|---|---|
| **WAF（HTML+JS）** | 实测跑通（本功能） | 一屏文字/列表/按钮，点了就跳转的**内容型**界面 |
| **GTK+2 原生（C/C++）** | 环境齐备，只差交叉工具链（实测） | 多窗口、对话框、要用系统键盘、长期常驻的**真应用** |
| **Python + Pillow + fbink** | 全部就绪（实测） | 单屏自绘、图表/仪表盘；**能自己掌控墨水屏刷新** |
| KOReader 插件 | 未装 | 想白拿一套成熟 UI 框架（控件、手势、刷新、i18n） |
| `com.lab126.pillow` 弹窗 | 就绪 | 只是想让脚本弹个确认框 |

**一句话**：墨水屏上「**谁控制刷新**」比「用什么语言」更决定体验。fbink 让你控制，WAF 和 GTK 把控制权交给系统的 `lab126_ligl.lua`。你现有的脚本体系离 Python+fbink 最近，你现有的 JS/TS 项目离 WAF 最近。

## 2 WAF 是什么，和 Mesquito / KWebBrew 什么关系

**WAF**（Web Application Framework）是 Kindle 里跑 WebKit 应用的机制：一个目录，里面必须有 `config.xml`（元数据 + 权限 + 开放哪些 JS API）和入口页（`config.xml` 里 `<content src>` 指定），再在 `appreg.db` 里注册，就能被 `appmgrd` 像系统应用一样启动。商店、浏览器、设置里的很多页面都是 WAF。

社区的两个"启动器"都利用了这套机制，但**借道方式不同**，这决定了它们的常驻性：

| | KWebBrew | Mesquito |
|---|---|---|
| 宿主 | 体验版**浏览器** WAF | **商店** WAF |
| 入口 | 书签 → `file:///mnt/us/kwebbrew/index.html` | 覆盖商店的 HTML5 缓存：`.active_content_sandbox/store/resource/cachedResources/index.html` |
| 劫持的是 | **用户数据**（书签） | **受管缓存**（appcache） |
| 系统会自动重建它吗 | 不会 → 持久 | 会 → **半持久** |
| `window.kindle` | 没有（无 lipc、无设备 API） | 有（完整 WAF 上下文） |
| 固件上限 | ≤ 5.16.3（5.16.4 起浏览器不支持 `file://`） | < 5.18.1 |
| 维护状态 | archived，最后提交 2024-11 | archived，最后提交 2025-05 |

Mesquito 是 KWebBrew 的继任者（同一作者，manifest 格式同源，Mesquito 用 `compatabilityWrapper.html` 兼容老的非 WAF 应用）。它俩的 README 自己都承认 Mesquito 是 "semi-persistent … might also randomly disappear by itself during cache refresh"。

**为什么 Mesquito 的常驻性天生差**（除了"商店会刷新缓存"这个设计层面的原因，还有一个设备上的硬证据）：

```
# /etc/upstart/filesystems_var_local.conf（开机脚本）
if [ -e /var/local/mesquite/store/resource/appcache/ApplicationCache.db ]; then
    rm -rf /var/local/mesquite/store/resource/appcache/ApplicationCache.db
    rmdir --ignore-fail-on-non-empty -p /var/local/mesquite/store/resource/appcache/
fi
```

**开机就会主动清掉商店的 app 缓存** —— 正是 Mesquito 用来引导自己的那个地方。

**本功能走的是第三条路：正规注册。** 不碰任何缓存，注册信息写在 `/var/local/appreg.db`（ext3 持久分区，不是只读 rootfs），`/var/local/mesquite/ktweb-*` 开机只被 `chown`、不会被删（文档证据）。所以拿 Mesquito 的能力、拿 KWebBrew 的耐久。

> ✅ **重启存活：已实测。** 原先这一条只有"开机脚本不碰 `appreg.db`、不删 `ktweb-*`"的文档证据；
> 后来一次真机重启后复查，`appreg.db` 里的 `com.kindletweaks` 注册**仍然在**（`webapp list` 仍列出
> `sample`，db 内匹配行数 8），`/mnt/us/videos/` 与播放器也都在。所以"正规注册 = 耐久"这条现在是实测结论，
> 不再是推断。（注意 `appreg.db` 的 md5 会在重启后变化 —— 框架自己会写这个库，属正常现象。）

## 3 怎么用

**前置条件**：已越狱（能 root）。不需要装 Mesquito/KWebBrew，不需要联网。

**放应用**：把应用目录放进 `/mnt/us/webapps/`，目录名就是应用名，里面必须有 `index.html`：

```
/mnt/us/webapps/
└── myapp/
    ├── index.html        ← 必须
    ├── manifest.json     ← 可选（决定菜单里显示的名字，Mesquito/KWebBrew 格式）
    └── config.xml        ← 可选（自己写就用自己的，不写就按模板生成）
```

**KUAL**：「Kindle Tweaks」→「常驻网页应用（WAF）」→ 候选应用 → 安装并常驻 / 立即打开 / 卸载。

**SSH**：

```sh
E=/mnt/us/extensions/kindletweaks
sh $E/tweak.sh webapp scan                 # 列出候选应用（名字|来源|是否已常驻）
sh $E/tweak.sh webapp install myapp        # 装到 /var/local/mesquite/ktweb-myapp 并注册
sh $E/tweak.sh webapp launch myapp         # 立即打开
sh $E/tweak.sh webapp state myapp          # on / off
sh $E/tweak.sh webapp uninstall myapp      # 取消注册并删安装目录（源目录保留）
sh $E/tweak.sh webapp restore              # 按安装清单重装全部（升级固件后用）
sh $E/tweak.sh webapp doctor               # 自检：sqlite3 / 参考行 / 已注册 / 日志
```

**也可以直接复用 Mesquito / KWebBrew 的应用**：扫描会把 `/mnt/us/apps/` 也当作来源。装过来之后它们就是正规 WAF 了，不再依赖缓存。

**内置示例**：`webapp/sample` 是一个「WAF 自检」页，逐项检查 `window.kindle` 的各个 API 是否可用。第一次用建议先装它确认链路通了，再换自己的应用。

### 安全设计

- 第一次动 `appreg.db` 之前**自动备份**到 `/mnt/us/kindletweaks_backup/appreg.db.bak`。要回滚：`cp` 回去即可。
- 卸载**只删 `com.kindletweaks.` 前缀的行**，不碰任何系统 WAF。
- 应用名只允许 `[A-Za-z0-9._-]`，杜绝路径穿越和 JSON 注入。
- 安装后会**写回校验**（`properties` 必须正好 3 行），不一致就不记入安装清单。

## 4 注册机制（设备实测的真实行）

要注册一个 WAF，`appreg.db` 里动三张表。为了不靠猜，本功能的写法**照抄设备上 `com.lab126.adviewer` 这类「独立 WAF」**，这也是 `doctor` 会把参考行打出来的原因。

```sql
-- 1) 注册 handler
insert or ignore into handlerIds(handlerId) values('com.kindletweaks.myapp');

-- 2) 启动方式和生命周期
insert or replace into properties(handlerId,name,value) values('com.kindletweaks.myapp',
    'command', '/usr/bin/mesquite -l com.kindletweaks.myapp -c file:///var/local/mesquite/ktweb-myapp/');
insert or replace into properties(handlerId,name,value) values('com.kindletweaks.myapp','framework','');
insert or replace into properties(handlerId,name,value) values('com.kindletweaks.myapp','unloadPolicy','unloadOnPause');

-- 3) 声明这是个可启动的「应用」
insert or replace into associations(handlerId,interface,contentId,defaultAssoc)
    values('com.kindletweaks.myapp','application','none','false');
```

启动：`lipc-set-prop com.lab126.appmgrd start app://com.kindletweaks.myapp/`

设备上真实的对照（实测）：

| 服务 | command / run | framework | unloadPolicy |
|---|---|---|---|
| `com.lab126.adviewer` | `command = /usr/bin/mesquite -l com.lab126.adviewer -c file:///var/local/mesquite/adviewer/` | 空 | `unloadOnPause` |
| `com.lab126.browser` | `command = … browser/ -j` | 空 | `unloadOnPause` |
| `com.lab126.store` | `framework = com.lab126.stored`，`run = -l com.lab126.store -c file:///var/local/mesquite/store/` | `com.lab126.stored` | `readDynConfig` |

两点要注意：

- **商店用的是另一种写法**（`run` + `framework` 指向常驻守护进程 `com.lab126.stored`）。我们不用它——那需要改系统 upstart 任务。
- `unloadPolicy = unloadOnPause` 表示**离开就卸载**（省内存），下次点开重新加载。**"常驻"指的是注册永久、随时可启动，不是常驻内存。** 想要留在内存里可换 `unloadWhenNeeded`，但 WAF 本身没有后台驻留的概念——真要后台常驻，那是你现有 upstart 脚本的活儿，两者配合正好。

### 启动时会怎样（实测）

```
activeApp=com.kindletweaks.sample
进程: /usr/bin/mesquite -l com.kindletweaks.sample -c file:///var/local/mesquite/ktweb-sample/
日志: mesquite[31800]: I com.kindletweaks.sample:JSObjectAppManager::eventsCallbackFunction:Execute callback for event->1
```

`appmgrd` 认它、mesquite 起了独立实例、`JSObjectAppManager` 回调说明 **`window.kindle` 桥接是活的**。

## 5 config.xml：它决定你能用哪些 API

`config.xml` 里的 `<feature>` 段就是 `window.kindle` 的白名单 —— 删掉哪个，JS 里哪个就是 `undefined`。设备上两个真实例子：

| 参数 | 商店 | 浏览器 |
|---|---|---|
| appmgr / chrome / device / gestures / messaging / net / popup / download | ✅ | ✅ |
| **dev / dconfig / todo** | ✅ | ❌ |
| bkgrnd / localprefs / winmgrUtils / bluetooth | ✅ | ❌ |
| viewport | ❌ | ✅ |

**这就是自己注册比借商店缓存可控的地方**：Mesquito 只能继承商店那套，你可以按需增删。

本功能的模板（`webapp/config.template.xml`）用的是**商店那套**（去掉只在测试机上用的 `uitest`），也就是这台机器上验证过可用的一套。常用 API 速查见 [15 WAF 与 Mesquite](15-wafs-and-mesquite.md#4-windowkindlewaf-能调的-js-api)。

`<kindle:permissions>` 决定两件额外的事：`local-port-access`（访问 localhost，主要是 9101 上的数据库接口）、`download-allowed`（往 `documents` 下载文件）。

## 6 开发一个 WAF 的现实约束

**① 只能用 ES5。** 设备上浏览器的 UA 自称 `AppleWebKit/531.2+ … Safari/533.2+`，约等于 Safari 5 时代。`const`/`let`、箭头函数、模板字符串、默认参数都别用。社区 polyfill 能补一部分，但**补不了箭头函数和默认参数**。你的 JS/TS 项目要先过 Babel 转译到 ES5。

**② 墨水屏刷新不归你管。** 实测 `xwininfo` 里 mesquite 的窗口标题就是 `mesquite`，**没走 Awesome WM 的分层标题协议**（`L:…_N:…`），而刷新策略在 `/etc/xdg/awesome/lab126_ligl.lua` 里。所以 WAF 会有残影、刷新时机不可控。要精细控制刷新就别走 WAF。

**③ 读本地文件只能用 iframe 技巧。** `file://` 上的 `fetch`/`XHR` 不可用（这也是 KWebBrew 当年发现的"漏洞"）。示例页里的 `readLocalFile()` 就是可用写法：建一个 iframe 指向目标文件，读它的 `contentDocument`。

**④ 调试靠日志。** 没有 devtools：

```sh
grep -i "com.kindletweaks.myapp" /var/log/messages | tail -30
```

mesquite 的日志其实挺详细（JS 异常、`undefined` 的 API 调用都会记），另一条路是在页面里用 `document.getElementById` 自己画一个日志区（示例页就是这么做的），或 `kindle.device.log()`。

**⑤ 注册 4 个生命周期回调。** `kindle.appmgr` 的可覆盖回调**只有 4 个**，名字是：

```
kindle.appmgr.ongo / onload / onpause / onunload
```

依据：`strings /usr/bin/mesquite | grep -E '^(ongo|onload|onpause|onunload)$'` 正好这 4 个，且与日志里的 `event->0..3` 吻合。**没有 `onback` / `onforward`**（这一点容易猜错——本仓库就先猜错了，注册了不存在的名字）。

不注册就会在 `/var/log/messages` 里留下：

```
W com.kindletweaks.sample:JSObjectAppManager::eventsCallbackFunction:cannot find callback function for [0]
```

不是错误，但会让日志变脏。系统自带的 `adviewer` 注册了 `ongo`/`onload`/`onpause`，所以它没有这个警告（实测：adviewer 启动时 `Execute callback` 2 次、警告 0 次；我们注册正确后同样是 2 次、0 次）。示例页在 `<head>` 里注册这 4 个，可作范本。

**⑥ 必须声明 `charset`，并小心中文字体和符号字形。** 这一条是实际踩出来的，分三点：

**(a) `<meta charset="UTF-8">` 是必须的。** WAF 页面走 `file://`，没有 HTTP 头可以携带编码信息，
只能靠这个声明。**不写的话中文会按默认编码解释 → 乱码。**
设备上 6 个系统 WAF（`store` / `browser` / `help` / `csapp` / `adviewer` / `kft`）**全都声明了 `charset="UTF-8"`**（实测）：

```html
<html lang="zh">
<head>
  <meta charset="UTF-8" />     <!-- 必须放在最前面 -->
```

**(b) 中文字体要靠系统回退，别写死英文字体。** 实测：

| 查询 | fontconfig 解析结果 |
|---|---|
| `fc-match dialog` | `STHeitiMedium.ttf`（"STHeiti"） |
| `fc-match sans-serif` | `STHeitiMedium.ttf` |
| `fc-match monospace` | `KindleBlackboxRegular.ttf` |

而 `Amazon-Ember-*.ttf` 和 `Bookerly-*.ttf` **一个中日韩字形都没有**（实测「中」字在它们的全部字重里都缺失）。
所以写 `font-family: "Bookerly", "Amazon Ember", serif` 时，中文完全依赖逐字回退，还摊上一个在设备上无效的 `serif`。
**系统 WAF 的 CSS 用的是 `font-family: dialog, sans-serif`**，照抄即可。

**(c) 符号字形很不可靠，状态标记用 ASCII。** 扫描设备上全部 87 个字体（实测）：

| 字符 | 有字形的字体数 |
|---|---|
| `✓` U+2713 | 31（Amazon Ember、Bookerly …） |
| `✗` U+2717 | **1（只有 `code2000.ttf`）** |
| `⚠` U+26A0 | **1（只有 `code2000.ttf`）** |

`dialog`/`monospace` 解析到的 STHeiti 和 KindleBlackbox **两个都没有**，所以 `✗`/`⚠` 能否显示
完全取决于 WebKit 会不会继续回退到 Code2000 —— 在你这台机器上能出来，但不能指望别的机型。
**状态标记、按钮文字这类关键信息只用 ASCII**；`—`（U+2014）和 `…`（U+2026）在全部候选字体里都有，可以放心用。

> 想自己核对某个字符有没有字形，用设备上的 Pillow（示例：把 `dialog` 换成你实际用的字体路径）：
>
> ```sh
> LD_LIBRARY_PATH=/mnt/us/python3/lib /mnt/us/python3/bin/python3.9 - <<'EOF'
> from PIL import Image, ImageDraw, ImageFont
> f = ImageFont.truetype('/usr/java/lib/fonts/STHeitiMedium.ttf', 32)
> def render(ch):
>     im = Image.new('L', (64, 64), 255); ImageDraw.Draw(im).text((2, 2), ch, font=f, fill=0)
>     return im.tobytes()
> notdef = render('\u0378')          # 未分配码位，必定是 .notdef
> for ch in ['\u4e2d', '\u2713', '\u2717']:
>     print('U+%04X' % ord(ch), '有' if render(ch) != notdef else '缺（会变豆腐块）')
> EOF
> ```

## 7 排错

| 现象 | 原因 / 处理 |
|---|---|
| **中文显示成乱码**（`å¸¸é§` 这种） | **缺 `<meta charset="UTF-8">`**。WAF 走 `file://`，没有 HTTP 头，只能靠这个声明。加上并放在 `<head>` 最前面，然后重装（见下面"改了还是旧页"） |
| **某些符号显示成方块/豆腐块** | 该字符在你实际用到的字体里没有字形。用上面的 Pillow 脚本逐个核对，关键文字改成 ASCII。`✓` 有 31 个字体含它，但 `✗`/`⚠` 在这台机器上只有 `code2000.ttf` 有 |
| 中文能显示但排版挤/换行怪 | `font-family` 写死了英文字体（Bookerly/Amazon Ember 都没有 CJK 字形）。改用系统 WAF 的 `dialog, sans-serif` |
| **改了 index.html，打开还是旧页** | **WebKit 的 HTML5 应用缓存**。`<安装目录>/resource` 就是 `config.xml` 里的 `ApplicationCachePath`。本功能在每次 `install` 时会清掉；手动清：`sh tweak.sh webapp clearcache myapp`，或直接 `rm -rf /var/local/mesquite/ktweb-myapp/resource`，然后重新打开 |
| 打开后弹「应用程序错误：无法启动选定的应用程序」 | `appmgrd` 在应用还没注册好 lipc 服务时被 `go` 了。等一下再点；`restart kppmainapp` 之后要等约 7 秒（见 [09 第 4 节](09-lab126-internals.md#4-appmgrd应用生命周期)） |
| 菜单里没有我的应用 | 应用目录要在 `/mnt/us/webapps/<名字>/`，且**里面必须有 `index.html`**；名字只能是字母数字和 `. _ -` |
| 白屏或黑屏 | 先 `sh tweak.sh webapp doctor` 看有没有注册；再 `grep -i mesquite /var/log/messages`。JS 抛异常会导致空白页 |
| `state` 是 on 但打不开 | 检查安装目录在不在：`ls /var/local/mesquite/ktweb-<名字>/`。可能在别处被改过，重新 `install` 即可 |
| 想确认 `window.kindle` 到底有没有 | 装内置示例 `sample`，它是逐项自检页 |
| 想彻底回滚 `appreg.db` | `cp /mnt/us/kindletweaks_backup/appreg.db.bak /var/local/appreg.db`（先 `stop framework`，之后 `start framework`） |

## 8 附录：UI 选型的实测数据

在 Oasis 3 / FW 5.15.1.1（`005-juno_150101_stinger_zelda-392503`，platform `zelda` / board `stinger`）上实测：

**图形栈 —— 原生 GTK 路线是通的**

| 项目 | 结果 |
|---|---|
| Xorg | 在跑（PID 4739，`Xorg -nolisten tcp +bs -ardelay 0 -arinterval 0`），socket `/tmp/.X11-unix/X0` 世界可写，无 `.Xauthority` |
| 外部 X 客户端 | **能连**：`ctypes` 调 `libX11` 的 `XOpenDisplay(":0")` 返回非空（实测） |
| GTK+2 | `libgtk-x11-2.0.so.0.2000.1`、`libgdk-x11-2.0`、`glib 2.29.18`、`pango 1.26`、`cairo 1.10`，`ldd` 依赖齐全 |
| Qt | **没有** |
| 窗口管理器 | `awesome`（PID 8229）+ `awesome-client`；配置在 `/etc/xdg/awesome/lab126_*.lua`，含 `lab126_ligl.lua`（墨水屏刷新）、`lab126_flash_triggers.lua`、`lab126_layLogic`、`lab126_lipc.lua` |
| 编译器 | **设备上没有** gcc/cc → 原生必须交叉编译（koxtoolchain `kindlepw2` + Kindle SDK，见 [14](14-kindle-homebrew-and-dev.md#4-原生开发)） |
| X 工具 | 有 `xwininfo`、`xrandr`、`xset`；没有 `xdotool`、`xprop` |

**脚本自绘路线 —— 全部就绪**

| 项目 | 结果 |
|---|---|
| Python | 3.9.8；**Pillow 9.0.0**；`ctypes` 可用；**没有 tkinter、没有 gi** |
| fbink | `/mnt/us/libkh/bin/fbink` v1.25.0，认出 `Kindle Oasis 3 (0WM -> 0x3D5 => Stinger on Zelda)`，`1264x1680, 8bpp`，`mxc_epdc_fb`；特性 `Draw=Yes Bitmap=Yes`，但 **`Fonts=No Unifont=No OpenType=No Image=No`** |
| 屏幕 | `/dev/fb0` root:video；`fbset` → `1264x1680-0`，line length 1280 |
| 触摸 | `/dev/input/event8 = cyttsp5_mt` |
| Lua | 5.1.4 内置 |

> `fbink` 这个构建**没有字体支持**，所以 `fbink "文字"` 不一定能直接打出来；稳妥做法是**用 Pillow 把整屏（或局部）渲染成位图再贴上去**。

**WAF 路线的约束**（实测）：只能用 ES5；`/var/local/mesquite` 开机不被删但只被 `chown`；窗口不参与 Awesome 分层 → 刷新时机不可控；首次加载约 1~2 秒。

**给脚本开发者的建议**：

1. 先用 **WAF** 把"界面"做出来——它是唯一能复用你现有 JS/TS 代码的路线，注册链路已经验证通了；
2. 后台逻辑继续用你现在的脚本（upstart + Python），两边用 `/tmp` 文件或 lipc 通信；
3. 一旦遇到"平滑滚动、频繁局部刷新、动画"，就别在 WAF 上硬扛，换 **Python+Pillow+fbink**：单屏自绘、刷新自己说了算、零交叉编译。

## 9 参考资料

- [KindleModding Wiki — WAFs & Mesquite](https://kindlemodding.org/wafs-and-mesquite/)（CC BY-NC 4.0）：`config.xml` 与 `window.kindle` 的完整规范。
- [Mesquito](https://github.com/KindleModding/Mesquito)（archived）/[KWebBrew](https://github.com/KindleModding/KWebBrew)（archived）：社区的两个 WAF 启动器，第 2 节的对比依据。
- [15 WAF 与 Mesquite](15-wafs-and-mesquite.md)：`config.xml` 逐节说明、`window.kindle` API 与枚举。
- [13 Kindle 系统参考资料](13-kindle-system-reference.md#2-appregdb)：`appreg.db` 的表结构与 extractor/application 关联。
- [14 自制软件与原生开发](14-kindle-homebrew-and-dev.md)：GTK+2 交叉编译、Awesome WM 窗口标题规范、KPM/Scriptlets。
- [FBInk](https://github.com/NiLuJe/FBInk)：墨水屏绘制与刷新控制。
- [KOReader](https://github.com/koreader/koreader)：现成的 Kindle UI 框架与插件体系。
