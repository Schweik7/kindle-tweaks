/*
 * keyshot —— 上下翻页键同时按住：截屏（X 层抓键版）
 *
 * 行为：在 root window 上 XGrabKey 抢走 PageUp / PageDown。
 *   - 两键在 PAIR_WINDOW_MS 内先后按下  → 判定为组合：两个事件全部吞掉，
 *     阅读器一个键都收不到，画面完全不翻页，此时再截屏（截到的正是当前这页）。
 *   - 只按了一个键                      → 临时放开该键，用 XTestFakeDeviceKeyEvent
 *     把一次完整点击原样重放给阅读器，照常翻页，用户无感。
 *
 * 为什么必须走 X 层：v1 旁听 evdev 只能看不能吞，每次截图都顺带翻一页；
 * 而本机没有 uinput，做不了「grab + 虚拟键盘重放」，只剩 X 层的 grab/XTEST 可用。
 *
 * 为什么重放要指定 keypad 设备：实测阅读器（KPP）按输入设备过滤按键，
 * core XTEST（"Virtual core XTEST keyboard"）发出去它不认，必须伪装成
 * device name="keypad" 的那台 slave keyboard 才会翻页。
 *
 * 为什么不依赖 KeyRelease：实测 grab 期间「第二个键」的 release 会被
 * X server 吞掉（不送给 grabbing client），所以状态机只用 KeyPress 推进，
 * 组合后靠冷却期复位，单键重放后立即复位 —— release 到不到都不影响。
 *
 * 设备上没有 X11 头文件，故手动声明原型，链接设备自带 libX11/libXtst/libXi。
 */
#include <unistd.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <stdlib.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <time.h>
#include <sys/time.h>
#include <sys/stat.h>
#include <sys/select.h>

/* ---- Xlib 最小声明 ---- */
typedef struct _XDisplay Display;
typedef unsigned long Window;
typedef unsigned long XID;
typedef unsigned long Time;
typedef unsigned char KeyCode;
typedef unsigned long KeySym;
typedef int Bool;

typedef union { char pad[192]; long l; } XEvent;

typedef struct {
    int type;
    unsigned long serial;
    Bool send_event;
    Display *display;
    Window window;
    Window root;
    Window subwindow;
    Time time;
    int x, y;
    int x_root, y_root;
    unsigned int state;
    unsigned int keycode;
    Bool same_screen;
} XKeyEvent;

typedef struct {
    int deviceid;
    char *name;
    int use;
    int attachment;
    Bool enabled;
    int num_classes;
    void **classes;
} XIDeviceInfo;

extern Display *XOpenDisplay(const char *);
extern int XCloseDisplay(Display *);
extern Window XDefaultRootWindow(Display *);
extern KeySym XStringToKeysym(const char *);
extern KeyCode XKeysymToKeycode(Display *, KeySym);
extern int XGrabKey(Display *, int, unsigned int, Window, Bool, int, int);
extern int XUngrabKey(Display *, int, unsigned int, Window);
extern int XNextEvent(Display *, XEvent *);
extern int XPending(Display *);
extern int XSync(Display *, Bool);
extern int XFlush(Display *);
extern int XConnectionNumber(Display *);
extern XIDeviceInfo *XIQueryDevice(Display *, int, int *);
extern int XIFreeDeviceInfo(XIDeviceInfo *);
extern void *XOpenDevice(Display *, XID);
extern int XCloseDevice(Display *, void *);
extern int XTestFakeDeviceKeyEvent(Display *, void *, unsigned int, Bool,
                                   unsigned long, unsigned int *, int);

#define KeyPress_       2
#define KeyRelease_     3
#define AnyModifier_    0x8000
#define GrabModeAsync_  1

/* ---- 可调参数（毫秒） ---- */
#define PAIR_WINDOW_MS    150  /* 两键按下的最大时间差，超过就是两次独立翻页 */
#define COOLDOWN_MS       700  /* 组合之后静默多久，用来吞掉余下的抖动/迟到事件 */
#define REPLAY_GAP_MS      40  /* 重放时 press 与 release 的间隔 */
#define REPLAY_SETTLE_MS   90  /* 重放后等 server 执行完再把 grab 装回去 */
#define SHOT_SETTLE_MS    200  /* 组合判定后到抓帧之间留的稳定时间 */
#define LOG_MAX_BYTES   65536

static const char *SHOT_DIR = "/mnt/us/screenshots";
static const char *LOG_PATH = "/mnt/us/extensions/kindletweaks/keyshot/keyshot.log";
static const char *SHOT_BIN = "/usr/sbin/screenshot";

static Display *dpy;
static Window root;
static void *keypad_dev;
static int kc_up, kc_dn;
static int pair_window = PAIR_WINDOW_MS;
static int debug_on;

/* 状态：只由 KeyPress 推进 */
static int held_up, held_dn;
static int pending;                    /* 0=无, 1=PageUp, 2=PageDown */
static long long pending_since;
static long long cooldown_until;
static long shots_taken;

static volatile sig_atomic_t quit;

