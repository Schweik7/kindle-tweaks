# 09 Kindle 系统内部（com.lab126）笔记

> 在 Kindle Oasis 3、FW 5.15.1.1 上做功能时摸清的系统结构，供开发和排错参考。
> 除非注明「推测」，都是在真机上验证过的。`lab126` 是亚马逊做 Kindle 的部门名，系统服务和应用的 ID 都以 `com.lab126.` 开头。

## 1 进程和它们的依赖

```
init.exe（upstart）
├─ Xorg                      X 显示服务器：所有界面都画在它上面，读触摸屏 /dev/input/event8
│  ├─ framework（cvm）       Java 框架 com.lab126.kaf：阅读器、设置、注册、商店后端、内容索引……
│  ├─ kppmainapp             主页 + 图书馆（React Native / Hermes，/app/bin/KPPMainAppV2）
│  ├─ pillow                 系统弹窗、状态栏、快捷设置（WebKit）
│  ├─ stored / 浏览器        都是 mesquite（WebKit 外壳）的实例
│  └─ winmgr                 窗口管理，屏保、标题栏
├─ appmgrd                   应用生命周期，按 URI 启动 / 切换应用
├─ powerd                    电源、屏保、休眠、电源键
├─ deviced、btfd、phd ……
└─ 你装的 upstart 任务（/etc/upstart/*.conf）
```

**依赖链很重要**：Xorg 一崩，framework、kfxreader、statusbar、webreader 等都会跟着退出。pillow 会被 upstart 自动拉起，**framework 不会**。framework 不在时的症状：

| 症状 | 原因 |
|---|---|
| 设置打不开、显示「需要注册 Kindle」（fakereg 看似失效） | 注册状态由 framework 提供，`com.lab126.amazonRegistrationService` 查不到 |
| 电源键没反应 | powerd 查不到 `com.lab126.kaf`，日志 `Splash screen is on. Ignoring power button` |
| `lipc-set-prop … powerButton` 等模拟电源键都不进屏保 | 同上 |

恢复：`start framework`，或者干脆 `reboot`（最干净）。查状态用 `status framework`、`pidof cvm`。

## 2 upstart

- 任务定义在系统分区 `/etc/upstart/*.conf`，改之前 `mntroot rw`，改完 `mntroot ro`。升级固件会丢。
- `start` / `stop` / `restart` / `status <任务>`，在 `/sbin`（非交互 SSH 要先补 PATH）。
- 常见触发：`start on started framework`、`start on starting kppmainapp`、`stop on (stopping framework or ota-update)`。
- `respawn` + `respawn limit 5 300`：5 分钟内退出超过 5 次就不再拉起。
- 替换一个**正在运行的可执行文件**后，`mntroot ro` 会报 `/ is busy`：还有进程映射着已删除的旧文件。找出来重启它：
  ```sh
  for p in /proc/[0-9]*; do readlink $p/exe | grep -q deleted && echo "$p $(readlink $p/exe)"; done
  ```
  例：替换 `/usr/bin/mesquite` 后要 `restart stored`（商店后台进程也是 mesquite）。

## 3 lipc：服务之间的通信

```sh
lipc-probe -l                                  # 所有服务
lipc-probe -v com.lab126.powerd                # 属性、类型、当前值（r 读 / w 写）
lipc-get-prop com.lab126.powerd state          # active / screenSaver / ……
lipc-set-prop -i com.lab126.powerd powerButton 1   # ⚠ Int 属性必须加 -i，否则静默失败
lipc-wait-event com.lab126.powerd goingToScreenSaver           # 等一个事件
lipc-wait-event -s 40 com.lab126.appmgrd historyChange          # 最多等 40 秒
lipc-wait-event -m com.lab126.powerd readyToSuspend             # 持续输出（-m）
```

- `lipc-wait-event -m` 接管道时输出有缓冲，事件不能及时处理。脚本里用循环 + 单次等待。
- 错误码：`lipc_status=8` / `0x8` 服务存在但还没准备好（应用刚启动、未注册）；`0x3 lipcErrNoSuchSource` 服务不存在（进程没在跑）。

