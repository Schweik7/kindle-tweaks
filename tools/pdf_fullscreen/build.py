"""
一键生成 PDF 全屏补丁的 .orig / .patched（在电脑上跑）。

    python build.py <从 Kindle 拷来的 /opt/amazon/ebook/lib 目录> <输出目录>

需要 JDK 9+（用 javac --release 8 编译，Kindle 的 JVM 只认 class 52）。
找 javac/java 的顺序：环境变量 JAVA_HOME → PATH。
输出目录里得到 3 对文件，直接拷到 Kindle 的 /mnt/us/extensions/kindletweaks/files/：
    PDFReader-impl.jar.orig/.patched  ReaderSDK-impl.jar.orig/.patched  ReaderSDK-impl-zh.jar.orig/.patched
最后会用本机 JVM 以 -Xverify:all 加载改过的类，任何 VerifyError 都会让脚本失败——
上机前就能发现字节码问题（Kindle 上出 VerifyError 的表现是阅读器打不开书）。
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
JARS = ("PDFReader-impl.jar", "ReaderSDK-impl.jar", "ReaderSDK-impl-zh.jar")
CHECK = ("com.amazon.ebook.booklet.reader.impl.ReaderUIImpl",
         "com.amazon.ebook.booklet.reader.impl.ui.GlobalFooterBar",
         "com.amazon.ebook.booklet.pdfreader.impl.PDFBookMetaData",
         "com.amazon.ebook.booklet.pdfreader.impl.PdfZeroMargin")


def tool(name):
    home = os.environ.get("JAVA_HOME")
    if home:
        for ext in ("", ".exe"):
            p = os.path.join(home, "bin", name + ext)
            if os.path.isfile(p):
                return p
    p = shutil.which(name)
    if not p:
        sys.exit(f"找不到 {name}，请安装 JDK 9+ 或设置 JAVA_HOME")
    return p


def run(cmd):
    print(">", " ".join(cmd))
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    if r.returncode:
        sys.exit(r.stdout + r.stderr)
    return r.stdout


def main():
    lib, out = sys.argv[1:3]
    for j in JARS:
        if not os.path.isfile(os.path.join(lib, j)):
            sys.exit(f"{lib} 里没有 {j}")
    cp_all = os.path.join(lib, "*")
    os.makedirs(out, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        cls = os.path.join(tmp, "classes")
        patched = os.path.join(tmp, "patched")
        srcs = [os.path.join(dp, f) for dp, _, fs in os.walk(os.path.join(HERE, "src", "com")) for f in fs if f.endswith(".java")]
        run([tool("javac"), "--release", "8", "-nowarn", "-Xlint:-options", "-encoding", "UTF-8",
             "-cp", cp_all, "-d", cls] + srcs)
        run([sys.executable, os.path.join(HERE, "patch_pdf_fullscreen.py"), lib, patched, cls])

        # 校验：改过的 jar 放在 classpath 最前面，盖住原版
        vdir = os.path.join(tmp, "verify")
        run([tool("javac"), "--release", "8", "-nowarn", "-Xlint:-options", "-d", vdir, os.path.join(HERE, "src", "VerifyLoad.java")])
        cp = os.pathsep.join([vdir] + [os.path.join(patched, j) for j in JARS] + [cp_all])
        res = run([tool("java"), "-Xverify:all", "-cp", cp, "VerifyLoad"] + list(CHECK))
        print(res)
        if "VERIFY-FAIL" in res:
            sys.exit("字节码校验失败，不要装到 Kindle 上")

        for j in JARS:
            shutil.copyfile(os.path.join(lib, j), os.path.join(out, j + ".orig"))
            shutil.copyfile(os.path.join(patched, j), os.path.join(out, j + ".patched"))
    print(f"完成：{out} 里的 6 个文件拷到 Kindle 的 /mnt/us/extensions/kindletweaks/files/")


if __name__ == "__main__":
    main()
