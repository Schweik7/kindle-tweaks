#!/bin/sh
# 安装 upstart 任务（在系统分区，升级固件后需要重新开启）
export PATH=/usr/sbin:/sbin:/usr/bin:/bin:$PATH
mntroot rw
cp /mnt/us/extensions/foldercoll/foldercoll.conf /etc/upstart/foldercoll.conf
chmod 644 /etc/upstart/foldercoll.conf
mntroot ro
start foldercoll