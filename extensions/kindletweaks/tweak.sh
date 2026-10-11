#!/bin/sh
# kindle-tweaks 管理脚本（KUAL 菜单和 SSH 都调用它）
#   tweak.sh status                      打印所有功能的状态
#   tweak.sh menu                        按当前状态重新生成 KUAL 菜单
#   tweak.sh <popup|collview|pdffull|browserdl|all> on|off   开关系统文件补丁
#   tweak.sh coll sync|on|off|purge      文件夹收藏夹：立即同步 / 开机自动同步 / 关闭 / 删除生成的收藏夹
#   tweak.sh ssrandom on|off             linkss 屏保开机随机排序
#   tweak.sh airplane on|off             飞行模式（KUAL 菜单里叫「泡面模式」；on = 关无线）
#   tweak.sh manga on|off|now            epub 自动转换（大漫画充电→PDF，文字书传完→AZW3）：自动转换开关 / 立即转换
#   tweak.sh manga dir <序号>            按目录转换（序号是菜单生成时 mangaconv/dirs.txt 的行号）
#   tweak.sh debugawake always|charging|off   调试模式：始终阻止 / 仅充电阻止 / 关闭深度休眠推迟
#   tweak.sh libraryview on|off          主界面重载时默认进入收藏夹视图
#   tweak.sh nowifi on|off               隐藏状态栏的无线图标（给 JunoStatusBarDriver 注入 libkt_nowifi.so）
#   tweak.sh wxsend on|off|now           微信传书：亮屏自动同步开关 / 立即同步（配置 wxsend/config）
#   tweak.sh webapp install|uninstall|launch|state <名字>   常驻网页应用（WAF）：安装并注册 / 卸载 / 打开 / 看状态
#   tweak.sh webapp scan|list|doctor|restore               候选应用 / 已安装清单 / 自检 / 升级固件后重装
#   tweak.sh fbvideo play <文件> [A2|DU|GC16]              墨水屏视频播放（后台放，屏幕由播放器接管）
#   tweak.sh fbvideo toggle|pause|resume|restart           控制正在播的播放器（也能直接在设备上点触摸屏/按翻页键）
#   tweak.sh fbvideo stop|state|status|menujson            停止 / 状态 / 在放哪个第几帧 / 子菜单 JSON
# 补丁文件放在 files/：<系统文件名>.orig（本机原版）和 <系统文件名>.patched（电脑上生成）
export PATH=/usr/sbin:/sbin:/usr/bin:/bin:$PATH
EXT=/mnt/us/extensions/kindletweaks
F=${EXT}/files
LOG=${EXT}/tweak.log
UNITS="popup collview pdffull browserdl"
NEED=""

files_of() {
	case "$1" in
		popup) echo /app/KPPMainApp/js/KPPMainApp.js.hbc ;;
		collview) echo /app/lib/libKSDKLibrary.so ;;
		pdffull) echo /opt/amazon/ebook/lib/PDFReader-impl.jar /opt/amazon/ebook/lib/ReaderSDK-impl.jar /opt/amazon/ebook/lib/ReaderSDK-impl-zh.jar ;;
		browserdl) echo /usr/bin/mesquite ;;
	esac
}

# 改完后要重启哪个进程：书库界面（KPPMainApp）只需重启它自己，Java 阅读器要重启整个 framework；
# 浏览器离开就退出（unloadOnPause），下次打开即生效
restart_of() {
	case "$1" in
		pdffull) echo framework ;;
		browserdl) echo none ;;
		*) echo kppmainapp ;;
	esac
}

m() { md5sum "$1" 2>/dev/null | cut -d' ' -f1; }

say() {
	echo "$*"
	echo "$(date '+%m-%d %H:%M:%S') $*" >> ${LOG}
}

# 屏幕底部打一行（eips 只能显示 ASCII）
screen() {
	eips 1 2 "                                                  " >/dev/null 2>&1
	eips 1 2 "$1" >/dev/null 2>&1
}

# on / off / mixed（多个文件不一致）/ unknown（与 .orig、.patched 都对不上）/ missing（缺补丁文件）
state() {
	s=""
	for T in $(files_of $1); do
		N=${T##*/}
		[ -f ${F}/${N}.orig ] && [ -f ${F}/${N}.patched ] || { echo missing; return; }
		c=$(m ${T})
		if [ "${c}" = "$(m ${F}/${N}.patched)" ]; then t=on
		elif [ "${c}" = "$(m ${F}/${N}.orig)" ]; then t=off
		else echo unknown; return; fi
		[ -z "${s}" ] && s=${t}
		[ "${s}" = "${t}" ] || { echo mixed; return; }
	done
	echo ${s}
}

set_unit() {
	u=$1
	want=$2
	[ "${want}" = on ] && suf=patched || suf=orig
	# 先全部检查一遍，任何一个文件对不上就整组不动
	for T in $(files_of ${u}); do
		N=${T##*/}
		[ -f ${F}/${N}.orig ] && [ -f ${F}/${N}.patched ] || { say "${u}: 缺少 files/${N}.orig 或 .patched"; return 1; }
		# 临时试用留下的 bind mount 先卸掉
		grep -q " ${T} " /proc/mounts && umount -l ${T}
		c=$(m ${T})
		[ "${c}" = "$(m ${F}/${N}.orig)" ] || [ "${c}" = "$(m ${F}/${N}.patched)" ] || {
			say "${u}: ${N} 与 .orig/.patched 都不一致（固件变了？），未改动"
			return 1
		}
	done
	if [ "$(state ${u})" = "${want}" ]; then
		say "${u}: 已经是 ${want}"
		return 0
	fi
	mntroot rw
	for T in $(files_of ${u}); do
		N=${T##*/}
		S=${F}/${N}.${suf}
		[ "$(m ${T})" = "$(m ${S})" ] && continue
		# 先写 .new 再 mv：正在运行的进程仍持有旧文件，不会读到半截；可执行文件保留 755
		[ -x ${T} ] && md=755 || md=644
		cp ${S} ${T}.new && chmod ${md} ${T}.new && mv ${T}.new ${T}
	done
	sync
	# 商店后台进程 stored 也是 mesquite，不重启它，旧文件仍被占用，根分区切不回只读
	[ ${u} = browserdl ] && restart stored >/dev/null 2>&1
	mntroot ro
	if [ "$(state ${u})" = "${want}" ]; then
		say "${u}: -> ${want}"
		NEED="${NEED} $(restart_of ${u})"
	else
		say "${u}: 写入后校验失败！"
		return 1
	fi
}

do_restart() {
	case " ${NEED} " in
	*kppmainapp*) restart kppmainapp ;;
	esac
	case " ${NEED} " in
	*framework*)
		screen "kindle-tweaks: restarting framework..."
		# 脱离 KUAL 进程组，否则 framework 一停脚本也跟着没了。
		# framework 起来后会恢复上次的应用（KUAL），那里会是一片白屏，所以最后切回主页。
		setsid sh -c '
			sleep 2
			stop framework
			for i in $(seq 1 30); do pidof cvm >/dev/null || break; sleep 1; done
			start framework
			for i in $(seq 1 120); do lipc-get-prop com.lab126.appmgrd activeApp >/dev/null 2>&1 && break; sleep 1; done
			sleep 20
			lipc-set-prop com.lab126.appmgrd start app://com.lab126.booklet.home
		' >/dev/null 2>&1 </dev/null &
		;;
	esac
}

coll() {
	C=${EXT}/foldercoll
	case "$1" in
		sync | autosync | purge)
			[ "$1" = purge ] && a=--purge || a=""
			if [ -f ${C}/sync.log ] && [ "$(wc -c < ${C}/sync.log)" -gt 200000 ]; then mv ${C}/sync.log ${C}/sync.log.old; fi
			LD_LIBRARY_PATH=/mnt/us/python3/lib PYTHONIOENCODING=utf-8 /mnt/us/python3/bin/python3.9 ${C}/sync.py ${a} >> ${C}/sync.log 2>&1
			rc=$?
			[ "$1" = autosync ] || say "coll: $1 done (rc=${rc})"
			return ${rc}
			;;
		on)
			# upstart 任务在系统分区，升级固件后需要重新开启
			mntroot rw
			cp ${C}/foldercoll.conf /etc/upstart/foldercoll.conf
			chmod 644 /etc/upstart/foldercoll.conf
			mntroot ro
			start foldercoll >/dev/null 2>&1
			say "coll: auto sync on"
			;;
		off)
			stop foldercoll >/dev/null 2>&1
			mntroot rw
			[ -f /etc/upstart/foldercoll.conf ] && mv /etc/upstart/foldercoll.conf /tmp/foldercoll.conf.disabled
			mntroot ro
			say "coll: auto sync off"
			;;
	esac
}

