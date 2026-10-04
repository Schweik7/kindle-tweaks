# 06 调试模式：控制深度休眠

用于需要长时间保持 Wi-Fi、SSH 或后台调试进程在线的场景。菜单提供三种模式：

- **不深度休眠**：无论是否充电都持续推迟深度休眠。
- **充电时不深度休眠**：只有 `isCharging=1` 时才持续推迟，拔电后恢复正常。
- **关闭调试模式**：停止服务，完全恢复 Kindle 原生行为。

启用任一防休眠模式后：

- 屏幕仍会正常进入屏保，不强制常亮。
- powerd 发出 `readyToSuspend` 时按当前模式决定是否发送 `deferSuspend 300`。
- 300 秒后如果仍准备休眠，会再次收到事件并继续推迟。
- 使用“充电时不深度休眠”模式时，拔掉电源便不再发送 `deferSuspend`，Kindle 恢复正常深度休眠。

KUAL 菜单：「Kindle Tweaks」→「调试模式」。第一项显示当前模式；使用充电模式时还会显示当前是否正在充电。

SSH 等价命令：

```sh
E=/mnt/us/extensions/kindletweaks
sh $E/tweak.sh debugawake always
sh $E/tweak.sh debugawake charging
sh $E/tweak.sh debugawake off
```

启用模式记录在 `debugawake/mode`，服务通过安装或移除 `/etc/upstart/kindletweaks-debugawake.conf` 实现。固件升级会替换系统分区，升级后如有需要请重新开启。平时不调试时建议关闭。
