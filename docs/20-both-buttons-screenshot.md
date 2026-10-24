# 20 上下翻页键同时按住 = 截屏（keyshot）

> 设备：Oasis 3（10th gen），FW 5.15.1.1。本文实测数据都来自这台机器，**没在别的机型上试过**。
> 功能开关：KUAL →「上下翻页键同时按住：截屏」，SSH 等价命令 `tweak.sh keyshot on|off`。

## 1 要解决的问题

Oasis 的翻页键就在右手拇指下面，但截图得把手挪到屏幕上比对角线手势。想要的是「读着读着，
拇指同时按下上下两个键，就存一张图」。

**而且截图时页面不能动** —— 要截的是你正在看的那一页，不是翻过去之后的下一页。

## 2 结论

能，并且能做到**完全不翻页**。做法是让守护进程当一个 X 客户端，在 root window 上
`XGrabKey` 抢走 PageUp / PageDown：

- 两键在 150 ms 内先后按下 → 判定为组合，**这一对按键整个吞掉**（阅读器一个事件都收不到，
  画面纹丝不动），随后调 `/usr/sbin/screenshot` 存图；
- 只按了一个键 → 临时放开这个键，用 `XTestFakeDeviceKeyEvent` 把**一次完整点击**原样重放给阅读器，
  翻页照常，用户完全无感。

一句话对比前后两版：

| 版本 | 机制 | 截图时翻页吗 |
|---|---|---|
| v1 | 旁听 `/dev/input/event3`，只看不吞 | 会翻 1 页（截到的是下一页） |
| v2（现在） | X 层 `XGrabKey` 抢键 + XTEST 重放 | 完全不翻页 |

## 3 为什么 v1 做不到

v1 的思路是旁听 evdev。旁听能「看见」按键，但**吞不掉**：事件照样送到 Xorg / 阅读器。
而要做到「吞掉 + 原样转发」，标准做法是 `EVIOCGRAB` 独占设备，再用 uinput 造一个虚拟键盘重放 ——
本机**没有 uinput**（`/dev/uinput` 不存在，`/proc/modules` 里也没有），这条路直接封死。

X 层恰好把这个缺口补上了：`XGrabKey` 提供「抢键」，XTEST 提供「重放」。

## 4 关键实测：这条链路是一步步验出来的

下面每条都是 SSH 上跑出来的，不是推测。

### 4.1 翻页键在 X 里是谁

```
/var/log/Xorg.0.log:
  (**) keypad: Device: "/dev/input/event3"
  (II) keypad: Configuring as keyboard
  (II) XINPUT: Adding extended input device "keypad" (type: KEYBOARD)
```

`/dev/input/event3`（gpio-keys）被 Xorg 的 evdev 驱动注册成 **`keypad`，一台 slave keyboard，
同时是 CoreKeyboard**。`XIQueryDevice` 列出的设备表：

| id | use | name |
|---|---|---|
| 3 | master keyboard | Virtual core keyboard |
| 5 | slave keyboard | **Virtual core XTEST keyboard** |
| 6 | slave keyboard | **keypad** ← 真正的翻页键 |
| 8 | slave keyboard | bma_interrupt |

keycode：`Prior`(PageUp) = **112**，`Next`(PageDown) = **117**。

### 4.2 XGrabKey 抓得到，没有冲突

```
XGrabKey(PageUp, AnyModifier, root) + XGrabKey(PageDown, ...) → errors=0
```

没有别的客户端占着这两个键（否则会收到 `BadAccess`）。XTEST 扩展在服务端也已初始化（v0.2）。

### 4.3 坑一：XTEST 发出去，阅读器不认

先用最普通的 `XTestFakeKeyEvent` 发一个 PageUp —— **画面一点没变**，阅读器毫无反应。
焦点是对的（`XGetInputFocus` 拿到的窗口名就是
`L:A_N:application_ID:com.lab126.booklet.reader…`），所以不是焦点问题。

换 `XTestFakeDeviceKeyEvent(dpy, dev=keypad, …)`，把事件来源伪装成 **keypad 那台设备** ——
**立刻翻页成功**。结论：

