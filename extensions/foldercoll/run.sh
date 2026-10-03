#!/bin/sh
# 执行一次同步，日志在 sync.log
D=/mnt/us/extensions/foldercoll
export LD_LIBRARY_PATH=/mnt/us/python3/lib PYTHONIOENCODING=utf-8
if [ -f $D/sync.log ] && [ "$(wc -c < $D/sync.log)" -gt 200000 ]; then mv $D/sync.log $D/sync.log.old; fi
/mnt/us/python3/bin/python3.9 $D/sync.py "$@" >> $D/sync.log 2>&1