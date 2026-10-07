#!/bin/sh
# kindle-tweaks 管理脚本（KUAL 菜单和 SSH 都调用它）
#   tweak.sh status                      打印所有功能的状态
#   tweak.sh menu                        按当前状态重新生成 KUAL 菜单
#   tweak.sh <popup|collview|pdffull|browserdl|all> on|off   开关系统文件补丁
#   tweak.sh coll sync|on|off|purge      文件夹收藏夹：立即同步 / 开机自动同步 / 关闭 / 删除生成的收藏夹
#   tweak.sh ssrandom on|off             linkss 屏保开机随机排序
#   tweak.sh manga on|off|now            epub 自动转换（大漫画充电→PDF，文字书传完→AZW3）：自动转换开关 / 立即转换
#   tweak.sh manga dir <序号>            按目录转换（序号是菜单生成时 mangaconv/dirs.txt 的行号）
#   tweak.sh debugawake always|charging|off   调试模式：始终阻止 / 仅充电阻止 / 关闭深度休眠推迟
#   tweak.sh libraryview on|off          主界面重载时默认进入收藏夹视图
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
			mntroot ro
			start kindletweaks-libraryview >/dev/null 2>&1 || { say "libraryview: 无法启动监听任务"; return 1; }
			say "libraryview: default collections on"
			restart kppmainapp >/dev/null 2>&1 || true
			;;
		off)
			stop kindletweaks-libraryview >/dev/null 2>&1 || true
			mntroot rw
			[ -f ${J} ] && mv ${J} /tmp/kindletweaks-libraryview.conf.disabled
			mntroot ro
			say "libraryview: default collections off"
			;;
		apply)
			libraryview_apply
			return $?
			;;
	esac
}

libraryview_state() { [ -f /etc/upstart/kindletweaks-libraryview.conf ] && echo on || echo off; }

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
		toggle "去除「云端不可用」弹窗" "$(state popup)" popup 1 "关闭（还原原版）"
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
		{"name": "升级固件后：全部补丁重新开启", "priority": 10, "refresh": true, "action": "${EXT}/tweak.sh", "params": "all on"},
		{"name": "全部补丁还原原版", "priority": 11, "refresh": true, "action": "${EXT}/tweak.sh", "params": "all off"}
		]
	}
	]
}
EOF
	} > ${EXT}/menu.json.new && mv ${EXT}/menu.json.new ${EXT}/menu.json
}

case "$1" in
	status)
		for u in ${UNITS}; do echo "${u}: $(state ${u})"; done
		echo "coll(auto): $(coll_state)"
		echo "ssrandom: $(ss_state)"
		echo "manga(auto): $(manga_state) $(manga_status)"
		echo "libraryview(default collections): $(libraryview_state)"
		echo "debugawake: $(debugawake_status)"
		;;
	menu)
		menu
		;;
	all)
		for u in ${UNITS}; do [ "$(state ${u})" = missing ] || set_unit ${u} $2; done
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
	manga)
		manga $2 $3
		rc=$?
		[ "$2" = autorun ] && exit ${rc}
		screen "kindle-tweaks: manga convert $2"
		menu
		;;
	*)
		sed -n '2,9p' $0
		;;
esac
exit 0