> **KPP（阅读器）按输入设备过滤按键**，只认 `keypad` 发来的事件，
> core XTEST 那台虚拟键盘（id=5）发的它一概不理。

这一条是整个方案的地基：重放必须走 `XTestFakeDeviceKeyEvent` 并指定 keypad 设备，
否则「单键翻页」会彻底失效。

### 4.4 坑二：grab 期间的 release 会被吞

用 grab 拦住设备级事件后重新测试：`XGrabKey` 确实把 keypad 的事件全收走了，画面不动 ✓。
但下一步做状态机时发现 —— **第二个键的 release 永远收不到**：

```
ev PRESS   kc=112                       ← 收到
ev PRESS   kc=117                       ← 收到
BOTH held -> swallowed, shooting
ev RELEASE kc=112                       ← 收到
（RELEASE kc=117 从未出现）
```

和截图无关（禁用 fork 复测，一样丢），是 X server 的行为：passive grab 激活期间，
非触发键的 release 不送给 grabbing client。

**所以状态机绝不能依赖 KeyRelease**。现在的设计：

- 判定只用 **KeyPress** 推进；
- 组合成立后立刻把内部状态复位，并进入 700 ms 冷却期，期间的一切事件（含迟到的 release）全部丢弃；
- 单键重放后同样立刻复位（重放的是一次完整点击，逻辑上这个键已经结束了）。

好处是：release 到不到都不影响功能；万一用户按住不放或者事件真丢了，冷却期一过自动回到干净状态，
不会出现「翻页键永久失效」。

### 4.5 坑三：按住稍久再松手，完全没反应

真机上手第一反馈：**快速点一下能翻页，按住两百毫秒再松手就没反应**。

原因是 X server 的按键状态。真实按键被 grab 吞掉时，server 内部认为这个键**仍然按着**；
此时再伪造一个 `press`，会被当成「重复按下」直接丢掉 —— 什么都不发，阅读器自然毫无反应。

而快速按时，真实的 `release` 先到了我们手里（server 状态已变 up），伪造的 press 才点得响。
所以同一个重放函数，两条路径行为不同，靠自动测试（XTEST 伪造的按键时序规整）没暴露出来。

先确认 KPP 到底在哪个时刻翻页，这决定修法：

```
fake PRESS only（不松开）  → 画面变化   ← 翻页了
fake RELEASE only          → 画面不变   ← 松开不触发
```

**KPP 是「按下即翻页」**。于是修法很直接：重放前先把状态清成 up。

```
fake release（清状态，KPP 收到也无所谓 —— 它不靠 release 翻页）
fake press   （这一下才真正翻页）
fake release（恢复干净状态）
```

多出来的那个 release 不会导致多翻一页，正好。

顺手还捡了个好处：万一真实 release 丢了导致状态残留，每次重放前清一遍也能自愈。

### 4.6 坑四：带 delay 的 fake event 不可靠

`XTestFakeDeviceKeyEvent` 有个 `delay` 参数（排程多久后投递）。用它排「60 ms 后按下第二个键、
400 ms 后一起松开」，结果**连 release 一起丢了**，客户端一断开排程中的事件就作废。

现在全部用 `delay=0` 立即投递，时序由用户态 `usleep` 控制。

### 4.7 坑五：格式串不匹配会段错误

写日志时 `shots_taken` 是 `long long` 却用了 `%ld`。ARM EABI 上 64 位参数占两个寄存器，
后面的 `%s` 于是读到一个错位的指针 → 解引用 → SIGSEGV。改用 `long` 就正常了。

（v1 里那个「`fprintf(stderr, …)` 在本机段错误」的怪现象，大概率也是同一类问题。）

## 5 实现

源码：`extensions/kindletweaks/keyshot/keyshot.c`（约 400 行，单个 C 文件，无第三方依赖）。

### 5.1 判定参数