# epub -> PDF/AZW3（mangaconv/）
manga() {
	M=${EXT}/mangaconv
	# 环境变量只给 Python：系统自带的 sqlite3 等程序加载到 Python 的库会出错
	PY="env LD_LIBRARY_PATH=/mnt/us/python3/lib PYTHONIOENCODING=utf-8 /mnt/us/python3/bin/python3.9 -u ${M}/mangaconv.py"
	if [ -f ${M}/convert.log ] && [ "$(wc -c < ${M}/convert.log)" -gt 200000 ]; then mv ${M}/convert.log ${M}/convert.log.old; fi
	case "$1" in
		autorun)
			# 后台任务调用：文字书随时转、漫画等充电；返回码给任务判断是否需要重试
			${PY} run >> ${M}/convert.log 2>&1
			return $?
			;;
		now)
			# 不等充电，立即处理队列；脱离 KUAL 在后台跑
			setsid sh -c "nice -n 19 ${PY} run --force >> ${M}/convert.log 2>&1" >/dev/null 2>&1 </dev/null &
			say "manga: 已在后台开始转换"
			;;
		dir)
			# 菜单里按序号选目录（路径有空格、中文，不直接放进 KUAL 参数）
			D=$(sed -n "${2}p" ${M}/dirs.txt 2>/dev/null)
			[ -d "${D}" ] || { say "manga: 目录序号 $2 无效，请刷新菜单"; return 1; }
			setsid sh -c "nice -n 19 ${PY} run --dir \"${D}\" >> ${M}/convert.log 2>&1" >/dev/null 2>&1 </dev/null &
			say "manga: 开始转换目录 ${D}"
			;;
		on)
			mntroot rw
			cp ${M}/mangaconv.conf /etc/upstart/mangaconv.conf
			chmod 644 /etc/upstart/mangaconv.conf
			mntroot ro
			start mangaconv >/dev/null 2>&1
			say "manga: auto convert on"
			;;
		off)
			stop mangaconv >/dev/null 2>&1
			mntroot rw
			[ -f /etc/upstart/mangaconv.conf ] && mv /etc/upstart/mangaconv.conf /tmp/mangaconv.conf.disabled
			mntroot ro
			say "manga: auto convert off"
			;;
	esac
}

manga_state() { [ -f /etc/upstart/mangaconv.conf ] && echo on || echo off; }
manga_min() { sed -n 's/.*"min_size_mb"[^0-9]*\([0-9]*\).*/\1/p' ${EXT}/mangaconv/config.json 2>/dev/null | head -1; }

# 含 epub/md/docx（且旁边还没有同名输出）的目录 -> KUAL 菜单项；序号对应 dirs.txt 的行号
manga_dir_items() {
	M=${EXT}/mangaconv
	find /mnt/us/documents \( -iname "*.epub" -o -iname "*.md" -o -iname "*.markdown" -o -iname "*.docx" \) 2>/dev/null | while read -r f; do
		b=${f%.*}
		[ -f "${b}.pdf" ] || [ -f "${b}.mobi" ] || [ -f "${b}.azw3" ] || [ -f "${b}.azw" ] || echo "${f%/*}"
	done | sort | uniq -c > ${M}/dirs.count
	sed 's/^ *[0-9]* //' ${M}/dirs.count > ${M}/dirs.txt
	n=0
	sep=""
	while read -r cnt d; do
		n=$((n + 1))
		name=${d#/mnt/us/documents}
		name=${name#/}
		[ -z "${name}" ] && name="documents 根目录（连同子目录）"
		name=$(printf '%s' "${name}" | sed 's/["\\]/ /g')
		printf '%s\t\t\t\t{"name": "%s（%s 本）", "priority": %d, "refresh": true, "exitmenu": false, "action": "%s/tweak.sh", "params": "manga dir %d"}' "${sep}" "${name}" "${cnt}" ${n} "${EXT}" ${n}
		sep=",
"
	done < ${M}/dirs.count
	[ ${n} = 0 ] && printf '\t\t\t\t{"name": "documents 里没有待转换的 epub/md/docx", "priority": 1, "refresh": true, "exitmenu": false, "action": "%s/tweak.sh", "params": "menu"}' "${EXT}"
	echo
}
manga_status() { head -c 120 ${EXT}/mangaconv/status.txt 2>/dev/null | tr -d '"\\\n' || true; }

text_backend_label() {
	b=false
	k=false
	[ -f ${EXT}/bin/boko ] && b=true
	[ -f ${EXT}/bin/kindling-cli ] && k=true
	if ${b} && ${k}; then
		echo "boko→Kindling 回退"
	elif ${b}; then
		echo "boko（缺 Kindling 回退）"
	elif ${k}; then
		echo "Kindling（缺 boko）"
	else
		echo "缺 boko/Kindling"
	fi
}

ssrandom() {
	L=/mnt/us/linkss
	[ -d ${L} ] || { say "ssrandom: 没装 linkss"; return 1; }
	case "$1" in
		on) [ -f ${L}/random.off ] && mv ${L}/random.off ${L}/random; touch ${L}/random ;;
		off) [ -f ${L}/random ] && mv ${L}/random ${L}/random.off ;;
	esac
	say "ssrandom: $1"
}

# 飞行模式（无线开关），KUAL 菜单里叫「泡面模式」。隐藏无线界面的补丁
# （tools/patch_kpp_nowifi.py）会把快捷设置里那一排按钮（含飞行模式）一起去掉，
# 界面上就没有开关无线的入口了，所以放到 KUAL 菜单里。
# 走的是 KPP 快捷设置里飞行模式小部件同一条路（反汇编 /app/bin/KPPMainAppV2 得到的结论）：
#   KPPSettings::QuickSettings::AirplaneWidgetController::execute
#     → ConnectionManagerServiceProvider::toggleWirelessConnection
#     → lipc set com.lab126.cmd wirelessEnable
# 属性 1 = 无线开，0 = 无线关（飞行模式）；读同一个属性拿当前状态。
# ⚠ 关无线会同时断掉 WiFi 上的 SSH（USB 网的 SSH 不受影响）。
# 命令名保持 airplane（SSH 用），只有菜单项显示成「泡面模式」。
AIRPLANE_SVC=com.lab126.cmd
airplane_raw() { lipc-get-prop -i ${AIRPLANE_SVC} wirelessEnable 2>/dev/null; }
airplane_state() { [ "$(airplane_raw)" = 0 ] && echo on || echo off; }

airplane() {
	case "$1" in
		on) want=0 ;;   # 开飞行模式 = 关无线
		off) want=1 ;;
		*) say "airplane: 用法 airplane on|off"; return 1 ;;
	esac
	if [ "$(airplane_raw)" = "${want}" ]; then
		say "airplane: 已经$(label $(airplane_state))"
		return 0
	fi
	lipc-set-prop -i ${AIRPLANE_SVC} wirelessEnable ${want} || { say "airplane: 写 wirelessEnable 失败"; return 1; }
	# 连接管理器要一点时间才把状态切过来，等它真的变了再报成功（关无线时 SSH 可能已经断了，只认属性值）
	i=0
	while [ ${i} -lt 20 ]; do
		[ "$(airplane_raw)" = "${want}" ] && break
		sleep 1
		i=$((i + 1))
	done
	[ "$(airplane_raw)" = "${want}" ] || { say "airplane: 20 秒内没切成 ${want}（当前 $(airplane_raw)）"; return 1; }
	[ "${want}" = 0 ] && say "airplane: 已开启（离线）" || say "airplane: 已关闭（联网）"
}

coll_state() { [ -f /etc/upstart/foldercoll.conf ] && echo on || echo off; }
ss_state() { [ -f /mnt/us/linkss/random ] && echo on || echo off; }

debugawake() {
	D=${EXT}/debugawake/kindletweaks-debugawake.conf
	M=${EXT}/debugawake/mode
	J=/etc/upstart/kindletweaks-debugawake.conf
	case "$1" in
		always | charging)
			[ -f ${D} ] || { say "debugawake: 缺 ${D}"; return 1; }
			echo "$1" > ${M}.new && mv ${M}.new ${M} || { say "debugawake: 写模式失败"; return 1; }
			mntroot rw
			cp ${D} ${J}
			chmod 644 ${J}
			mntroot ro
			start kindletweaks-debugawake >/dev/null 2>&1 || true
			say "debugawake: $1"
			;;
		off)
			stop kindletweaks-debugawake >/dev/null 2>&1 || true
			mntroot rw
			[ -f ${J} ] && mv ${J} /tmp/kindletweaks-debugawake.conf.disabled
			mntroot ro
			rm -f ${M} ${M}.new
			say "debugawake: off"
			;;
	esac
}

