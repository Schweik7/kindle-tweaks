# 07 默认收藏夹视图

> 效果：允许临时切换视图；进入屏保后，下次进入图书馆瞬间恢复收藏夹视图（注入 KPP，不重启、不白屏）。没有定时轮询，也不会阻止深度休眠。

## 1 三种容易混淆的状态

Kindle 5.15.1.1 把下面几件事混在相近的菜单里：

- **主页**固定显示横向封面网格，不能改成收藏夹视图。
- **图书馆 → 收藏夹**是内容模式；在本固件上，收藏夹卡片本来就以三列网格显示。
- **图书馆 → 全部 → 网格**才是书籍平铺。它与收藏夹模式不是同一状态。

实际状态保存在 `/var/local/LIBRARY_CONFIG`：

```json
"library_layout_selected":"GRID",
"library_mode_selected":"COLLECTIONS"
```

因此看到 `GRID` 不代表出错；判断收藏夹视图要看 `library_mode_selected` 是否为 `COLLECTIONS`。

## 2 为什么会回到「全部 + 网格」

真机验证表明，正常重启 `kppmainapp` 后 `COLLECTIONS` 会被保留，所以单纯放置一段时间或深度休眠不会改写它。

这台假注册设备出现回退时，`LIBRARY_CONFIG` 记录的是：

```json
"library_view_model_context.LIBRARY":{"filters":[8], ...},
"library_layout_selected":"GRID",
"library_mode_selected":"LIBRARY"
```

其中筛选值 `8` 是「已下载」。收藏夹模式与「全部内容」的筛选上下文相互独立；进入「已下载」等内容筛选，或在查看选项里选择网格/列表，会切回 `LIBRARY`。此外，唤醒后如果停在主页，主页看起来也始终是网格。这些现象容易被误认为“闲置一段时间后自动重置”。

现有的 `collview` 二进制补丁只负责让假注册机器上的「收藏夹」选项可以点击，不负责强制默认值。

## 3 实现

KUAL →「Kindle Tweaks」→「默认收藏夹视图」→「开启」。SSH 等价命令：

```sh
sh /mnt/us/extensions/kindletweaks/tweak.sh libraryview on
```

开启时会安装 `/etc/upstart/kindletweaks-libraryview.conf`：

1. `kppmainapp` 启动前，把顶层 `library_mode_selected` 校正为 `COLLECTIONS`。
2. 之后阻塞等待 `com.lab126.powerd` 的 `goingToScreenSaver` 事件，不做定时轮询。
3. 每次进入屏保时：
   - KPP 已注入 `libkt_libview.so`（默认）：只创建标记 `/tmp/kindletweaks-libraryview.reset`。唤醒后第一次进入图书馆时，注入库调用 KPP 自己的 `SetMode(COLLECTIONS)`，瞬间切换，不重启、不白屏。
   - 没有注入库：校正配置并重载一次 KPP。屏保盖住整个屏幕，重载时的白屏看不到；appmgrd 会在 KPP 重新注册后恢复原来的界面。

### 3.1 注入库：把原生切换函数「暴露」出来

`extensions/kindletweaks/libraryview/libkt_libview.c`，开启时由 `tweak.sh` 把 `/etc/upstart/kppmainapp.conf` 最后一行改成

```sh
exec env LD_PRELOAD=/mnt/us/extensions/kindletweaks/libraryview/libkt_libview.so /app/bin/KPPMainApp
```

（备份在 `/mnt/us/kindletweaks_backup/kppmainapp.conf.orig`；改完给 init 发 `SIGHUP` 让 upstart 0.6.6 重读，关闭时还原并重启 KPP。`/mnt/us` 没挂载时 ld.so 只提示「无法预加载」，KPP 照常启动。）

原理（FW 5.15.1.1，`/app/lib/libKSDKLibrary.so`）：

| 符号 | 作用 |
|---|---|
| `LibraryViewModelImpl::OnViewActivate()` | 图书馆视图激活时调用。虚表槽位是**按符号名的 `ARM_ABS32` 动态重定位**，所以 LD_PRELOAD 里的同名函数会顶替它 |
| `LibraryViewModelImpl::SetMode(LibraryMode)` | 界面上点「查看选项 → 收藏夹」走的就是它：经虚表调 `SetModeWithLayout(mode, 当前布局)` → `SetContext`，KPP 自己通知界面刷新并保存 `LIBRARY_CONFIG` |
| `LibraryViewModelImpl::Mode() const` | 当前模式。枚举 `LibraryMode`：0 `LIBRARY`、1 `COLLECTIONS`、2 `INSIDE_COLLECTION`、3 `LIBRARY_SEARCH`、4 `HOME` … |
| `LibraryModeToString(LibraryMode)` | 加载时核对枚举值；对不上或缺符号就停用，只透传原函数 |

钩子只在「有标记」且模式是 `LIBRARY` / `COLLECTIONS` 的实例上动作，主页（`HOME`）、收藏夹内部、搜索等实例不受影响。日志 `/tmp/kindletweaks-libraryview.log` 只记加载和实际切换。

编译（电脑上，`pip install ziglang`）：

```sh
cd extensions/kindletweaks/libraryview
python -m ziglang cc -target arm-linux-gnueabi.2.20 -mcpu=cortex_a7 -shared -fPIC -O2 -s -Wl,-z,lazy -o libkt_libview.so libkt_libview.c
```

`-Wl,-z,lazy` 必需：zig 默认 `BIND_NOW`，Kindle 的 glibc 2.20 ld.so 会报 `unexpected reloc type 0x24`。`.so` 不进 git。

**为什么不模拟点击**：试过往触摸屏注入「查看选项 → 收藏夹」的点击，结果 Xorg 崩溃、framework 退出，只能重启恢复（见 [09 第 6 节](09-lab126-internals.md#6-输入设备)）。

它不会锁住 `LIBRARY_CONFIG`，也不会改排序、筛选上下文或收藏夹数据库。使用中仍可临时切到「全部」或网格/列表，这个选择保持到这次用完；下次唤醒恢复收藏夹视图。

**为什么不在进入图书馆时立刻校正**：KPP 只在启动时读 `LIBRARY_CONFIG`，校正只能靠重载 KPP——加载 React Native、书库和封面并重新向 appmgrd 注册约 7 秒，整屏白屏。旧版本就是这样做的（还会在 KPP 注册前发跳转 URI，触发「无法启动选定的应用程序」弹窗）。

**`LIBRARY_CONFIG` 整个消失**：实测这个文件会被删掉（推测是 KPP 收到 `kRegistrationChangedEvent` 重置书库时一起删的，假注册设备唤醒联网、获取凭证失败时会触发；尚未确认），之后 KPP 按默认的「全部 + 网格」显示。校正时文件不存在就写一个最小配置 `{"library_mode_selected":"COLLECTIONS"}`，KPP 能正常读取，其余键用默认值。

关闭时只移除自动校正任务，不改当前选择：

```sh
sh /mnt/us/extensions/kindletweaks/tweak.sh libraryview off
```

与其他 Upstart 任务一样，升级或重刷固件后需要在 KUAL 里重新开启。
