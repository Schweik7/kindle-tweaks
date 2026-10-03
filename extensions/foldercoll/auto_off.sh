#!/bin/sh
export PATH=/usr/sbin:/sbin:/usr/bin:/bin:$PATH
stop foldercoll
J=/etc/upstart/foldercoll.conf
mntroot rw
[ -f "$J" ] && mv "$J" /tmp/foldercoll.conf.disabled
mntroot ro