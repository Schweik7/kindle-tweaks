# 第三方组件

仓库本身不提交转换器二进制；`tools/build_ebook_converters.py` 从以下固定源码提交构建：

| 组件 | 版本与源码 | 许可证 | 用途 |
|---|---|---|---|
| boko | [0.5.0 / `b148716`](https://github.com/zacharydenton/boko/tree/b148716498fdac70134555293a7405913988256a) | GPL-3.0 | epub → AZW3 主转换器 |
| Kindling | [0.27.0 / `d0ffe18`](https://github.com/CuteLicense/kindling-epub-to-mobi/tree/d0ffe18c6a78252844774ca8dd02e3a93f4ac6d7) | MIT | boko 失败时的回退转换器 |

二者均编译为 `armv7-unknown-linux-musleabi` 静态 ELF，适配老 Kindle 的 ARMv7 soft-float 用户空间。分发二进制时也应保留相应许可证，并按 GPL-3.0 的要求提供 boko 对应源代码。

当前构建脚本的 strip release 产物：boko 4,937,504 字节（4.71 MiB），Kindling 10,821,184 字节（10.32 MiB），合计 15.03 MiB。
