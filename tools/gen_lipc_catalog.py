"""
从真机的 lipc 转储重新生成 docs/12-lipc-service-catalog.md，并把服务索引嵌回
docs/11-lipc-and-services.md 的第 3 节。

为什么要这个脚本：服务是按需注册的，机型和固件不同，属性和当前值都不一样。
docs/11 的「职责」是我们自己标注的（下面的 DESC），而属性名、类型、读写权限、
示例值全部来自设备本身，所以换机器/换固件后重新跑一遍就行。

用法：
    # ① 在 Kindle 上导出（-a 探测全部服务，输出很长，可能要跑一会儿）
    export PATH=/usr/sbin:/sbin:$PATH
    lipc-probe -a -v > /mnt/us/lipc.txt

    # ② 取回电脑
    scp root@<kindle-ip>:/mnt/us/lipc.txt .

    # ③ 重新生成
    python tools/gen_lipc_catalog.py lipc.txt

    # 只想预览、不写文件：
    python tools/gen_lipc_catalog.py lipc.txt --dry-run

脚本会打印：
  - 新出现（没有描述）的服务 —— 把它们补进下面的 DESC 再跑一次；
  - 这次没出现、但 DESC 里有记录的服务 —— 通常只是当时没运行，正常。
"""
import argparse
import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# 服务 -> (一句话职责, 分类)
# 分类: core / ui / net / content / account / power / peripheral / other
# 说明为本仓库自行撰写；标「推测」的是依据属性名推断，未逐一实机验证。
# ---------------------------------------------------------------------------
DESC = {
    "com.lab126.appmgrd": ("应用生命周期管理器：按 URI 启动/切换/暂停应用，维护前台应用状态", "core"),
    "com.lab126.booklet": ("booklet 通用 run/kill 入口", "core"),
    "com.lab126.cvm": ("cvm 进程的日志开关（框架 JVM 的入口）", "core"),
    "com.lab126.kaf": ("Java 框架（cvm）本体：注册/商店/设置等所有 booklet 的宿主", "core"),
    "com.lab126.pmond": ("进程/内存监视：超限杀进程、重启", "core"),
    "com.lab126.system": ("系统信息与全局动作：固件版本、面板波形、时间、截图、VoiceView、调试命令入口", "core"),
    "com.lab126.todo": ("待办队列：系统级异步任务（下载、注册、广告包等）的调度", "core"),
    "com.lab126.todo.kaf": ("待办队列在 Java 框架侧的接收端（handleToDoItem）", "core"),
    "com.lab126.volumd": ("用户分区（/mnt/us）挂载与空间管理", "core"),

    "com.amazon.kindle.inputMethod": ("输入法（IME）与原生层的预编辑接口", "ui"),
    "com.lab126.KIWIBridge": ("WAF 与原生层之间的 uiQuery 桥", "ui"),
    "com.lab126.blanket": ("全屏「毯子」层：语言选择、USB 提示、广告屏保等覆盖界面", "ui"),
    "com.lab126.blanket.ad_screensaver": ("广告屏保毯子层的状态查询", "ui"),
    "com.lab126.booklet.home": ("主页/图书馆 booklet 的控制入口", "ui"),
    "com.lab126.chromebar": ("顶部/底部 chrome 栏（搜索栏、活动指示器）", "ui"),
    "com.lab126.imageViewer": ("图片查看器（无 lipc 属性）", "ui"),
    "com.lab126.keyboard": ("屏幕键盘：语言、布局、显示/隐藏、预编辑串", "ui"),
    "com.lab126.kwis": ("KWIS 小部件守护进程", "ui"),
    "com.lab126.pillow": ("系统弹窗、状态栏、快捷设置（WebKit 外壳）", "ui"),
    "com.lab126.quickactions": ("快捷操作：飞行模式开关、立即同步", "ui"),
    "com.lab126.winmgr": ("窗口管理器：窗口列表、方向、屏保层、刷新/闪烁控制", "ui"),
    "com.lab126.winmgr.ligl": ("winmgr 的 LIGL（墨水屏刷新算法）日志开关", "ui"),

    "com.amazon.ebook.util.net.certmanutilities": ("证书管理工具（无 lipc 属性）", "net"),
    "com.lab126.cmd": ("网络连接管理：可用接口、当前接口、强制联网", "net"),
    "com.lab126.dynconfig": ("动态配置下发", "net"),
    "com.lab126.linux.arm.connectionutilities": ("连接工具：WiFi 弹窗/飞行模式的响应入口", "net"),
    "com.lab126.refreshCache": ("定期刷新各类缓存（联网后触发）", "net"),
    "com.lab126.transfer": ("传输队列：下载/上传请求入队与查询", "net"),
    "com.lab126.transferService": ("传输进度通知", "net"),
    "com.lab126.wifid": ("WiFi 管理守护进程：扫描、配置文件（profile）、证书、信号强度", "net"),

    "DeviceMessaging.LanguageLayer.MessageResponse": ("语言层消息响应", "content"),
    "com.lab126.LocalizationServices": ("本地化：词典、内容包语言", "content"),
    "com.lab126.archive": ("云端文档（Archive）同步与待办处理", "content"),
    "com.lab126.bookcacher": ("按需缓存书本资源", "content"),
    "com.lab126.ccat": ("内容目录（cc.db / ccat）服务", "content"),
    "com.lab126.contentpackd": ("内容包（字体、键盘布局）的安装与挂载", "content"),
    "com.lab126.coverArtService": ("封面提取与缓存", "content"),
    "com.lab126.extractor.java": ("Java 提取器的注册与删除", "content"),
    "com.lab126.grokservice": ("全文检索（grokservice）", "content"),
    "com.lab126.indexer": ("内容索引器：扫描 documents、生成 cc.db 条目", "content"),
    "com.lab126.instantSearch": ("即时搜索与搜索建议", "content"),
    "com.lab126.reader.languagelayer": ("语言层（生词提示/词典）重置", "content"),
    "com.lab126.reader.languagelayer.pinyin": ("拼音语言层重置", "content"),
    "com.lab126.reader.qa": ("阅读器字体/行距的快捷设置（QA 用）", "content"),
    "com.lab126.reader.readingtimer": ("阅读计时统计", "content"),
    "com.lab126.readingstreams": ("阅读会话流（阅读进度上报）", "content"),
    "com.lab126.readnow": ("「立即阅读」入口：直接打开一本书", "content"),
    "com.lab126.scanner": ("内容扫描器：按 appreg.db 的 extractor 关联识别并登记新文件", "content"),
    "com.lab126.stored": ("商店后台进程（mesquite 实例）", "content"),
    "com.lab126.yjff": ("YJ 相关（无 lipc 属性）", "content"),
    "com.lab126.yjlipclistener": ("YJ（KFX）索引开关", "content"),

    "AssetOwnership.DeviceSharingUpdated": ("设备共享状态变更消息", "account"),
    "AssetOwnership.SMD.Poll": ("资产归属轮询（借阅/共享）", "account"),
    "HouseholdMessage.Updates": ("Household 更新消息", "account"),
    "com.amazon.java.messagingservice": ("Amazon 消息服务（s2dm/adm 下行消息）", "account"),
    "com.lab126.DeviceAuthenticationService": ("设备认证 Cookie 的获取与安装", "account"),
    "com.lab126.IdentityService": ("身份令牌（accessToken）的获取与失效", "account"),
    "com.lab126.KindleIdentity": ("设备类型与 GUID", "account"),
    "com.lab126.amazonRegistrationService": ("注册状态：isRegistered、注册/注销令牌", "account"),
    "com.lab126.freetime": ("Amazon Kids+（FreeTime）订阅状态", "account"),
    "com.lab126.household": ("家庭/多用户档案（Household & Profiles）", "account"),

    "com.lab126.phd": ("电源/健康相关的计划任务（SPH 调度）", "power"),
    "com.lab126.powerd": ("电源管理：屏保、休眠、充电、电源键、前光", "power"),

    "com.lab126.btService": ("蓝牙音频可用性查询", "peripheral"),
    "com.lab126.btfd": ("蓝牙：配对、连接、A2DP、BLE", "peripheral"),
    "com.lab126.deviced": ("设备抽象层：触摸开关、USB 音频等硬件事件", "peripheral"),
    "com.lab126.odot": ("ODOT 消息队列（推测与 OTG/配件有关）", "peripheral"),
    "com.lab126.tphv3": ("TPH v3（推测与触控/手势处理有关）", "peripheral"),

    "CampaignSync.Invalidate": ("营销活动缓存失效（无 lipc 属性）", "other"),
    "CampaignSync.Update": ("营销活动更新消息", "other"),
    "DPCService.SettingChanged": ("DPC 设置变更消息", "other"),
    "com.lab126.JournalingService": ("日志/日记服务开关", "other"),
    "com.lab126.adManager": ("广告（Special Offers）管理", "other"),
    "com.lab126.adRotationManager": ("屏保广告轮播", "other"),
    "com.lab126.bev": ("（无 lipc 属性，作用未知）", "other"),
    "com.lab126.demd": ("设备指标（metrics）上报", "other"),
    "com.lab126.demoservice": ("演示模式（无 lipc 属性）", "other"),
    "com.lab126.devicemetrics": ("设备指标按类上报", "other"),
    "com.lab126.dpm.apps": ("按应用维度的策略开关（注释/公开笔记等）", "other"),
    "com.lab126.dpmManager": ("设备策略管理：家长控制、限制项、设备密码", "other"),
    "com.lab126.dsus": ("设备软件更新服务（DSUS）版本上报", "other"),
    "com.lab126.fastMetrics": ("高优先级指标快报", "other"),
    "com.lab126.kindleStatusService": ("设备状态日志上报", "other"),
    "com.lab126.kwis.weblabTreatments": ("Weblab 实验开关（KWIS 侧）", "other"),
    "com.lab126.legalComplianceService": ("GDPR/合规提示状态", "other"),
    "com.lab126.linux.arm.metrics": ("指标上报（无 lipc 属性）", "other"),
    "com.lab126.lxinit": ("（无 lipc 属性，作用未知）", "other"),
    "com.lab126.merchant": ("商户/推荐位（shuffle、removeAll）", "other"),
    "com.lab126.sharing": ("分享到社交网络", "other"),
    "com.lab126.sph": ("（无 lipc 属性，作用未知）", "other"),
    "com.lab126.tutorialService": ("新手引导状态", "other"),
    "com.lab126.wishlist": ("心愿单缓存刷新", "other"),
}