static long long now_ms(void)
{
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (long long)tv.tv_sec * 1000 + tv.tv_usec / 1000;
}

static void msg(const char *fmt, ...)
{
    char buf[512];
    va_list ap;
    int n;
    va_start(ap, fmt);
    n = vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    if (n <= 0) return;
    write(1, buf, (size_t)n);

    int fd = open(LOG_PATH, O_WRONLY | O_CREAT | O_APPEND, 0644);
    if (fd < 0) return;
    struct stat st;
    if (fstat(fd, &st) == 0 && st.st_size > LOG_MAX_BYTES) {
        close(fd);
        fd = open(LOG_PATH, O_WRONLY | O_CREAT | O_TRUNC, 0644);
        if (fd < 0) return;
    }
    char line[600];
    time_t t = time(NULL);
    struct tm tmv;
    localtime_r(&t, &tmv);
    int m = snprintf(line, sizeof(line), "[%02d:%02d:%02d] ",
                     tmv.tm_hour, tmv.tm_min, tmv.tm_sec);
    if (m > 0) write(fd, line, (size_t)m);
    write(fd, buf, (size_t)n);
    close(fd);
}

static void on_signal(int sig) { (void)sig; quit = 1; }

static void grab_key(int kc)
{
    XGrabKey(dpy, kc, AnyModifier_, root, 0, GrabModeAsync_, GrabModeAsync_);
    XSync(dpy, 0);
}

static void ungrab_key(int kc)
{
    XUngrabKey(dpy, kc, AnyModifier_, root);
    XSync(dpy, 0);
}

/* 在 keypad 设备上伪造一次完整点击。
 *
 * pre_release 这一步不能省：真实按键被 grab 吞掉时，X server 里该键仍是「按下」状态，
 * 此时直接伪造 press 会被当成「重复按下」丢掉 —— 这正是「按住稍久再松手就没反应」的原因。
 * 先伪造一个 release 把状态清成 up，再点，才点得响。
 * （实测 KPP 是 press 翻页、release 不触发，所以这个多出来的 release 不会多翻一页。）
 * 顺带一招通用：就算真实 release 丢了导致状态残留，每次先清一遍也能自愈。 */
static void replay_tap(int kc)
{
    XTestFakeDeviceKeyEvent(dpy, keypad_dev, (unsigned int)kc, 0, 0, NULL, 0);
    XFlush(dpy);
    usleep(15000);

    XTestFakeDeviceKeyEvent(dpy, keypad_dev, (unsigned int)kc, 1, 0, NULL, 0);
    XFlush(dpy);
    usleep(REPLAY_GAP_MS * 1000);

    XTestFakeDeviceKeyEvent(dpy, keypad_dev, (unsigned int)kc, 0, 0, NULL, 0);
    XFlush(dpy);
}

static void take_screenshot(void)
{
    char path[256], stamp[32];
    time_t t = time(NULL);
    struct tm tmv;
    localtime_r(&t, &tmv);
    strftime(stamp, sizeof(stamp), "%Y%m%d_%H%M%S", &tmv);
    snprintf(path, sizeof(path), "%s/kt_%s_%02ld.png",
             SHOT_DIR, stamp, shots_taken % 100);

    pid_t pid = fork();
    if (pid == 0) {
        int fd = open("/dev/null", O_RDWR);
        if (fd >= 0) { dup2(fd, 1); dup2(fd, 2); if (fd > 2) close(fd); }
        execl(SHOT_BIN, "screenshot", "-f", path, (char *)NULL);
        _exit(127);
    }
    if (pid > 0) {
        shots_taken++;
        msg("screenshot #%ld -> %s\n", shots_taken, path);
    } else {
        msg("fork failed, errno=%d\n", errno);
    }
}

/* 判定为单键：把一次完整点击重放给阅读器 */
static void resolve_pending(void)
{
    if (!pending) return;
    int which = pending;
    int kc = (which == 1) ? kc_up : kc_dn;
    const char *name = (which == 1) ? "PageUp" : "PageDown";
    long long held_for = now_ms() - pending_since;
    pending = 0;
    /* 重放的是完整的一次点击，所以这一路状态到此为止，不等 release */
    if (which == 1) held_up = 0; else held_dn = 0;

    ungrab_key(kc);            /* 只放开这一个键，另一个仍攥在手里 */
    replay_tap(kc);
    usleep(REPLAY_SETTLE_MS * 1000);
    grab_key(kc);

    msg("single %s (%lldms) -> replayed\n", name, held_for);
}

static void do_combo(void)
{
    pending = 0;
    held_up = held_dn = 0;     /* 不等 release，直接复位 */
    cooldown_until = now_ms() + COOLDOWN_MS;
    msg("BOTH held -> swallowed, no page turn; shooting\n");
    usleep(SHOT_SETTLE_MS * 1000);
    take_screenshot();
}

