"""
隐藏无线相关界面（功能 13）：给 KPPMainApp.js.hbc 打补丁。

三处改动：
  1. 下拉快捷设置里那一排按钮（飞行模式 / 夜间模式 / 同步 / 全部设置 …）：
     画这一排的 render（testID 'quicksettings.widgetview'）开头改成 return null。
  2. 顶栏的购物车按钮：RenderTopNavBarButtons 里 KPP_STORE 分支的第一条指令改成 return null。
  3. 主页 ⋮ 菜单里的「Amazon Kids」「网页浏览器」「设置」：ContextMenuItem 前面插一段判断，
     item.id 命中就 return null。快捷设置里的「全部设置」随 1 一起没了，
     这样界面上就进不了设置（无线、账户等都在里面）。函数变长了放不回原处，
     就把整个函数体搬到文件末尾（footer 前），改函数头里的偏移和长度，再改 fileLength。
     Hermes 的跳转都是相对地址，函数体整体平移不影响；函数里没有 switch 表和异常表（脚本会检查）。

     ⋮ 菜单的条目由原生 KPPMainAppV2 造：
       kpp::library::native::KPPChromeConfigUtils::BuildOverflowMenuConfig 用
       KPPNavigation::NavigationActionFactory 的动作 id 建菜单，固定顺序是
       goodreads / freetime / browser / settings / legal / kindleSpecialOffers
       （另外还会按状态加 readingList、kindleUnlimited；「新建收藏夹」来自书库动作表）。
       条目的 id 就是动作 id —— NavigationActionInterface::getId() 返回构造时第二个字符串，
       getBrowserItem 传 'browser'、getSettingsItem 传 'settings'、
       而「Amazon Kids」由 getFreeTimeItem 传的是 **'freetime'**（标签键才是
       chrome.header.overflow.menu.amazon_kids）。所以三段判断是：
         id === 'browser'  → 网页浏览器
         id === 'settings' → 设置
         id 是 'freetime'  → Amazon Kids
       字符串表里没有 'freetime' 这个字面量（只有 freetime.conditionsofuse.landing.page），
       所以对后者用 indexOf 判前缀：'freetime.conditionsofuse.landing.page'.indexOf(id) === 0
       只对 'freetime' 及其真前缀成立。
最后重新计算文件末尾的 SHA1。

输入可以是原版，也可以是已经打了「云端弹窗」补丁（patch_kpp.py）的版本，两个补丁互不重叠。

依赖：pip install git+https://github.com/P1sec/hermes-dec
用法：python patch_kpp_nowifi.py <输入 hbc> <输出 hbc>
"""
import ctypes
import hashlib
import importlib
import struct
import sys
from io import BytesIO

from hermes_dec.parsers.hbc_bytecode_parser import parse_hbc_bytecode
from hermes_dec.parsers.hbc_file_parser import HBCReader

try:
    # Windows 控制台默认 GBK，打印 '⋮' 会直接抛 UnicodeEncodeError
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

src, dst = sys.argv[1], sys.argv[2]
data = bytearray(open(src, "rb").read())
assert hashlib.sha1(data[:-20]).digest() == bytes(data[-20:]), "原文件末尾 SHA1 不对，可能不是完整的 hbc"

reader = HBCReader()
reader.read_whole_file(BytesIO(bytes(data)))
ver = reader.header.version
assert ver < 97, f"只按 bytecode < 97 的函数头格式写的，当前 {ver}"
ops = importlib.import_module(f"hermes_dec.parsers.hbc_opcodes.hbc{ver}")
print(f"Hermes 字节码版本 {ver}")


def sid(s):
    hits = [i for i, x in enumerate(reader.strings) if x == s]
    if not hits:
        sys.exit(f"字符串表里没有 {s!r}")
    return hits[0]


def insts(fid):
    return list(parse_hbc_bytecode(reader.function_headers[fid], reader))


def funcs_named(name):
    return [i for i, h in enumerate(reader.function_headers) if reader.strings[h.functionName] == name]


def enc(name, *args):
    """按 hermes-dec 的操作数定义编码一条指令"""
    inst = getattr(ops, name)
    st = inst.structure()
    for k, v in zip(("arg1", "arg2", "arg3", "arg4", "arg5", "arg6"), args):
        setattr(st, k, v)
    b = bytes([inst.opcode]) + bytes(st)
    assert len(b) == inst.binary_size, name
    return b


RET_NULL = enc("LoadConstNull", 0) + enc("Ret", 0)


def jump_targets(fid):
    t = set()
    for ins in insts(fid):
        for i, op in enumerate(ins.inst.operands):
            if op.operand_type.name in ("Addr8", "Addr32"):
                t.add(ins.original_pos + getattr(ins, "arg%d" % (i + 1)))
    return t


def overwrite_ret_null(fid, pos, what):
    """在函数 fid 的 pos 处写 return null；确认不会切到别的跳转目标中间"""
    h = reader.function_headers[fid]
    bad = [t for t in jump_targets(fid) if pos < t < pos + len(RET_NULL)]
    assert not bad, f"{what}: 覆盖范围内有跳转目标 {bad}"
    off = h.offset + pos
    if data[off:off + len(RET_NULL)] == RET_NULL:
        print(f"{what}: 已经是补丁版")
        return
    print(f"{what}: 函数 #{fid} +0x{pos:x}（文件 0x{off:x}）{data[off:off + 4].hex(' ')} -> {RET_NULL.hex(' ')}")
    data[off:off + len(RET_NULL)] = RET_NULL