CAT_ORDER = ["core", "ui", "net", "content", "account", "power", "peripheral", "other"]
CAT_NAME = {
    "core": "系统与框架",
    "ui": "界面与输入",
    "net": "网络与同步",
    "content": "内容与索引",
    "account": "账号与设备身份",
    "power": "电源",
    "peripheral": "外设",
    "other": "其他",
}

# 本仓库（kindle-tweaks）实际用到的服务，会在表里打 ⭐
USED = {
    "com.lab126.powerd": "功能 6/7：屏保、休眠、电源键",
    "com.lab126.appmgrd": "打开书、回主页、查前台应用",
    "com.lab126.kaf": "framework 是否可用（注册状态、电源键响应）",
    "com.lab126.amazonRegistrationService": "判断假注册机器上的注册状态",
    "com.lab126.pillow": "弹窗排错（appmgrAppFailedFatal）",
    "com.lab126.winmgr": "窗口/屏保层",
    "com.lab126.blanket": "广告屏保、语言选择层",
    "com.lab126.system": "固件版本、面板波形、截图",
    "com.lab126.indexer": "文件放进 documents 后的索引",
    "com.lab126.scanner": "新文件识别",
    "com.lab126.volumd": "/mnt/us 挂载状态（USB 模式）",
    "com.lab126.cmd": "联网状态（微信传书取件）",
}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC11 = os.path.join(ROOT, "docs", "11-lipc-and-services.md")
DOC12 = os.path.join(ROOT, "docs", "12-lipc-service-catalog.md")