debugawake_state() {
	[ -f /etc/upstart/kindletweaks-debugawake.conf ] || { echo off; return; }
	m=$(cat ${EXT}/debugawake/mode 2>/dev/null)
	case "${m}" in always | charging) echo "${m}" ;; *) echo charging ;; esac
}

debugawake_label() {
	case "$(debugawake_state)" in
		always) echo "不深度休眠" ;;
		charging) echo "充电时不深度休眠" ;;
		off) echo "已关闭" ;;
	esac
}

debugawake_status() {
	s=$(debugawake_state)
	if [ "${s}" = charging ]; then
		[ "$(lipc-get-prop com.lab126.powerd isCharging 2>/dev/null)" = 1 ] && p="当前充电中" || p="当前未充电"
		echo "充电时不深度休眠，${p}"
	else
		debugawake_label
	fi
}

# Home 页固定使用封面网格；图书馆里的内容筛选也会切回 LIBRARY 模式。
# 只校正顶层默认模式，不锁文件、不动排序/筛选，仍允许当前会话临时切换视图。
libraryview_apply() {
	C=/var/local/LIBRARY_CONFIG
	N=${C}.kindletweaks.new
	if [ ! -f ${C} ]; then
		# KPP 有时会整个删掉这个文件（之后按默认的「全部 + 网格」显示），只写这一个键它也认
		printf '{"library_mode_selected":"COLLECTIONS"}' > ${N} || return 1
		chown framework:javausers ${N}
		chmod 664 ${N}
		mv ${N} ${C}
		return 10
	fi
	grep -q '"library_mode_selected"[[:space:]]*:[[:space:]]*"COLLECTIONS"' ${C} 2>/dev/null && return 0
	sed 's/"library_mode_selected"[[:space:]]*:[[:space:]]*"[^"]*"/"library_mode_selected":"COLLECTIONS"/' ${C} > ${N} || return 1
	grep -q '"library_mode_selected":"COLLECTIONS"' ${N} || { rm -f ${N}; return 1; }
	chown framework:javausers ${N}
	chmod 664 ${N}
	mv ${N} ${C}
	return 10
}

# 免重启切换：给 KPPMainApp 注入 libkt_libview.so（LD_PRELOAD），它在进入图书馆时调用原生 SetMode。
# 改的是系统分区的 /etc/upstart/kppmainapp.conf 最后一行 exec，调用前须已 mntroot rw。
LV_SO=${EXT}/libraryview/libkt_libview.so
LV_FLAG=/tmp/kindletweaks-libraryview.reset
KPP_JOB=/etc/upstart/kppmainapp.conf

libraryview_preload() {
	case "$1" in
		on)
			[ -f ${LV_SO} ] || return 1
			grep -q "^exec env LD_PRELOAD=${LV_SO} /app/bin/KPPMainApp\$" ${KPP_JOB} && return 0
			sed -i "s|^exec /app/bin/KPPMainApp\$|exec env LD_PRELOAD=${LV_SO} /app/bin/KPPMainApp|" ${KPP_JOB}
			;;
		off)
			sed -i 's|^exec env LD_PRELOAD=[^ ]* /app/bin/KPPMainApp$|exec /app/bin/KPPMainApp|' ${KPP_JOB}
			;;
	esac
	# upstart 0.6.6 没有 initctl，改了任务文件要发 SIGHUP 让它重读
	kill -HUP 1
}

# 当前运行的 KPP 是否已加载注入库
libraryview_injected() { grep -q libkt_libview /proc/$(pidof KPPMainApp 2>/dev/null)/maps 2>/dev/null; }

libraryview() {
	D=${EXT}/libraryview/kindletweaks-libraryview.conf
	J=/etc/upstart/kindletweaks-libraryview.conf
	case "$1" in
		on)
			[ -f ${D} ] || { say "libraryview: 缺 ${D}"; return 1; }
			libraryview_apply
			rc=$?
			[ ${rc} = 0 ] || [ ${rc} = 10 ] || { say "libraryview: 无法更新 /var/local/LIBRARY_CONFIG"; return 1; }
			stop kindletweaks-libraryview >/dev/null 2>&1 || true
			mntroot rw
			cp ${D} ${J}
			chmod 644 ${J}
			libraryview_preload on || say "libraryview: 缺 ${LV_SO}，进入屏保时改用重载 KPP"
			mntroot ro
			start kindletweaks-libraryview >/dev/null 2>&1 || { say "libraryview: 无法启动监听任务"; return 1; }
			say "libraryview: default collections on"
			restart kppmainapp >/dev/null 2>&1 || true
			;;
		off)
			stop kindletweaks-libraryview >/dev/null 2>&1 || true
			mntroot rw
			[ -f ${J} ] && mv ${J} /tmp/kindletweaks-libraryview.conf.disabled
			libraryview_preload off
			mntroot ro
			rm -f ${LV_FLAG}
			say "libraryview: default collections off"
			libraryview_injected && restart kppmainapp >/dev/null 2>&1
			;;
		apply)
			libraryview_apply
			return $?
			;;
		screensaver)
			# 进入屏保时由监听任务调用：注入库在就只留标记，下次进入图书馆瞬间切换；
			# 否则校正配置，返回 10 让任务重载 KPP
			if libraryview_injected; then
				touch ${LV_FLAG} && chown framework ${LV_FLAG}
				return 0
			fi
			libraryview_apply
			return $?
			;;
	esac
}

libraryview_state() { [ -f /etc/upstart/kindletweaks-libraryview.conf ] && echo on || echo off; }
libraryview_status() {
	[ "$(libraryview_state)" = on ] || { echo off; return; }
	libraryview_injected && echo "on（注入，免重启）" || echo "on（屏保时重载 KPP）"
}

# ---------------------------------------------------------------- 状态栏的无线图标隐藏（nowifi）
# 状态栏进程 JunoStatusBarDriver 的图标全交给 librsvg 渲染，注入 libkt_nowifi.so 后把
# Wi-Fi 扇形、WAN 信号条、AirplaneMode.svg 换成同尺寸空白 SVG（特征与原理见 docs/19）。
# 和 libraryview 一样改 upstart 任务的 exec 行；这台的 upstart 没有 initctl，改完要 kill -HUP 1 重读。
# hbc 那部分（快捷设置那一排、顶栏购物车、⋮ 菜单三项）在 popup 的 .patched 里，
# 生成步骤见 README：patch_kpp.py 打底，再 patch_kpp_nowifi.py 叠加。
NW_SO=${EXT}/nowifi/libkt_nowifi.so
STATUS_JOB=/etc/upstart/statusbar.conf

nowifi_preload() {
	case "$1" in
		on)
			[ -f ${NW_SO} ] || return 1
			grep -q "LD_PRELOAD=${NW_SO} /app/bin/JunoStatusBarDriver" ${STATUS_JOB} && return 0
			# exec 行在 script 段里、前面有缩进，所以不能用 ^exec 锚
			sed -i "s|\(^[[:space:]]*\)exec /app/bin/JunoStatusBarDriver\$|\1exec env LD_PRELOAD=${NW_SO} /app/bin/JunoStatusBarDriver|" ${STATUS_JOB}
			;;
		off)
			sed -i "s|\(^[[:space:]]*\)exec env LD_PRELOAD=[^ ]* /app/bin/JunoStatusBarDriver\$|\1exec /app/bin/JunoStatusBarDriver|" ${STATUS_JOB}
			;;
	esac
	# upstart 0.6.6 没有 initctl，改了任务文件要发 SIGHUP 让它重读
	kill -HUP 1
}

nowifi_state() { grep -q "LD_PRELOAD=${NW_SO}" ${STATUS_JOB} 2>/dev/null && echo on || echo off; }
nowifi_injected() { grep -q libkt_nowifi /proc/$(pidof JunoStatusBarDriver 2>/dev/null)/maps 2>/dev/null; }
nowifi_status() {
	[ "$(nowifi_state)" = on ] || { echo off; return; }
	nowifi_injected && echo "on（状态栏已注入）" || echo "on（下次状态栏重启生效）"
}