### 常用服务

| 服务 | 用途 |
|---|---|
| `com.lab126.appmgrd` | `start <URI>` 启动/切换应用；`activeApp` 当前前台应用；事件 `historyChange`、`appStateChange`、`appActivating` |
| `com.lab126.powerd` | `state`、`isCharging`、`powerButton`、`preventScreenSaver`、`deferSuspend`（只在屏保状态下有效）；事件 `goingToScreenSaver`、`outOfScreenSaver`、`readyToSuspend`、`suspending`、`resuming` |
| `com.lab126.KPPMainApp` | KPP 注册的服务；`lipc-probe` 能查到它，说明 KPP 已经可以接收跳转 |
| `com.lab126.amazonRegistrationService` | `isRegistered`（framework 提供） |
| `com.lab126.pillow` | `pillowAlert` 显示系统弹窗 |
| `com.lab126.winmgr` | 窗口、屏保相关 |

## 4 appmgrd：应用生命周期

- 应用注册表：`/var/local/appreg.db`（sqlite，`properties` 表的 `handlerId` / `name` / `value`），例如浏览器的启动命令：
  `com.lab126.browser | command | /usr/bin/mesquite -l com.lab126.browser -c file:///var/local/mesquite/browser/ -j`
- 常用 URI：
  - `app://com.lab126.booklet.home` 主页
  - `app://com.lab126.KPPMainApp/?view=KPP_LIBRARY` 图书馆
  - `app://com.lab126.booklet.reader/mnt/us/documents/书.pdf` 打开书（文件必须已被索引）
- 状态机（日志 `appmgr_history:app_state_change`）：`EXECUTED → REGISTERED → LOAD_SENT → LOADED → GO_SENT → STARTED`，暂停时 `PAUSE_SENT → PAUSED`。
- **重启前台应用后不要马上发 `start`**。`restart kppmainapp` 后新进程约 7 秒才注册 lipc 服务，在此之前 appmgrd 的 `go` 会失败（`lipc_status=8`），pillow 弹出「应用程序错误：无法启动选定的应用程序」（`appmgrAppFailedFatal`）。其实 appmgrd 会在 KPP 注册后**自动恢复到原来的视图**，等 `historyChange` 即可。
- 这个弹窗会一直留在屏幕上，跨过屏保和休眠，唤醒后仍在。

## 5 文件和数据库

| 路径 | 内容 |
|---|---|
| `/var/local/cc.db` | 内容目录。`Entries` 表：`p_location`、`p_titles_0_nominal`、`p_cdeType`（`EBOK` 电子书 / `PDOC` 文档 / `EBSP` 样章 …）、`p_type`（`Entry:Item`、`Entry:Item:Dictionary`、`Entry:Item:Comic` …） |
| `/var/local/LIBRARY_CONFIG` | 图书馆视图（JSON）：`library_mode_selected`（`LIBRARY` / `COLLECTIONS`）、`library_layout_selected`（`GRID` / `LIST`）、各模式的排序和筛选。KPP 只在启动时读；文件不存在用默认值；最小内容 `{"library_mode_selected":"COLLECTIONS"}` 也认 |
| `/var/local/ksdk.library.settings.db` | KSDK 设置（如最近打开的书） |
| `/var/local/appreg.db` | 应用注册表 |
| `/var/local/mesquite/browser/` | 体验版浏览器的 HTML/JS 界面 |
| `/var/log/messages` | 系统日志，约每 15 分钟轮转到 `/var/local/log/messages_*.gz`，查旧日志用 `zcat` |

**筛选器里的分类**看的是 `p_cdeType`，它来自 MOBI/AZW3 文件 EXTH 记录 501；PDF、TXT 没有这个字段，侧载一律是 `PDOC`（文档）。「漫画」筛选查的是 `p_type = 'Entry:Item:Comic'`（推测只有商店漫画才有）。

## 6 输入设备

```
event0  snvs-powerkey   电源键（KEY_POWER）
event1  max77796-key
event2  hall_sensor_disp  保护套霍尔传感器
event3  gpio-keys       翻页键
event4/5 max44009_als    环境光
event6/7 bma2x2          加速度计
event8  cyttsp5_mt       触摸屏，ABS_MT 0–1263 × 0–1679，与屏幕像素一一对应
```

