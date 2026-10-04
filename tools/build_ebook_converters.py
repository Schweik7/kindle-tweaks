#!/usr/bin/env python3
"""构建 Kindle 可直接运行的 boko + Kindling ARMv7 静态二进制。

用法：
    python tools/build_ebook_converters.py extensions/kindletweaks/bin

需要 rustup、Cargo 和 Rust 1.91+。脚本固定源码提交并使用 rust-lld，不需要
ARM 交叉 GCC；Windows、Linux 和 WSL 均可运行。
"""

import argparse
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile


TARGET = "armv7-unknown-linux-musleabi"
PROJECTS = (
    {
        "name": "boko",
        "package": "boko",
        "binary": "boko",
        "version": "0.5.0",
        "url": "https://github.com/zacharydenton/boko.git",
        "rev": "b148716498fdac70134555293a7405913988256a",
    },
    {
        "name": "Kindling",
        "package": "kindling-mobi",
        "binary": "kindling-cli",
        "version": "0.27.0",
        "url": "https://github.com/CuteLicense/kindling-epub-to-mobi.git",
        "rev": "d0ffe18c6a78252844774ca8dd02e3a93f4ac6d7",
    },
)


def run(args, **kwargs):
    print("+", " ".join(map(str, args)), flush=True)
    subprocess.run([str(x) for x in args], check=True, **kwargs)


def output(args):
    return subprocess.check_output([str(x) for x in args], text=True).strip()


def find_rust_lld():
    rustc = shutil.which("rustc")
    if not rustc:
        raise RuntimeError("找不到 rustc；请先安装并启用 rustup toolchain")
    host = next((line.split(":", 1)[1].strip()
                 for line in output([rustc, "-vV"]).splitlines()
                 if line.startswith("host:")), None)
    if not host:
        raise RuntimeError("无法从 rustc -vV 判断 host triple")
    suffix = ".exe" if os.name == "nt" else ""
    candidate = Path(output([rustc, "--print", "sysroot"])) / "lib" / "rustlib" / host / "bin" / ("rust-lld" + suffix)
    if candidate.is_file():
        return candidate
    found = shutil.which("rust-lld")
    if found:
        return Path(found)
    raise RuntimeError("找不到 rust-lld（通常随 rustup toolchain 一起安装）")


def validate_arm_elf(path):
    data = path.read_bytes()[:52]
    if len(data) < 52 or data[:4] != b"\x7fELF" or data[4:6] != b"\x01\x01":
        raise RuntimeError("%s 不是 32 位 little-endian ELF" % path)
    machine = struct.unpack_from("<H", data, 18)[0]
    flags = struct.unpack_from("<I", data, 36)[0]
    if machine != 40:
        raise RuntimeError("%s 不是 ARM ELF（e_machine=%d）" % (path, machine))
    if flags & 0x400:
        raise RuntimeError("%s 被标记成 hard-float，旧 Kindle 无法运行" % path)


def install(project, stage, target_dir, env):
    cargo = shutil.which("cargo")
    if not cargo:
        raise RuntimeError("找不到 cargo")
    run([
        cargo, "install",
        "--git", project["url"],
        "--rev", project["rev"],
        "--locked",
        "--target", TARGET,
        "--target-dir", target_dir,
        "--root", stage,
        "--bin", project["binary"],
        project["package"],
    ], env=env)
    built = stage / "bin" / project["binary"]
    if not built.is_file():
        raise RuntimeError("Cargo 未生成 %s" % built)
    validate_arm_elf(built)
    return built


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="输出目录，通常是 extensions/kindletweaks/bin")
    args = parser.parse_args()

    if not shutil.which("rustup"):
        raise RuntimeError("找不到 rustup")
    run(["rustup", "target", "add", TARGET])
    lld = find_rust_lld()
    env = os.environ.copy()
    env["CARGO_TARGET_ARMV7_UNKNOWN_LINUX_MUSLEABI_LINKER"] = str(lld)
    env["CARGO_PROFILE_RELEASE_STRIP"] = "symbols"
    env["CARGO_PROFILE_RELEASE_PANIC"] = "abort"

    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="kindle-ebook-build-") as temp:
        temp = Path(temp)
        stage = temp / "install"
        target_dir = temp / "target"
        for project in PROJECTS:
            built = install(project, stage, target_dir, env)
            destination = args.output / project["binary"]
            pending = destination.with_name(destination.name + ".new")
            shutil.copy2(built, pending)
            pending.chmod(0o755)
            os.replace(pending, destination)
            mib = destination.stat().st_size / 1048576
            print("生成 %s %s：%s（%.2f MiB）" %
                  (project["name"], project["version"], destination, mib))


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        print("错误：%s" % exc, file=sys.stderr)
        sys.exit(1)