# 改了 exec 行以后要真的重启状态栏进程：upstart 的 respawn 不会换环境
nowifi_restart_statusbar() {
	stop statusbar >/dev/null 2>&1
	pid=$(pidof JunoStatusBarDriver 2>/dev/null)
	[ -n "${pid}" ] && kill ${pid} 2>/dev/null
	i=0
	while [ ${i} -lt 10 ]; do
		[ -z "$(pidof JunoStatusBarDriver 2>/dev/null)" ] && break
		sleep 1
		i=$((i + 1))
	done
	start statusbar >/dev/null 2>&1
	sleep 2
}

nowifi() {
	case "$1" in
		on | off) ;;
		*) say "nowifi: 用法 nowifi on|off"; return 1 ;;
	esac
	mntroot rw
	nowifi_preload "$1" || { mntroot ro; say "nowifi: 缺 ${NW_SO}（先在电脑上编译，见 docs/19）"; return 1; }
	mntroot ro
	[ "$(nowifi_state)" = "$1" ] || { say "nowifi: 写 ${STATUS_JOB} 后校验失败"; return 1; }
	nowifi_restart_statusbar
	if nowifi_injected; then
		say "nowifi: $1（状态栏已注入）"
	else
		say "nowifi: $1（状态栏进程没加载到，重启后或换个进程再看）"
	fi
}

# 微信传书：VPS 上的 server/wxsend 收下微信里发来的书，这里拉到 documents
WX=${EXT}/wxsend
TAB=$(printf '\t')

wxsend_note() { echo "$(date '+%m-%d %H:%M') $*" > ${WX}/status.txt; }

# 本机设备码：第一次用时随机生成，写进 config。服务器按它分发书，管理页上用它认出这台 Kindle
wxsend_device() {
	d=$(sed -n 's/^DEVICE=\([A-Za-z0-9]*\).*/\1/p' ${WX}/config 2>/dev/null | head -1)
	if [ ${#d} -lt 6 ]; then
		d=$(tr -dc A-Z0-9 < /dev/urandom | head -c 8)
		printf '\n# 本机设备码（自动生成），管理页上按它绑定\nDEVICE=%s\n' "${d}" >> ${WX}/config
	fi
	echo "${d}"
}

# 不覆盖已有的书：重名时加「 (2)」「 (3)」……
wxsend_dest() {
	d="$1/$2"
	n=2
	while [ -e "${d}" ]; do
		d="$1/${2%.*} (${n}).${2##*.}"
		n=$((n + 1))
	done
	echo "${d}"
}

wxsend_pull() {
	[ -f ${WX}/config ] || { wxsend_note "缺 wxsend/config"; return 1; }
	URL=""; TOKEN=""; DIR=/mnt/us/documents; DEVICE=""
	. ${WX}/config
	[ -n "${URL}" ] || { wxsend_note "config 里没填 URL"; return 1; }
	DEVICE=$(wxsend_device)
	Q="?device=${DEVICE}"
	mkdir -p "${DIR}" /mnt/us/.wxsend-part
	C="curl -fsS --connect-timeout 15"
	# 服务器开了口令校验（config.json 的 auth）才需要 TOKEN
	[ -n "${TOKEN}" ] && C="${C} -H X-Token:${TOKEN}"
	# 系统自带的 CA 证书偏旧；有 certifi 的证书包就用它
	CA=/mnt/us/python3/lib/python3.9/site-packages/certifi/cacert.pem
	[ -f ${CA} ] && C="${C} --cacert ${CA}"
	L=/tmp/wxsend.list
	${C} -m 30 "${URL}/list${Q}" -o ${L} 2>/tmp/wxsend.err || { wxsend_note "连不上服务器：$(head -c 80 /tmp/wxsend.err)"; return 2; }
	got=0
	bad=0
	while IFS="${TAB}" read -r id size name; do
		[ -n "${id}" ] && [ -n "${name}" ] || continue
		# 先下到 documents 外面，校验完再 mv 进去（同一分区，mv 是原子的），扫描器和 mangaconv 不会看到半截文件
		P=/mnt/us/.wxsend-part/${id}
		if ${C} -m 900 "${URL}/file/${id}${Q}" -o ${P} </dev/null 2>/dev/null && [ "$(wc -c < ${P})" = "${size}" ]; then
			D=$(wxsend_dest "${DIR}" "${name}")
			mv ${P} "${D}" && ${C} -m 30 -X POST "${URL}/ack/${id}${Q}" -o /dev/null </dev/null 2>/dev/null
			got=$((got + 1))
		else
			rm -f ${P}
			bad=$((bad + 1))
		fi
	done < ${L}
	if [ ${got} -gt 0 ] || [ ${bad} -gt 0 ]; then
		wxsend_note "取到 ${got} 本$([ ${bad} -gt 0 ] && echo "，${bad} 本下载失败（下次重试）")"
	else
		wxsend_note "同步正常，没有新书"
	fi
	[ ${bad} = 0 ]
}

wxsend() {
	D=${WX}/kindletweaks-wxsend.conf
	J=/etc/upstart/kindletweaks-wxsend.conf
	case "$1" in
		on)
			[ -f ${WX}/config ] || { say "wxsend: 先把 wxsend/config.example 复制成 config 并填好"; return 1; }
			mntroot rw
			cp ${D} ${J}
			chmod 644 ${J}
			mntroot ro
			start kindletweaks-wxsend >/dev/null 2>&1 || true
			say "wxsend: on"
			;;
		off)
			stop kindletweaks-wxsend >/dev/null 2>&1 || true
			mntroot rw
			[ -f ${J} ] && mv ${J} /tmp/kindletweaks-wxsend.conf.disabled
			mntroot ro
			say "wxsend: off"
			;;
		now)
			wxsend_pull
			;;
		autopull)
			# 后台任务调用。屏保中不拉；刚唤醒时 WiFi 还在重连，最多等 60 秒
			case "$(lipc-get-prop com.lab126.powerd state 2>/dev/null)" in
				*creen[Ss]aver* | *uspend*) return 0 ;;
			esac
			for i in 1 2 3 4 5 6; do
				wxsend_pull
				[ $? = 2 ] || return 0
				sleep 10
			done
			;;
	esac
}

wxsend_state() { [ -f /etc/upstart/kindletweaks-wxsend.conf ] && echo on || echo off; }
wxsend_status() { head -c 120 ${WX}/status.txt 2>/dev/null | tr -d '"\\\n' || true; }

# ---------------------------------------------------------------- 常驻网页应用（WAF）
# 把 /mnt/us 下的 HTML+JS 应用注册成 appreg.db 里的一等 WAF，由 appmgrd 启动。
#
# 和 Mesquito 的区别：Mesquito 是覆盖「商店」的 HTML5 应用缓存来借到 WAF 上下文，
# 商店一刷新缓存就没了（半持久）；这里是正规注册，注册信息在 /var/local/appreg.db，
# 不依赖任何缓存，重启和缓存刷新都不影响（原理、实测与选型对比见 docs/16-webapp-waf.md）。
#
# 写法照抄设备上 com.lab126.adviewer 这类「独立 WAF」：
#   handlerIds     一行      <id>
#   properties     command        /usr/bin/mesquite -l <id> -c file://<安装目录>/
#                  framework      （空）
#                  unloadPolicy   unloadOnPause
#   associations   application | none | false
WA=${EXT}/webapp
WA_TPL=${WA}/config.template.xml
WA_LIST=${WA}/installed.txt          # 安装清单（在 /mnt/us，固件更新不会丢）
WA_ROOTS="${WA} /mnt/us/webapps /mnt/us/apps"   # 内置示例 / 自己的应用 / Mesquito·KWebBrew 的应用
WA_DST=/var/local/mesquite
WA_PREFIX=ktweb-                     # 安装目录前缀，避免和系统 WAF 撞名
WA_ID=com.kindletweaks.              # 应用 ID 前缀；卸载时只删这个前缀的行
WA_BAK=/mnt/us/kindletweaks_backup

