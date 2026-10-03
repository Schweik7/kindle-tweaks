#!/usr/bin/env python3
"""
按文件夹自动生成 Kindle 收藏夹（FW 5.12+，在 Kindle 上运行）。

规则：documents 下名字以 prefix（config.json，默认「收藏夹_」；设为 "" 则所有文件夹都算）开头的文件夹 -> 同名（去掉前缀）收藏夹，
      文件夹里（含子文件夹）的书都加入；多层匹配时书同时属于每一层。
      .sdr 和 exclude 列表里的文件夹（默认 dictionaries、Downloads）跳过。
      只管理自己创建的收藏夹（记录在 state.json），手动建的收藏夹不碰。
原理：书和路径从 /var/local/cc.db 只读查询；增删改通过 ccat 的 http://127.0.0.1:9101/change，
      请求头 AuthToken = /tmp/session_token（注意大小写，urllib 会改成 Authtoken 导致 401）。

用法：sync.py [--dry] [--purge]
"""
import http.client, json, os, re, sqlite3, sys, time, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(HERE, "config.json")
STATE = os.path.join(HERE, "state.json")
DOCS = "/mnt/us/documents/"
DEFAULT_CONF = {"prefix": "收藏夹_", "exclude": ["dictionaries", "Downloads"]}


def log(*a):
    print(time.strftime("%m-%d %H:%M:%S"), *a, flush=True)


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def natkey(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def post(commands):
    tok = open("/tmp/session_token").read().strip()
    body = json.dumps({"type": "ChangeRequest", "id": 1, "commands": commands}).encode()
    c = http.client.HTTPConnection("127.0.0.1", 9101, timeout=60)
    c.putrequest("POST", "/change")
    c.putheader("AuthToken", tok)
    c.putheader("Content-Type", "application/json")
    c.putheader("Content-Length", str(len(body)))
    c.endheaders(body)
    r = c.getresponse()
    txt = r.read().decode("utf-8", "replace")
    if r.status != 200 or '"ok":true' not in txt.replace(" ", ""):
        raise RuntimeError(f"ccat 返回 {r.status}: {txt[:300]}")
    return txt


def main():
    dry = "--dry" in sys.argv
    purge = "--purge" in sys.argv
    conf = dict(DEFAULT_CONF, **load(CONF, {}))
    prefix = conf["prefix"]
    exclude = set(conf.get("exclude", []))
    state = load(STATE, {})  # 收藏夹名 -> uuid

    db = sqlite3.connect("file:/var/local/cc.db?mode=ro", uri=True, timeout=30)
    books = db.execute("select p_uuid, p_location from Entries where p_type='Entry:Item' "
                       "and p_location like ?", (DOCS + "%",)).fetchall()
    colls = {u: t for u, t in db.execute("select p_uuid, p_titles_0_nominal from Entries where p_type='Collection'")}
    members = {}
    for cu, mu in db.execute("select i_collection_uuid, i_member_uuid from Collections order by i_order"):
        members.setdefault(cu, []).append(mu)
    db.close()

    # 期望的 收藏夹名 -> [成员 uuid]
    want = {}
    if not purge:
        for bu, loc in sorted(books, key=lambda x: natkey(x[1])):
            parts = loc[len(DOCS):].split("/")[:-1]
            for d in parts:
                if d.startswith(prefix) and not d.endswith(".sdr") and d not in exclude and len(d) > len(prefix):
                    want.setdefault(d[len(prefix):], []).append(bu)
        for k in want:  # 去重保序
            want[k] = list(dict.fromkeys(want[k]))

    cmds, new_state, actions = [], {}, []
    by_title = {}
    for u, t in colls.items():
        by_title.setdefault(t, u)
    for name, mem in want.items():
        cu = state.get(name)
        if cu not in colls:
            cu = by_title.get(name)  # state 丢了的话接管同名收藏夹
        if cu not in colls:
            cu = str(uuid.uuid4())
            cmds.append({"insert": {"type": "Collection", "uuid": cu, "lastAccess": int(time.time()),
                                    "titles": [{"display": name, "collation": name, "language": "zh"}],
                                    "isVisibleInHome": True, "isArchived": False,
                                    "mimeType": "application/x-kindle-collection", "collections": None}})
            actions.append(f"新建「{name}」{len(mem)} 本")
            cmds.append({"update": {"type": "Collection", "uuid": cu, "members": mem}})
        elif members.get(cu, []) != mem:
            actions.append(f"更新「{name}」{len(members.get(cu, []))} -> {len(mem)} 本")
            cmds.append({"update": {"type": "Collection", "uuid": cu, "members": mem}})
        new_state[name] = cu
    for name, cu in state.items():
        if name not in want and cu in colls:
            actions.append(f"删除「{name}」（文件夹已不存在）")
            cmds.append({"delete": {"uuid": cu}})

    if not cmds:
        if new_state != state and not dry:
            json.dump(new_state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return
    for a in actions:
        log(("[预览] " if dry else "") + a)
    if dry:
        return
    post(cmds)
    json.dump(new_state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log("完成")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log("出错:", repr(e))
        sys.exit(1)
