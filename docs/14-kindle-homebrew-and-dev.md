# 14 Kindle 自制软件与原生开发

> 在 Kindle 上「装自己的东西」有四种层次，本文都覆盖：
> **hotfix**（拿到并维持 root 的底座）→ **Scriptlets**（最简单，一个 `.sh` 就是入口）→
> **KPM**（正经的包管理）→ **原生应用**（C/C++ + GTK + Meson 交叉编译）。
>
> 内容整理自 [KindleModding Wiki — Kindle Development](https://kindlemodding.org/kindle-dev/) 与
> [Kindle Hacking](https://kindlemodding.org/kindle-hacking/)（CC BY-NC 4.0），并与本仓库的实践经验合并。

## 1 hotfix

热修复（hotfix）是越狱的落地组件：越狱只负责把 root 文件系统打开、装上自制签名公钥（见
[13 第 5 节](13-kindle-system-reference.md#5-越狱到底改了什么)），**hotfix 才把工具链真正铺到机器上并维持住**。

它以 **OTA 包**的形式分发（`.bin`），所以越狱第一步必须换 OTA 签名公钥——否则 Kindle 根本不肯装。

### 1.1 包结构

以 Universal Hotfix 为例：

```
.
├── install.sh
├── kmc.tar
├── libotautils6
├── mkk.tar
└── update-filelist.dat
```

Kindle 安装 OTA 时有一个特殊行为：**会执行包内所有 `.sh` 文件**。所以 entry point 就是 `install.sh`。

### 1.2 install.sh 做了哪些事

1. `source libotautils6` 拿到辅助函数。
2. 算 `/var/local/kmc` 和 `/var/local/mkk` 当前占用（它们会被替换，所以要减掉），**空间不够就报错退出**。
3. 建目录，把 `mkk.tar`、`kmc.tar` 解到 `/var/local/` 下。
4. 给 `/var/local/kmc` 里的库和二进制设权限。
5. 删掉旧的 `bridge.conf`（老 hotfix 遗留），装自己的 `kmc.conf`。
6. 建符号链接把架构目录接上：
   `/var/local/kmc/armhf/bin → /var/local/kmc/bin`，`armhf/lib → /var/local/kmc/lib`。
7. **把 `gandalf` 链接成 `su`**：`gandalf` 是一个 busybox 构建，必须以 `su` 这个名字存在才能当提权工具用。
8. 把 `dispatch.sh`（调试命令）复制成 `/usr/bin/logThis.sh`，也就是 `;log` 命令（见 [13 第 4.2 节](13-kindle-system-reference.md#42-log-与热修复)）。
9. 改 `appreg.db`，注册热修复 booklet 与 `sh_integration`。

装完 hotfix，**还差最后一步在 OTA 环境里做不了的事**，所以会生成一个 `Run Hotfix` booklet：

- 判断设备架构，跑对应架构的 `su` 提权。
- 遍历 hotfix 里的 job 逐个执行。
- 重启 `lab126_gui`。

几个有代表性的 job：

| job | 作用 |
|---|---|
| `install_mkk_dev_keystore.sh` | 装 Java keystore，**让 KUAL 这类老式 booklet（Kindlet）能跑** |
| `install_mkk_kindlet_jb.sh` | 装运行 Kindlet 用的老 jar（现在已不需要） |
| `setup_fbink.sh` | 把 fbink 二进制放到预期位置 |

> 本仓库的前置条件（KUAL + MRPI + USBNetwork）本质上都是跑在 hotfix 铺好的地面上。
> 遇到「KUAL 打不开」先怀疑 keystore 那一步。

### 1.3 upstart 侧

hotfix 装的 `/etc/upstart/kmc.conf` 在 `framework_ready` 时运行，逻辑是：

- 如果 `/mnt/us/emergency.sh` 存在，**执行它**（这就是「救砖脚本」通道）；
- 否则校正 `/var/local/kmc` 里二进制和库的权限（它们存放在 vfat 上，权限位不可靠）。

`/mnt/us/emergency.sh` 值得记住：开机就执行，不需要 SSH、不需要界面。

## 2 Scriptlets

Scriptlets 是 Universal Hotfix（WinterBreak 时代）引入的**最简单的运行方式**：
**把 `.sh` 扔进 `/mnt/us/documents`，它就会像书一样被索引，出现在书库里，点一下就能运行。**

底层靠 [sh_integration](https://github.com/KindleModding/sh_integration)：
它在 [appreg.db](13-kindle-system-reference.md#22-associations谁处理什么) 里注册了 `GL:*.sh → com.notmarek.shell_integration.extractor`，
于是扫描器会把 `.sh` 登记成内容条目。

### 2.1 元数据

在文件开头用注释声明：

```sh
#!/bin/sh
# Name: Test Script
# Author: Hackerdude

echo "Hello, World!"
```

书库里就会显示成 **Test Script / Hackerdude**。

### 2.2 可用的 flag

| flag | 作用 |
|---|---|
| `# Icon: <路径或 data URI>` | 自定义图标。可以是绝对路径，也可以是 base64 的 `data:image/png;base64,…`。**注意有些转换工具生成的 base64 里 MIME 类型和实际数据不符，要自己对一下** |
| `# UseHooks` | 不把整个脚本当一次运行，而是改成回调：`on_install()` / `on_remove()` / `on_run()` |
| `# DontUseFBInk` | 默认脚本的 stdout/stderr 会被接到 FBink 上显示在屏幕；加上这个就不显示 |

`# UseHooks` 的例子：

```sh
#!/bin/sh
# Name: Test For Events
# Author: Hackerdude
# UseHooks

on_install() { echo "on_install called!"  >> /mnt/us/test.log; }
on_remove()  { echo "on_remove called!"   >> /mnt/us/test.log; }
on_run()     { echo "on_run called!"      >> /mnt/us/test.log; }
```

### 2.3 与本仓库的关系

本仓库走的是 **KUAL 菜单**（`extensions/kindletweaks/`），不是 Scriptlets。两者可以共存：

| | KUAL 扩展 | Scriptlets |
|---|---|---|
| 入口 | KUAL 菜单 | 书库里的一本书 |
| 形态 | `extensions/<名字>/menu.json` + 脚本 | `/mnt/us/documents/xxx.sh` |
| 依赖 | KUAL + keystore | hotfix 的 sh_integration |
| 适合 | 有状态、多级菜单的开关（本仓库） | 一次性脚本、小工具、快捷入口 |
| 不依赖界面 | ❌ 需要能进 KUAL | ❌ 需要能进书库 |

**两个都需要界面。** 界面起不来时只有 SSH、`;log runme`（见 [13 第 4.2 节](13-kindle-system-reference.md#42-log-与热修复)）
和 `/mnt/us/emergency.sh` 可用——这一点在 [README 的风险与救砖](../README.md#风险与救砖) 里也强调了。

## 3 KPM（Kindle Package Manager）

KPM 是社区做的 Kindle 包管理器：**在设备上索引、下载、安装自制软件**。它正在成为推荐的发行方式（`hdnext` 之后）。

### 3.1 包结构

```sh
python kpm-helper.py package init ./example_package
```

生成一个只有 `manifest.json` 的目录。往里放文件 + 三个可选 hook：

| 文件 | 触发时机 |
|---|---|
| `install.sh` | 包解压后、安装时运行 |
| `uninstall.sh` | 卸载后运行 |
| `launch.sh` | 从启动器里启动包时运行 |

打包：

```sh
python kpm-helper.py package pack FOLDER_PATH OUTPUT_PATH     # 产出 .kpkg
```

`./kpm-helper.py package pack --supported-platform kindlepw2 …` 或手写 `manifest.json` 里的
`supported_platforms` 数组可以限定目标平台：

| 平台名 | 覆盖范围 |
|---|---|
| `kindle` | 比 K5 更老的机型 |
| `kindle5` | K5 及更新 |
| `kindlepw2` | PW2 及更新 |
| `kindlehf` | armhf 平台 |

### 3.2 硬性规则

- **hook 运行时的 cwd 就是包目录**（包处于解压状态），可以直接用相对路径引用包内文件。
- **hook 绝对不能写 rootfs，也不能把 rootfs 重新挂成 rw。** 目前不支持这种做法，官方说以后会给方案。
  这一点对本仓库有直接影响：本仓库的功能全都要写 `/etc/upstart/`（在 rootfs 上），
  所以**不适合直接做成 KPM 包**，除非改成「hook 只放文件，实际写入由用户手动/开机脚本完成」。
- 升级流程：旧包 `uninstall.sh upgrade` → 删旧文件 → 解新文件 → 新包 `install.sh`。
  所以 `uninstall.sh` **不要自己删包文件**，KPM 会处理。
- 推荐做法：`install.sh` 往 `/mnt/us/documents` 放一个 Scriptlet，
  这个 Scriptlet 执行 `/var/local/kmc/bin/kpm launch PACKAGENAME`，

### 3.3 仓库

绝大多数情况**不需要自己建仓库**，把包提交到
[官方仓库](https://github.com/KindleModding/repo/pulls) 就行。要自建：

```sh
python kpm-helper.py repo init ./example_repository
python kpm-helper.py repo add ./example_repository PACKAGE_PATH   # PACKAGE_PATH 是 .kpkg
```

或者直接 fork [示例仓库模板](https://github.com/KindleModding/kpm-repository-template)。
仓库可以静态托管（比如 GitHub Pages）。

## 4 原生开发

想写跑在 Kindle 上的原生程序（而不是脚本），标准路径是
**koxtoolchain（交叉工具链）+ Kindle SDK（头文件与库）+ Meson**。

### 4.1 工具链

[koxtoolchain](https://github.com/koreader/koxtoolchain)（KOReader 项目维护）：

```sh
git clone --recursive --depth=1 https://github.com/koreader/koxtoolchain.git
cd koxtoolchain
chmod +x ./gen-tc.sh
./gen-tc.sh <target>          # 装到 ~/x-tools/
```

| 工具链 target | 支持机型 | 说明 |
|---|---|---|
| `kindle` | K2 / DX / DXg / K3 | 太老，GTK 教程不支持 |
| `kindle5` | K4 / Touch / PW1 | 太老，GTK 教程不支持 |
| `kindlepw2` | PW2 及以后、且 FW < 5.16.3 | **本仓库验证机（KOA3 / 5.15.1.1）属于这一档** |
| `kindlehf` | 任意 FW ≥ 5.16.3 的机型 | 硬浮点，新机型用 |

> 编译很慢，**每个 target 约 30 分钟**。不想自己编就用
> [预编译 release](https://github.com/koreader/koxtoolchain/releases/latest)。

宿主机要装的包（Debian/Ubuntu）：

```sh
sudo apt-get install build-essential autoconf automake bison flex gawk libtool libtool-bin \
                     libncurses-dev curl file git gperf help2man texinfo unzip wget
sudo apt-get install curl sed libarchive-dev nettle-dev      # SDK 需要
sudo apt-get install meson libgtk2.0-dev                     # GTK 应用需要
```

### 4.2 Kindle SDK

[Kindle SDK](https://github.com/KindleModding/kindle-sdk) 是社区做的非官方 SDK，
**在已有 koxtoolchain 之上补上 Kindle 的头文件和 `.pc` 文件**，让 Meson 的
`dependency('gtk+-2.0')` 之类能正常工作。

它的工作方式是：**下载对应机型的官方固件，把里面的库拷进工具链的 `sysroot`，再为支持的库生成 `.pc` 文件。**

```sh
git clone --recursive --depth=1 https://github.com/KindleModding/kindle-sdk.git
cd kindle-sdk
chmod +x ./gen-sdk.sh
./gen-sdk.sh <target>        # target 与工具链相同
```

装完会输出一个 `meson-crosscompile.txt` 的路径（通常在 `~/x-tools/<工具链>/meson-crosscompile.txt`），**记下来，下面要用**。

### 4.3 Meson 工程

`meson.options`：

```python
option('kindle_root_dir', type : 'string', value: '', description: 'The path to the Kindle\'s mounted rootfs (for linking libraries)')
```

`meson.build`：

```python
project('example_gtk_application', 'cpp', version: 'v1.0.0',
        default_options: ['cpp_std=c++17'], meson_version: '>=1.1')

gtk_dep = dependency('gtk+-2.0')

sources = files('./src/main.cpp')
include_dirs = include_directories('./src/include/')

executable('example_gtk_application', sources,
           include_directories: include_dirs,
           dependencies: [gtk_dep],
           cpp_args: '-static-libstdc++', link_args: '-static-libstdc++')
```

> **`-static-libstdc++` 是必须的**：koxtoolchain 带的 GCC 比 Kindle 系统里的 libstdc++ 新，
> 动态链接会在设备上报符号缺失。静态链上就没事。

编译：

```sh
meson setup builddir                                  # 本机跑，验证代码
meson compile -C builddir

meson setup --cross-file <meson_crosscompile_path> builddir_<target>   # 给 Kindle 编
meson compile -C builddir_<target>
```

**本仓库对照**：`tools/build_ebook_converters.py` 走的是另一条路（Rust + musl 静态链接），
`extensions/kindletweaks/libraryview/libkt_libview.c` 用的是 zig 直接交叉编译成 `.so`。
两条路都不需要 koxtoolchain，因为目标分别是「静态可执行文件」和「用 LD_PRELOAD 顶替符号的库」——
都不需要链接 Kindle 的库。**只有当你需要链接 Kindle 自带的库（GTK、lipc 等）时，才必须上 SDK。**
LD_PRELOAD 的做法见 [09 第 8 节](09-lab126-internals.md#8-给系统进程注入代码ld_preload)。

### 4.4 窗口标题：Awesome WM 的约定

Kindle 用的是打过补丁的 **Awesome Window Manager**。**每个 GUI 窗口的标题都不是给人看的，而是一个键值对串**，
窗口管理器靠它决定窗口放哪一层、显示哪些 chrome。**标题写错 = 窗口不显示或行为诡异。**

```
L:A_N:application_PC:TS_ID:com.lab126.store
```

`_` 分隔键值对，等价于：

```json
{ "L": "A", "N": "application", "PC": "TS", "ID": "com.lab126.store" }
```

| 键 | 含义 | 取值 |
|---|---|---|
| `L` | **Layer** 层级 | `A` APP、`C` CHROME、`D` DIALOG、`KB` 键盘、`SS` 屏保。屏保层在 APP 层之上（从上到下渲染） |
| `N` | **Name/Role** 角色 | `application`、`dialog`、`titlebar`、`searchResult`、`pillowAlert`（会挡住 home 键）、`topBar`、`mediaBar`、`keyboard`、`screenSaver`、`searchBar` …。常用只有 `application` 和 `dialog` |
| `PC` | **Persistent Chrome** 常驻界面元素 | `T` 顶部状态栏、`S` 搜索栏、`B` 老式底栏、`N` 都不要；可以组合，如 `TS`、`TSB`（**`TSB` 的窗口缩放是坏的，别用**） |
| `ID` | **Identifier** | 反向域名，如 `com.lab126.store`。**不能含下划线**（下划线是分隔符）。`blankBackground` 是保留值，用了窗口会变成 invalid |
| `BARTYPE` | 配合 `N:topBar` | `T` 顶栏、`S` 搜索栏、`B` 底栏、`A` 应用工具条 |
| `O` | **Orientation** 支持的方向掩码 | `U`/`D`/`L`/`R` 的任意组合，如 `ULR`、`UDLR` |
| `HIDE` | 隐藏窗口 | 更新 title 去掉这个键即可重新显示；可带值 `background`（不抢焦点） |
| `RC` | **Rounded Corners**，对话框圆角 | 当 flag 用，或给像素半径；给 `custom` 时用 `RCTL` / `RCTR` / `RCBL` / `RCBR` 单独设四角，如 `RC:custom_RCTL_RCTR` |
| `M` | **Modality**，对话框模态 | 可带值 `dismissable` |
| `RKB` | **Require KeyBoard** | 让对话框不要被弹出的键盘挡住 |
| `PALMR` | 手掌误触 | 用途未知，只和 `M:dismissable` 一起出现 |

最小可用的 GTK 窗口标题（来自官方教程）：

```c
gtk_window_set_title(GTK_WINDOW(window),
    "L:A_N:application_ID:org.kindlemodding.example-gtk-application_PC:T");
```

> 这一节对**改界面**也有用：本仓库功能 1、3、8 改的是 React Native 的 KPP 和 Java 框架，
> 不走 Awesome WM；但功能 4 改的 Java 阅读器 jar 和功能 9 的 mesquite（浏览器）都是普通窗口，
> 排查「谁的窗口盖住了谁」时就要读这个 title。

## 5 四种方式怎么选

| 需求 | 选 |
|---|---|
| 几行脚本、一次性任务 | **Scriptlet**（丢进 documents） |
| 有状态的开关菜单、要嵌进系统 | **KUAL 扩展**（本仓库的做法） |
| 想给别人分发、要版本管理 | **KPM 包**（但注意不能写 rootfs） |
| 要接 Kindle 的库、要真正的 GUI | **原生 + koxtoolchain + Kindle SDK** |
| 要改系统进程的行为而不改文件 | **LD_PRELOAD**（见 [09 第 8 节](09-lab126-internals.md#8-给系统进程注入代码ld_preload)） |

## 6 参考资料

- [KindleModding Wiki — Kindle Development](https://kindlemodding.org/kindle-dev/)：
  [KPM](https://kindlemodding.org/kindle-dev/kpm/)、[Scriptlets](https://kindlemodding.org/kindle-dev/scriptlets.html)、
  [Kindle SDK](https://kindlemodding.org/kindle-dev/kindle-sdk.html)、
  [GTK Tutorial](https://kindlemodding.org/kindle-dev/gtk-tutorial/)、
  [Awesome Window Manager](https://kindlemodding.org/kindle-dev/awesome-window-manager/)。
- [KindleModding Wiki — Hotfix](https://kindlemodding.org/kindle-hacking/hotfix.html)。
- [KPM](https://github.com/KindleModding/KPM) / [示例包](https://github.com/KindleModding/example_kpm_package) /
  [仓库模板](https://github.com/KindleModding/kpm-repository-template)。
- [sh_integration](https://github.com/KindleModding/sh_integration) / [Hotfix 的 job 列表](https://github.com/KindleModding/Hotfix/tree/rewrite-lite/src/kmc/hotfix/jobs)。
- [koxtoolchain](https://github.com/koreader/koxtoolchain) / [kindle-sdk](https://github.com/KindleModding/kindle-sdk)。
- [09 Kindle 系统内部](09-lab126-internals.md)：upstart、LD_PRELOAD、交叉编译本仓库用到的做法。