# 名字只允许字母数字和 . _ -，杜绝路径穿越和 JSON 注入
webapp_valid() {
	case "$1" in
		'' | . | .. | */* | *[!A-Za-z0-9._-]*) return 1 ;;
	esac
	return 0
}

webapp_src() {
	for r in ${WA_ROOTS}; do
		[ -d "${r}/$1" ] && { echo "${r}/$1"; return 0; }
	done
	return 1
}

# 从 manifest.json 取字段（Mesquito / KWebBrew 的格式）
webapp_manifest() {
	sed -n "s/.*\"$2\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p" "$1/manifest.json" 2>/dev/null | head -1
}

# 用模板渲染 config.xml。名字来自 manifest.json，先滤掉会破坏 sed/XML/JSON 的字符
webapp_config() {
	d=$1
	id=$2
	slug=$3
	[ -f ${WA_TPL} ] || return 1
	n=$(webapp_manifest "${d}" name)
	n=$(printf '%s' "${n}" | tr -d '&/\\"<>|')
	[ -n "${n}" ] || n=${slug}
	e=$(webapp_manifest "${d}" entrypoint)
	case "${e}" in '' | */* | *..*) e=index.html ;; esac
	sed -e "s|__APPID__|${id}|g" -e "s|__APPDIR__|${WA_PREFIX}${slug}|g" \
		-e "s|__ENTRY__|${e}|g" -e "s|__NAME__|${n}|g" \
		${WA_TPL} > "${d}/config.xml.new" || return 1
	mv "${d}/config.xml.new" "${d}/config.xml"
}

webapp_list_add() { grep -qx "$1" ${WA_LIST} 2>/dev/null || echo "$1" >> ${WA_LIST}; }
webapp_list_del() {
	[ -f ${WA_LIST} ] || return 0
	grep -vx "$1" ${WA_LIST} > ${WA_LIST}.new 2>/dev/null
	mv ${WA_LIST}.new ${WA_LIST}
}

webapp_state() {
	[ "$(sqlite3 -readonly /var/local/appreg.db \
		"select count(*) from properties where handlerId='${WA_ID}$1' and name='command';" 2>/dev/null)" = 1 ] &&
		echo on || echo off
}

webapp_count() {
	n=$(sqlite3 -readonly /var/local/appreg.db \
		"select count(*) from properties where handlerId like '${WA_ID}%' and name='command';" 2>/dev/null)
	echo ${n:-0}
}

# 候选应用：名字|来源目录|是否已常驻
webapp_scan() {
	for r in ${WA_ROOTS}; do
		[ -d "${r}" ] || continue
		for d in "${r}"/*/; do
			d=${d%/}
			[ -f "${d}/index.html" ] || continue
			s=${d##*/}
			webapp_valid "${s}" || continue
			echo "${s}|${r}|$(webapp_state ${s})"
		done
	done
}

# 清 WebKit 的 HTML5 应用缓存。<安装目录>/resource 就是 config.xml 里的 ApplicationCachePath。
# 实测：改完 index.html 不清它，打开还是旧页面（这个坑很费时间，所以安装时无条件清）
webapp_clearcache() {
	rm -rf "${WA_DST}/${WA_PREFIX}$1/resource" "${WA_DST}/${WA_PREFIX}$1/.cache"
}

webapp_install() {
	s=$1
	webapp_valid "${s}" || { say "webapp: 名字非法：${s}"; return 1; }
	src=$(webapp_src "${s}") || { say "webapp: 找不到应用目录 ${s}"; return 1; }
	[ -f "${src}/index.html" ] || { say "webapp: ${src} 里没有 index.html"; return 1; }
	id="${WA_ID}${s}"
	dst="${WA_DST}/${WA_PREFIX}${s}"

	# 第一次动 appreg.db 前先备份一次，出问题直接 cp 回去
	if [ ! -f ${WA_BAK}/appreg.db.bak ]; then
		mkdir -p ${WA_BAK}
		cp /var/local/appreg.db ${WA_BAK}/appreg.db.bak && say "webapp: 已备份 appreg.db 到 ${WA_BAK}/"
	fi

	# 装文件：源目录自带的 config.xml 优先，没有才用模板生成
	rm -rf "${dst}"
	mkdir -p "${dst}"
	cp -r "${src}/." "${dst}/" || { say "webapp: 复制文件失败"; return 1; }
	rm -f "${dst}/config.xml.new"
	[ -f "${dst}/config.xml" ] || webapp_config "${dst}" "${id}" "${s}" || { say "webapp: 渲染 config.xml 失败"; return 1; }
	webapp_clearcache "${s}"
	chown -R framework:javausers "${dst}" 2>/dev/null
	find "${dst}" -type d -exec chmod 755 {} \; 2>/dev/null
	find "${dst}" -type f -exec chmod 644 {} \; 2>/dev/null

	sqlite3 /var/local/appreg.db "insert or ignore into handlerIds(handlerId) values('${id}');" || { say "webapp: 写 handlerIds 失败"; return 1; }
	sqlite3 /var/local/appreg.db "insert or replace into properties(handlerId,name,value) values('${id}','command','/usr/bin/mesquite -l ${id} -c file://${dst}/');" || return 1
	sqlite3 /var/local/appreg.db "insert or replace into properties(handlerId,name,value) values('${id}','framework','');" || return 1
	sqlite3 /var/local/appreg.db "insert or replace into properties(handlerId,name,value) values('${id}','unloadPolicy','unloadOnPause');" || return 1
	sqlite3 /var/local/appreg.db "insert or replace into associations(handlerId,interface,contentId,defaultAssoc) values('${id}','application','none','false');" || return 1
	sync

	n=$(sqlite3 -readonly /var/local/appreg.db "select count(*) from properties where handlerId='${id}';" 2>/dev/null)
	if [ "${n}" = 3 ]; then
		webapp_list_add "${s}"
		say "webapp: ${s} 已安装并常驻（${id}）"
	else
		say "webapp: ${s} 注册后校验失败（properties 只有 ${n} 行），未记入安装清单"
		return 1
	fi
}

webapp_uninstall() {
	s=$1
	webapp_valid "${s}" || { say "webapp: 名字非法：${s}"; return 1; }
	id="${WA_ID}${s}"
	# 只删这个前缀的行，不碰系统 WAF
	sqlite3 /var/local/appreg.db "delete from properties where handlerId='${id}';"
	sqlite3 /var/local/appreg.db "delete from associations where handlerId='${id}';"
	sqlite3 /var/local/appreg.db "delete from handlerIds where handlerId='${id}';"
	sync
	rm -rf "${WA_DST}/${WA_PREFIX}${s}"
	rm -rf "/mnt/us/.active_content_sandbox/${id}"
	webapp_list_del "${s}"
	say "webapp: ${s} 已卸载（源目录保留）"
}

webapp_launch() {
	s=$1
	[ "$(webapp_state ${s})" = on ] || { say "webapp: ${s} 还没安装"; return 1; }
	lipc-set-prop com.lab126.appmgrd start "app://${WA_ID}${s}/"
	say "webapp: 启动 ${s}"
}

# 升级/重刷固件后重新装一遍（安装清单在 /mnt/us，不受影响）
webapp_restore() {
	[ -f ${WA_LIST} ] || { say "webapp: 没有安装记录"; return 0; }
	n=0
	while read -r s; do
		[ -n "${s}" ] || continue
		webapp_src "${s}" >/dev/null 2>&1 || { say "webapp: ${s} 的源目录没了，跳过"; continue; }
		webapp_install "${s}" && n=$((n + 1))
	done < ${WA_LIST}
	say "webapp: 重新安装 ${n} 个"
}

webapp_doctor() {
	echo "== 常驻网页应用（WAF）自检 =="
	echo "sqlite3        : $(command -v sqlite3 2>/dev/null || echo 缺失)"
	echo "mesquite       : $(ls -l /usr/bin/mesquite 2>/dev/null | awk '{print $5" 字节"}' || echo 缺失)"
	echo "appmgrd 前台   : $(lipc-get-prop com.lab126.appmgrd activeApp 2>/dev/null || echo 查不到)"
	echo "config 模板    : $([ -f ${WA_TPL} ] && echo 有 || echo "缺 ${WA_TPL}")"
	echo "安装清单       : $([ -f ${WA_LIST} ] && echo "${WA_LIST}（$(grep -c . ${WA_LIST} 2>/dev/null) 项）" || echo 还没安装过)"
	echo "appreg.db 备份 : $(ls -l ${WA_BAK}/appreg.db.bak 2>/dev/null | awk '{print $5" 字节"}' || echo 还没备份)"
	echo
	echo "-- 设备上现成的参考行（我们的写法就是照它来的）--"
	sqlite3 -readonly /var/local/appreg.db "select handlerId||'  |  '||value from properties where handlerId='com.lab126.adviewer' and name='command';" 2>/dev/null
	# 字段集合漂移检测：不盲抄参考 WAF 的行，但如果新固件给它加了字段，这里会立刻显出来
	ref=com.lab126.adviewer
	if [ "$(sqlite3 -readonly /var/local/appreg.db "select count(*) from properties where handlerId='${ref}';" 2>/dev/null)" != 0 ]; then
		exp="command framework unloadPolicy"
		got=$(sqlite3 -readonly /var/local/appreg.db "select name from properties where handlerId='${ref}' order by name;" 2>/dev/null | tr '\n' ' ' | sed 's/ *$//')
		if [ "${got}" = "${exp}" ]; then
			echo "字段集合与 ${ref} 一致：${got}"
		else
			echo "⚠ 字段集合与 ${ref} 不一致，新固件可能改了注册方式："
			echo "    参考 WAF : ${got}"
			echo "    我们写入 : ${exp}"
		fi
	fi
	echo
	echo "-- kindle-tweaks 已注册的应用 --"
	sqlite3 -readonly /var/local/appreg.db "select handlerId||'  |  '||value from properties where handlerId like '${WA_ID}%' and name='command';" 2>/dev/null
	echo
	echo "-- 候选应用（名字 | 来源目录 | 状态）--"
	webapp_scan | sed 's/|/  |  /g'
	echo
	echo "-- 应用数据 / 缓存目录 --"
	ls -d /mnt/us/.active_content_sandbox/${WA_ID}* 2>/dev/null || echo "(无)"
	echo
	echo "-- 最近 mesquite 日志 --"
	grep -iE "mesquite.*(error|fail)|cannot find callback function" /var/log/messages 2>/dev/null | tail -6
}

