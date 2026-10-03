"""
去掉 Kindle 书库"云端不可用，您必须注册"弹窗：给 KPPMainApp.js.hbc 打补丁。

做法：找到函数 invokeDeviceNotRegisteredDialog，把开头 4 字节改成
    LoadConstUndefined r0 ; Ret r0
（一进函数就返回），再重新计算文件末尾的 SHA1。

依赖：pip install git+https://github.com/P1sec/hermes-dec
用法：python patch_kpp.py KPPMainApp.js.hbc.orig KPPMainApp.js.hbc.patched
"""
import hashlib
import importlib
import sys
from io import BytesIO

from hermes_dec.parsers.hbc_file_parser import HBCReader

TARGET = "invokeDeviceNotRegisteredDialog"

src, dst = sys.argv[1], sys.argv[2]
data = bytearray(open(src, "rb").read())
assert hashlib.sha1(data[:-20]).digest() == bytes(data[-20:]), "原文件末尾 SHA1 不对，可能不是完整的 hbc"

reader = HBCReader()
reader.read_whole_file(BytesIO(bytes(data)))
ver = reader.header.version
ops = importlib.import_module(f"hermes_dec.parsers.hbc_opcodes.hbc{ver}")
undef, ret = ops.LoadConstUndefined.opcode, ops.Ret.opcode
print(f"Hermes 字节码版本 {ver}：LoadConstUndefined=0x{undef:02x} Ret=0x{ret:02x}")

hits = [(i, h) for i, h in enumerate(reader.function_headers) if reader.strings[h.functionName] == TARGET]
if len(hits) != 1:
    sys.exit(f"找到 {len(hits)} 个 {TARGET}，需要人工检查（见方法文档第 4 步）")
fid, h = hits[0]
off = h.offset
print(f"函数 #{fid} {TARGET}：偏移 0x{off:x}，{h.bytecodeSizeInBytes} 字节")
print("原始开头:", data[off:off + 8].hex(" "))

patch = bytes([undef, 0, ret, 0])
if data[off:off + 4] == patch:
    sys.exit("已经是补丁版了")
assert h.bytecodeSizeInBytes >= 4

data[off:off + 4] = patch
data[-20:] = hashlib.sha1(data[:-20]).digest()
open(dst, "wb").write(data)
print("补丁后开头:", data[off:off + 8].hex(" "))
print("原文件 md5:", hashlib.md5(open(src, "rb").read()).hexdigest())
print("补丁版 md5:", hashlib.md5(data).hexdigest())
