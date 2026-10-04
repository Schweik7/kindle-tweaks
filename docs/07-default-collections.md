# 07 默认收藏夹视图

> 效果：允许临时切换视图；下次进入「图书馆」时仍以收藏夹视图打开。没有定时轮询，也不会阻止深度休眠。

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
2. 之后阻塞等待 `com.lab126.appmgrd` 的 `historyChange` 事件，不做定时轮询。
3. 每次进入 `KPP_LIBRARY` 时再次检查；如果刚从网格/列表或内容筛选切回，校正配置并只重载一次主界面。

它不会锁住 `LIBRARY_CONFIG`，也不会改排序、筛选上下文或收藏夹数据库。当前会话仍可临时切到网格/列表；离开后再次进入图书馆才恢复收藏夹视图。

关闭时只移除自动校正任务，不改当前选择：

```sh
sh /mnt/us/extensions/kindletweaks/tweak.sh libraryview off
```

与其他 Upstart 任务一样，升级或重刷固件后需要在 KUAL 里重新开启。