webapp() {
	case "$1" in
		install) webapp_install "$2" ;;
		uninstall) webapp_uninstall "$2" ;;
		launch) webapp_launch "$2" ;;
		state) webapp_state "$2" ;;
		clearcache)
			webapp_clearcache "$2"
			say "webapp: 已清 $2 的页面缓存"
			;;
		scan) webapp_scan ;;
		restore) webapp_restore ;;
		doctor) webapp_doctor ;;
		list) cat ${WA_LIST} 2>/dev/null ;;
	esac
}

# 「常驻网页应用」子菜单：每个候选应用一个子菜单
webapp_menu_items() {
	webapp_scan > /tmp/wa.scan 2>/dev/null
	n=0
	sep=""
	while IFS='|' read -r s r st; do
		[ -n "${s}" ] || continue
		n=$((n + 1))
		[ "${st}" = on ] && lbl="已常驻" || lbl="未安装"
		[ "${r}" = "${WA}" ] && lbl="${lbl}·内置示例"
		printf '%s\t\t\t\t{"name": "%s [%s]", "priority": %d, "items": [' "${sep}" "${s}" "${lbl}" ${n}
		printf '{"name": "安装并常驻", "priority": 1, "refresh": true, "exitmenu": false, "action": "%s/tweak.sh", "params": "webapp install %s"}, ' "${EXT}" "${s}"
		printf '{"name": "立即打开", "priority": 2, "exitmenu": false, "action": "%s/tweak.sh", "params": "webapp launch %s"}, ' "${EXT}" "${s}"
		printf '{"name": "卸载（源目录保留）", "priority": 3, "refresh": true, "exitmenu": false, "action": "%s/tweak.sh", "params": "webapp uninstall %s"}]}' "${EXT}" "${s}"
		sep=",
"
	done < /tmp/wa.scan
	[ ${n} = 0 ] && printf '\t\t\t\t{"name": "没找到应用：把含 index.html 的目录放进 /mnt/us/webapps/", "priority": 1, "refresh": true, "exitmenu": false, "action": "%s/tweak.sh", "params": "menu"}' "${EXT}"
	echo
}

# ---------------------------------------------------------------- 墨水屏视频播放（fbink）
# 用 py-fbink 直接写 framebuffer 播放 .ktvid 帧序列（格式与转码见 tools/make_ktvid.py、docs/17）。
#
# 为什么视频走 fbink 而不是 WAF：视频要的是「快速局部刷新 + 可控波形」，
# 只有直接操作 EPDC 才拿得到（实测 A2 波形 640x480 约 115ms/帧 = 8.6fps）；
# WAF 的刷新时机归系统的 lab126_ligl.lua 管，拿不到这个速度。
#
# 注意：fbink 画的内容会被系统整体重绘冲掉（实测 restart kppmainapp 后消失），
# 所以播放器播放期间自己压住屏保，停下来时切回主页让界面重绘。
FB=${EXT}/fbvideo
FB_PY=${FB}/play.py
FB_LOG=${FB}/play.log
FB_CTL=${FB}/ctl
FB_STATE=${FB}/state
FB_PY3=/mnt/us/python3/bin/python3
FB_LIB=/mnt/us/python3/lib
# 自动扫描这些目录里的 *.ktvid（不递归）。
#
# 坑：/mnt/us 是 Amazon 的 fsp(FUSE) 层，**大小写不敏感** ——
# /mnt/us/videos 和 /mnt/us/Videos 是同一个目录（实测写一个小写路径的文件，大写路径立刻可见；
# du 两块报的是同一份数据）。但 FUSE 对两种拼写会返回**不同的 inode**，
# 所以按 inode 去重是无效的，反而会把同一个视频列两遍。
# 结论：只用一个规范目录名，额外目录写进 ${FB}/dirs（空格或换行分隔）。
FB_DIRS="/mnt/us/videos"
[ -f ${FB}/dirs ] && FB_DIRS="${FB_DIRS} $(tr '\n' ' ' < ${FB}/dirs 2>/dev/null)"

fbvideo_files() {
	_seen=""
	for d in ${FB_DIRS}; do
		[ -d "$d" ] || continue
		for f in "$d"/*.ktvid; do
			[ -f "$f" ] || continue
			# 兜底去重：同名 + 同大小 + 同 mtime 就当成同一个文件
			# （正是大小写变体互相指向同一份数据时的情况）
			_key=$(ls -l "$f" 2>/dev/null | awk '{print $5"_"$6"_"$7"_"$8}')
			_key="${f##*/}|${_key}"
			case " ${_seen} " in *" ${_key} "*) continue ;; esac
			_seen="${_seen} ${_key}"
			echo "$f"
		done
	done
}

fbvideo_pids() {
	for p in /proc/[0-9]*; do
		c=$( { tr '\0' ' ' < $p/cmdline; } 2>/dev/null )
		case "$c" in *${FB_PY}*) echo "${p##*/}" ;; esac
	done
}

# 状态：off（没进程）/ playing / paused（进程在，再看状态文件）
fbvideo_state() {
	[ -n "$(fbvideo_pids)" ] || { echo off; return; }
	case "$(sed -n 's/^status=//p' ${FB_STATE} 2>/dev/null | head -1)" in
		paused) echo paused ;;
		*) echo playing ;;
	esac
}

fbvideo_get() { sed -n "s/^$1=//p" ${FB_STATE} 2>/dev/null | head -1; }

# 给菜单标题用的一行摘要
fbvideo_label() {
	case "$(fbvideo_state)" in
		off) echo "未播放" ;;
		paused) echo "已暂停 $(fbvideo_get frame)/$(fbvideo_get total)" ;;
		*) echo "播放中 $(fbvideo_get frame)/$(fbvideo_get total)" ;;
	esac
}

# 给「播放状态」和 SSH 用的一行摘要
fbvideo_info() {
	if [ "$(fbvideo_state)" = off ]; then
		echo "当前没有在播放（扫描目录：${FB_DIRS}）"
		return 0
	fi
	echo "$(fbvideo_state)  $(fbvideo_get name)  $(fbvideo_get frame)/$(fbvideo_get total) 帧  波形$(fbvideo_get waveform)  目标$(fbvideo_get fps)fps"
}

# 写控制命令（播放器读到就删）：pause / resume / toggle / stop / restart
fbvideo_ctl() {
	[ -n "$(fbvideo_pids)" ] || { say "fbvideo: 没有在播放"; return 1; }
	printf '%s\n' "$1" > ${FB_CTL}
}

fbvideo_count() {
	n=$(fbvideo_files | grep -c . 2>/dev/null)
	echo ${n:-0}
}

fbvideo_play() {
	f=$1
	wf=${2:-A2}
	[ -f "$f" ] || { say "fbvideo: 找不到 $f"; return 1; }
	[ -f ${FB_PY} ] || { say "fbvideo: 缺 ${FB_PY}"; return 1; }
	[ -x ${FB_PY3} ] || { say "fbvideo: 缺 python3（KUAL 的 python3 扩展）"; return 1; }
	fbvideo_stop >/dev/null 2>&1
	rm -f ${FB_CTL} ${FB_STATE}
	# 后台放：KUAL 不能阻塞几分钟，播放期间屏幕由播放器接管。
	# --ctl/--state 让它能被 KUAL 暂停/继续/停止，并把进度写出来给菜单显示。
	nohup env LD_LIBRARY_PATH=${FB_LIB} PYTHONIOENCODING=utf-8 ${FB_PY3} ${FB_PY} "$f" \
		--waveform ${wf} --gc-every 120 --ctl ${FB_CTL} --state ${FB_STATE} >> ${FB_LOG} 2>&1 &
	say "fbvideo: 开始播放 ${f##*/}（波形 ${wf}；点屏幕暂停，翻页键停止）"
}

