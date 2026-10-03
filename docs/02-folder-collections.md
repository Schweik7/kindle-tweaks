# 02 文件夹 → 收藏夹自动同步

> 验证：Kindle Oasis 3，FW 5.15.1.1，越狱 + fakereg 假注册。
> 效果：`documents` 下的每个文件夹自动变成一个同名收藏夹，文件夹里的书自动加入。增删书、改文件夹名，大约 1～2 分钟内收藏夹会跟着变。
> 代码：[`extensions/kindletweaks/foldercoll/`](../extensions/kindletweaks/foldercoll/)，菜单和开关在 [`tweak.sh`](../extensions/kindletweaks/tweak.sh)。

---

## 1. 背景：为什么要自己做

- Kindle 原生**不会**按文件夹生成收藏夹，所有书都平铺在书库里。
- 未注册（包括 fakereg 假注册）时，书库里的「新建收藏夹」是**灰色**的，手动也建不了。
- 但收藏夹本质上只是书库数据库里的一条记录。灰色限制只存在于界面，绕过界面直接调用系统内部接口就能创建。所以没有去改 KPPMainApp 的按钮逻辑。

---

## 2. 原理

### 2.1 书库数据库 `/var/local/cc.db`

| 表 | 作用 |
|---|---|
| `Entries` | 所有书、收藏夹、字典都是一行。书是 `p_type='Entry:Item'`，路径在 `p_location`（如 `/mnt/us/documents/漫画/xxx.mobi`）；收藏夹是 `p_type='Collection'`，名字在 `p_titles_0_nominal`，书数在 `p_memberCount` |
| `Collections` | 收藏夹和书的关联表：`i_collection_uuid` → `i_member_uuid`，`i_order` 为顺序 |

**不要直接写这个数据库**：
- 它由系统的 ccat 服务管理，直接改不会通知界面，还可能和服务的写入冲突。
- `Entries` 表用了 `COLLATE icu`，Kindle 自带的 sqlite3 写不进去。

只用它来**只读查询**。

### 2.2 ccat 的修改接口：`http://127.0.0.1:9101/change`

ccat 服务运行在 Java 进程 `cvm` 里，只监听本机。这个接口就是 LibrarianSync 用的那个。发 JSON 命令即可增删改收藏夹，修改会立刻在界面生效，不用重启：

```json
{"type": "ChangeRequest", "id": 1, "commands": [
  {"insert": {"type": "Collection", "uuid": "<新 uuid>", "lastAccess": 1790000000,
              "titles": [{"display": "漫画", "collation": "漫画", "language": "zh"}],
              "isVisibleInHome": true, "isArchived": false,
              "mimeType": "application/x-kindle-collection", "collections": null}},
  {"update": {"type": "Collection", "uuid": "<同一个 uuid>", "members": ["<书的 p_uuid>", "..."]}},
  {"delete": {"uuid": "<要删的收藏夹 uuid>"}}
]}
```

- `update` 里的 `members` 是**完整成员列表**，会整体覆盖，列表顺序就是书在收藏夹里的顺序。
- 返回 `{"ok":true,"type":"ChangeResponse",...,"changes":N}` 表示成功。
- 已知限制（来自 LibrarianSync 讨论帖）：单个收藏夹超过约 900 本书会失败，因为 SQLite 一条语句最多 999 个变量。

### 2.3 认证：AuthToken（**重点**）

FW 5.12 起，这个接口需要认证，请求头要带：

```
AuthToken: <文件 /tmp/session_token 的内容>
```

---

## 3. 找 token 的过程（排错记录）

1. **第一次请求返回 `HTTP 401`**。这说明接口还在，只是加了认证。老版本的 LibrarianSync 不需要认证。
2. **查资料**：MobileRead 上 LibrarianSync 的讨论帖说，5.12 以后的固件要在请求头里加 `AuthToken`，值取自 `/tmp/session_token`。
3. **加上之后仍然 401**。
4. **怀疑 token 过期**：`/tmp/session_token` 的时间是开机时的 10:42，而 `cvm` 进程因为重启过界面，是 11:19 才启动的。
5. **查 token 是怎么生成的**：在 `/etc/upstart/` 里搜 `session_token`，找到 `system.conf`：
   ```sh
   head -c 32 /dev/urandom | base64 | tr -d '\n' > /tmp/session_token
   chmod 644 /tmp/session_token
   ```
   说明 token 只在**开机挂载 /tmp 时**生成一次，重启界面不会变。所以 token 没有过期，问题出在别处。
