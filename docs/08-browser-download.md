# 08 浏览器下载任意文件

> 效果：体验版网页浏览器可以下载 epub、pdf 等任意文件，照常保存到 `/mnt/us/documents/`。epub 由「epub 自动转换」接手。

## 1 限制在哪里

浏览器是 `/usr/bin/mesquite`（WebKitGTK 外壳）。下载相关逻辑都在它的 `JSObjectDownload` 里，
`/var/local/mesquite/browser/javascripts/fileManager.js` 只负责弹确认框和显示结果。

| 位置（FW 5.15.1.1） | 函数 | 逻辑 |
|---|---|---|
| `0x47894` | `s_MimeTypeDecisionCallback` | 响应 MIME 浏览器不能直接显示时，只有 `application/x-mobi8-ebook`、`application/x-mobipocket-ebook`、`text/x-prc` 等 5 种转为下载，其余 `ignore` 并通知页面「文件类型无效」 |
| `0x471B8` | `s_DownloadRequestCallback` | 建议文件名的扩展名必须是 `.azw/.azw1/.azw2/.azw3/.prc/.mobi/.txt`，没有扩展名也拒绝 |
| `0x46644` | `s_DownloadLaunch` | 保存路径写死为 `/mnt/us/documents/` + 文件名 |

所以 miniserve 等服务器给 epub 返回 `application/epub+zip`，在第一道就被拦下。

## 2 补丁

`tools/patch_mesquite.py` 按特征码找 3 处，各改 4 字节（ARM）：

1. MIME 循环里 `strcasecmp` 后的 `BNE 下一项` → `NOP`：第一次比较就当作匹配，任何 MIME 都转为下载。
2. 扩展名循环结束仍未匹配的 `MOV R7,#0` → `MOV R7,#1`。
3. 文件名没有 `.` 时的 `MOV R7,#0` → `MOV R7,#1`。

下载前的确认框、下载权限（`config.xml` 的 `download-allowed`）和保存路径都不变。

## 3 开关

KUAL →「Kindle Tweaks」→「浏览器可下载任意文件」。SSH：

```sh
sh /mnt/us/extensions/kindletweaks/tweak.sh browserdl on    # off 还原
```

浏览器离开即退出（`unloadOnPause`），下次打开就是新版本。商店后台进程 `stored` 也是 mesquite，
开关时脚本会重启它，否则旧文件仍被占用，根分区无法切回只读。
