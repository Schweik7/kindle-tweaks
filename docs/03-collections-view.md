# 03 解锁「查看选项 → 收藏夹」视图

> 验证：Kindle Oasis 3，FW 5.15.1.1。补丁脚本：[`tools/patch_ksdk.py`](../tools/patch_ksdk.py)，会按特征码自动定位。配合 [02 文件夹收藏夹](02-folder-collections.md) 使用效果最好。


## 1 问题

收藏夹建好后，里面的书**仍然会在书库第一层再平铺一份**。Kindle 本来有对应的功能：书库右上角「查看选项」里可以选「全部」或「收藏夹」视图。选「收藏夹」视图时，第一层只显示收藏夹和没有归入任何收藏夹的书，收藏夹里的书只出现在收藏夹里面。但在假注册的机器上，这个选项是**灰色**的。

（其他看起来相关、但其实没用的东西：
- 设置里「在图书馆中显示收藏夹」（`CollectionPreference.pref` 里的 `ShowCollectionsInLibrary`，可选 ALL / NONE / FAVORITE）只决定第一层是否混入收藏夹的图块，不会隐藏书。
- 系统的「丛书分组」（`Series` 表）也能把书折叠起来，但需要直接写数据库并重启 ccat，比较麻烦。）

## 2 排查过程

1. **书库界面（KPPMainApp.js.hbc）**：「查看选项」弹窗里每个选项是否可点，取决于 `isEnabled` 字段，在 `_renderLibraryLayoutOption` 里转成 `optionDisabled = !isEnabled`。这些选项数据（`layoutModeOptionsRows`）是原生模块传进来的，JS 里没有判断逻辑，所以要再往下一层找。
2. **找选项数据从哪里来**：选项 ID 是 `com.amazon.library.library_layout_mode_option.collections`。
   - 在 590 个 jar 里都没搜到这个字符串。
   - 在 Kindle 上执行 `grep -rl library_layout_mode_option /app /opt/amazon`，命中了 `/app/lib/libKSDKLibrary.so`（C++ 原生库，只有 `/app/bin/KPPMainApp` 加载它）。
3. **用 IDA 分析 `libKSDKLibrary.so`**（ARM Thumb，带 C++ 符号）：
   - 字符串 `...layout_mode_option.collections` 被一个静态初始化函数引用，它赋值给全局变量 `LibraryLayoutModeOption::COLLECTIONS_OPTION`。
   - 这个全局变量又被两个函数引用：`LibraryViewModelImpl::LibraryLayoutModeOptions()`（对应网格 / 列表 / 收藏夹）和 `LibraryViewModelImpl::LibraryModeOptions()`（对应全部 / 收藏夹）。
   - 反编译后看到，收藏夹选项的 `isEnabled` 等于 `this->[+0xE8]->虚函数[+8]()` 的返回值。
4. **`+0xE8` 是什么对象**：看 `LibraryViewModelImpl` 的构造函数，它的最后一个参数 `shared_ptr<HouseholdUtils>` 存在 `+0xE8`。查 `HouseholdUtilsImpl` 的虚函数表，第 3 项（偏移 +8）是 **`HouseholdUtilsImpl::HasActiveProfile()`**。
5. **`HasActiveProfile()` 的实现**只有一行：判断文件 **`/var/local/token/activeprofile.txt`** 是否存在。
   - 正式注册的机器上，这个文件记录家庭共享（Household）当前的个人资料。
   - 假注册不会生成这个文件，`/var/local/token/` 目录本身都不存在，所以「收藏夹」视图是灰色的。
6. **为什么不直接创建这个文件**：jar 和 so 里有一大堆地方读它，包括 `libauth.so`、`libextractor_util.so`、WhisperSync、FreeTime 儿童模式、家庭共享、Audible 等。伪造它可能引发难以预料的副作用。所以选择**只改这两处判断**。

## 3 补丁内容（FW 5.15.1.1）

两处 `BLX R3`（调用 `HasActiveProfile`）改成 `MOVS R0, #1`（直接当作「可用」）。都是 2 字节的 Thumb 指令，文件偏移和虚拟地址相同：

| 位置 | 所在函数 | 原字节 | 改为 |
|---|---|---|---|
| `0x15E94A` | `LibraryLayoutModeOptions()` | `98 47`（BLX R3） | `01 20`（MOVS R0,#1） |
| `0x15EB32` | `LibraryModeOptions()` | `98 47`（BLX R3） | `01 20`（MOVS R0,#1） |

| 文件 | md5 |
|---|---|
| `/app/lib/libKSDKLibrary.so` 原版 | `ce623d137447a1beef8e6431561f4528` |
| 补丁版 | `26d0934235303a407a76854e2d9d3073` |

两个指令前面都是 `LDR R0,[Rx,#0xE8]; ...; LDR R3,[R0]; LDR R3,[R3,#8]`，在 IDA 里很好认。ELF 不像 Hermes 字节码那样有整体校验值，改完不需要修复任何东西。

## 4 安装、还原

KUAL →「Kindle Tweaks」→「解锁「查看选项→收藏夹」」→「开启 / 关闭（还原原版）」。SSH 等价命令：

```sh
ssh root@<kindle-ip> sh /mnt/us/extensions/kindletweaks/tweak.sh collview on    # off = 还原
```

需要的文件：`extensions/kindletweaks/files/libKSDKLibrary.so.orig`、`libKSDKLibrary.so.patched`。用 `tools/patch_ksdk.py` 从自己机器的 `.orig` 生成 `.patched`。

建议先临时试用，再永久写入：

```sh
export PATH=/usr/sbin:/sbin:$PATH
mount --bind /mnt/us/extensions/kindletweaks/files/libKSDKLibrary.so.patched /app/lib/libKSDKLibrary.so
restart kppmainapp      # 必须重启书库进程才会加载新的 .so；出问题长按电源键 40 秒重启即恢复
grep libKSDKLibrary /proc/$(pidof KPPMainApp)/maps   # 设备号 00:13 = 正在用补丁版；fe:05 = 系统分区里的文件
```

## 5 新固件上怎么重做

1. 从新固件提取文件：`scp root@<kindle>:/app/lib/libKSDKLibrary.so .`
2. 用 IDA（或 Ghidra）打开，搜索字符串 `library_layout_mode_option.collections`，找到引用 `COLLECTIONS_OPTION` 的 `LibraryLayoutModeOptions` 和 `LibraryModeOptions` 两个函数。
3. 在两个函数里找到给收藏夹选项算 isEnabled 的那次虚函数调用，确认调用的是 `HouseholdUtilsImpl::HasActiveProfile`（构造函数里看成员偏移，再看虚函数表），把那条 `BLX Rx` 改成 `MOVS R0,#1`（`01 20`）。
4. 如果是 Thumb-2 的 4 字节 BL，就改成 `MOVS R0,#1; NOP` = `01 20 00 BF`。
5. 按第 4 节先临时试用，确认没问题再放进 `files/`，在 KUAL 里开启。

---

