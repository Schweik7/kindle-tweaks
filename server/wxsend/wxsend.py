#!/usr/bin/env python3
"""微信传书：VPS 端服务。

在微信里给 ClawBot 发书（文件消息），这里收下、解密，放进待取队列；
Kindle 醒来时通过 HTTP 接口拉走，拉走后在微信里回一句「已送达」。

协议是微信 ClawBot 插件用的 iLink（https://ilinkai.weixin.qq.com），HTTP/JSON：
  扫码绑定  GET  ilink/bot/get_bot_qrcode?bot_type=3 → get_qrcode_status 轮询到 confirmed，拿到 bot_token
  收消息    POST ilink/bot/getupdates   长轮询，get_updates_buf 是游标
  回消息    POST ilink/bot/sendmessage  必须带对方消息里的 context_token（只能回复，不能主动推）
  文件      novac2c.cdn.weixin.qq.com/c2c/download?encrypted_query_param=… 下载密文，AES-128-ECB 解密

用法：
  wxsend.py login     打印二维码，用微信扫码绑定（会话过期 ret=-14 时重新执行）
  wxsend.py serve     收书 + 给 Kindle 的拉取接口（systemd 跑这个）
  wxsend.py token     打印 Kindle 用的拉取口令（没有就生成；config.json 里 auth 为 true 才校验）
  wxsend.py status    队列和绑定状态

数据目录 $WXSEND_DATA（默认 /var/lib/kindle-wxsend）：
  config.json   改后重启服务：
                  "auth": false            拉取接口是否校验口令，默认不校验
                  "source": "ilink"|"kf"   消息来源：ClawBot（默认）或企业微信「微信客服」
                  "kf": {"corpid", "secret", "token", "aeskey"}   微信客服用：企业 ID、自建应用 Secret、
                                           接收消息的 Token 和 EncodingAESKey
                  "admin_password": "…"    管理页 /admin 的密码（Basic Auth，用户名随意）；不设则管理页不可用
  users.json    微信用户 → 绑定的 Kindle；devices.json  来取过书的 Kindle（设备码、备注、上次来取）
  account.json  bot_token 等（只给 root 读）
  kindle_token  Kindle 拉取口令
  sync_buf      getupdates 游标
  peers.json    每个联系人最近的 context_token，用来回「已送达」
  queue/<id>/<文件名>  待取的书
"""
import base64
import hashlib
import http.server
import json
import logging
import os
import re
import secrets
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

BASE_URL = "https://ilinkai.weixin.qq.com"
CDN_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
DATA = os.environ.get("WXSEND_DATA", "/var/lib/kindle-wxsend")
QUEUE = os.path.join(DATA, "queue")
LISTEN = os.environ.get("WXSEND_LISTEN", "127.0.0.1:8860")

# Kindle 能读或 kindle-tweaks 能转换的格式；其他文件（图片、压缩包……）不收
BOOK_EXT = {".epub", ".azw3", ".azw", ".mobi", ".prc", ".kfx", ".pdf", ".txt",
            ".md", ".markdown", ".docx"}
MAX_SIZE = 200 * 1024 * 1024
SESSION_EXPIRED = -14

# 消息条目类型（item_list[].type）
TEXT, IMAGE, VOICE, FILE, VIDEO = 1, 2, 3, 4, 5

log = logging.getLogger("wxsend")
lock = threading.Lock()
state = {"expired": False}


def path(name):
    return os.path.join(DATA, name)


