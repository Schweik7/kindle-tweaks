#!/bin/sh
# 还原为原版文件
# 用法: ssh root@<kindle> sh /mnt/us/kpp_patch/restore.sh
export PATH=/usr/sbin:/sbin:/usr/bin:/bin:$PATH
D=/mnt/us/kpp_patch
m() { md5sum "$1" | cut -d' ' -f1; }
# 目标文件:补丁文件前缀（kpp_patch/ 里需有 <前缀>.orig 和 <前缀>.patched）
PAIRS="/app/KPPMainApp/js/KPPMainApp.js.hbc:KPPMainApp.js.hbc /app/lib/libKSDKLibrary.so:libKSDKLibrary.so"
changed=0
for p in $PAIRS; do
  T=${p%%:*}; N=${p##*:}
  [ -f ${D}/${N}.orig ] || continue
  ORIG=$(m ${D}/${N}.orig)
  grep -q " ${T} " /proc/mounts && umount -l ${T}
  [ "$(m ${T})" = "${ORIG}" ] && { echo "${N} 已是原版"; continue; }
  mntroot rw
  cp ${D}/${N}.orig ${T}.new && chmod 644 ${T}.new && mv ${T}.new ${T}
  sync
  mntroot ro
  [ "$(m ${T})" = "${ORIG}" ] && { echo "${N} 还原成功"; changed=1; } || echo "${N} 还原后校验失败！"
done
[ "${changed}" = 1 ] && restart kppmainapp
exit 0