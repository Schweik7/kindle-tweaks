# files/

放补丁用的系统文件（不进 git）。每个系统文件两份：

| 功能 | 文件 |
|---|---|
| popup | `KPPMainApp.js.hbc.orig` / `.patched` |
| collview | `libKSDKLibrary.so.orig` / `.patched` |
| pdffull | `PDFReader-impl.jar`、`ReaderSDK-impl.jar`、`ReaderSDK-impl-zh.jar` 各一对 `.orig` / `.patched` |

`.orig` 从你自己的 Kindle 上拷出来，`.patched` 用仓库 `tools/` 里的脚本在电脑上生成，见 README。
缺哪个功能的文件，菜单里该功能就显示「缺补丁文件」，其他功能照常可用。