def load(name, default):
    try:
        with open(path(name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(name, obj, mode=0o600):
    tmp = path(name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path(name))


# ── iLink ────────────────────────────────────────────────────────────────


def http_json(url, body=None, token=None, timeout=15):
    headers = {"Content-Type": "application/json"}
    if token:
        headers.update({
            "Authorization": "Bearer " + token,
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": base64.b64encode(secrets.token_bytes(4)).decode(),
        })
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="GET" if body is None else "POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


class Bot:
    def __init__(self, account):
        self.token = account["bot_token"]
        self.bot_id = account["bot_id"]
        self.owner = account["user_id"]
        self.base = account.get("base_url") or BASE_URL
        # 回复只能发往 *.weixin.qq.com，防止被篡改的 baseurl 把 token 带走
        host = urllib.parse.urlparse(self.base).hostname or ""
        if not self.base.startswith("https://") or not host.endswith(".weixin.qq.com"):
            self.base = BASE_URL

    def call(self, api, body, timeout=15):
        return http_json(f"{self.base}/ilink/bot/{api}", body, self.token, timeout)

    def get_updates(self, buf):
        return self.call("getupdates", {"get_updates_buf": buf} if buf else {}, timeout=45)

    def reply(self, to, ctx, text):
        msg = {
            "from_user_id": self.bot_id, "to_user_id": to,
            "client_id": f"wxsend-{int(time.time() * 1000)}-{secrets.token_hex(3)}",
            "message_type": 2, "message_state": 2, "context_token": ctx,
            "item_list": [{"type": TEXT, "text_item": {"text": text}}],
        }
        for delay in (0, 3, 6, 12):
            time.sleep(delay)
            try:
                r = self.call("sendmessage", {"msg": msg})
            except (OSError, ValueError) as e:
                log.warning("回复失败：%s", e)
                continue
            if r.get("ret") == -2:          # 发得太快，被限流
                continue
            if r.get("ret") not in (None, 0):
                log.warning("回复被拒：%s", r)
                return False
            return True
        return False

    def reply_to(self, sender, text):
        ctx = load("peers.json", {}).get(sender)
        return bool(ctx) and self.reply(sender, ctx, text)


def aes_key(b64):
    """aes_key 有两种编码：base64(16 字节密钥)，或 base64(32 个十六进制字符)。"""
    raw = base64.b64decode(b64)
    key = raw if len(raw) == 16 else bytes.fromhex(raw.decode())
    if len(key) != 16:
        raise ValueError(f"AES 密钥长度 {len(key)}")
    return key


def download(media):
    q = media["encrypt_query_param"]
    url = f"{CDN_URL}/download?encrypted_query_param={urllib.parse.quote(q, safe='')}"
    with urllib.request.urlopen(url, timeout=300) as r:
        enc = r.read(MAX_SIZE + 16 + 1)
    if not enc or len(enc) % 16 or len(enc) > MAX_SIZE + 16:
        raise ValueError(f"CDN 数据长度不对：{len(enc)}")
    dec = Cipher(algorithms.AES(aes_key(media["aes_key"])), modes.ECB()).decryptor()
    plain = dec.update(enc) + dec.finalize()
    unpad = padding.PKCS7(128).unpadder()
    return unpad.update(plain) + unpad.finalize()


def file_media(item):
    fi = item.get("file_item") or {}
    for m in (fi.get("media"), fi.get("cdn_media")):
        if m and m.get("encrypt_query_param") and m.get("aes_key"):
            return fi.get("file_name") or "", m
    return fi.get("file_name") or "", None


# ── 队列 ──────────────────────────────────────────────────────────────────


def clean_name(name):
    name = os.path.basename(name.replace("\\", "/"))
    name = re.sub(r'[\x00-\x1f"*:<>?|\t]', "_", name).strip().lstrip(".")
    stem, ext = os.path.splitext(name)
    # 文件系统按字节限长，留余量给 Kindle 端重名时加的「 (2)」
    while len((stem + ext).encode()) > 180:
        stem = stem[:-1]
    return (stem or "book") + ext.lower()


def enqueue(name, data, sender):
    item = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(4)
    d = os.path.join(QUEUE, item)
    os.makedirs(d)
    with open(os.path.join(d, name + ".part"), "wb") as f:
        f.write(data)
    os.replace(os.path.join(d, name + ".part"), os.path.join(d, name))
    with open(os.path.join(d, ".from"), "w") as f:
        f.write(sender)
    return item


def queue_items():
    """[(id, 文件名, 大小, 发送者)]，按时间排序；还在写入的跳过。"""
    out = []
    for item in sorted(os.listdir(QUEUE)) if os.path.isdir(QUEUE) else []:
        d = os.path.join(QUEUE, item)
        names = [n for n in os.listdir(d) if not n.startswith(".") and not n.endswith(".part")]
        if len(names) != 1:
            continue
        try:
            sender = open(os.path.join(d, ".from")).read().strip()
        except OSError:
            sender = ""
        out.append((item, names[0], os.path.getsize(os.path.join(d, names[0])), sender))
    return out


# ── 用户和设备 ────────────────────────────────────────────────────────────
#
# users.json    {发送者 ID: {name, avatar, device, first, last}}   发送者 = 微信客服的 external_userid / iLink 用户 ID
# devices.json  {设备码: {label, seen, ip}}                         Kindle 拉取时带 ?device=<设备码>，第一次来就登记
# 书按「发送者 → 他绑定的设备」分发；没绑定的先留在队列里，在管理页绑定后自动转给那台 Kindle。

DEVICE_RE = re.compile(r"[A-Za-z0-9]{6,32}")


def touch_user(uid, **info):
    with lock:
        users = load("users.json", {})
        u = users.setdefault(uid, {"name": "", "avatar": "", "devices": [], "first": time.time()})
        u.update({k: v for k, v in info.items() if v})
        u["last"] = time.time()
        save("users.json", users)
        return u


def user_devices(uid, users=None):
    """一个用户可以绑定多台 Kindle，他的书每台都送一份。"""
    return (users if users is not None else load("users.json", {})).get(uid, {}).get("devices", [])


def acked(item):
    """已经取走这本书的设备。"""
    try:
        return open(os.path.join(QUEUE, item, ".acked")).read().split()
    except OSError:
        return []


def items_for(device):
    users = load("users.json", {})
    return [it for it in queue_items()
            if device in user_devices(it[3], users) and device not in acked(it[0])]


def seen_device(code, ip, offered=0):
    with lock:
        devs = load("devices.json", {})
        d = devs.setdefault(code, {"label": "", "seen": 0, "ip": ""})
        d.update(seen=time.time(), ip=ip, offered=offered)   # offered：这次同步有几本待取
        save("devices.json", devs)


def event(ev, item, **kw):
    """同步记录（events.jsonl）：recv 收到 / fetch 开始下载 / ack 某台取走 / done 全部送达 / delete 删除。
    只追加；超过 4000 行时保留最近 2000 行。"""
    p = path("events.jsonl")
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.time(), "ev": ev, "id": item, **kw}, ensure_ascii=False) + "\n")
    try:
        if os.path.getsize(p) > 1 << 20:
            lines = open(p, encoding="utf-8").readlines()
            if len(lines) > 4000:
                with open(p + ".tmp", "w", encoding="utf-8") as f:
                    f.writelines(lines[-2000:])
                os.replace(p + ".tmp", p)
    except OSError:
        pass


def history(limit=60):
    """按书汇总最近的同步记录，新的在前。"""
    books = {}
    try:
        lines = open(path("events.jsonl"), encoding="utf-8").readlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        b = books.setdefault(e["id"], {"id": e["id"], "fetch": {}, "ack": {}})
        if e["ev"] == "recv":
            b.update(name=e.get("name"), size=e.get("size"), sender=e.get("sender"), recv=e["t"])
        elif e["ev"] in ("fetch", "ack"):
            b[e["ev"]][e.get("device", "")] = e["t"]
        elif e["ev"] in ("done", "delete"):
            b[e["ev"]] = e["t"]
    out = [b for b in books.values() if b.get("recv")]
    out.sort(key=lambda b: -b["recv"])
    return out[:limit]