MARK_START = "<!-- 服务索引：由 tools/gen_lipc_catalog.py 生成，改结构请同步改脚本 -->"
MARK_END = "## 4 常用服务详解"

SERVICE_RE = re.compile(r"^[A-Za-z0-9_]+\.[A-Za-z0-9_.]+$")


def parse_dump(path):
    """把 `lipc-probe -a -v` 的输出解析成 {服务: [属性]}。

    格式（制表符分隔，第一列是空的）：
        com.lab126.powerd
        <TAB>rw<TAB>Str<TAB>logLevel<TAB>[Current log level=none ...]
        <TAB>r <TAB>Int<TAB>battLevel<TAB>[51]
    """
    lines = open(path, "r", encoding="utf8", errors="replace").read().split("\n")
    services, order = {}, []
    cur = None
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if SERVICE_RE.match(stripped):
            cur = stripped
            if cur not in services:
                services[cur] = []
                order.append(cur)
            i += 1
            continue
        if cur is not None and line.startswith("\t") and len(line) > 1 and line[1] in "rw":
            parts = line.split("\t")
            access = parts[1].strip()
            ptype = parts[2].strip()
            name = parts[3].strip() if len(parts) > 3 else ""
            value = ""
            if len(parts) > 4:
                chunks = [parts[4].strip()]
                opens = sum(c.count("[") for c in chunks)
                closes = sum(c.count("]") for c in chunks)
                j = i
                while opens != closes and j + 1 < len(lines):
                    j += 1
                    extra = lines[j].split("\t")[-1].strip()
                    chunks.append(extra)
                    opens += extra.count("[")
                    closes += extra.count("]")
                i = j
                value = " ".join(chunks)
            services[cur].append({"access": access, "type": ptype,
                                  "name": name, "value": value})
        i += 1
    return order, services