static void handle_key(const XKeyEvent *k)
{
    int is_up_key = (k->keycode == kc_up);
    int is_dn_key = (k->keycode == kc_dn);
    if (!is_up_key && !is_dn_key) return;

    long long t = now_ms();

    if (debug_on)
        msg("  ev %s kc=%d  up=%d dn=%d pend=%d cd=%lld\n",
            k->type == KeyPress_ ? "PRESS" : "RELEASE", k->keycode,
            held_up, held_dn, pending,
            cooldown_until > t ? cooldown_until - t : 0);

    /* 组合之后的静默期：余下的事件（含迟到的 release）一律吞掉 */
    if (cooldown_until) {
        if (t < cooldown_until) return;
        cooldown_until = 0;
        held_up = held_dn = 0;
        pending = 0;
        msg("cooldown over\n");
    }

    if (k->type == KeyPress_) {
        if (is_up_key) held_up = 1; else held_dn = 1;

        /* 另一个键还按着（且没被判成单键）→ 组合 */
        if ((is_up_key && held_dn) || (is_dn_key && held_up)) {
            do_combo();
            return;
        }

        if (pending == 0) {
            pending = is_up_key ? 1 : 2;
            pending_since = t;
        }
        return;
    }

    /* KeyRelease：只用来收尾，不能作为判定依据 */
    if (is_up_key) held_up = 0; else held_dn = 0;
    if (pending && ((pending == 1 && is_up_key) || (pending == 2 && is_dn_key))) {
        resolve_pending();      /* 窗口内就松手了，立刻按单键放行 */
    }
}

static void find_keypad(void)
{
    int n = 0;
    int best = 0;
    XIDeviceInfo *devs = XIQueryDevice(dpy, 0, &n);
    if (devs) {
        for (int i = 0; i < n; i++) {
            if (devs[i].use != 4) continue;          /* XISlaveKeyboard */
            if (strcmp(devs[i].name, "keypad") == 0) { best = devs[i].deviceid; break; }
            if (!best) best = devs[i].deviceid;
        }
        XIFreeDeviceInfo(devs);
    }
    keypad_dev = best ? XOpenDevice(dpy, (XID)best) : NULL;
    msg("keypad device id=%d open=%s\n", best, keypad_dev ? "ok" : "FAILED");
}

int main(int argc, char **argv)
{
    int argi = 1;
    if (argc > argi && argv[argi][0] >= '0' && argv[argi][0] <= '9') {
        int v = atoi(argv[argi++]);
        if (v >= 50 && v <= 600) pair_window = v;
    }
    debug_on = getenv("KSHOT_DEBUG") != NULL;
    /* upstart 拉起来时环境里通常没有 DISPLAY，X 客户端必须自己补上 */
    if (!getenv("DISPLAY")) setenv("DISPLAY", ":0", 1);

    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = on_signal;
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGINT, &sa, NULL);
    signal(SIGPIPE, SIG_IGN);

    /* framework 刚起来时 X 可能还没就绪 */
    for (int i = 0; i < 60 && !quit; i++) {
        dpy = XOpenDisplay(NULL);
        if (dpy) break;
        sleep(2);
    }
    if (!dpy) { msg("cannot open display, giving up\n"); return 1; }

    mkdir(SHOT_DIR, 0755);
    root = XDefaultRootWindow(dpy);
    kc_up = XKeysymToKeycode(dpy, XStringToKeysym("Prior"));
    kc_dn = XKeysymToKeycode(dpy, XStringToKeysym("Next"));
    if (!kc_up || !kc_dn) { msg("keycode lookup failed\n"); return 1; }
    msg("start: PageUp=%d PageDown=%d pair_window=%dms\n", kc_up, kc_dn, pair_window);

    find_keypad();
    if (!keypad_dev) { msg("no keypad device, replay impossible -> abort\n"); return 1; }

    grab_key(kc_up);
    grab_key(kc_dn);
    msg("grabbed PageUp/PageDown, waiting\n");

    int xfd = XConnectionNumber(dpy);

    while (!quit) {
        while (XPending(dpy)) {
            XEvent ev;
            XNextEvent(dpy, &ev);
            if (ev.pad[0] == KeyPress_ || ev.pad[0] == KeyRelease_)
                handle_key((const XKeyEvent *)&ev);
        }

        long long wait = 100;
        if (pending) {
            long long left = pending_since + pair_window - now_ms();
            if (left <= 0) { resolve_pending(); continue; }
            if (left < wait) wait = left;
        }
        if (cooldown_until) {
            long long left = cooldown_until - now_ms();
            if (left <= 0) { cooldown_until = 0; held_up = held_dn = 0; }
            else if (left < wait) wait = left;
        }

        fd_set fds;
        FD_ZERO(&fds);
        FD_SET(xfd, &fds);
        struct timeval tv;
        tv.tv_sec = 0;
        tv.tv_usec = (long)(wait * 1000);
        select(xfd + 1, &fds, NULL, NULL, &tv);
    }

    msg("exiting, releasing grabs\n");
    ungrab_key(kc_up);
    ungrab_key(kc_dn);
    if (keypad_dev) XCloseDevice(dpy, keypad_dev);
    XCloseDisplay(dpy);
    return 0;
}
