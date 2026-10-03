"""
解锁书库「查看选项 → 收藏夹」视图：给 /app/lib/libKSDKLibrary.so 打补丁。

原理：LibraryViewModelImpl::LibraryLayoutModeOptions() 和 LibraryModeOptions() 里，
收藏夹选项的 isEnabled = HouseholdUtils::HasActiveProfile()（检查 /var/local/token/activeprofile.txt
是否存在），未注册/假注册的机器上为 false。把这两次虚函数调用改成「返回 1」。

特征（ARM Thumb）：
    LDR.W R0, [Rn, #0xE8]      ; this->householdUtils      (xx F8 E8 00, xx = D0..DF)
    ... (≤14 字节)
    LDR   R3, [R0]             ; 03 68
    LDR   R3, [R3, #8]         ; 9B 68   vtable[2] = HasActiveProfile
    BLX   R3                   ; 98 47   -> 改成 MOVS R0, #1 (01 20)

用法：python patch_ksdk.py libKSDKLibrary.so.orig libKSDKLibrary.so.patched
已在 Kindle Oasis 3 FW 5.15.1.1 验证（原版 md5 ce623d137447a1beef8e6431561f4528，
补丁偏移 0x15E94A、0x15EB32，补丁版 md5 26d0934235303a407a76854e2d9d3073）。
"""
import hashlib
import re
import sys

SIG = re.compile(rb"[\xd0-\xdf]\xf8\xe8\x00.{0,14}?\x03\x68\x9b\x68\x98\x47", re.S)

src, dst = sys.argv[1], sys.argv[2]
data = bytearray(open(src, "rb").read())
assert data[:4] == b"\x7fELF", "不是 ELF 文件"
print("原文件 md5:", hashlib.md5(data).hexdigest())

hits = [m.end() - 2 for m in SIG.finditer(data)]  # BLX R3 的位置
if len(hits) == 0 and data.count(b"\x01\x20") and b"library_layout_mode_option.collections" in data:
    sys.exit("没找到特征，可能已经是补丁版，或者新固件改了代码（见 docs/03-collections-view.md 手动方法）")
if len(hits) != 2:
    sys.exit(f"找到 {len(hits)} 处特征（预期 2 处），需要人工确认：{[hex(h) for h in hits]}")

for o in hits:
    print(f"0x{o:x}: {data[o - 6:o + 2].hex(' ')} -> BLX R3 改为 MOVS R0,#1")
    data[o:o + 2] = b"\x01\x20"
open(dst, "wb").write(data)
print("补丁版 md5:", hashlib.md5(data).hexdigest())
