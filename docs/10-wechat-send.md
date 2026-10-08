# 10 微信传书

> 效果：在微信里把 epub/pdf/mobi/azw3/txt/md/docx 以「文件」发给 ClawBot 或企业微信「微信客服」（[3.1 节](#31-换成企业微信微信客服)），Kindle 下次亮屏联网时自动取走、放进 documents；epub/md/docx 再由[功能 5](05-manga-convert.md) 转成 AZW3。取走后微信里会收到「✅ 已送达 Kindle」。

> 文中的 `download.psyventures.cn` 是作者自用的服务器，只用来说明方法可行，不对外提供服务、不保证可用。请按第 3 节用自己的 VPS 和企业微信（或 ClawBot）搭一套。

## 1 架构

```
手机微信 ──发文件──▶ ClawBot（微信官方插件）
                       │ iLink 长轮询
                       ▼
VPS: server/wxsend/wxsend.py serve（systemd，7×24 在线）
     下载 CDN 密文 → AES-128-ECB 解密 → queue/ → 回复「📚 收到《…》」
     拉取接口 127.0.0.1:8860，nginx 以 https://<域名>/kindle/ 对外，X-Token 校验
                       ▲
Kindle: upstart 任务 kindletweaks-wxsend
     默认只在亮屏（outOfScreenSaver）时拉；可选醒着时每 N 分钟再拉
     curl /list → /file/<id> → 校验大小 → mv 进 documents → POST /ack/<id>
```

为什么要 VPS 中转：iLink 收消息是长轮询，Kindle 大部分时间在屏保或深度休眠，挂不住连接；而且微信只允许**回复**（需要对方消息里的 `context_token`），不能主动推，所以只能由一个常驻服务收下，Kindle 自己来取。

## 2 iLink 协议（ClawBot 扫码绑定是怎么实现的）

来自微信官方 OpenClaw 插件 `@tencent-weixin/openclaw-weixin` 用的接口，参考实现见 [wechat-claude-code](https://github.com/Wechat-ggGitHub/wechat-claude-code) 的 `src/wechat/`。

**扫码绑定**相当于设备码登录，发起方不需要公网地址：

```
GET https://ilinkai.weixin.qq.com/ilink/bot/get_bot_qrcode?bot_type=3
  → {qrcode: <ID>, qrcode_img_content: "https://liteapp.weixin.qq.com/q/…"}   把链接做成二维码
GET …/ilink/bot/get_qrcode_status?qrcode=<ID>        长轮询，状态 wait → scaned → confirmed / expired（约 5 分钟）
  → confirmed 时返回 {bot_token, ilink_bot_id, ilink_user_id, baseurl}
```

手机扫码确认后，微信里多出一个 ClawBot 单聊。它只和扫码的人对话，不支持群。

**之后的接口**都是 POST JSON，带请求头：

```
Authorization: Bearer <bot_token>
AuthorizationType: ilink_bot_token
X-WECHAT-UIN: <随机 4 字节 base64>
```

| 接口 | 说明 |
|---|---|
| `ilink/bot/getupdates` | 长轮询收消息（约 35 秒），请求和响应里的 `get_updates_buf` 是游标；`ret=-14` 会话过期，要重新扫码 |
| `ilink/bot/sendmessage` | 回消息，必须带收到消息里的 `context_token`；`ret=-2` 是限流，退避重试 |
| `ilink/bot/getuploadurl` | 机器人往外发文件时取上传地址（传书用不到） |

消息的 `item_list[].type`：1 文本、2 图片、3 语音、4 文件、5 视频。文件条目：

```json
{"type": 4, "file_item": {"file_name": "三体.epub", "len": "123456",
  "media": {"encrypt_query_param": "…", "aes_key": "…"}}}
```

下载 `https://novac2c.cdn.weixin.qq.com/c2c/download?encrypted_query_param=…` 得到密文，用 AES-128-ECB（PKCS#7 填充）解密。`aes_key` 有两种编码：base64 解出 16 字节就是密钥；否则解出来是 32 个十六进制字符，再按 hex 转成 16 字节。单个文件上限约 100 MB。

## 3 VPS 端

需要 Python 3.8+ 和 `cryptography`（Ubuntu 自带 `python3-cryptography`），以及一个有证书的 HTTPS 站点。

```sh
mkdir -p /opt/kindle-wxsend
cp server/wxsend/wxsend.py /opt/kindle-wxsend/
cp server/wxsend/kindle-wxsend.service /etc/systemd/system/
systemctl daemon-reload

# 扫码绑定。终端里显示二维码需要 python3-qrcode；没有就把打印出的链接在电脑上做成二维码再扫
WXSEND_DATA=/var/lib/kindle-wxsend python3 /opt/kindle-wxsend/wxsend.py login

systemctl enable --now kindle-wxsend
```

拉取接口默认**不校验口令**。要开启：`/var/lib/kindle-wxsend/config.json` 写 `{"auth": true}`，`systemctl restart kindle-wxsend`，再把 `wxsend.py token` 打印的口令填进 Kindle 的 `config`。不开的话，知道地址的人都能看到、取走待取队列（书被 Kindle 取走后就从服务器删了）。

把 `server/wxsend/nginx-location.conf` 的 `location /kindle/` 加进已有 HTTPS 站点的 `server {}`，`nginx -t && systemctl reload nginx`。验证：`curl https://<域名>/kindle/health` 返回 `ok`（会话过期时返回 `expired`）。

拉取接口（开了口令校验时要带 `X-Token`，`/health` 除外；都要带 `?device=<设备码>`）：

| 请求 | 返回 |
|---|---|
| `GET /list?device=…` | 发给这台 Kindle、它还没取过的书，一行一本：`id\t字节数\t文件名`（不用 JSON，方便 busybox sh 解析）。第一次请求时登记这台设备 |
| `GET /file/<id>?device=…` | 文件内容；不是发给这台的返回 404 |
| `POST /ack/<id>?device=…` | 记下这台已取走；绑定的每台都取走后从服务器删除。10 秒内取走的书合并成一条「已送达」回复 |

微信里的命令：`状态`（自己的待取列表和各台 Kindle 上次来取的时间）、`清空`（只清自己的）；其他文字回复用法说明。图片、视频和非电子书格式的文件不收。

### 3.2 多人、多台 Kindle 和管理页

好友扫同一个客服码就能发书，不用加入企业。书按「发送者 → 他绑定的 Kindle」分发：

- 每台 Kindle 第一次同步时随机生成设备码（写进 `wxsend/config` 的 `DEVICE=`，KUAL 菜单「立即同步（本机编号 …）」里能看到），之后出现在管理页。
- 管理页 `https://<域名>/kindle/admin`，Basic Auth，用户名随意，密码是 `config.json` 的 `admin_password`。列出 Kindle（设备码、备注名、上次来取、IP）和发过消息的微信用户（昵称、头像来自 `kf/customer/batchget`）。
- 给用户勾选一台或多台 Kindle；多台时每台送一份。改绑定时会在微信里通知对方。
- 没绑定的人发来的书先存着，绑定后自动送过去。
- 可以勾选多台 Kindle 一起删除；绑定它们的用户随之解绑。删掉的 Kindle 下次来取书时会重新出现。
- 修改接口只收 `Content-Type: application/json`，别的网站没法借浏览器里的登录状态跨站提交。

管理页最上面是**同步情况**：最近 60 本书，每本显示发送者、大小、收到时间，以及每台目标 Kindle 的状态（✓ 已送达和时间 / 下载中 / 下载中断、下次同步重试 / 等待来取和它上次来的时间），整体标「同步中」「全部送达」「已删除」或「未绑定，暂存」。数据来自 `events.jsonl`（recv / fetch / ack / done / delete 事件，只追加，过长时自动截断）。

数据在 `users.json`（用户 → 设备列表）和 `devices.json`（设备码 → 备注、上次来取、那次有几本待取）。队列里每本书的 `.acked` 记录已经取走它的设备。

日志：`journalctl -u kindle-wxsend -f`。

## 3.1 换成企业微信「微信客服」

一个微信号只能连一个 OpenClaw。已经被别的 ClawBot 应用（比如 wechat-claude-code）占用时，再扫码会提示「继续连接将解除原有的连接」。这种情况改用微信客服：它是企业微信的官方 API，个人微信扫客服码进会话，像聊天一样转发文件，和 ClawBot 互不影响。限制：文件 20 MB 以内；回复要在用户发消息后 48 小时内。

```
个人微信 ──转发文件──▶ 微信客服账号
                         │ 回调 https://<域名>/kindle/wecom：只通知「有新消息」，
                         │ 消息体 AES-256-CBC 加密（key = EncodingAESKey，iv = key 前 16 字节），SHA1 验签
                         ▼
wxsend.py：kf/sync_msg 拉消息（带回调里的 Token）→ media/get 下载文件 → 队列 → kf/send_msg 回复
```

企业微信后台（企业不用认证）：

1. 「应用管理 → 自建」建一个应用，可见范围选自己，记下 **Secret**。
2. 服务端 `config.json` 写好再启动服务（`token`、`aeskey` 自己生成：32 位和 43 位字母数字；`corpid` 可以留空，第一次回调时自动记下）：
   ```json
   {"source": "kf", "kf": {"corpid": "", "secret": "<Secret>", "token": "<32 位>", "aeskey": "<43 位>"}}
   ```
3. 应用 →「接收消息 → 设置 API 接收」：URL `https://<域名>/kindle/wecom`，Token、EncodingAESKey 和上面一致。保存时企业微信会立刻 GET 校验，服务必须已经在跑，否则报「openapi 回调地址请求不通过」（nginx 日志里是 502）。
4. 应用 →「企业可信 IP」填 VPS 的公网 IP，否则调接口报 60020。
5. 「微信客服」建一个客服账号；「微信客服 → API」里把可调用接口的应用设为这个自建应用，并把账号交给它管理（`kf/account/list` 里 `manage_privilege` 变成 `true`）。
6. 用 `kf/add_contact_way` 生成客服链接，个人微信打开即进会话。

## 4 Kindle 端

```sh
cd /mnt/us/extensions/kindletweaks/wxsend
cp config.example config      # 填 URL；服务器开了口令校验才填 TOKEN
sh ../tweak.sh wxsend now     # 先手动同步一次试试
sh ../tweak.sh wxsend on      # 安装 upstart 任务
```

或者 KUAL →「Kindle Tweaks」→「微信传书」。菜单第一行显示上次同步的结果。

- 第一次同步时生成本机设备码，追加到 `config` 的 `DEVICE=`；之后在管理页把微信用户绑到它。
- 下载先写到 `/mnt/us/.wxsend-part/`，校验字节数后再 `mv` 进 documents（同一分区，原子操作），书库扫描器和 mangaconv 不会看到半截文件。新书由系统扫描器自动收录，不用额外操作。
- 重名不覆盖，改名为「书名 (2).epub」。
- `config` 里的 `DIR` 可以改成 `/mnt/us/documents/微信传书`；再开启[文件夹收藏夹](02-folder-collections.md)，就会自动归进同名收藏夹。
- 系统自带的 CA 证书偏旧，有 `/mnt/us/python3/…/certifi/cacert.pem` 时 curl 用它验证证书。
- **同步时机**看 `config` 的 `INTERVAL`（任务每轮重读，改了不用重启）：
  - `INTERVAL=0`（默认）：只在亮屏（出屏保）时同步一次。最省电；想马上收书就按一下电源键、或点 KUAL「立即同步」。
  - `INTERVAL=N`：亮屏时同步，醒着时再每 N 分钟同步一次，适合一直开着屏看书时也想收新书。
- 屏保和休眠期间任务阻塞在 `lipc-wait-event … outOfScreenSaver`，不唤醒 CPU。刚唤醒时 Wi-Fi 还在重连，连不上服务器会每 10 秒重试，最多 1 分钟。

## 5 注意

- iLink 是微信给 OpenClaw 用的接口，这里属于自用的非官方客户端，接口可能变。
- 每次 `login` 都是新绑定；旧的 `bot_token` 是否随之失效未验证。会话过期（`ret=-14`）时服务日志会提示，重新 `login` 后 `systemctl restart kindle-wxsend`。
- 换口令：删掉 `/var/lib/kindle-wxsend/kindle_token`，重启服务，再改 Kindle 上的 `config`。
- 微信 CDN 上的文件本身是 AES 加密的，解密是协议的一部分，和上面的口令开关无关。
