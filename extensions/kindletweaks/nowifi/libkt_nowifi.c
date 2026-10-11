/*
 * libkt_nowifi.so — 注入状态栏进程 JunoStatusBarDriver（LD_PRELOAD），把右上角的
 * Wi-Fi / 飞行模式 / WAN 信号图标换成同尺寸的空白 SVG。
 *
 * 状态栏（libJunoStatusBarShared.so）的图标都交给 librsvg 渲染：
 *   Wi-Fi 信号      SvgIcon::createWifiSvg 现场拼的 SVG，特征是半径 70 的扇形圆弧
 *   WAN 信号        5 根竖条，宽 14.3（有信号）或 16（无服务）
 *   飞行模式        文件 /app/KPPMainApp/res/core/systemStatus/AirplaneMode.svg
 * 拦截 rsvg_handle_new_from_data / rsvg_handle_new_from_file，命中的换成空白；
 * 电池、锁、音量等其他图标原样放行。viewBox 不变，所以布局不动，只是那一格画成空白。
 *
 * 编译（-z lazy 必需：zig 默认 BIND_NOW，Kindle 的 glibc 2.20 ld.so 会报 unexpected reloc type 0x24）：
 *   python -m ziglang cc -target arm-linux-gnueabi.2.20 -mcpu=cortex_a7 -shared -fPIC -O2 -s \
 *       -Wl,-z,lazy -o libkt_nowifi.so libkt_nowifi.c
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <string.h>

typedef void *(*from_data_t)(const unsigned char *, unsigned long, void **);
typedef void *(*from_file_t)(const char *, void **);

static const char BLANK[] = "<svg viewBox=\"0 0 100 100\" xmlns=\"http://www.w3.org/2000/svg\"/>";

/* 数据不一定以 0 结尾，自己按长度找 */
static int has(const unsigned char *d, unsigned long n, const char *s)
{
	unsigned long k = strlen(s);
	for (unsigned long i = 0; i + k <= n; i++)
		if (d[i] == (unsigned char)s[0] && memcmp(d + i, s, k) == 0)
			return 1;
	return 0;
}

static int is_network_icon(const unsigned char *d, unsigned long n)
{
	return has(d, n, "A 70.000000,70.000000") ||        /* Wi-Fi */
	       has(d, n, "width=\"14.300000\" height=\"20.000000\"") ||  /* WAN 信号条 */
	       has(d, n, "width=\"16.000000\" height=\"5.000000\"");     /* WAN 无服务 */
}

void *rsvg_handle_new_from_data(const unsigned char *d, unsigned long n, void **e)
{
	static from_data_t real;
	if (!real)
		real = (from_data_t)dlsym(RTLD_NEXT, "rsvg_handle_new_from_data");
	if (d && is_network_icon(d, n))
		return real((const unsigned char *)BLANK, sizeof(BLANK) - 1, e);
	return real(d, n, e);
}

void *rsvg_handle_new_from_file(const char *p, void **e)
{
	static from_file_t real;
	static from_data_t data;
	if (!real)
		real = (from_file_t)dlsym(RTLD_NEXT, "rsvg_handle_new_from_file");
	if (p && strstr(p, "/AirplaneMode.svg")) {
		if (!data)
			data = (from_data_t)dlsym(RTLD_NEXT, "rsvg_handle_new_from_data");
		return data((const unsigned char *)BLANK, sizeof(BLANK) - 1, e);
	}
	return real(p, e);
}
