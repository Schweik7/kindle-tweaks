# kindle-tweaks

让越狱 Kindle 更好用的一组小改造，主要针对**未注册 / fakereg 假注册**的机器。

*A collection of tweaks for jailbroken Kindles (especially unregistered / fake-registered ones): remove the "cloud unavailable" nag, auto-build collections from folders, and unlock the Collections view. Docs are in Chinese; scripts are self-explanatory.*

> 验证设备：Kindle Oasis 3（10th gen），FW **5.15.1.1**，LanguageBreak 越狱 + KUAL + [fakereg](https://www.mobileread.com/forums/showpost.php?p=4122357&postcount=125)。
> 其他机型和固件的原理大概率相同，但偏移和特征码可能不同。脚本都会先校验，不匹配就不动。

## 功能

| # | 功能 | 解决的问题 | 文档 |
|---|---|---|---|
| 1 | 去掉「云端不可用」弹窗 | 假注册后每次进书库都弹「云端不可用，您必须注册 kindle…」 | [docs/01-cloud-popup.md](docs/01-cloud-popup.md) |
| 2 | 文件夹 → 收藏夹自动同步 | Kindle 不认文件夹；未注册时「新建收藏夹」是灰色的 | [docs/02-folder-collections.md](docs/02-folder-collections.md) |
| 3 | 解锁「查看选项 → 收藏夹」视图 | 收藏夹里的书仍在书库第一层平铺；该视图在未注册时是灰色的 | [docs/03-collections-view.md](docs/03-collections-view.md) |

后续还会加入更多功能。

## 目录

```
patches/kpp_patch/          系统文件补丁（1、3）
  patch_kpp.py              在电脑上生成 KPPMainApp.js.hbc 的补丁版（需要 hermes-dec）
  patch_ksdk.py             在电脑上生成 libKSDKLibrary.so 的补丁版（纯 Python）
  apply.sh / restore.sh     在 Kindle 上安装 / 还原（校验 md5，原子替换，重启书库进程）
extensions/foldercoll/      KUAL 扩展：文件夹 → 收藏夹（2）
docs/                       原理、排查过程、新固件上怎么重做
```

> ⚠ 本仓库**不包含任何亚马逊的原始文件或补丁后的文件**。补丁都是从你自己机器上提取的文件生成的。

## 前置条件

- 已越狱，装好 KUAL 和 MRPI。
- 能在 Kindle 上以 root 执行命令，二选一：
  - [USBNetwork](https://www.mobileread.com/forums/showthread.php?t=225030) 开启 SSH over WiFi（推荐，下文用 `ssh root@<kindle-ip>`）。
  - hotfix 自带的 `;log runme`：在书库搜索栏输入，会以 root 执行根目录的 `RUNME.sh`。
- 功能 2 需要 Kindle 上有 Python 3（例如 KUAL 的 python3 扩展，装在 `/mnt/us/python3`）。
- 功能 1 需要电脑上装 [hermes-dec](https://github.com/P1sec/hermes-dec)：`pip install git+https://github.com/P1sec/hermes-dec`。

## 快速开始

### 补丁（功能 1 + 3）

```sh
# 1. 从 Kindle 提取原始文件
scp root@<kindle-ip>:/app/KPPMainApp/js/KPPMainApp.js.hbc KPPMainApp.js.hbc.orig
scp root@<kindle-ip>:/app/lib/libKSDKLibrary.so          libKSDKLibrary.so.orig

# 2. 在电脑上生成补丁版
python patches/kpp_patch/patch_kpp.py   KPPMainApp.js.hbc.orig KPPMainApp.js.hbc.patched
python patches/kpp_patch/patch_ksdk.py  libKSDKLibrary.so.orig libKSDKLibrary.so.patched

# 3. 传到 Kindle 的 /mnt/us/kpp_patch/ 并安装
ssh root@<kindle-ip> mkdir -p /mnt/us/kpp_patch
scp *.orig *.patched patches/kpp_patch/apply.sh patches/kpp_patch/restore.sh root@<kindle-ip>:/mnt/us/kpp_patch/
ssh root@<kindle-ip> sh /mnt/us/kpp_patch/apply.sh
```

- 想还原：`ssh root@<kindle-ip> sh /mnt/us/kpp_patch/restore.sh`。
- 第一次用建议先临时试用（bind mount，重启即失效），见各功能文档。

### 文件夹收藏夹（功能 2）

1. 把 `extensions/foldercoll/` 拷到 Kindle 的 `extensions/` 下。
2. 打开 KUAL →「文件夹收藏夹」，先点「立即同步」，再点「开启自动同步（开机自启）」。
3. 之后 `documents/` 下的每个文件夹都会成为同名收藏夹。增删书、改文件夹名，大约 1～2 分钟内收藏夹会自动跟着变。

## 升级 / 重刷固件之后

系统分区会被整个替换，所以补丁和自动同步的开机任务都会失效。处理方法：

- **固件版本不变**：执行 `apply.sh`，再在 KUAL 里重新「开启自动同步」。
- **固件版本变了**：`apply.sh` 会因为 md5 对不上而跳过。用新固件的文件重新跑 `patch_*.py` 生成补丁版；如果脚本找不到特征，按 docs 里的手动方法重新定位。

## 风险与救砖

改的是书库界面程序。万一改坏，可能出现白屏：

- **临时试用阶段**：长按电源键约 40 秒强制重启，自动恢复。
- **已永久写入**：
  - 能 SSH 就执行 `restore.sh`（usbnet 的 SSH 不依赖界面）。
  - 不能 SSH 就重刷同版本官方固件（书不会丢）。

请自行承担风险。

## 致谢

- [LibrarianSync](https://github.com/NiLuJe/librariansync)：ccat `/change` 接口与 AuthToken。
- [kindle-auto-collections](https://github.com/poketjomon/kindle-auto-collections)：cc.db 结构。
- MobileRead [t=357149](https://www.mobileread.com/forums/showthread.php?t=357149)：「云端不可用」弹窗的来源分析。
- [hermes-dec](https://github.com/P1sec/hermes-dec)。

## License

MIT