| 宏 | 值 | 作用 |
|---|---|---|
| `PAIR_WINDOW_MS` | 150 | 两键按下的最大时间差。超过就是两次独立翻页 |
| `COOLDOWN_MS` | 700 | 组合判定后的静默期，吞掉余下抖动和迟到 release |
| `REPLAY_GAP_MS` | 40 | 重放时 press 与 release 的间隔 |
| `REPLAY_SETTLE_MS` | 90 | 重放后等 server 执行完再把 grab 装回去 |
| `SHOT_SETTLE_MS` | 200 | 组合判定到抓帧的稳定时间 |

`PAIR_WINDOW_MS` 可以命令行覆盖：`keyshot 300`（范围 50–600）。

### 5.2 单键重放为什么要 ungrab

重放的事件如果落在 grab 有效期内，会被**自己再抓回来**（实测：grab 状态下用
`XTestFakeDeviceKeyEvent` 发 keypad 事件，监听端照样收到，画面不动）。所以每次重放：

```
ungrab(该键) → fake release(清状态) → 15ms → fake press → 40ms → fake release → 等 90ms → grab(该键)
```

那个开头的 `fake release` 是 4.5 挖出来的必需品，省掉就会出现「按住稍久没反应」。

只放开**这一个**键，另一个仍攥在手里 —— 万一用户这时候按另一个键，还是能判成组合。

这个 90 ms 窗口是唯一可能漏事件的时刻，实际概率极低（要求用户刚好在重放的几十毫秒里按另一个键）。

### 5.3 截图

`fork` + `exec /usr/sbin/screenshot -f <path>`，产物 `/mnt/us/screenshots/kt_YYYYmmdd_HHMMSS_NN.png`。
用子进程是为了不阻塞事件循环（截图本身约 0.6 s CPU）。

`SHOT_SETTLE_MS` 只等 200 ms 而不是 v1 的 800 ms：因为**根本没翻页**，画面从一开始就没变过，
不需要躲黑白闪屏。200 ms 只是给前一次 e-ink 刷新留点余量。

### 5.4 DISPLAY

X 客户端需要 `DISPLAY`，而 upstart 拉起来的环境里通常没有。双重兜底：

- upstart 任务里 `env DISPLAY=:0`；
- 程序里 `if (!getenv("DISPLAY")) setenv("DISPLAY", ":0", 1);`。

启动时如果 X 还没就绪，会每 2 秒重试一次，最多 60 次（framework 早起时 Xorg 可能还在初始化）。

## 6 风险与兜底

| 风险 | 后果 | 兜底 |
|---|---|---|
| 进程卡死但连接不断 | 翻页键被吞，无法翻页 | `killall keyshot` 即可恢复；X 连接断开时 server 自动释放 grab |
| release 事件丢失 | 状态卡在「键还按着」 | 5000 ms 组合超时 + 700 ms 冷却期自动复位 |
| 找不到 keypad 设备 | 无法重放 | 启动时打印 `no keypad device … abort` 并直接退出（**宁可功能不生效，也不能让翻页键失效**） |
| grab 被别人占了 | 抓不到事件 | 功能静默不生效，翻页正常（不会破坏原有行为） |
| 重放的 90 ms 窗口里用户又按键 | 那一次按键绕过本程序，直接原生生效 | 行为仍正确（翻一页），只是没走我们的判定 |

设计上的一条底线：**任何失败路径都不能把翻页键卡死**。所以 keypad 设备打不开就直接退出，
而不是硬着头皮 grab 完却没法重放。

一个已知的行为差异：单键重放的是**一次 40 ms 的短点击**。如果阅读器自己实现了「长按连续翻页」
（靠计时而不是内核的 `EV_REP`，本机确实没有 `EV_REP`），那长按翻页键现在只会翻一页。
实测这台机器上没有这个行为（按住只翻一次），暂时不必处理；换机型时如果发现，就把重放改成
「press → 等真实 release 时长 → release」。

## 7 编译

设备上没有 X11 头文件，源码里手动声明了需要的 Xlib / XTest / XInput2 原型，
链接时才用设备自带的 `.so`。首次先把它们拉下来当链接桩（`tmp/` 已在 `.gitignore` 里）：

