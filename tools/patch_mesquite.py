"""
体验版网页浏览器允许下载任意类型的文件：给 /usr/bin/mesquite 打补丁。

原理：浏览器下载有两道关卡，都在 mesquite 的 JSObjectDownload 里：
  1. s_MimeTypeDecisionCallback：响应的 MIME 不能直接显示时，只有 5 种
     （mobi8/mobipocket/x-prc/text/plain 等）会转成下载，其余直接忽略，弹「文件类型无效」。
     循环里 strcasecmp 不相等就 BNE 到下一项 —— 改成 NOP，第一项就接受。
  2. s_DownloadRequestCallback：建议文件名的扩展名必须是 .azw/.azw1/.azw2/.azw3/.prc/.mobi/.txt。
     不匹配和没有扩展名两条路径都是 MOV R7,#0（不允许）—— 改成 MOV R7,#1。
保存位置不变：/mnt/us/documents/<文件名>（同样写死在 s_DownloadLaunch 里）。

特征（ARM，小端）：
    LDR R0,[R9,R4,LSL#2]; MOV R1,R7; BL strcasecmp; CMP R0,#0; BNE   -> BNE 改 NOP
    CMP R7,#7; BNE; MOV R7,#0                                       -> MOV R7,#1
    B; MOV R7,#0; LDR R0,[R4,#0x28]                                 -> MOV R7,#1

用法：python patch_mesquite.py mesquite.orig mesquite.patched
已在 Kindle Oasis 3 FW 5.15.1.1 验证（原版 md5 29331a28b0e362fe3873a1b5ecbdff4d，
补丁偏移 0x3F928、0x3F294、0x3F2AC）。
"""
import hashlib
import re
import sys

NOP = b"\x00\x00\xa0\xe1"
MOV_R7_1 = b"\x01\x70\xa0\xe3"
SIGS = [
    # (说明, 正则, 要改的 4 字节在匹配里的偏移, 新内容)
    ("MIME 白名单 BNE -> NOP",
     re.compile(rb"\x04\x01\x99\xe7\x07\x10\xa0\xe1...\xeb\x00\x00\x50\xe3...\x1a", re.S), 16, NOP),
    ("扩展名不匹配 MOV R7,#0 -> #1",
     re.compile(rb"\x07\x00\x57\xe3...\x1a\x00\x70\xa0\xe3", re.S), 8, MOV_R7_1),
    ("没有扩展名 MOV R7,#0 -> #1",
     re.compile(rb"...\xea\x00\x70\xa0\xe3\x28\x00\x94\xe5", re.S), 4, MOV_R7_1),
]

src, dst = sys.argv[1], sys.argv[2]
data = bytearray(open(src, "rb").read())
assert data[:4] == b"\x7fELF", "不是 ELF 文件"
assert b"JSObjectDownload::s_MimeTypeDecisionCallback" in data, "不像是 mesquite"
print("原文件 md5:", hashlib.md5(data).hexdigest())

for name, sig, rel, new in SIGS:
    hits = [m.start() + rel for m in sig.finditer(data)]
    if len(hits) != 1:
        sys.exit(f"{name}：找到 {len(hits)} 处特征（预期 1 处），可能已经是补丁版或固件变了：{[hex(h) for h in hits]}")
    o = hits[0]
    print(f"0x{o:x}: {data[o:o + 4].hex(' ')} -> {new.hex(' ')}  {name}")
    data[o:o + 4] = new
open(dst, "wb").write(data)
print("补丁版 md5:", hashlib.md5(data).hexdigest())
