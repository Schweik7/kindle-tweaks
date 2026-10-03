#!/bin/sh
# 安装两个补丁：书库「云端不可用」弹窗 + 「查看选项 → 收藏夹」视图灰色
# kpp_patch/ 里需有本机固件的 .orig（从本机提取）和对应的 .patched
# 用法: ssh root@<kindle> sh /mnt/us/kpp_patch/apply.sh
export PATH=/usr/sbin:/sbin:/usr/bin:/bin:$PATH
D=/mnt/us/kpp_patch
m() { md5sum "$1" | cut -d' ' -f1; }
# 目标文件:补丁文件前缀（kpp_patch/ 里需有 <前缀>.orig 和 <前缀>.patched）
PAIRS="/app/KPPMainApp/js/KPPMainApp.js.hbc:KPPMainApp.js.hbc /app/lib/libKSDKLibrary.so:libKSDKLibrary.so"
changed=0
for p in $PAIRS; do
  T=${p%%:*}; N=${p##*:}
  [ -f ${D}/${N}.orig ] && [ -f ${D}/${N}.patched ] || { echo "跳过 ${N}（缺 .orig/.patched）"; continue; }
  ORIG=$(m ${D}/${N}.orig); PATCHED=$(m ${D}/${N}.patched)
  grep -q " ${T} " /proc/mounts && umount -l ${T}
  CUR=$(m ${T})
  if [ "${CUR}" = "${PATCHED}" ]; then echo "${N} 已是补丁版"; continue; fi
  [ "${CUR}" = "${ORIG}" ] || { echo "${N} 系统文件和 .orig 不一致（固件变了？），跳过"; continue; }
  mntroot rw
  cp ${D}/${N}.patched ${T}.new && chmod 644 ${T}.new && mv ${T}.new ${T}
  sync
  mntroot ro
  [ "$(m ${T})" = "${PATCHED}" ] && { echo "${N} 写入成功"; changed=1; } || echo "${N} 写入后校验失败！"
done
[ "${changed}" = 1 ] && restart kppmainapp
exit 0