fbvideo_stop() {
	pids=$(fbvideo_pids)
	if [ -z "${pids}" ]; then
		rm -f ${FB_CTL} ${FB_STATE}
		say "fbvideo: 没有正在播放的任务"
		return 0
	fi
	# 先礼后兵：让播放器自己收尾（恢复 preventScreenSaver、切回主页）
	mkdir -p ${FB} 2>/dev/null
	printf 'stop\n' > ${FB_CTL}
	i=0
	while [ ${i} -lt 6 ]; do
		[ -z "$(fbvideo_pids)" ] && break
		sleep 1
		i=$((i + 1))
	done
	pids=$(fbvideo_pids)
	if [ -n "${pids}" ]; then
		for p in ${pids}; do kill ${p} 2>/dev/null; done
		sleep 1
		for p in $(fbvideo_pids); do kill -9 ${p} 2>/dev/null; done
		# 播放器没来得及收尾时兜底
		lipc-set-prop com.lab126.powerd preventScreenSaver 0 >/dev/null 2>&1
		lipc-set-prop com.lab126.appmgrd start app://com.lab126.booklet.home >/dev/null 2>&1
	fi
	rm -f ${FB_CTL} ${FB_STATE}
	say "fbvideo: 已停止播放"
}

# 每个视频一个子菜单：点开选波形（默认 A2）
fbvideo_menu_items() {
	n=5
	# ⚠ sep 必须是「首个为空、其后为逗号」——调用方在上一项末尾已经有一个逗号，
	# 这里若首项也给逗号就会拼出 `},,` 而让 menu.json 变成非法 JSON（KUAL 直接读不了）。
	sep=""
	for f in $(fbvideo_files); do
		b=${f##*/}
		b=${b%.ktvid}
		b=$(printf '%s' "$b" | tr -d '"\\')
		n=$((n + 1))
		kb=$(( $(wc -c < "$f" 2>/dev/null || echo 0) / 1024 ))
		printf '%s\t\t\t\t{"name": "%s (%d KB)", "priority": %d, "items": [' "${sep}" "${b}" ${kb} ${n}
		printf '{"name": "播放（A2，推荐：唯一快的真实波形）", "priority": 1, "exitmenu": true, "action": "%s/tweak.sh", "params": "fbvideo play %s A2"}, ' "${EXT}" "${f}"
		printf '{"name": "播放（DU：更慢但不闪，~4fps）", "priority": 2, "exitmenu": true, "action": "%s/tweak.sh", "params": "fbvideo play %s DU"}, ' "${EXT}" "${f}"
		printf '{"name": "播放（GC16：最干净最慢，~2.7fps）", "priority": 3, "exitmenu": true, "action": "%s/tweak.sh", "params": "fbvideo play %s GC16"}]}' "${EXT}" "${f}"
		sep=",
"
	done
	echo
	[ "$(fbvideo_count)" = 0 ] && printf '\t\t\t\t{"name": "（没扫到视频）把 .ktvid 放进 %s", "priority": 5, "refresh": true, "exitmenu": false, "action": "%s/tweak.sh", "params": "menu"}\n' "${FB_DIRS}" "${EXT}"
}

label() {
	case "$1" in
		on) echo "已开启" ;;
		off) echo "已关闭" ;;
		mixed) echo "部分生效" ;;
		unknown) echo "文件不匹配" ;;
		missing) echo "缺补丁文件" ;;
	esac
}

