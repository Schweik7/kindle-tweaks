#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读导出 KOA3 已加载到普通 DDR 的 EPDC waveform blob。

本工具不访问 EPDC MMIO。物理地址来自本机此前在安全更新窗口内确认的
EPDC_WVADDR=0x92800000；导出前会校验设备 compatible、顶层表大小和指针范围。
"""
import argparse
import hashlib
import mmap
import os
import struct
import sys

EXPECTED_COMPATIBLE = b"fsl,imx7d-zelda"
DEFAULT_PHYS = 0x92800000
DEFAULT_SIZE = 2475341
EXPECTED_TOP_TABLE_BYTES = 0x70


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ap.add_argument("--phys", type=lambda value: int(value, 0), default=DEFAULT_PHYS)
    ap.add_argument("--size", type=lambda value: int(value, 0), default=DEFAULT_SIZE)
    args = ap.parse_args()

    compatible = open("/proc/device-tree/compatible", "rb").read()
    if EXPECTED_COMPATIBLE not in compatible:
        raise RuntimeError("设备 compatible 不匹配: %r" % compatible)
    if args.phys % mmap.PAGESIZE:
        raise ValueError("物理地址必须按页对齐")
    if args.size < 4096 or args.size > 0x400000:
        raise ValueError("导出大小超出安全范围")

    fd = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
    mm = None
    try:
        mm = mmap.mmap(fd, args.size, mmap.MAP_SHARED, mmap.PROT_READ, offset=args.phys)
        top_bytes = struct.unpack_from("<Q", mm, 0)[0]
        if top_bytes != EXPECTED_TOP_TABLE_BYTES:
            raise RuntimeError("地址指纹不匹配: 首个 uint64=0x%x，预期 0x%x" %
                               (top_bytes, EXPECTED_TOP_TABLE_BYTES))
        top_slots = top_bytes // 8
        pointers = struct.unpack_from("<%dQ" % top_slots, mm, 0)
        if any(pointer < top_bytes or pointer >= args.size for pointer in pointers):
            raise RuntimeError("顶层指针越界: %s" %
                               " ".join("0x%x" % pointer for pointer in pointers))
        blob = bytes(mm[:args.size])
    finally:
        if mm is not None:
            mm.close()
        os.close(fd)

    with open(args.output, "wb") as output:
        output.write(blob)
    digest = hashlib.sha256(blob).hexdigest()
    print("已只读导出 %d bytes: %s" % (len(blob), args.output))
    print("sha256=%s" % digest)
    print("top_slots=%d pointers=%s" %
          (top_slots, " ".join("0x%x" % pointer for pointer in pointers)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