def cell(s):
    return s.replace("|", "\\|").strip()


def anchor(heading_text):
    """复现 GitHub 的标题 -> 锚点规则（转小写、去掉标点、空格换连字符）。"""
    t = heading_text.strip().lower().replace("`", "")
    t = "".join(ch for ch in t if ch.isalnum() or ch in " -_")
    return t.replace(" ", "-")


def shorten(v, n=58):
    v = " ".join(v.split()).strip("[]")
    if v == "*NOT SHOWN*":
        return "hash 属性，未展开"
    if v.startswith("Current log level="):
        # lipc-probe 会把完整的日志级别说明一起打出来，只留当前值
        v = v[len("Current log level="):].split(" (")[0].strip()
    if len(v) > n:
        v = v[: n - 1] + "…"
    return v


def build_index(order, services):
    lines = []
    for cat in CAT_ORDER:
        members = sorted(s for s in order if DESC[s][1] == cat)
        if not members:
            continue
        lines.append("### %s\n" % CAT_NAME[cat])
        lines.append("| 服务 | 职责 | 属性数 |")
        lines.append("|---|---|---|")
        for s in members:
            used = " ⭐" if s in USED else ""
            lines.append("| [`%s`](12-lipc-service-catalog.md#%s)%s | %s | %d |"
                         % (s, anchor(s), used, DESC[s][0], len(services[s])))
        lines.append("")
    return "\n".join(lines)