6. **找服务端校验代码**：
   - `/usr/lib/ccat/*.lua`（包括 change.lua）里没有认证逻辑。
   - 把 `/opt/amazon/ebook/lib/*.jar` 全部拉回电脑搜索，也没搜到 `session_token`，校验应该在原生代码里。这条路先放下。
7. **真正的原因：请求头名字的大小写被改了**。我用的是 Python 的 `urllib.request`，它会把请求头名字规范化成「首字母大写、其余小写」，`AuthToken` 实际发出去变成了 `Authtoken`。服务端按原样区分大小写比对，所以一直 401。
8. **改用 `http.client` 手动 `putheader("AuthToken", tok)`**，大小写保持原样，马上返回 `200 {"ok":true}`。LibrarianSync 用的 `requests` 库会保留原始大小写，所以它没遇到这个问题。

**结论**：token 就是 `/tmp/session_token` 的内容，每次开机变一次，每次用时现读即可。请求头必须一字不差地写成 `AuthToken`。

用 curl 测试接口的写法（usbnet 自带 curl，会保留请求头大小写）：
```sh
/mnt/us/usbnet/bin/curl -s -H "AuthToken: $(cat /tmp/session_token)" -H "Content-Type: application/json" \
  -d '{"type":"ChangeRequest","id":1,"commands":[]}' http://127.0.0.1:9101/change
```

---

## 4. 实现：KUAL 扩展 `kindletweaks` 里的 `foldercoll/`

KUAL →「Kindle Tweaks」→「文件夹收藏夹」：立即同步 / 开启自动同步 / 关闭自动同步 / 删除所有自动生成的收藏夹。

```
extensions/kindletweaks/
├─ tweak.sh                 菜单动作都调用它：tweak.sh coll sync|on|off|purge
└─ foldercoll/
   ├─ config.json           配置（见下）
   ├─ sync.py               同步逻辑（用 Kindle 上的 /mnt/us/python3）
   ├─ foldercoll.conf       upstart 任务模板（开机自启），coll on/off 把它装进 /etc/upstart/ 或移除
   ├─ state.json            记录「本工具创建的收藏夹名 → uuid」
   └─ sync.log              日志（超过 200KB 自动轮换）
```

> 从 1.x 的独立扩展 `extensions/foldercoll/` 升级：把旧目录里的 `config.json`、`state.json` 拷进 `kindletweaks/foldercoll/`，删掉旧扩展，再在菜单里「开启自动同步」一次（会用新路径覆盖 upstart 任务）。

### 4.1 配置 `config.json`

```json
{
 "prefix": "",
 "exclude": ["dictionaries", "Downloads"]
}
```

- `prefix` 为 `""` 时，**所有文件夹**都会变成收藏夹（当前设置）。
- 如果只想让一部分文件夹生效，比如只认 `收藏夹_漫画` 这类名字，就改成 `"prefix": "收藏夹_"`，收藏夹名会去掉前缀。
- `exclude` 里的文件夹不处理。`.sdr` 文件夹（阅读进度、笔记）里面没有书，本来就不会生成收藏夹，代码里也额外跳过了。
- 改完配置后，下一轮自动同步会按新规则调整。

### 4.2 同步逻辑 `sync.py`

1. **只读**打开 `cc.db`，查出 `documents` 下所有书的 `p_uuid` 和 `p_location`，以及现有的收藏夹和成员。
2. 根据路径里的文件夹名算出「收藏夹名 → 成员列表」。成员按文件路径做自然排序，卷02 排在卷10 前面。子文件夹里的书也会加入上层文件夹对应的收藏夹。
3. 和现状比对，只发需要的命令：
   - 没有这个收藏夹：`insert` 新建，再 `update` 设置成员。
   - 成员不一致：`update`。
   - `state.json` 里记录过、但对应文件夹已经没了：`delete`。