def mb(n):
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{max(n // 1024, 1)} KB"


def ago(t):
    if not t:
        return "还没来取过"
    s = int(time.time() - t)
    if s < 120:
        return "刚刚"
    if s < 7200:
        return f"{s // 60} 分钟前"
    if s < 172800:
        return f"{s // 3600} 小时前"
    return f"{s // 86400} 天前"


# ── 收消息 ────────────────────────────────────────────────────────────────

HELP = ("把书以「文件」发给我，Kindle 下次亮屏联网时自动取走，放进 documents。\n"
        f"支持：{' '.join(sorted(e[1:] for e in BOOK_EXT))}；epub/md/docx 会在 Kindle 上自动转成 AZW3。\n"
        "命令：状态 / 清空")


def receive_file(name, fetch, sender):
    """下载一本书放进队列，返回给用户的一行回复。fetch() 返回 (文件名, 内容)，文件名可为空。"""
    if name and os.path.splitext(clean_name(name))[1] not in BOOK_EXT:
        return f"《{clean_name(name)}》不是电子书格式，没收。"
    try:
        real, data = fetch()
    except (OSError, ValueError) as e:
        log.warning("下载 %s 失败：%s", name, e)
        return f"《{name or '文件'}》下载失败（{e}），请重发一次。"
    name = clean_name(name or real or "")
    if os.path.splitext(name)[1] not in BOOK_EXT:
        return f"《{name}》不是电子书格式，没收。"
    with lock:
        item_id = enqueue(name, data, sender)
        event("recv", item_id, name=name, size=len(data), sender=sender)
    log.info("收到 %s（%s）-> %s", name, mb(len(data)), item_id)
    return f"📚 收到《{name}》（{mb(len(data))}）"


def where(sender):
    """发送者的书现在会送到哪：一句给用户看的说明。"""
    mine = user_devices(sender)
    if not mine:
        return "你还没绑定 Kindle，书先存着；管理员在后台把你绑定到 Kindle 后会自动送过去。"
    devs = load("devices.json", {})
    n = sum(1 for it in queue_items() if it[3] == sender)
    seen = "，".join(f"「{devs.get(d, {}).get('label') or d}」{ago(devs.get(d, {}).get('seen'))}" for d in mine)
    return f"Kindle 下次亮屏联网时自动取走（你待取 {n} 本；上次来取：{seen}）。"


def finish(lines, sender):
    if any(x.startswith("📚") for x in lines):
        lines.append(where(sender))
    return "\n".join(lines)


def handle(bot, msg):
    if msg.get("message_type") != 1:      # 只处理用户发来的
        return
    sender = msg.get("from_user_id") or ""
    ctx = msg.get("context_token") or ""
    if not sender or not ctx:
        return
    peers = load("peers.json", {})
    peers[sender] = ctx
    save("peers.json", peers)
    touch_user(sender)

    lines = []
    for item in msg.get("item_list") or []:
        t = item.get("type")
        if t == FILE:
            name, media = file_media(item)
            if not media:
                lines.append(f"《{name}》拿不到下载地址，请重发一次。")
                continue
            lines.append(receive_file(name, lambda m=media: ("", download(m)), sender))
        elif t == TEXT:
            text = ((item.get("text_item") or {}).get("text") or "").strip()
            lines.append(command(text, sender))
        elif t in (IMAGE, VIDEO, VOICE):
            lines.append("这里只收电子书文件。\n" + HELP)
    if lines:
        bot.reply(sender, ctx, finish(lines, sender))


def command(text, sender):
    """只看、只清发送者自己的书。"""
    mine = [it for it in queue_items() if it[3] == sender]
    if text in ("状态", "列表", "status"):
        return "\n".join([where(sender)] + [f"· {n}（{mb(s)}）" for _, n, s, _ in mine])
    if text in ("清空", "clear"):
        with lock:
            for it in mine:
                shutil.rmtree(os.path.join(QUEUE, it[0]), ignore_errors=True)
                event("delete", it[0])
        return f"已清空你的待取队列（{len(mine)} 本）。"
    return HELP


def poll_loop(bot):
    buf = load("sync_buf", "")
    seen = []
    fails = 0
    while True:
        try:
            r = bot.get_updates(buf)
        except (OSError, ValueError) as e:
            fails += 1
            log.warning("getupdates 出错（%d）：%s", fails, e)
            time.sleep(min(300, 3 * 2 ** min(fails, 7)))
            continue
        ret = r.get("ret")
        if ret == SESSION_EXPIRED:
            state["expired"] = True
            log.error("会话过期，请运行 wxsend.py login 重新扫码，然后重启服务")
            time.sleep(600)
            continue
        if ret not in (None, 0):
            fails += 1
            log.warning("getupdates ret=%s %s", ret, r.get("retmsg", ""))
            time.sleep(min(300, 3 * 2 ** min(fails, 7)))
            continue
        fails = 0
        state["expired"] = False
        if r.get("get_updates_buf"):
            buf = r["get_updates_buf"]
            save("sync_buf", buf)
        for msg in r.get("msgs") or []:
            mid = msg.get("message_id")
            if mid:
                if mid in seen:
                    continue
                seen = (seen + [mid])[-500:]
            try:
                handle(bot, msg)
            except Exception:
                log.exception("处理消息出错")


# ── 企业微信「微信客服」 ──────────────────────────────────────────────────
#
# 个人微信扫客服二维码进会话，转发文件。企业微信把「有新消息」回调到
# https://<域名>/kindle/wecom（消息体用 EncodingAESKey 做 AES-256-CBC 加密，SHA1 验签），
# 收到后用回调里的 Token 调 kf/sync_msg 拉消息，文件用 media/get 下载，回复走 kf/send_msg。

QYAPI = "https://qyapi.weixin.qq.com/cgi-bin"


class WecomCrypt:
    """企业微信回调消息的验签和解密（官方 WXBizMsgCrypt 的必要部分）。"""

    def __init__(self, token, aeskey, corpid):
        self.token = token
        self.key = base64.b64decode(aeskey + "=")
        self.corpid = corpid
        if len(self.key) != 32:
            raise ValueError("EncodingAESKey 应为 43 个字符")

    def check(self, signature, timestamp, nonce, encrypt):
        s = hashlib.sha1("".join(sorted([self.token, timestamp, nonce, encrypt])).encode()).hexdigest()
        return secrets.compare_digest(s, signature or "")

    def decrypt(self, encrypt):
        dec = Cipher(algorithms.AES(self.key), modes.CBC(self.key[:16])).decryptor()
        plain = dec.update(base64.b64decode(encrypt)) + dec.finalize()
        plain = plain[:-plain[-1]]                      # PKCS#7，块大小 32
        n = int.from_bytes(plain[16:20], "big")         # 16 字节随机数 + 4 字节长度 + 消息 + corpid
        msg, corpid = plain[20:20 + n], plain[20 + n:].decode()
        if not self.corpid:
            # 还没配企业 ID：签名已经用 Token 验过，从第一次回调里记下来
            self.corpid = corpid
            conf = load("config.json", {})
            conf.setdefault("kf", {})["corpid"] = corpid
            save("config.json", conf)
            log.info("记下企业 ID：%s", corpid)
        if corpid != self.corpid:
            raise ValueError(f"corpid 不符：{corpid}")
        return msg.decode()


def xml_field(xml, tag):
    m = re.search(rf"<{tag}>(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))</{tag}>", xml, re.S)
    return (m.group(1) if m.group(1) is not None else m.group(2)) if m else ""


class WecomKf:
    def __init__(self, conf):
        self.secret = conf.get("secret", "")
        self.crypt = WecomCrypt(conf["token"], conf["aeskey"], conf.get("corpid", ""))
        self.access = ("", 0)
        self.sync_lock = threading.Lock()
        self.started = time.time()

    def access_token(self, refresh=False):
        tok, exp = self.access
        if refresh or time.time() > exp - 300:
            r = http_json(f"{QYAPI}/gettoken?corpid={self.crypt.corpid}&corpsecret={self.secret}")
            if r.get("errcode"):
                raise ValueError(f"gettoken：{r}")
            self.access = (r["access_token"], time.time() + r.get("expires_in", 7200))
        return self.access[0]

    def api(self, path, body):
        for refresh in (False, True):
            r = http_json(f"{QYAPI}/{path}?access_token={self.access_token(refresh)}", body)
            if r.get("errcode") not in (40014, 42001):  # access_token 失效就换一个重试
                break
        if r.get("errcode"):
            log.warning("%s 出错：%s", path, r)
        return r

    def media(self, media_id):
        url = f"{QYAPI}/media/get?access_token={self.access_token()}&media_id={urllib.parse.quote(media_id)}"
        with urllib.request.urlopen(url, timeout=300) as r:
            if "json" in r.headers.get("Content-Type", ""):
                raise ValueError(f"media/get：{r.read(300).decode(errors='replace')}")
            data = r.read(MAX_SIZE + 1)
            cd = r.headers.get("Content-Disposition", "")
        if len(data) > MAX_SIZE:
            raise ValueError("文件太大")
        m = re.search(r"filename\*=(?:UTF-8|utf-8)''([^;]+)", cd) or re.search(r'filename="?([^";]+)"?', cd)
        # 企业微信按表单编码文件名：空格是「+」，真正的加号是 %2B
        name = urllib.parse.unquote_plus(m.group(1)) if m else ""
        try:                                            # 有的版本把 UTF-8 文件名按 latin-1 塞进头里
            name = name.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        return name, data

    def send(self, user, kfid, text):
        r = self.api("kf/send_msg", {"touser": user, "open_kfid": kfid, "msgtype": "text", "text": {"content": text}})
        return not r.get("errcode")

    def reply_to(self, sender, text):
        kfid = load("kf_peers.json", {}).get(sender)
        return bool(kfid) and self.send(sender, kfid, text)

    def on_event(self, xml):
        """回调只通知「有新消息」，真正的消息用 sync_msg 拉。"""
        if xml_field(xml, "Event") != "kf_msg_or_event":
            return
        threading.Thread(target=self.sync, args=(xml_field(xml, "Token"), xml_field(xml, "OpenKfId")),
                         daemon=True).start()

    def sync(self, event_token, kfid):
        try:
            self._sync(event_token, kfid)
        except (OSError, ValueError) as e:
            log.warning("拉取客服消息失败：%s", e)

    def _sync(self, event_token, kfid):
        with self.sync_lock:
            cursor = load("kf_cursor", "")
            seen = load("kf_seen.json", [])
            while True:
                r = self.api("kf/sync_msg", {"cursor": cursor, "token": event_token, "limit": 1000, "open_kfid": kfid})
                if r.get("errcode"):
                    return
                for m in r.get("msg_list") or []:
                    if m.get("msgid") in seen:
                        continue
                    seen = (seen + [m.get("msgid")])[-1000:]
                    save("kf_seen.json", seen)
                    try:
                        self.handle(m)
                    except Exception:
                        log.exception("处理客服消息出错")
                cursor = r.get("next_cursor") or cursor
                save("kf_cursor", cursor)
                if not r.get("has_more"):
                    return

    def handle(self, m):
        kfid = m.get("open_kfid", "")
        if m.get("msgtype") == "event":
            ev = m.get("event") or {}
            # 用户进入会话：用 welcome_code 发一条用法说明
            if ev.get("event_type") == "enter_session" and ev.get("welcome_code"):
                self.api("kf/send_msg_on_event", {"code": ev["welcome_code"], "msgtype": "text", "text": {"content": HELP}})
            return
        # origin 3 = 客户发的；第一次拉到的游标前 3 天历史不处理
        if m.get("origin") != 3 or m.get("send_time", 0) < self.started - 60:
            return
        user = m.get("external_userid", "")
        peers = load("kf_peers.json", {})
        peers[user] = kfid
        save("kf_peers.json", peers)
        if not touch_user(user).get("name"):
            touch_user(user, **self.profile(user))
        t = m.get("msgtype")
        if t == "file":
            line = receive_file("", lambda: self.media(m["file"]["media_id"]), user)
        elif t == "text":
            line = command((m.get("text") or {}).get("content", "").strip(), user)
        else:
            line = "这里只收电子书文件（单个 20 MB 以内）。\n" + HELP
        self.send(user, kfid, finish([line], user))

    def contact_link(self):
        """客服链接（微信里点开就进会话），第一次生成后存进 config.json，之后一直用这个。"""
        conf = load("config.json", {})
        link = conf.get("kf", {}).get("link")
        if link:
            return link
        accounts = self.api("kf/account/list", {"offset": 0, "limit": 100}).get("account_list") or []
        for a in accounts:
            if a.get("manage_privilege"):
                link = self.api("kf/add_contact_way", {"open_kfid": a["open_kfid"], "scene": "kindle"}).get("url")
                if link:
                    conf.setdefault("kf", {})["link"] = link
                    save("config.json", conf)
                    return link
        return ""

    def profile(self, user):
        """昵称和头像，给管理页看（只能查 48 小时内发过消息的客户）。"""
        r = self.api("kf/customer/batchget", {"external_userid_list": [user], "need_enter_session_context": 0})
        for c in r.get("customer_list") or []:
            return {"name": c.get("nickname", ""), "avatar": (c.get("avatar") or "").replace("http://", "https://", 1)}
        return {}


# ── Kindle 拉取接口 ───────────────────────────────────────────────────────


ADMIN_HTML = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>微信传书</title>
<style>
:root{--bg:#f6f5f2;--card:#fff;--fg:#1d1d1f;--mute:#6b6b70;--line:#e4e2dd;--acc:#2f6f4f;--warn:#b4532a}
@media (prefers-color-scheme:dark){:root{--bg:#161616;--card:#202020;--fg:#ececec;--mute:#9a9a9f;--line:#333;--acc:#6fbf94;--warn:#e08a5f}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
main{max-width:860px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--mute);margin:0 0 24px;font-size:13px}
h2{font-size:15px;margin:28px 0 10px;color:var(--mute);font-weight:600}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-bottom:10px}
.row{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
label{display:inline-flex;gap:4px;align-items:center;font-size:14px;cursor:pointer}
.grow{flex:1;min-width:160px}
img.av{width:40px;height:40px;border-radius:8px;object-fit:cover;background:var(--line)}
.name{font-weight:600}
.meta{color:var(--mute);font-size:12px}
code{font:13px ui-monospace,Consolas,monospace;background:var(--bg);padding:1px 6px;border-radius:4px}
select,input{font:inherit;color:inherit;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:6px 8px}
button{font:inherit;font-size:13px;border:0;background:none;color:var(--warn);cursor:pointer;padding:4px}
ul{margin:8px 0 0 52px;padding:0;list-style:none}
li{display:flex;justify-content:space-between;gap:8px;font-size:13px;padding:3px 0;border-top:1px dashed var(--line)}
.unbound{color:var(--warn);font-size:12px}
.empty{color:var(--mute);font-size:13px}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
.chip{font-size:12px;border-radius:999px;padding:2px 10px;border:1px solid var(--line);color:var(--mute)}
.chip.ok{color:var(--acc);border-color:var(--acc)}
.chip.run{color:var(--fg);border-style:dashed}
.chip.bad{color:var(--warn);border-color:var(--warn)}
.tag{font-size:12px;margin-left:6px}
.tag.ok{color:var(--acc)} .tag.bad{color:var(--warn)} .tag.run{color:var(--mute)}
</style></head><body><main>
<h1>微信传书</h1>
<p class="sub">给每个微信用户勾选他的 Kindle（可多台），他发的书每台送一份，都取走后从服务器删除。没绑定的人发来的书先存着，绑定后自动送过去。<br>
邀请朋友：把 <a href="join" target="_blank">客服二维码页</a> 发给他们。</p>
<h2>同步情况 <span class="meta" id="refreshed"></span></h2><div id="books"></div>
<h2>Kindle</h2><div id="devices"></div>
<h2>微信用户</h2><div id="users"></div>
</main>
<script>
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function ago(t, now) {
  if (!t) return "从未";
  const s = now - t;
  if (s < 120) return "刚刚";
  if (s < 7200) return Math.floor(s / 60) + " 分钟前";
  if (s < 172800) return Math.floor(s / 3600) + " 小时前";
  return Math.floor(s / 86400) + " 天前";
}
async function post(action, body) {
  const r = await fetch("admin/" + action, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  if (!r.ok) alert("操作失败：" + r.status);
  load();
}
async function load() {
  const s = await (await fetch("admin/state")).json();
  const name = code => { const d = s.devices.find(x => x.code === code); return esc(d && d.label || code); };
  const clock = t => { const d = new Date(t * 1000), n = new Date(s.now * 1000);
    const hm = d.toTimeString().slice(0, 5);
    return d.toDateString() === n.toDateString() ? hm : `${d.getMonth() + 1}-${d.getDate()} ${hm}`; };
  // 每台目标 Kindle 一个状态：已送达 / 下载中（或中断，等下次重试）/ 等待来取
  const chip = (b, code) => {
    const dev = s.devices.find(x => x.code === code) || {};
    if (b.ack[code]) return `<span class="chip ok">✓ ${name(code)} ${clock(b.ack[code])}</span>`;
    if (b.delete) return `<span class="chip">${name(code)} 未取</span>`;
    if (b.fetch[code]) return s.now - b.fetch[code] < 900
      ? `<span class="chip run">⇣ ${name(code)} 下载中</span>`
      : `<span class="chip bad">${name(code)} 下载中断，下次同步重试</span>`;
    return `<span class="chip run">${name(code)} 等待来取 · 上次来 ${ago(dev.seen, s.now)}</span>`;
  };
  $("#refreshed").textContent = "· " + clock(s.now) + " 更新，每 30 秒刷新";
  $("#books").innerHTML = s.books.length ? s.books.map(b => {
    const tag = b.done ? `<span class="tag ok">全部送达</span>` : b.delete ? `<span class="tag bad">已删除</span>`
      : b.targets.length ? `<span class="tag run">同步中</span>` : `<span class="tag bad">未绑定，暂存</span>`;
    return `<div class="card">
      <div><span class="name">${esc(b.name)}</span>${tag}</div>
      <div class="meta">${esc(b.who || "（未知）")} · ${b.size} · ${clock(b.recv)} 收到${b.done ? " · " + clock(b.done) + " 送完" : ""}</div>
      <div class="chips">${b.targets.map(c => chip(b, c)).join("")}</div>
    </div>`; }).join("") : `<p class="empty">还没有同步记录。</p>`;
  $("#devices").innerHTML = s.devices.length ? s.devices.map(d => `
    <div class="card row">
      <input type="checkbox" class="pick" value="${esc(d.code)}">
      <div class="grow"><code>${esc(d.code)}</code> <span class="meta">上次来取 ${ago(d.seen, s.now)}（${d.offered ? "有 " + d.offered + " 本待取" : "没有新书"}） · ${esc(d.ip)}</span></div>
      <input value="${esc(d.label)}" placeholder="备注名，比如 我的 Oasis" data-dev="${esc(d.code)}" class="lbl">
    </div>`).join("") + `<div class="row" style="justify-content:flex-end"><button id="forget">删除所选 Kindle</button></div>`
    : `<p class="empty">还没有 Kindle 来取过书。Kindle 开启「微信传书」并联网同步一次后会出现在这里。</p>`;
  $("#users").innerHTML = s.users.length ? s.users.map(u => `
    <div class="card">
      <div class="row">
        ${u.avatar ? `<img class="av" src="${esc(u.avatar)}" referrerpolicy="no-referrer" alt="">` : `<div class="av"></div>`}
        <div class="grow"><div class="name">${esc(u.name || "（未知昵称）")}</div>
          <div class="meta">最近 ${ago(u.last, s.now)} · ${esc(u.id.slice(0, 10))}…</div></div>
      </div>
      <div class="row bind" data-user="${esc(u.id)}" style="margin:8px 0 0 52px">
        ${s.devices.length ? s.devices.map(d => `<label><input type="checkbox" value="${esc(d.code)}" ${(u.devices || []).includes(d.code) ? "checked" : ""}> ${name(d.code)}</label>`).join("")
          : `<span class="meta">还没有 Kindle 可绑定</span>`}
      </div>
      ${(u.devices || []).length ? "" : `<div class="unbound" style="margin:6px 0 0 52px">未绑定：发来的书暂存在服务器</div>`}
      ${u.pending.length ? `<ul>${u.pending.map(p => `<li><span>${esc(p.name)} <span class="meta">${p.size}${p.acked.length ? " · 已送达 " + p.acked.map(name).join("、") : ""}</span></span><button data-del="${esc(p.id)}">删除</button></li>`).join("")}</ul>` : ""}
    </div>`).join("") : `<p class="empty">还没有人发过消息。</p>`;
}
document.addEventListener("change", e => {
  const box = e.target.closest(".bind");
  if (box) post("bind", {user: box.dataset.user, devices: [...box.querySelectorAll("input:checked")].map(i => i.value)});
  if (e.target.classList.contains("lbl")) post("label", {device: e.target.dataset.dev, label: e.target.value});
});
document.addEventListener("click", e => {
  if (e.target.id === "forget") {
    const codes = [...document.querySelectorAll(".pick:checked")].map(i => i.value);
    if (!codes.length) return alert("先勾选要删除的 Kindle");
    if (confirm(`删除 ${codes.length} 台 Kindle？绑定它们的用户会解绑。Kindle 下次来取书时会重新出现。`)) post("forget", {devices: codes});
  }
  if (e.target.dataset.del && confirm("删除这本待取的书？")) post("delete", {id: e.target.dataset.del});
});
load();
setInterval(load, 30000);
</script></body></html>
"""


JOIN_HTML = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>微信传书</title>
<style>
:root{--bg:#f6f5f2;--card:#fff;--fg:#1d1d1f;--mute:#6b6b70;--line:#e4e2dd;--acc:#2f6f4f}
@media (prefers-color-scheme:dark){:root{--bg:#161616;--card:#202020;--fg:#ececec;--mute:#9a9a9f;--line:#333;--acc:#6fbf94}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
main{max-width:520px;margin:0 auto;padding:32px 16px 48px;text-align:center}
h1{font-size:24px;margin:0 0 6px}
.sub{color:var(--mute);margin:0 0 24px}
#qr{display:inline-block;background:#fff;padding:14px;border-radius:12px;border:1px solid var(--line)}
a.btn{display:inline-block;margin:20px 0 4px;padding:10px 22px;border-radius:999px;background:var(--acc);color:#fff;text-decoration:none;font-weight:600}
ol{text-align:left;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 16px 16px 36px;margin-top:28px}
li{margin:6px 0}
.mute{color:var(--mute);font-size:13px}
</style></head><body><main>
<h1>📚 微信传书</h1>
<p class="sub">在微信里把电子书发给客服，Kindle 亮屏联网时自动收到。</p>
<div id="qr"></div><br>
<a class="btn" href="__LINK__">在微信里打开</a>
<p class="mute">手机上直接点按钮；电脑上用微信扫二维码。</p>
<ol>
<li>进入客服会话，把书以「文件」转发过去（单本 20 MB 以内，支持 epub、pdf、mobi、azw3、txt、md、docx）。</li>
<li>Kindle 要越狱并装好 kindle-tweaks，在 KUAL →「Kindle Tweaks」→「微信传书」里开启，再点一次「立即同步」，记下菜单里显示的「本机编号」。</li>
<li>把本机编号告诉管理员，绑定好之后，你发的书就会送到你的 Kindle，送达后微信里会有通知。</li>
</ol>
</main>
<script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>
<script>new QRCode(document.getElementById("qr"), {text: "__LINK__", width: 220, height: 220, correctLevel: QRCode.CorrectLevel.M});</script>
</body></html>
"""


def notify_delivered(channel, batch):
    """batch：{发送者: {设备码: [书名]}}，每个发送者合成一条消息。"""
    devs = load("devices.json", {})
    for sender, by_dev in batch.items():
        lines = [f"✅ 已送达 Kindle「{devs.get(d, {}).get('label') or d}」：" + "、".join(f"《{n}》" for n in names)
                 for d, names in by_dev.items()]
        channel.reply_to(sender, "\n".join(lines))


class Handler(http.server.BaseHTTPRequestHandler):
    bot = None              # 消息来源：Bot（iLink）或 WecomKf，都有 reply_to
    token = ""
    delivered = {}          # 本轮已取走、还没通知的：{发送者: {设备码: [书名]}}
    timer = None

    def log_message(self, fmt, *args):
        log.debug("%s %s", self.address_string(), fmt % args)

    def send(self, code, body=b"", ctype="text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authed(self):
        if not self.token:          # config.json 里 auth 为 false：不校验口令
            return True
        got = self.headers.get("X-Token", "")
        if got and secrets.compare_digest(got, self.token):
            return True
        self.send(403, b"forbidden\n")
        return False

    def query(self):
        return {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).items()}

    def device(self):
        """Kindle 的设备码（?device=）；格式不对返回 None 并已回 400。"""
        code = self.query().get("device", "")
        if DEVICE_RE.fullmatch(code):
            return code
        self.send(400, b"need ?device=<6-32 letters/digits>\n")
        return None

    def item_dir(self, item, device):
        """只有发给这台 Kindle 的书才能取、才能确认。"""
        for i, _, _, sender in items_for(device):
            if i == item:
                return os.path.join(QUEUE, item)
        return None

    def admin_ok(self):
        pw = load("config.json", {}).get("admin_password", "")
        auth = self.headers.get("Authorization", "")
        if pw and auth.startswith("Basic "):
            try:
                _, _, got = base64.b64decode(auth[6:]).decode().partition(":")
            except ValueError:
                got = ""
            if secrets.compare_digest(got.encode(), pw.encode()):
                return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="kindle-wxsend", charset="UTF-8"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def json_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(min(n, 65536)) or b"{}")
        except ValueError:
            return {}

    def admin_state(self):
        users = load("users.json", {})
        devs = load("devices.json", {})
        pending = {}
        for i, n, s, sender in queue_items():
            pending.setdefault(sender, []).append({"id": i, "name": n, "size": mb(s), "acked": acked(i)})
        return {
            "devices": [{"code": c, **d} for c, d in sorted(devs.items(), key=lambda x: -x[1].get("seen", 0))],
            "users": [{"id": u, **info, "pending": pending.get(u, [])}
                      for u, info in sorted(users.items(), key=lambda x: -x[1].get("last", 0))],
            # 同步情况：每本书的目标设备取当前绑定（改绑定会影响还没送完的书）
            "books": [{**b, "who": users.get(b.get("sender"), {}).get("name", ""),
                       "size": mb(b.get("size") or 0),
                       "targets": sorted(set(user_devices(b.get("sender"), users)) | set(b["ack"]))}
                      for b in history()],
            "now": time.time(),
        }

    def admin_post(self, action):
        b = self.json_body()
        with lock:
            users = load("users.json", {})
            devs = load("devices.json", {})
            if action == "bind" and b.get("user") in users and isinstance(b.get("devices"), list) \
                    and all(d in devs for d in b["devices"]):
                users[b["user"]]["devices"] = b["devices"]
                save("users.json", users)
                # 去掉的设备不再等：剩下的都取过了就删
                for i, _, _, sender in queue_items():
                    if sender == b["user"] and b["devices"] and set(b["devices"]) <= set(acked(i)):
                        shutil.rmtree(os.path.join(QUEUE, i), ignore_errors=True)
                        event("done", i)
                names = "、".join(f"「{devs[d].get('label') or d}」" for d in b["devices"])
                note = (f"已把你绑定到 Kindle {names}，发来的书会在它们亮屏联网时送过去。"
                        if b["devices"] else "已解除你和 Kindle 的绑定，发来的书会先存着。")
                threading.Thread(target=self.bot.reply_to, args=(b["user"], note), daemon=True).start()
            elif action == "label" and b.get("device") in devs:
                devs[b["device"]]["label"] = str(b.get("label", ""))[:40]
                save("devices.json", devs)
            elif action == "forget" and isinstance(b.get("devices"), list):
                # 可以一次删多台；绑定了它们的用户同时解绑
                for code in b["devices"]:
                    devs.pop(code, None)
                    for info in users.values():
                        if code in info.get("devices", []):
                            info["devices"].remove(code)
                save("devices.json", devs)
                save("users.json", users)
            elif action == "delete" and re.fullmatch(r"[0-9]{8}-[0-9]{6}-[0-9a-f]{8}", b.get("id", "")):
                shutil.rmtree(os.path.join(QUEUE, b["id"]), ignore_errors=True)
                event("delete", b["id"])
            else:
                return self.send(400, b"bad request\n")
        self.send(200, b"ok\n")

    def wecom(self, body=None):
        """企业微信回调。GET 是配置 URL 时的校验（解密 echostr 原样返回），POST 是新消息通知。"""
        kf = self.bot if isinstance(self.bot, WecomKf) else None
        q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).items()}
        enc = q.get("echostr", "") if body is None else xml_field(body, "Encrypt")
        if not kf or not kf.crypt.check(q.get("msg_signature"), q.get("timestamp", ""), q.get("nonce", ""), enc):
            return self.send(403, b"bad signature\n")
        try:
            plain = kf.crypt.decrypt(enc)
        except (ValueError, IndexError) as e:
            log.warning("回调解密失败：%s", e)
            return self.send(400, b"bad message\n")
        if body is None:
            return self.send(200, plain.encode())
        kf.on_event(plain)
        self.send(200, b"success")

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/health":
            return self.send(200, b"expired\n" if state["expired"] else b"ok\n")
        if p == "/wecom":
            return self.wecom()
        if p == "/join":
            # 公开页：给朋友看的客服二维码和用法（客服链接本来就是要分享出去的）
            link = self.bot.contact_link() if isinstance(self.bot, WecomKf) else ""
            if not link.startswith("https://work.weixin.qq.com/"):
                return self.send(404, b"not available\n")
            return self.send(200, JOIN_HTML.replace("__LINK__", link).encode(), "text/html; charset=utf-8")
        if p in ("/admin", "/admin/state"):
            if not self.admin_ok():
                return
            if p == "/admin":
                return self.send(200, ADMIN_HTML.encode(), "text/html; charset=utf-8")
            return self.send(200, json.dumps(self.admin_state(), ensure_ascii=False).encode(), "application/json")
        if not self.authed():
            return
        dev = self.device()
        if not dev:
            return
        if p == "/list":
            # 一行一本：id \t 字节数 \t 文件名（Kindle 端用 busybox sh 解析，不用 JSON）
            mine = items_for(dev)
            seen_device(dev, self.headers.get("X-Real-IP") or self.client_address[0], len(mine))
            body = "".join(f"{i}\t{s}\t{n}\n" for i, n, s, _ in mine)
            return self.send(200, body.encode())
        m = re.fullmatch(r"/file/([^/]+)", p)
        d = m and self.item_dir(m.group(1), dev)
        if not d:
            return self.send(404, b"not found\n")
        name = [n for n in os.listdir(d) if not n.startswith(".") and not n.endswith(".part")][0]
        f = os.path.join(d, name)
        event("fetch", m.group(1), device=dev)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(os.path.getsize(f)))
        self.end_headers()
        with open(f, "rb") as src:
            shutil.copyfileobj(src, self.wfile, 1 << 16)

    def do_POST(self):
        if self.path.split("?")[0] == "/wecom":
            n = int(self.headers.get("Content-Length") or 0)
            return self.wecom(self.rfile.read(min(n, 1 << 20)).decode(errors="replace"))
        m = re.fullmatch(r"/admin/(bind|label|forget|delete)", self.path.split("?")[0])
        if m:
            # 只收 JSON：别的网站跨站提交不了 application/json（会触发预检）
            if not self.admin_ok():
                return
            if "application/json" not in self.headers.get("Content-Type", ""):
                return self.send(415, b"json only\n")
            return self.admin_post(m.group(1))
        if not self.authed():
            return
        dev = self.device()
        if not dev:
            return
        m = re.fullmatch(r"/ack/([^/]+)", self.path.split("?")[0])
        d = m and self.item_dir(m.group(1), dev)
        if not d:
            return self.send(404, b"not found\n")
        with lock:
            users = load("users.json", {})
            for i, n, _, sender in queue_items():
                if i != m.group(1):
                    continue
                Handler.delivered.setdefault(sender, {}).setdefault(dev, []).append(n)
                done = set(acked(i)) | {dev}
                event("ack", i, device=dev)
                # 绑定的每台 Kindle 都取走了才删
                if set(user_devices(sender, users)) <= done:
                    shutil.rmtree(d, ignore_errors=True)
                    event("done", i)
                else:
                    with open(os.path.join(d, ".acked"), "w") as f:
                        f.write("\n".join(sorted(done)))
        # 一次同步可能取走好几本，攒 10 秒合成一条通知
        with lock:
            if not Handler.timer:
                Handler.timer = threading.Timer(10, Handler.flush)
                Handler.timer.start()
        self.send(200, b"ok\n")

    @classmethod
    def flush(cls):
        with lock:
            batch, cls.delivered, cls.timer = cls.delivered, {}, None
        try:
            notify_delivered(cls.bot, batch)
        except Exception:
            log.exception("送达通知失败")


# ── 命令行 ────────────────────────────────────────────────────────────────


def kindle_token():
    try:
        return open(path("kindle_token")).read().strip()
    except OSError:
        t = secrets.token_urlsafe(24)
        fd = os.open(path("kindle_token"), os.O_WRONLY | os.O_CREAT, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(t + "\n")
        return t


def show_qr(content):
    print("\n用微信扫描下面的二维码绑定 ClawBot：\n")
    try:
        import qrcode
        q = qrcode.QRCode(border=1)
        q.add_data(content)
        q.print_ascii(invert=True)
    except ImportError:
        print("（装了 python3-qrcode 才能直接在终端显示二维码；也可以把下面的链接做成二维码再扫）")
    print(content, flush=True)


def login():
    for _ in range(3):          # 二维码约 5 分钟过期，过期就换一张
        if login_once():
            return
        print("二维码过期，换一张", flush=True)
    sys.exit("连续 3 张二维码都过期了，重新运行 login")


def login_once():
    r = http_json(f"{BASE_URL}/ilink/bot/get_bot_qrcode?bot_type=3")
    if r.get("ret") != 0 or not r.get("qrcode"):
        sys.exit(f"获取二维码失败：{r}")
    show_qr(r["qrcode_img_content"])
    last = ""
    while True:
        try:
            s = http_json(f"{BASE_URL}/ilink/bot/get_qrcode_status?qrcode="
                          + urllib.parse.quote(r["qrcode"]), timeout=60)
        except OSError:
            continue
        st = s.get("status", "")
        if st != last:
            print({"wait": "等待扫码…", "scaned": "已扫码，请在手机上确认…"}.get(st, st), flush=True)
            last = st
        if st == "confirmed":
            save("account.json", {
                "bot_token": s["bot_token"], "bot_id": s["ilink_bot_id"],
                "user_id": s["ilink_user_id"], "base_url": s.get("baseurl") or BASE_URL,
                "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            for stale in ("sync_buf", "peers.json"):
                try:
                    os.remove(path(stale))
                except OSError:
                    pass
            print("绑定成功。重启服务：systemctl restart kindle-wxsend")
            return True
        if st == "expired":
            return False
        if st not in ("wait", "scaned"):
            sys.exit(f"扫码失败：{s.get('retmsg') or st}")
        time.sleep(2)


def serve():
    conf = load("config.json", {})
    source = conf.get("source", "ilink")
    if source == "kf":
        bot = WecomKf(conf["kf"])
    else:
        account = load("account.json", None)
        if not account:
            sys.exit("还没绑定，先运行 wxsend.py login")
        bot = Bot(account)
    os.makedirs(QUEUE, exist_ok=True)
    Handler.bot = bot
    auth = bool(conf.get("auth", False))
    Handler.token = kindle_token() if auth else ""
    host, port = LISTEN.rsplit(":", 1)
    srv = http.server.ThreadingHTTPServer((host, int(port)), Handler)
    log.info("来源 %s，拉取接口 http://%s（口令校验%s）", source, LISTEN, "开" if auth else "关")
    if source == "kf":
        srv.serve_forever()             # 微信客服靠回调，不用轮询
    else:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        poll_loop(bot)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.makedirs(DATA, mode=0o700, exist_ok=True)
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "login":
        login()
    elif cmd == "serve":
        serve()
    elif cmd == "token":
        print(kindle_token())
    elif cmd == "status":
        a = load("account.json", None)
        print("绑定：" + (f"{a['user_id']}（{a['created']}）" if a else "未绑定"))
        for i, n, s, _ in queue_items():
            print(f"{i}  {mb(s):>9}  {n}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
