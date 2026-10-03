# 01 去掉书库「云端不可用」弹窗

## 现象

用 fakereg 伪造注册后，设置里看起来已经注册了，但每次打开书库（以及从别处切回书库）都会弹出：

> 云端不可用 —— 您必须注册 kindle 才能查看和下载云端内容

## 原因

| 项目 | 说明 |
|---|---|
| 弹窗出自 | 书库/主页界面程序 `/app/KPPMainApp/js/KPPMainApp.js.hbc`，是 React Native 打包出的 **Hermes 字节码**。进程是 `/app/bin/KPPMainApp`，由 upstart 服务 `kppmainapp` 管理 |
| 触发逻辑 | 书库组件在 `componentDidMount` 和 `componentDidUpdate`（切回书库）时调用 `IsDeviceRegistered()`，返回假就调用 `invokeDeviceNotRegisteredDialog()` |
| fakereg 为什么无效 | fakereg 只伪造了 `/var/local/java/prefs/reginfo`。这个检查依赖真实注册下发的设备凭证，日志里能看到 `kppAction Action:kppCustomerMembership Result:Failure` |
| 弹窗文字的 key | `library.dialog.error.cloud_not_available.*`，在 `/app/KPPMainApp/locale/<语言>/LC_MESSAGES/mainapp.mo` 里 |

## 补丁

把 `invokeDeviceNotRegisteredDialog` 的开头 4 个字节改成：

```
LoadConstUndefined r0
Ret r0
```

也就是一进函数就返回。两个调用点都不用它的返回值，所以不影响别的功能。然后重新计算文件末尾的 SHA1：Hermes 文件的最后 20 字节是前面全部内容的 SHA1。运行时其实不检查这个值，但修好后反编译工具能正常解析，方便以后校验。

| 固件 | Hermes 版本 | 函数 # | 偏移 | 原始字节 | 补丁 | 原版 md5 | 补丁版 md5 |
|---|---|---|---|---|---|---|---|
| KOA3 5.15.1.1 | 84 | 6904 | 0x144AFF | `27 00 00 2c` | `70 00 58 00` | b6fc25dd4b24b83f06d9ca619e4cbe27 | c308448c3796121852319096678b2aa1 |

> 欢迎用 PR 补充其他机型和固件的记录。

## 操作步骤

### 1. 提取

```sh
ssh root@<kindle-ip> "cat /etc/prettyversion.txt; md5sum /app/KPPMainApp/js/KPPMainApp.js.hbc"
scp root@<kindle-ip>:/app/KPPMainApp/js/KPPMainApp.js.hbc KPPMainApp.js.hbc.orig
```

⚠ 确认拿到的是**原版**。如果以前打过补丁，先在 KUAL 里把这项「关闭（还原原版）」。

### 2. 生成补丁（自动）

```sh
pip install git+https://github.com/P1sec/hermes-dec
python tools/patch_kpp.py KPPMainApp.js.hbc.orig KPPMainApp.js.hbc.patched
```

这个脚本会：

1. 用 hermes-dec 解析文件，按函数名找到 `invokeDeviceNotRegisteredDialog`。
2. 根据字节码版本查出 `LoadConstUndefined` 和 `Ret` 的操作码。
3. 打补丁，并重新计算 SHA1。

### 2'. 手动定位（脚本报错时用）

```sh
hbc-file-parser  KPPMainApp.js.hbc.orig             # Version = 字节码版本
hbc-disassembler KPPMainApp.js.hbc.orig dis.hasm
hbc-decompiler   KPPMainApp.js.hbc.orig dec.js
```

1. 在 `dec.js` 里搜 `cloud_not_available`，找到生成弹窗内容的地方，往上找到显示弹窗的函数。
2. 搜这个函数名，确认调用方是 `if (!IsDeviceRegistered()) xxx()` 这种结构，而且没有使用返回值。
3. 在 `dis.hasm` 里搜 `=> [Function #... "<函数名>"`，`@ offset` 后面就是它在文件里的偏移。
4. 在 hermes-dec 的 `parsers/hbc_opcodes/hbc<版本>.py` 里查 `LoadConstUndefined` 和 `Ret` 的操作码（**不同版本的操作码可能不同**）。
5. 把这个偏移处的 4 字节改成 `<LoadConstUndefined> 00 <Ret> 00`，再重新计算末尾的 SHA1。
6. 如果函数改了名字，修改 `patch_kpp.py` 里的 `TARGET` 就能继续用。

### 3. 临时试用（不动系统分区）

```sh
ssh root@<kindle-ip>
export PATH=/usr/sbin:/sbin:$PATH
# 先用 scp 把 .orig / .patched 传到 /mnt/us/extensions/kindletweaks/files/
mount --bind /mnt/us/extensions/kindletweaks/files/KPPMainApp.js.hbc.patched /app/KPPMainApp/js/KPPMainApp.js.hbc
restart kppmainapp
```

- **必须 `restart kppmainapp`。** 书库进程从开机起一直把旧文件映射在内存里，只在界面上切换不会重新加载。
- 确认进程用的是哪个文件：`grep hbc /proc/$(pidof KPPMainApp)/maps`。设备号 `00:13` 之类表示用的是 U 盘区的补丁版，`fe:05` 表示用的是系统分区里的文件。
- 出问题（白屏）时：长按电源键约 40 秒强制重启，bind mount 会失效，系统恢复原样。

### 4. 永久写入

KUAL →「Kindle Tweaks」→「去除「云端不可用」弹窗」→「开启」。也可以用 SSH：

```sh
ssh root@<kindle-ip> sh /mnt/us/extensions/kindletweaks/tweak.sh popup on    # off = 还原
```

`tweak.sh` 对每个文件的处理步骤：

1. 解除临时试用留下的 bind mount。
2. 核对系统里的文件 md5 是否等于 `.orig` 或 `.patched`，都不等就整组不动（固件变了）。
3. `mntroot rw`。
4. 先复制成 `.new`，再用 `mv` 原子替换。
5. `mntroot ro`。
6. 校验 md5。
7. `restart kppmainapp`。

脚本不写死 md5，而是和 `files/` 里的 `.orig` / `.patched` 比对。换了固件以后，只需要换掉这两个文件。

## 没有 SSH 时

把要执行的命令写进 Kindle 根目录的 `RUNME.sh`，用 LF 换行。然后在书库搜索栏输入 `;log runme`，这需要 LanguageBreak 的 hotfix。输出可以重定向到 `/mnt/us/xxx.log`，再通过 USB 查看。

## 其他方案为什么不行

- **真实注册**：需要有效的序列号。部分机器重置后序列号被清零（前缀之后全是 0），无法注册。fakereg 往 hosts 里加的屏蔽也会让注册失败。
- **MobileRead 上的现成补丁**：只适用于 5.16.2.1.1，偏移不同。
- **开机直接跳到书库页**：弹窗照样出现。