4. **只管自己建的收藏夹**（`state.json` 里记录的那些）。手动建的收藏夹不碰。如果 `state.json` 丢了，会接管同名的收藏夹。
5. 判断书在哪里，用的是书库数据库，而不是扫描磁盘。所以 USB 连电脑、`/mnt/us` 暂时不可用时，不会误判成文件夹都没了而删掉收藏夹。

### 4.3 自动同步：upstart 任务 `foldercoll`

- 任务文件在 `/etc/upstart/foldercoll.conf`（系统分区），`start on started framework`，开机自启。
- 循环逻辑：开机后等 90 秒，之后每 60 秒检查一次。用系统自带的 `sqlite3` 查出所有书的路径和所有收藏夹的 uuid，算 md5 当作签名；签名变了才调用 `tweak.sh coll autosync` 同步（不在屏幕上打提示）。平时只多一条很轻的 SQL 查询，几乎不耗电。
- 循环本身写在系统分区的任务文件里，Python 只在需要时才启动。USB 连电脑时 `/mnt/us` 被卸载，这一轮会失败，但签名不会更新，下一轮自动重试。
- 实测：把文件夹改名后，大约 80 秒收藏夹就跟着更新了。

### 4.4 常用命令

```sh
ssh root@<kindle-ip>
sh /mnt/us/extensions/kindletweaks/tweak.sh coll sync     # 立即同步
sh /mnt/us/extensions/kindletweaks/tweak.sh coll purge    # 删除所有自动生成的收藏夹
LD_LIBRARY_PATH=/mnt/us/python3/lib /mnt/us/python3/bin/python3.9 /mnt/us/extensions/kindletweaks/foldercoll/sync.py --dry   # 只预览，不修改
tail /mnt/us/extensions/kindletweaks/foldercoll/sync.log  # 看日志
status foldercoll                                  # 看自动同步是否在运行（需要先 export PATH=/usr/sbin:/sbin:$PATH）
sqlite3 /var/local/cc.db "select p_titles_0_nominal, p_memberCount from Entries where p_type='Collection'"
```

⚠ 用系统自带的 `sqlite3` 时，**不要**同时设置 `LD_LIBRARY_PATH=/mnt/us/python3/lib`，否则会报 `SQLite header and source version mismatch`（加载了 Python 带的另一版 libsqlite）。

---

## 5. 整理书的注意事项

- 在电脑上（USB）或 SSH 里直接移动文件就行。书库会自动识别新位置，收藏夹也会自动跟着更新。
- **移动书的时候，同名的 `.sdr` 文件夹要一起移**（例如 `xxx.mobi` 和 `xxx.sdr`），里面存着阅读进度和笔记。
---

## 6. 升级固件之后

- `/etc/upstart/foldercoll.conf` 在系统分区，**升级或重刷后会被清掉**，到时在 KUAL →「Kindle Tweaks」→「文件夹收藏夹」→「开启自动同步」再装一次即可。
- 「收藏夹」视图补丁见 [03-collections-view.md](03-collections-view.md)。
- `extensions/kindletweaks/`、已有的收藏夹（存在 `/var/local`）都不受影响。
- 如果新固件的接口又改了（比如再次返回 401），按第 3 节的思路排查：
  1. 看 `/etc/upstart/system.conf` 里 token 是怎么生成的。
  2. 用 curl 测接口。
  3. 去看 LibrarianSync 的新版本。

---

## 参考

- LibrarianSync：<https://github.com/NiLuJe/librariansync>，讨论帖 <https://www.mobileread.com/forums/showthread.php?t=245691>（AuthToken 的出处）
- kindle-auto-collections：<https://github.com/poketjomon/kindle-auto-collections>（cc.db 结构说明）
- 相关文档：[01-cloud-popup.md](01-cloud-popup.md)、[03-collections-view.md](03-collections-view.md)
