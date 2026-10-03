# kindle-tweaks

让越狱 Kindle 更好用的一组小改造，主要针对**未注册 / fakereg 假注册**的机器。所有功能集中在一个 KUAL 菜单「Kindle Tweaks」里，可以单独开关。

*A collection of tweaks for jailbroken Kindles (especially unregistered / fake-registered ones), managed from a single KUAL menu: remove the "cloud unavailable" nag, auto-build collections from folders, unlock the Collections view, and full-screen PDF (no footer, no margins). Docs are in Chinese; scripts are self-explanatory.*

> 验证设备：Kindle Oasis 3（10th gen），FW **5.15.1.1**，LanguageBreak 越狱 + KUAL + [fakereg](https://www.mobileread.com/forums/showpost.php?p=4122357&postcount=125)。
> 其他机型和固件的原理大概率相同，但偏移和特征码可能不同。脚本都会先校验，不匹配就不动。

## 功能

| # | 功能 | 解决的问题 | 文档 |
|---|---|---|---|
| 1 | 去掉「云端不可用」弹窗 | 假注册后每次进书库都弹「云端不可用，您必须注册 kindle…」 | [docs/01-cloud-popup.md](docs/01-cloud-popup.md) |
| 2 | 文件夹 → 收藏夹自动同步 | Kindle 不认文件夹；未注册时「新建收藏夹」是灰色的 | [docs/02-folder-collections.md](docs/02-folder-collections.md) |
| 3 | 解锁「查看选项 → 收藏夹」视图 | 收藏夹里的书仍在书库第一层平铺；该视图在未注册时是灰色的 | [docs/03-collections-view.md](docs/03-collections-view.md) |
| 4 | PDF 全屏 | PDF 底部常驻阅读百分比、四周有白边，设置里关不掉 | [docs/04-pdf-fullscreen.md](docs/04-pdf-fullscreen.md) |
| 5 | 大漫画 epub 充电时自动转 PDF | Kindle 打不开 epub；KCC 依赖的 KindleGen 只有 x86 版。在 Kindle 上用精简移植的 KCC 直接转成全屏 PDF | [docs/05-manga-convert.md](docs/05-manga-convert.md) |
| 6 | 屏保开机随机排序开关 | linkss 开机时重排所有屏保，图多时开机很慢 | （菜单里直接切换） |

## KUAL 菜单

```
Kindle Tweaks
├─ 去除「云端不可用」弹窗 [已开启]   → 开启 / 关闭（还原原版）
├─ 解锁「查看选项→收藏夹」 [已开启] → 开启 / 关闭（还原原版）
├─ PDF 全屏（无底栏无边距） [已开启] → 开启 / 关闭（还原原版）
├─ 文件夹收藏夹 [自动同步已开启]     → 立即同步 / 开启自动同步 / 关闭自动同步 / 删除所有自动生成的收藏夹
├─ 大漫画 epub 转 PDF [充电自动转换已开启 · 转换中 1/2 本，第 57/197 页]
│                                    → 开启 / 关闭自动转换 / 立即转换（不等充电）/ 刷新进度
├─ 屏保开机随机排序（linkss） [已关闭] → 开启 / 关闭
├─ 升级固件后：全部补丁重新开启
└─ 全部补丁还原原版
```

菜单项里的 `[状态]` 是按系统文件实际的 md5 算出来的，每次操作后自动刷新。缺补丁文件的功能会显示「缺补丁文件」，不影响其他功能。

## 目录

```
extensions/kindletweaks/    KUAL 扩展，整个目录拷到 Kindle 的 extensions/ 下
  tweak.sh                  所有开关的实现（KUAL 和 SSH 共用），生成 menu.json
  foldercoll/               文件夹 → 收藏夹（sync.py + upstart 任务模板）
  mangaconv/                漫画 epub → PDF（kcc_lite.py 移植自 KCC，mangaconv.py + upstart 任务模板）
  files/                    补丁用的系统文件 *.orig / *.patched（自己生成，不进 git）
tools/                      在电脑上生成 .patched
  patch_kpp.py              KPPMainApp.js.hbc（功能 1，需要 hermes-dec）
  patch_ksdk.py             libKSDKLibrary.so（功能 3，纯 Python）
  pdf_fullscreen/build.py   3 个 Java jar（功能 4，需要 JDK 9+）
docs/                       原理、排查过程、新固件上怎么重做
```

> ⚠ 本仓库**不包含任何亚马逊的原始文件或补丁后的文件**。补丁都是从你自己机器上提取的文件生成的。

## 前置条件

- 已越狱，装好 KUAL 和 MRPI。
- 能在 Kindle 上以 root 执行命令，二选一：
  - [USBNetwork](https://www.mobileread.com/forums/showthread.php?t=225030) 开启 SSH over WiFi（推荐，下文用 `ssh root@<kindle-ip>`）。
  - hotfix 自带的 `;log runme`：在书库搜索栏输入，会以 root 执行根目录的 `RUNME.sh`。
- 功能 2、5 需要 Kindle 上有 Python 3（例如 KUAL 的 python3 扩展，装在 `/mnt/us/python3`，自带 Pillow）。
- 生成补丁需要电脑上有 Python 3；功能 1 还要 [hermes-dec](https://github.com/P1sec/hermes-dec)（`pip install git+https://github.com/P1sec/hermes-dec`），功能 4 还要 JDK 9+。

## 快速开始

```sh
# 0. 装扩展
scp -r extensions/kindletweaks root@<kindle-ip>:/mnt/us/extensions/
F=/mnt/us/extensions/kindletweaks/files

# 1. 从 Kindle 提取原始文件
scp root@<kindle-ip>:/app/KPPMainApp/js/KPPMainApp.js.hbc KPPMainApp.js.hbc.orig
scp root@<kindle-ip>:/app/lib/libKSDKLibrary.so          libKSDKLibrary.so.orig
scp -r root@<kindle-ip>:/opt/amazon/ebook/lib            ebook-lib

# 2. 在电脑上生成补丁版（需要哪个功能就生成哪个）
python tools/patch_kpp.py  KPPMainApp.js.hbc.orig KPPMainApp.js.hbc.patched
python tools/patch_ksdk.py libKSDKLibrary.so.orig libKSDKLibrary.so.patched
python tools/pdf_fullscreen/build.py ebook-lib pdf-out     # 生成 3 对 jar 的 .orig/.patched

# 3. 传到扩展的 files/
scp *.orig *.patched pdf-out/* root@<kindle-ip>:$F/
```

然后打开 KUAL →「Kindle Tweaks」→「首次使用：刷新状态」，菜单就会列出全部功能。

- 建议每个补丁第一次用时先临时试用（bind mount，重启即失效），方法见各功能文档。
- SSH 等价命令：`sh /mnt/us/extensions/kindletweaks/tweak.sh status`、`tweak.sh pdffull on`、`tweak.sh all off` 等。不带参数运行会显示用法。

## 升级 / 重刷固件之后

系统分区会被整个替换，所以补丁和自动同步的开机任务都会失效。`extensions/kindletweaks/` 在用户分区，不受影响。

- **固件版本不变**：KUAL →「升级固件后：全部补丁重新开启」，再在「文件夹收藏夹」里重新「开启自动同步」、在「大漫画 epub 转 PDF」里重新「开启」。
- **固件版本变了**：菜单里会显示「文件不匹配」，脚本不会写入。
  1. 用新固件的文件重新生成 `.orig` / `.patched`。
  2. 如果生成脚本找不到特征，按 docs 里的手动方法重新定位。

## 风险与救砖

补丁改的是书库界面程序（功能 1、3）和 Java 阅读器框架（功能 4）。万一改坏，可能出现白屏：

- **临时试用阶段**：长按电源键约 40 秒强制重启，自动恢复。
- **已永久写入**：
  - 能 SSH 就执行 `sh /mnt/us/extensions/kindletweaks/tweak.sh all off`。usbnet 的 SSH 不依赖界面，白屏时一样能连。
  - 不能 SSH 就重刷同版本官方固件（书不会丢）。
- 白屏也可能只是 framework 重启后停在了 KUAL 的空白页，见 [docs/04 第 6 节](docs/04-pdf-fullscreen.md#6-排错笔记)。

请自行承担风险。

## 致谢

- [LibrarianSync](https://github.com/NiLuJe/librariansync)：ccat `/change` 接口与 AuthToken。
- [kindle-auto-collections](https://github.com/poketjomon/kindle-auto-collections)：cc.db 结构。
- MobileRead [t=357149](https://www.mobileread.com/forums/showthread.php?t=357149)：「云端不可用」弹窗的来源分析。
- [hermes-dec](https://github.com/P1sec/hermes-dec)、[CFR](https://www.benf.org/other/cfr/)。
- [Kindle Comic Converter (KCC)](https://github.com/ciromattia/kcc)：`mangaconv/kcc_lite.py` 的裁边、去页码、跨页拆分算法移植自 KCC。

## License

GPL-3.0-or-later（见 [LICENSE](LICENSE)）。`kcc_lite.py` 移植自 KCC 的 GPLv3 代码，所以整个仓库从 MIT 改为 GPL。
