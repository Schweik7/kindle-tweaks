/*
 * kindle-tweaks：图书馆不重启 KPP 就切回收藏夹视图。GPL-3.0-or-later。
 *
 * 用 LD_PRELOAD 注入 KPPMainApp。libKSDKLibrary.so 里 LibraryViewModelImpl 的虚表槽位
 * 是按符号名动态重定位的（ARM_ABS32），所以这里定义的同名函数会顶替原来的 OnViewActivate。
 *
 * 进入图书馆时 KPP 调用 OnViewActivate()。如果标记文件存在（upstart 任务在进入屏保时创建），
 * 且当前是「全部」模式（LIBRARY），就先调用原生的 SetMode(COLLECTIONS) —— 和在界面上点
 * 「查看选项 → 收藏夹」走同一条路径，KPP 自己会保存 LIBRARY_CONFIG —— 再执行原函数。
 * 标记用过即删，所以使用中临时切到「全部」会一直保持到下次进入屏保。主页（HOME）、收藏夹内部、
 * 搜索等其他视图模型实例的模式不是 LIBRARY/COLLECTIONS，不受影响。
 *
 * 安全：模式用原生 Mode() 读取；加载时用 LibraryModeToString 核对枚举值，符号缺失或对不上就
 * 停用自己，只透传原函数。
 *
 * 编译（-z lazy 必需：zig 默认 BIND_NOW，Kindle 的 glibc 2.20 ld.so 会报 unexpected reloc type 0x24）：
 *   python -m ziglang cc -target arm-linux-gnueabi.2.20 -mcpu=cortex_a7 -shared -fPIC -O2 -s \
 *       -Wl,-z,lazy -o libkt_libview.so libkt_libview.c
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define NS "_ZN4ksdk7library"
#define SYM_ACTIVATE NS "20LibraryViewModelImpl14OnViewActivateEv"
#define SYM_SETMODE NS "20LibraryViewModelImpl7SetModeENS0_11LibraryModeE"
#define SYM_MODE "_ZNK4ksdk7library20LibraryViewModelImpl4ModeEv"
#define SYM_MODESTR NS "19LibraryModeToStringENS0_11LibraryModeE"
#define FLAG "/tmp/kindletweaks-libraryview.reset"
#define LOG "/tmp/kindletweaks-libraryview.log"

enum { MODE_LIBRARY = 0, MODE_COLLECTIONS = 1 };    /* ksdk::library::LibraryMode */

typedef void (*activate_fn)(void *self);
typedef void (*setmode_fn)(void *self, int mode);
typedef int (*mode_fn)(const void *self);
/* std::string LibraryModeToString(LibraryMode)：按值返回对象，ARM EABI 用 r0 传返回地址。
 * 这版 libstdc++ 是写时复制的 std::string，对象就是一个指向字符数据的指针。 */
typedef void (*modestr_fn)(const char **out, int mode);

static activate_fn real_activate;
static setmode_fn set_mode;
static mode_fn get_mode;
static int enabled;

static void say(const char *fmt, ...)
{
	FILE *f = fopen(LOG, "a");
	if (!f)
		return;
	time_t t = time(NULL);
	char ts[32];
	strftime(ts, sizeof ts, "%m-%d %H:%M:%S", localtime(&t));
	fprintf(f, "%s ", ts);
	va_list ap;
	va_start(ap, fmt);
	vfprintf(f, fmt, ap);
	va_end(ap);
	fputc('\n', f);
	fclose(f);
}

static int mode_is(modestr_fn to_string, int mode, const char *name)
{
	const char *s = NULL;
	to_string(&s, mode);        /* 每次泄漏一个很小的字符串，只在加载时调用两次 */
	return s && strcmp(s, name) == 0;
}

static void init(void)
{
	real_activate = (activate_fn)dlsym(RTLD_NEXT, SYM_ACTIVATE);
	set_mode = (setmode_fn)dlsym(RTLD_NEXT, SYM_SETMODE);
	get_mode = (mode_fn)dlsym(RTLD_NEXT, SYM_MODE);
	modestr_fn to_string = (modestr_fn)dlsym(RTLD_NEXT, SYM_MODESTR);
	enabled = real_activate && set_mode && get_mode && to_string
		&& mode_is(to_string, MODE_LIBRARY, "LIBRARY")
		&& mode_is(to_string, MODE_COLLECTIONS, "COLLECTIONS");
	say("loaded, %s", enabled ? "enabled" : "DISABLED (symbols or enum changed)");
}

void _ZN4ksdk7library20LibraryViewModelImpl14OnViewActivateEv(void *self)
{
	static int ready;
	if (!ready) {
		init();
		ready = 1;
	}
	if (enabled && access(FLAG, F_OK) == 0) {
		int mode = get_mode(self);
		/* 只处理图书馆主视图：「全部」或「收藏夹」 */
		if (mode == MODE_LIBRARY || mode == MODE_COLLECTIONS) {
			unlink(FLAG);
			if (mode == MODE_LIBRARY) {
				set_mode(self, MODE_COLLECTIONS);
				say("LIBRARY -> COLLECTIONS");
			}
		}
	}
	if (real_activate)
		real_activate(self);
}