# 一个「开启 / 关闭」子菜单。$1 名称 $2 状态 $3 参数前缀 $4 优先级 $5 关闭项文字
toggle() {
	on_chk=false
	off_chk=false
	[ "$2" = on ] && on_chk=true
	[ "$2" = off ] && off_chk=true
	cat <<EOF
		{"name": "$1 [$(label $2)]", "priority": $4, "items": [
			{"name": "开启", "priority": 1, "checked": ${on_chk}, "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "$3 on"},
			{"name": "$5", "priority": 2, "checked": ${off_chk}, "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "$3 off"}
		]},
EOF
}

menu() {
	{
		cat <<EOF
{
	"items": [
	{
		"name": "Kindle Tweaks",
		"priority": 0,
		"items": [
EOF
		toggle "去除「云端不可用」弹窗 + 隐藏无线界面" "$(state popup)" popup 1 "关闭（还原原版）"
		toggle "解锁「查看选项→收藏夹」" "$(state collview)" collview 2 "关闭（还原原版）"
		toggle "PDF 全屏（无底栏无边距）" "$(state pdffull)" pdffull 3 "关闭（还原原版）"
		toggle "浏览器可下载任意文件（存到 documents）" "$(state browserdl)" browserdl 4 "关闭（还原原版）"
		cat <<EOF
		{"name": "文件夹收藏夹 [自动同步$(label $(coll_state))]", "priority": 5, "items": [
			{"name": "立即同步", "priority": 1, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "coll sync"},
			{"name": "开启自动同步（开机自启）", "priority": 2, "checked": $([ $(coll_state) = on ] && echo true || echo false), "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "coll on"},
			{"name": "关闭自动同步", "priority": 3, "checked": $([ $(coll_state) = off ] && echo true || echo false), "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "coll off"},
			{"name": "删除所有自动生成的收藏夹", "priority": 4, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "coll purge"}
		]},
EOF
		ms=$(manga_status)
		cat <<EOF
		{"name": "epub/md/docx 自动转换 [$(label $(manga_state))]", "priority": 6, "items": [
			{"name": "${ms:-还没运行过}（点此刷新）", "priority": 1, "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "menu"},
			{"name": "开启自动转换（文字书传完即转）", "priority": 2, "checked": $([ $(manga_state) = on ] && echo true || echo false), "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "manga on"},
			{"name": "关闭自动转换", "priority": 3, "checked": $([ $(manga_state) = off ] && echo true || echo false), "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "manga off"},
			{"name": "立即转换（不等充电）", "priority": 4, "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "manga now"},
			{"name": "规则：漫画≥$(manga_min)MB充电→PDF，文字书、md、docx传完→AZW3 [$(text_backend_label)]", "priority": 5, "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "menu"},
			{"name": "按目录转换（不限大小）", "priority": 6, "items": [
$(manga_dir_items)
			]}
		]},
EOF
		toggle "屏保开机随机排序（linkss）" "$(ss_state)" ssrandom 7 "关闭（固定顺序，开机更快）"
		toggle "泡面模式" "$(airplane_state)" airplane 13 "关闭"
		toggle "隐藏状态栏无线图标（nowifi）" "$(nowifi_state)" nowifi 14 "关闭（显示图标）"
		cat <<EOF
		{"name": "默认收藏夹视图 [$(label $(libraryview_state))]", "priority": 8, "items": [
			{"name": "开启（进入屏保时校正）", "priority": 1, "checked": $([ "$(libraryview_state)" = on ] && echo true || echo false), "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "libraryview on"},
			{"name": "关闭（不再强制，保留当前视图）", "priority": 2, "checked": $([ "$(libraryview_state)" = off ] && echo true || echo false), "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "libraryview off"}
		]},
		{"name": "调试模式 [$(debugawake_label)]", "priority": 9, "items": [
			{"name": "查看当前状态：$(debugawake_status)（点此刷新）", "priority": 1, "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "menu"},
			{"name": "不深度休眠", "priority": 2, "checked": $([ "$(debugawake_state)" = always ] && echo true || echo false), "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "debugawake always"},
			{"name": "充电时不深度休眠", "priority": 3, "checked": $([ "$(debugawake_state)" = charging ] && echo true || echo false), "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "debugawake charging"},
			{"name": "关闭调试模式", "priority": 4, "checked": $([ "$(debugawake_state)" = off ] && echo true || echo false), "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "debugawake off"}
		]},
		{"name": "微信传书 [$(label $(wxsend_state))]", "priority": 10, "items": [
			{"name": "$(s=$(wxsend_status); echo "${s:-还没同步过}")（点此刷新）", "priority": 1, "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "menu"},
			{"name": "立即同步（本机编号 $([ -f ${WX}/config ] && wxsend_device || echo 未配置)）", "priority": 2, "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "wxsend now"},
			{"name": "开启（亮屏时自动同步）", "priority": 3, "checked": $([ "$(wxsend_state)" = on ] && echo true || echo false), "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "wxsend on"},
			{"name": "关闭", "priority": 4, "checked": $([ "$(wxsend_state)" = off ] && echo true || echo false), "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "wxsend off"}
		]},
		{"name": "常驻网页应用（WAF） [$(webapp_count) 个已常驻]", "priority": 11, "items": [
			{"name": "自检 doctor（sqlite3 / 参考行 / 日志）", "priority": 1, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "webapp doctor"},
			{"name": "重新安装全部常驻应用（升级固件后用）", "priority": 2, "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "webapp restore"},
			{"name": "放置位置：/mnt/us/webapps/<名字>/index.html", "priority": 3, "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "menu"},
			{"name": "候选应用（点开可安装 / 打开 / 卸载）", "priority": 4, "items": [
$(webapp_menu_items)
			]}
		]},
		{"name": "墨水屏视频播放 [$(fbvideo_count) 个｜$(fbvideo_label)]", "priority": 12, "items": [
			{"name": "暂停 / 继续（点一下切换）", "priority": 1, "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "fbvideo toggle"},
			{"name": "停止播放", "priority": 2, "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "fbvideo stop"},
			{"name": "播放状态：$(fbvideo_info | tr -d '"\\')", "priority": 3, "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "menu"},
			{"name": "重新扫描视频目录", "priority": 4, "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "menu"},
			{"name": "── 下面点一个就播（自动扫描）──", "priority": 5, "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "menu"},
$(fbvideo_menu_items)
		]},
		{"name": "升级固件后：全部补丁重新开启（并重装常驻网页应用）", "priority": 15, "refresh": true, "action": "${EXT}/tweak.sh", "params": "all on"},
		{"name": "全部补丁还原原版（⚠ 要再点一次确认）", "priority": 16, "items": [
			{"name": "⚠ 确认还原原版（功能 1/3/4/9 + 隐藏无线界面）", "priority": 1, "refresh": true, "action": "${EXT}/tweak.sh", "params": "all off"},
			{"name": "取消，什么都不做", "priority": 2, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "menu"}
		]}
		]
	}
	]
}
EOF
	} > ${EXT}/menu.json.new
	# ⚠ 生成后**必须**校验 JSON 再落地：非法的话 KUAL 会读不了这个扩展的整个菜单。
	# 曾因 fbvideo_menu_items 的 sep 多打一个逗号拼出 `},,`，menu.json 非法 → KUAL 不工作。
	# 校验不过就退回一个「最小可用菜单」（并留证据），保证 KUAL 永远有东西可点。
	_menu_py=""
	for _c in python3 /mnt/us/python3/bin/python3 /usr/bin/python3; do
		command -v "${_c}" >/dev/null 2>&1 && { _menu_py="${_c}"; break; }
	done
	_menu_ok=true
	if [ -n "${_menu_py}" ]; then
		"${_menu_py}" -c 'import json,sys; json.load(open(sys.argv[1]))' ${EXT}/menu.json.new 2>/dev/null || _menu_ok=false
	fi
	if ${_menu_ok}; then
		mv ${EXT}/menu.json.new ${EXT}/menu.json
	else
		mkdir -p /mnt/us/kindletweaks_backup 2>/dev/null
		cp ${EXT}/menu.json.new /mnt/us/kindletweaks_backup/menu.json.bad 2>/dev/null
		echo "$(date '+%m-%d %H:%M:%S') menu: 生成的 menu.json 不是合法 JSON，已保留最小可用菜单（坏文件存到 /mnt/us/kindletweaks_backup/menu.json.bad）" >> ${EXT}/tweak.log
		cat > ${EXT}/menu.json <<MINEOF
{
	"items": [
		{"name": "Kindle Tweaks", "priority": 1, "items": [
			{"name": "⚠ 菜单生成出错（JSON 非法），点这里重试", "priority": 1, "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "menu"},
			{"name": "坏文件在 /mnt/us/kindletweaks_backup/menu.json.bad", "priority": 2, "refresh": true, "exitmenu": false, "action": "${EXT}/tweak.sh", "params": "menu"}
		]}
	]
}
MINEOF
	fi
	rm -f ${EXT}/menu.json.new
}

case "$1" in
	status)
		for u in ${UNITS}; do echo "${u}: $(state ${u})"; done
		echo "coll(auto): $(coll_state)"
		echo "ssrandom: $(ss_state)"
		echo "airplane: $(airplane_state)"
		echo "manga(auto): $(manga_state) $(manga_status)"
		echo "libraryview(default collections): $(libraryview_status)"
		echo "nowifi(statusbar icons): $(nowifi_status)"
		echo "debugawake: $(debugawake_status)"
		echo "wxsend: $(wxsend_state) $(wxsend_status)"
		echo "webapp(WAF): $(webapp_count) 个已常驻$([ -f ${WA_LIST} ] && echo "，清单 $(grep -c . ${WA_LIST} 2>/dev/null) 项" || echo "")"
		echo "fbvideo(墨水屏视频): $(fbvideo_label)，$(fbvideo_count) 个视频（扫描 ${FB_DIRS}）"
		;;
	menu)
		menu
		;;
	all)
		for u in ${UNITS}; do [ "$(state ${u})" = missing ] || set_unit ${u} $2; done
		# 状态栏注入不是文件补丁（改的是 upstart 任务里的 exec 行），单独走一遍
		if [ "$2" != on ] || [ -f ${NW_SO} ]; then
			nowifi $2
		else
			say "nowifi: 缺 ${NW_SO}，跳过（先在电脑上编译，见 docs/19）"
		fi
		# on 的时候顺手把常驻网页应用重装一遍：升级固件后 /var/local 或 appreg.db 可能被重置
		[ "$2" = on ] && webapp_restore
		menu
		do_restart
		;;
	popup | collview | pdffull | browserdl)
		set_unit $1 $2 && screen "kindle-tweaks: $1 $2 OK" || screen "kindle-tweaks: $1 $2 FAILED, see tweak.log"
		menu
		do_restart
		;;
	coll)
		coll $2
		rc=$?
		# autosync 是后台任务调用的，不打扰屏幕；返回码给任务判断是否同步成功
		[ "$2" = autosync ] && exit ${rc}
		screen "kindle-tweaks: folder collections $2"
		menu
		;;
	ssrandom)
		ssrandom $2
		screen "kindle-tweaks: screensaver random $2"
		menu
		;;
	airplane)
		airplane $2
		screen "kindle-tweaks: airplane $2"
		menu
		;;
	debugawake)
		debugawake $2
		screen "kindle-tweaks: debug awake $2"
		menu
		;;
	libraryview)
		libraryview $2
		rc=$?
		[ "$2" = apply ] && exit ${rc}
		screen "kindle-tweaks: default collections $2"
		menu
		;;
	nowifi)
		nowifi $2
		screen "kindle-tweaks: statusbar wifi icons $2"
		menu
		;;
	manga)
		manga $2 $3
		rc=$?
		[ "$2" = autorun ] && exit ${rc}
		screen "kindle-tweaks: manga convert $2"
		menu
		;;
	wxsend)
		wxsend $2
		rc=$?
		[ "$2" = autopull ] && exit ${rc}
		screen "kindle-tweaks: wechat send $2 ($(grep -o '[0-9]* 本' ${WX}/status.txt 2>/dev/null | head -1 | tr -dc 0-9) new)"
		menu
		;;
	webapp)
		webapp $2 $3
		rc=$?
		# doctor/scan/list 是给 SSH 看的，别弹菜单也别打屏幕
		case "$2" in doctor | scan | list) exit ${rc} ;; esac
		screen "kindle-tweaks: webapp $2 $3"
		menu
		;;
	fbvideo)
		case "$2" in
			# 播放是长任务：后台跑并立刻返回，别让 KUAL 卡住，也别在视频上叠字
			play)
				fbvideo_play "$3" "$4"
				exit 0
				;;
			stop) fbvideo_stop ;;
			toggle | pause | resume | restart) fbvideo_ctl "$2" ;;
			state)
				fbvideo_state
				exit 0
				;;
			status | info)
				fbvideo_info
				exit 0
				;;
			# 打印 KUAL 子菜单 JSON，方便在 SSH 上核对（别在 KUAL 里点）
			menujson)
				fbvideo_menu_items
				exit 0
				;;
		esac
		screen "kindle-tweaks: fbvideo $2"
		menu
		;;
	*)
		sed -n '2,13p' $0
		;;
esac
exit 0