def build_catalog(order, services):
    out = []
    w = out.append
    w("# 12 lipc 服务与属性总表")
    w("")
    w("> 本表由真机的 `lipc-probe -a -v` 输出整理而成：属性名、类型、读写权限、示例值都是设备上的事实数据；")
    w("> 「职责」和分类是本仓库自行标注的，标「推测」的未逐一实机验证。")
    w(">")
    w("> 服务是**按需注册**的：没跑的服务不会有，「示例值」列只代表采集那一刻的状态。")
    w(">")
    w("> 数据来自 [KindleModding Wiki](https://kindlemodding.org/kindle-apps-and-services/) 上的")
    w("> `lipc-probe -a -v` 转储（采集自 wiki 作者的测试机，机型与本仓库的验证机不同）。")
    w("> 本仓库只在 Oasis 3 / FW 5.15.1.1 上单独核实过 [11](11-lipc-and-services.md) 第 4 节点名的那些属性，")
    w("> **本表其余部分未在真机上逐条核对**；换机型或换固件后用")
    w("> `python tools/gen_lipc_catalog.py lipc.txt` 重新生成，真机数据才是准的。")
    w("")
    w("读写含义：`r` 只读、`w` 只写（通常是「动作」而非状态）、`rw` 可读可写。")
    w("⭐ 表示本仓库（kindle-tweaks）用到的服务。")
    w("")
    w("## 目录")
    w("")
    for cat in CAT_ORDER:
        members = sorted(s for s in order if DESC[s][1] == cat)
        if members:
            w("- [%s](#%s)（%d）" % (CAT_NAME[cat], CAT_NAME[cat], len(members)))
    w("")
    for cat in CAT_ORDER:
        members = sorted(s for s in order if DESC[s][1] == cat)
        if not members:
            continue
        w("## %s" % CAT_NAME[cat])
        w("")
        for s in members:
            w("### `%s`" % s)
            w("")
            w(DESC[s][0] + ("　⭐ 本仓库用到" if s in USED else ""))
            w("")
            props = sorted(services[s], key=lambda p: p["name"].lower())
            if not props:
                w("`lipc-probe` 没有列出任何属性（服务存在但不用 lipc，或该服务当时未运行）。")
                w("")
                continue
            w("| 属性 | 类型 | 读/写 | 示例值 |")
            w("|---|---|---|---|")
            for p in props:
                val = shorten(p["value"]) if p["access"] in ("r", "rw") else ""
                w("| `%s` | %s | %s | %s |"
                  % (cell(p["name"]), cell(p["type"]), p["access"], cell(val)))
            w("")
    w("---")
    w("")
    w("生成方式：`python tools/gen_lipc_catalog.py <lipc-probe 转储>`。")
    w("属性名与类型是设备上的事实数据；「职责」等描述为本仓库撰写。")
    w("参考资料：[KindleModding Wiki — Kindle Apps & Services]"
      "(https://kindlemodding.org/kindle-apps-and-services/)（CC BY-NC 4.0）。")
    w("")
    return "\n".join(out)


def splice_index(index):
    doc = open(DOC11, encoding="utf8").read()
    head, sep, rest = doc.partition(MARK_START)
    if not sep:
        raise SystemExit("docs/11 里找不到起始标记 %r" % MARK_START)
    _, sep2, tail = rest.partition(MARK_END)
    if not sep2:
        raise SystemExit("docs/11 里找不到结束标记 %r" % MARK_END)
    return head + MARK_START + "\n\n" + index + "\n" + MARK_END + tail


def write_atomic(path, text):
    """先写临时文件再替换：避免算到一半出错时把原文件截断成 0 字节。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf8") as f:
        f.write(text)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(description="从 lipc 转储重新生成 docs/11 索引与 docs/12")
    ap.add_argument("dump", help="`lipc-probe -a -v` 的输出文件")
    ap.add_argument("--dry-run", action="store_true", help="只报告，不写文件")
    args = ap.parse_args()

    order, services = parse_dump(args.dump)
    if not order:
        raise SystemExit("没解析出任何服务，确认文件是 `lipc-probe -a -v` 的输出")

    print("解析到 %d 个服务、%d 个属性"
          % (len(order), sum(len(v) for v in services.values())))

    unknown = [s for s in order if s not in DESC]
    missing = [s for s in DESC if s not in services]
    if unknown:
        print("\n⚠ 下列服务没有描述，已跳过；把它们补进本脚本的 DESC 再重跑：")
        for s in unknown:
            print("    %r: (\"\", \"other\")," % s)
    if missing:
        print("\nℹ 下列服务本次转储里没有（通常只是当时没运行）：")
        print("    " + ", ".join(sorted(missing)))

    known = [s for s in order if s in DESC]
    if not known:
        raise SystemExit("没有任何已知服务，先补 DESC")

    index = build_index(known, services)
    catalog = build_catalog(known, services)
    # 先把两段文本都算出来再落盘，splice_index 失败时不会破坏 docs/11
    doc11 = splice_index(index)

    if args.dry_run:
        print("\n--dry-run：未写入文件")
        return
    write_atomic(DOC12, catalog)
    write_atomic(DOC11, doc11)
    print("\n已写入 docs/12-lipc-service-catalog.md")
    print("已更新 docs/11-lipc-and-services.md 第 3 节")


if __name__ == "__main__":
    main()