- 看事件：`/mnt/us/usbnet/bin/evtest /dev/input/event8`。
- 注入事件：`evemu-event`，或直接向设备写 `struct input_event`（32 位 ARM 每个 16 字节）。
- ⚠ **不要往触摸屏注入事件**。实测 `evemu-event` 每发一个事件就启动一次进程，一次点击要 3 秒，会被当成长按，而且这次实验之后 **Xorg 崩溃**，连带 framework 退出（见第 1 节），只能重启恢复。改界面状态请走 lipc、配置文件或补丁，不要模拟点击。

## 7 系统自带的小工具

| 命令 | 用途 |
|---|---|
| `/usr/sbin/screenshot [-f 文件] [-x]` | 截屏（对角线手势调用的就是它），默认存 `/mnt/us/screenshot_<时间>.png`；`-x` 另存窗口信息 |
| `eips 列 行 "文字"` | 在屏幕上直接打字（只支持 ASCII） |
| `mntroot rw` / `mntroot ro` | 系统分区读写切换 |
| `powerd_test -p` | 发送「电源键长按」调试事件（不是短按） |
| `/usr/bin/delayShot.sh` | 延时截屏，只在开发机（存在 `/PRE_GM_DEBUGGING_FEATURES_ENABLED__REMOVE_AT_GMC`）上生效 |

## 8 给系统进程注入代码（LD_PRELOAD）

KPP、mesquite 等都是动态链接的 ELF（`/lib/ld-linux.so.3`，glibc 2.20，ARM EABI 软浮点）。以 root 启动、自己降权（没有 setuid 位）的进程不会忽略 `LD_PRELOAD`。

- **能顶替哪些函数**：看目标库的重定位表。`eu-readelf -r -W 库.so | grep 符号`，如果是按符号名的 `ARM_ABS32`（虚表槽位）或 `ARM_JUMP_SLOT`（PLT），预加载库里的同名函数就会被用上；只有 `ARM_RELATIVE` 或库内直接调用的则不行。
- **调用原函数**：`dlsym(RTLD_NEXT, "修饰后的符号名")`。C++ 成员函数按 ARM EABI 调用：`this` 在 r0，其余参数依次在 r1、r2…；按值返回的对象由调用者在 r0 传入返回地址。这一版 libstdc++ 的 `std::string` 是写时复制实现，对象就是一个指向字符的指针。
- **交叉编译**：电脑上 `pip install ziglang`，然后 `python -m ziglang cc -target arm-linux-gnueabi.2.20 -mcpu=cortex_a7 -shared -fPIC -O2 -s -Wl,-z,lazy`。必须加 `-Wl,-z,lazy`，否则 ld.so 报 `unexpected reloc type 0x24`。
- **挂到 upstart 任务上**：改 `/etc/upstart/<任务>.conf` 里的 `exec` 行为 `exec env LD_PRELOAD=… 程序`，然后 `kill -HUP 1`（upstart 0.6.6 没有 `initctl`，不发 SIGHUP 不会重读），再 `restart <任务>`。用 `grep 库名 /proc/$(pidof 进程)/maps` 确认已加载。
- 实例：[07 默认收藏夹视图](07-default-collections.md#31-注入库把原生切换函数暴露出来)。

## 9 busybox 和 shell 的坑（补充）

- `ps` 不显示完整命令行；要按参数找进程，读 `/proc/<pid>/cmdline`。
- `grep -l 关键字 /proc/[0-9]*/cmdline` 会匹配到 grep 自己，判断「是否在运行」时要排除自身。
- `sleep` 只接受整数，小数用 `usleep 微秒`。
- `chown` 的组名是 `javausers`（`ls -l` 显示被截断成 `javauser`）。
- 新版 OpenSSH 的 `scp` 默认走 SFTP，Kindle 上的 dropbear 没有 sftp-server，大文件用 `ssh … 'tar -cf - 目录' | tar -xf -` 传。
