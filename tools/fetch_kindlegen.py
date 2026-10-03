"""
下载 epub->mobi 需要的两个文件到 <输出目录>（拷到 Kindle 的 /mnt/us/extensions/kindletweaks/bin/）：

    qemu-i386-static  Debian 12 armel 包里的 x86 用户态模拟器（静态链接，GPL）
    kindlegen         Amazon KindleGen 2.9 Linux i386（静态链接；亚马逊已停止分发，取自 archive.org）

    python fetch_kindlegen.py <输出目录>

两者都是静态链接，不依赖 Kindle 的系统库。本仓库不包含这两个二进制。
"""
import io
import os
import sys
import tarfile
import urllib.request

QEMU_DEB = "http://deb.debian.org/debian/pool/main/q/qemu/qemu-user-static_7.2+dfsg-7+deb12u18+b3_armel.deb"
KINDLEGEN = "https://archive.org/download/kindlegen2.9/kindlegen_linux_2.6_i386_v2_9.tar.gz"


def get(url):
    print("下载", url)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=600).read()


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)

    deb = get(QEMU_DEB)
    assert deb[:8] == b"!<arch>\n", "不是 deb 包"
    i = 8
    while i < len(deb):
        name = deb[i:i + 16].decode().strip()
        size = int(deb[i + 48:i + 58].decode().strip())
        data = deb[i + 60:i + 60 + size]
        i += 60 + size + (size & 1)
        if name.startswith("data.tar"):
            with tarfile.open(fileobj=io.BytesIO(data)) as t:
                body = t.extractfile("./usr/bin/qemu-i386-static").read()
            open(os.path.join(out, "qemu-i386-static"), "wb").write(body)
            print("qemu-i386-static", len(body))

    with tarfile.open(fileobj=io.BytesIO(get(KINDLEGEN))) as t:
        body = t.extractfile("kindlegen").read()
    open(os.path.join(out, "kindlegen"), "wb").write(body)
    print("kindlegen", len(body))
    print("完成：把", out, "里的两个文件拷到 Kindle 的 /mnt/us/extensions/kindletweaks/bin/")


if __name__ == "__main__":
    main()