```bash
mkdir -p tmp/stub
scp root@kindle:/usr/lib/libX11.so.6.3.0  tmp/stub/libX11.so
scp root@kindle:/usr/lib/libXtst.so.6.1.0 tmp/stub/libXtst.so
scp root@kindle:/usr/lib/libXi.so.6.1.0   tmp/stub/libXi.so

python -m ziglang cc -target arm-linux-gnueabi.2.20 -mcpu=cortex_a7 -O2 -s \
    -L tmp/stub -lX11 -lXtst -lXi \
    -o extensions/kindletweaks/keyshot/keyshot extensions/kindletweaks/keyshot/keyshot.c
```

注意 zig 的 gnu target **拒绝 `-static`**，只能是动态链接 —— 这也正好，设备上这些库都有。

## 8 验证方法（不用人按）

这套功能可以无人值守回归测试：写个小工具用 `XTestFakeDeviceKeyEvent` 把事件伪装成 keypad 设备发出的
（详见 `tools/keytap.c`），它会被我们的 grab 抓住，效果等同真人按键：

```bash
# 编译（同样用上面的 stub）
python -m ziglang cc -target arm-linux-gnueabi.2.20 -mcpu=cortex_a7 -O2 -s \
    -L tmp/stub -lX11 -lXtst -lXi -o /tmp/keytap tools/keytap.c
scp /tmp/keytap root@kindle:/tmp/

# keytap combo    两键相隔 60ms 按下、一起按住 340ms  → 应截图且画面不变
# keytap tap_up   单击 PageUp                          → 应翻页
# keytap slow_pair 两键相隔 400ms                       → 应翻两次页，不截图
```

判定方法：每次操作前后各拍一张 `screenshot`，比 md5。组合场景 md5 必须完全相同，
单键场景必须变化。

已跑通的对照：

| 操作 | 截图 | 画面 |
|---|---|---|
| `combo`（先上后下）/ `combo_dn_first`（先下后上） | +1 张 | **完全不变** |
| `tap_up` / `tap_dn` | 不变 | 正常翻页 |
| `fast_tap_up`（30 ms 松手） | 不变 | 正常翻页（走「窗口内松手」即时放行） |
| `slow_pair`（相隔 400 ms） | 不变 | 当两次独立翻页 |

## 9 坑清单

1. **KPP 按输入设备过滤**：core XTEST 发的键阅读器不认，必须 `XTestFakeDeviceKeyEvent` 指定 keypad。
2. **grab 期间第二个键的 release 会被 X server 吞掉**：状态机不要依赖 release。
3. **带 delay 的 fake event 不可靠**：一律 `delay=0` + 用户态 `usleep`。
4. **`%ld` 打 `long long` 会在 ARM 上段错误**：参数类型必须和格式串严格对齐。
5. **重放前必须 ungrab 该键**，否则事件被自己抓回来，翻页永远不生效。
6. **重放前必须先把按键状态清成 up**（多发一个 fake release），否则真实按键还按着时
   伪造的 press 会被 server 当成重复按下丢掉 —— 表现为「按住稍久再松手没反应」。
   **KPP 是 press 翻页**，多发的那个 release 不会多翻一页。
7. **upstart 环境没有 `DISPLAY`**：任务里要 `env DISPLAY=:0`，程序里再兜一层。
8. **`XIQueryDevice` 的 use 字段**：`4` = `XISlaveKeyboard`，`2` = master keyboard，别抓错。
9. **`screenshot` 不需要 `DISPLAY`**，但 X 相关操作需要；两者别混着判断。
10. **zig 的 gnu target 拒绝 `-static`**。
11. **本机 glibc 的 stdio 比较脆**：日志统一 `snprintf` + `write`，别用 `fprintf(stderr, …)`。
12. **XTEST 伪造的按键测不出「状态残留」类问题**：它的事件时序太规整，
    真人按住不放才会踩到。这类 bug 只能上手试。