# ---- 1. 快捷设置按钮排 ----
WV = sid("quicksettings.widgetview")
hits = [fid for fid in range(len(reader.function_headers))
        if reader.strings[reader.function_headers[fid].functionName] == "render"
        and any(i.inst.name.startswith("LoadConstString") and i.arg2 == WV for i in insts(fid))]
assert len(hits) == 1, f"找到 {len(hits)} 个快捷设置按钮排的 render"
overwrite_ret_null(hits[0], 0, "快捷设置按钮排")

# ---- 2. 顶栏购物车 ----
hits = funcs_named("RenderTopNavBarButtons")
assert len(hits) == 1, f"找到 {len(hits)} 个 RenderTopNavBarButtons"
fid = hits[0]
seq = insts(fid)
STORE = sid("KPP_STORE")
cand = [seq[k + 1] for k in range(len(seq) - 1)
        if seq[k].inst.name.startswith("GetById") and seq[k].arg4 == STORE
        and seq[k + 1].inst.name.startswith("JStrictEqual")]
assert len(cand) == 1, f"找到 {len(cand)} 个 KPP_STORE 分支"
overwrite_ret_null(fid, cand[0].original_pos + cand[0].arg1, "购物车按钮")

# ---- 3. ⋮ 菜单里的 Amazon Kids / 网页浏览器 / 设置 ----
# 表里有现成字面量的直接比字符串；Amazon Kids（id 'freetime'）没有字面量，用前缀判断
MENU_IDS = ("browser", "settings")
FREETIME_PROBE = "freetime.conditionsofuse.landing.page"
hits = funcs_named("ContextMenuItem")
assert len(hits) == 1, f"找到 {len(hits)} 个 ContextMenuItem"
fid = hits[0]
h = reader.function_headers[fid]
assert not h.overflowed and not h.hasExceptionHandler, "ContextMenuItem 函数头格式不是预期的"
assert not any("Switch" in i.inst.name for i in insts(fid)), "ContextMenuItem 里有 switch 表，不能整体搬"
body = bytes(data[h.offset:h.offset + h.bytecodeSizeInBytes])
MARK = enc("LoadConstString", 2, sid("browser"))
if h.offset >= reader.header.debugInfoOffset and MARK in body[:40]:
    print("⋮ 菜单：已经是补丁版")
else:
    # 寄存器 r0..r4 在原函数体开头都会被重新赋值；属性缓存号 0 = 不缓存
    def gid(dst, obj, s):
        i = sid(s)
        return enc("GetByIdShort", dst, obj, 0, i) if i < 256 else enc("GetById", dst, obj, 0, i)

    def build(off_null, off_body):
        p = b""
        p += enc("LoadParam", 0, 1)                      # r0 = props
        p += gid(1, 0, "item")                           # r1 = props.item
        p += gid(1, 1, "id")                             # r1 = item.id
        for name in MENU_IDS:
            p += enc("LoadConstString", 2, sid(name))
            p += enc("JStrictEqual", off_null - len(p), 1, 2)
        p += enc("LoadConstString", 2, sid(FREETIME_PROBE))   # r2 = 'freetime.conditionsofuse...'
        p += enc("GetById", 3, 2, 0, sid("indexOf"))
        p += enc("Call2", 3, 3, 2, 1)                    # r3 = r2.indexOf(id)
        p += enc("LoadConstUInt8", 4, 0)
        p += enc("JStrictNotEqual", off_body - len(p), 3, 4)  # 非 0（不是前缀）→ 照常显示
        return p

    probe = build(0, 0)                                  # 先量长度，再填真实跳转距离
    off_null = len(probe)
    prologue = build(off_null, off_null + len(RET_NULL))
    assert len(prologue) == off_null
    assert off_null < 127, f"跳转距离 {off_null} 超过 Addr8"
    newbody = prologue + RET_NULL + body
    assert len(newbody) < (1 << 15)

    new_off = len(data) - 20                             # 放在 footer 前
    assert new_off < (1 << 25)
    data[new_off:new_off] = newbody

    # 改 SmallFuncHeader：word0 = offset:25 | paramCount:7，word1 = bytecodeSize:15 | functionName:17
    table = (ctypes.sizeof(reader.header) + 31) // 32 * 32
    ent = table + 16 * fid
    w0, w1 = struct.unpack_from("<II", data, ent)
    assert w0 & 0x1FFFFFF == h.offset and w1 & 0x7FFF == h.bytecodeSizeInBytes, "函数头位置算错了"
    w0 = (w0 & ~0x1FFFFFF) | new_off
    w1 = (w1 & ~0x7FFF) | len(newbody)
    struct.pack_into("<II", data, ent, w0, w1)
    struct.pack_into("<I", data, 32, len(data))          # header.fileLength（magic 8 + version 4 + sourceHash 20）
    print(f"⋮ 菜单：ContextMenuItem #{fid} 0x{h.offset:x}/{h.bytecodeSizeInBytes} -> 0x{new_off:x}/{len(newbody)}")

data[-20:] = hashlib.sha1(data[:-20]).digest()
open(dst, "wb").write(data)

# 自检：重新解析，确认三处都生效、函数还能完整反汇编
chk = HBCReader()
chk.read_whole_file(BytesIO(bytes(data)))
for f in funcs_named("ContextMenuItem"):
    n = sum(1 for _ in parse_hbc_bytecode(chk.function_headers[f], chk))
    print(f"自检：ContextMenuItem 共 {n} 条指令")
print("原文件 md5:", hashlib.md5(open(src, "rb").read()).hexdigest())
print("补丁版 md5:", hashlib.md5(data).hexdigest())
