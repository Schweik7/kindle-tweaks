/* keytap —— 用 XTEST 伪造「翻页键」事件，用来无人值守地验证 keyshot（docs/20）
 *
 * 关键点：事件必须伪装成 keypad 那台设备（XIQueryDevice 里 name="keypad"，
 * 本机 id=6）发出的，阅读器才认；用 core XTEST 发它不翻页。
 *
 * 用法: keytap <tap_up|tap_dn|fast_tap_up|combo|combo_dn_first|slow_pair> [devid]
 *   combo          两键相隔 60ms 按下、一起按住 340ms  → 应截图且画面不变
 *   tap_up         单击 PageUp                          → 应翻页
 *   fast_tap_up    30ms 就松手                          → 应翻页（走快按分支）
 *   slow_pair      两键相隔 400ms                       → 应翻两次页，不截图
 *   press_hold_release 按住 300ms 再松                 → 应翻页（实测 KPP 是按下即翻页）
 *   press_only / release_only                           → 用来判定翻页由哪一步触发
 */
#include <unistd.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdarg.h>

typedef struct _XDisplay Display;
typedef unsigned long XID;
typedef int Bool;

extern Display *XOpenDisplay(const char *);
extern int XCloseDisplay(Display *);
extern void *XOpenDevice(Display *, XID);
extern int XCloseDevice(Display *, void *);
extern int XTestFakeDeviceKeyEvent(Display *, void *, unsigned int, Bool,
                                   unsigned long, unsigned int *, int);
extern int XFlush(Display *);
extern int XSync(Display *, Bool);

#define UP 112
#define DN 117

static char out[256];
static void p(const char *fmt, ...)
{
    va_list ap;
    int n;
    va_start(ap, fmt);
    n = vsnprintf(out, sizeof(out), fmt, ap);
    va_end(ap);
    if (n > 0) write(1, out, (size_t)n);
}

static void *dev_;
static Display *dpy;

static void key(unsigned kc, int down)
{
    /* 一律用 delay=0 立即投递，时序由用户态 usleep 控制：
     * 实测带 delay 的 fake event 在这台 server 上不可靠，会连 release 一起丢。 */
    XTestFakeDeviceKeyEvent(dpy, dev_, kc, down, 0, NULL, 0);
    XFlush(dpy);
}

int main(int argc, char **argv)
{
    const char *mode = argc > 1 ? argv[1] : "combo";
    int devid = argc > 2 ? atoi(argv[2]) : 6;

    dpy = XOpenDisplay(NULL);
    if (!dpy) { p("XOpenDisplay FAILED\n"); return 1; }
    dev_ = XOpenDevice(dpy, (XID)devid);
    if (!dev_) { p("XOpenDevice(%d) FAILED\n", devid); return 1; }

    if (strcmp(mode, "tap_up") == 0) {
        key(UP, 1); usleep(80000); key(UP, 0);
    } else if (strcmp(mode, "tap_dn") == 0) {
        key(DN, 1); usleep(80000); key(DN, 0);
    } else if (strcmp(mode, "fast_tap_up") == 0) {
        key(UP, 1); usleep(30000); key(UP, 0);     /* 30ms 松手：走「快按」分支 */
    } else if (strcmp(mode, "combo") == 0) {
        key(UP, 1);  usleep(60000);                /* 相隔 60ms 按下 */
        key(DN, 1);  usleep(340000);               /* 一起按住 */
        key(UP, 0);  key(DN, 0);
    } else if (strcmp(mode, "combo_dn_first") == 0) {
        key(DN, 1);  usleep(60000);
        key(UP, 1);  usleep(340000);
        key(DN, 0);  key(UP, 0);
    } else if (strcmp(mode, "slow_pair") == 0) {
        key(UP, 1); usleep(80000); key(UP, 0);
        usleep(400000);                            /* 超过 150ms 窗口 */
        key(DN, 1); usleep(80000); key(DN, 0);
    } else if (strcmp(mode, "press_only") == 0) {
        key(UP, 1);                                /* 只按下不松开：验证「KPP 是否 press 翻页」 */
    } else if (strcmp(mode, "release_only") == 0) {
        key(UP, 0);                                /* 只松开 */
    } else if (strcmp(mode, "press_hold_release") == 0) {
        key(UP, 1); usleep(300000); key(UP, 0);    /* 按住 300ms：复现「状态残留」场景 */
    } else {
        p("unknown mode %s\n", mode); return 2;
    }

    XFlush(dpy);
    XSync(dpy, 0);
    usleep(900000);        /* 等 server 把带 delay 的 fake event 都执行完再断开 */
    p("sent %s via device %d\n", mode, devid);
    XCloseDevice(dpy, dev_);
    XCloseDisplay(dpy);
    return 0;
}
