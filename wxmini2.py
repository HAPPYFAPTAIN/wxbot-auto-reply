# -*- coding: utf-8 -*-
"""wxmini2: WeChat 4.1.12 PC automation — read + send via UIA.

Extends the hand-rolled UIA approach (no wxauto, direct UIA walking):
  list_sessions()      -> read left sidebar conversation list
  read_chat()          -> read current chat message list (visible bubble items)
  send_text(contact,t) -> open chat by search + type + Enter (verified)

Verified 2026-08-11: session_list id='session_list' (13 convs incl. groups),
chat_message_list id='chat_message_list' exposes bubble items with Name = text.
"""
import sys, time, ctypes, random
import ctypes.wintypes as wt
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

u = ctypes.windll.user32
k32 = ctypes.windll.kernel32

# ---------------------------------------------------------------- input
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_ulonglong)]

class _U(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]

class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _U)]

def type_unicode(text, delay=0.03):
    for ch in text:
        code = ord(ch)
        for flags in (0x0004, 0x0004 | 0x0002):
            inp = INPUT(); inp.type = 1
            inp.u.ki = KEYBDINPUT(0, code, flags, 0, 0)
            if u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) != 1:
                raise RuntimeError("SendInput failed")
        time.sleep(delay)

def key(vk):
    u.keybd_event(vk, 0, 0, 0); time.sleep(0.04); u.keybd_event(vk, 0, 2, 0)

# ---------------------------------------------------------------- clipboard paste
# 64-bit pointer fix: GlobalAlloc/GlobalLock return pointers
k32.GlobalAlloc.restype = ctypes.c_void_p
k32.GlobalLock.restype = ctypes.c_void_p
k32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
k32.GlobalLock.argtypes = [ctypes.c_void_p]
k32.GlobalUnlock.argtypes = [ctypes.c_void_p]

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

u.GetClipboardData.restype = ctypes.c_void_p
u.GetClipboardData.argtypes = [wt.UINT]
u.SetClipboardData.restype = ctypes.c_void_p
u.SetClipboardData.argtypes = [wt.UINT, ctypes.c_void_p]

def get_clipboard_text():
    """Read current clipboard as text (for verification). None = open failed."""
    for _ in range(5):
        if u.OpenClipboard(None):
            break
        time.sleep(0.1)
    else:
        return None
    try:
        h = u.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return ""
        ptr = k32.GlobalLock(h)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)
        finally:
            k32.GlobalUnlock(h)
    finally:
        u.CloseClipboard()

def set_clipboard(text):
    """Put text on the Windows clipboard as CF_UNICODETEXT."""
    data = (text + "\0").encode("utf-16-le")
    for _ in range(5):
        if u.OpenClipboard(None):
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("OpenClipboard failed")
    try:
        u.EmptyClipboard()
        h = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not h:
            raise RuntimeError("GlobalAlloc failed")
        ptr = k32.GlobalLock(h)
        ctypes.memmove(ptr, data, len(data))
        k32.GlobalUnlock(h)
        if not u.SetClipboardData(CF_UNICODETEXT, h):
            raise RuntimeError("SetClipboardData failed")
    finally:
        u.CloseClipboard()

def _ctrl_combo(vk):
    """Ctrl+<vk> chord."""
    u.keybd_event(0x11, 0, 0, 0); time.sleep(0.03)
    u.keybd_event(vk, 0, 0, 0); time.sleep(0.03)
    u.keybd_event(vk, 0, 2, 0); time.sleep(0.03)
    u.keybd_event(0x11, 0, 2, 0)

def paste():
    """Send Ctrl+V."""
    _ctrl_combo(0x56)

def select_all():
    _ctrl_combo(0x41)

def copy_selection():
    _ctrl_combo(0x43)

_PASTE_SENTINEL = "\x00PASTE_CHECK\x00"

def paste_verified(text):
    """真实粘贴并强制验证：剪贴板写入→读回校验→Ctrl+V→全选→复制→读回，
    确认输入框里真的有这段文字（不是注入、也不是静默失败）。Returns True/False。"""
    set_clipboard(text)
    if get_clipboard_text() != text:
        print("!! clipboard write verify failed")
        return False
    paste()
    time.sleep(random.uniform(0.45, 0.8))
    # 用哨兵清空剪贴板：若输入框为空，Ctrl+C 不会改剪贴板，读回仍是哨兵 → 检出
    set_clipboard(_PASTE_SENTINEL)
    select_all(); time.sleep(0.15)
    copy_selection(); time.sleep(random.uniform(0.35, 0.6))
    got = get_clipboard_text() or ""
    if got.strip() == text.strip():
        return True
    print("!! paste verify failed: input readback mismatch (got %r)" % got[:60])
    return False

_last_send_ts = [0.0]
MIN_SEND_GAP_S = 3.0  # 任意两次发送之间的全局最小间隔，防机关枪连发被风控

def click(x, y):
    u.SetCursorPos(int(x), int(y)); time.sleep(0.12)
    u.mouse_event(2, 0, 0, 0, 0); time.sleep(0.06); u.mouse_event(4, 0, 0, 0, 0)

# ---------------------------------------------------------------- window
def find_wechat():
    """Find the REAL WeChat main window (Qt51514QWindowIcon), not the Chrome
    搜一搜 webview which also has title 微信."""
    found = []
    def cb(hwnd, lparam):
        if not u.IsWindowVisible(hwnd):
            return True
        cls = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(hwnd, cls, 256)
        if cls.value == "Qt51514QWindowIcon":
            length = u.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            u.GetWindowTextW(hwnd, buf, length + 1)
            if buf.value.startswith("微信"):
                found.append(hwnd)
        return True
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    u.EnumWindows(WNDENUMPROC(cb), 0)
    if not found:
        raise RuntimeError("WeChat main window not found (is 微信 running?)")
    return found[0]

def force_foreground(hwnd):
    fg = u.GetForegroundWindow()
    tid_fg = u.GetWindowThreadProcessId(fg, None)
    tid_me = k32.GetCurrentThreadId()
    u.keybd_event(0x12, 0, 0, 0)
    u.AttachThreadInput(tid_me, tid_fg, True)
    u.ShowWindow(hwnd, 9)
    u.SetForegroundWindow(hwnd); u.BringWindowToTop(hwnd); u.SetActiveWindow(hwnd)
    u.AttachThreadInput(tid_me, tid_fg, False)
    u.keybd_event(0x12, 0, 2, 0)
    time.sleep(0.4)
    return u.GetForegroundWindow() == hwnd

def _root(hwnd):
    from wxauto4.uia import uiautomation as uia
    return uia.ControlFromHandle(hwnd)

def _walk(c, d, fn, maxd=24):
    if d > maxd: return None
    try:
        got = fn(c)
    except Exception:
        return None
    if got is not None: return got
    try:
        ch = c.GetChildren()
    except Exception:
        return None
    for x in ch:
        got = _walk(x, d + 1, fn, maxd)
        if got is not None: return got
    return None

def _walk_all(c, d, fn, maxd=24):
    if d > maxd: return
    try:
        fn(c)
    except Exception:
        return
    try:
        ch = c.GetChildren()
    except Exception:
        return
    for x in ch:
        _walk_all(x, d + 1, fn, maxd)

# ---------------------------------------------------------------- locate
def find_search_edit(hwnd):
    return _walk(_root(hwnd), 0, lambda c: c if (c.ControlTypeName == "EditControl" and c.Name == "搜索") else None)

def find_search_result(hwnd, name):
    """在搜索结果里找真正的联系人/群聊项。
    只在「联系人」「群聊」分组内匹配；绝不点「搜一搜」「搜索网络结果」「聊天记录」。"""
    root = _root(hwnd)
    items = []
    def ci(x):
        if getattr(x, "ControlTypeName", "") == "ListItemControl":
            items.append(x)
    _walk_all(root, 0, ci, maxd=14)
    GOOD_SECTIONS = ("联系人", "群聊", "最常使用")
    BAD_HEADERS = ("聊天记录", "搜索网络结果", "公众号", "小程序", "表情", "朋友圈")
    section = None
    for it in items:
        nm = (it.Name or "").strip()
        if not nm:
            continue
        if nm in GOOD_SECTIONS:
            section = nm
            continue
        if nm in BAD_HEADERS:
            section = "BAD"
            continue
        if nm.startswith("查看全部") or nm.startswith("查看更多"):
            continue
        if "搜一搜" in nm:
            continue
        if section not in GOOD_SECTIONS:
            continue
        first = nm.split("\n")[0].strip()
        if first == name or first.startswith(name):
            return it
    return None

def find_chat_page(hwnd):
    c = _walk(_root(hwnd), 0, lambda c: c if c.AutomationId == "chat_message_page" else None)
    if c is None: return None
    r = c.BoundingRectangle
    return (r.left, r.top, r.right, r.bottom)

def find_session_list(hwnd):
    return _walk(_root(hwnd), 0, lambda c: c if c.AutomationId == "session_list" else None)

def find_message_list(hwnd):
    return _walk(_root(hwnd), 0, lambda c: c if c.AutomationId == "chat_message_list" else None)

# ---------------------------------------------------------------- read
def list_sessions(hwnd=None):
    """Return [{name, last, raw}] for each conversation in the left sidebar."""
    hwnd = hwnd or find_wechat()
    sl = find_session_list(hwnd)
    if sl is None:
        return []
    items = []
    def ci(x):
        if getattr(x, "ControlTypeName", "") == "ListItemControl":
            items.append(x)
    _walk_all(sl, 0, ci, maxd=10)
    out = []
    for it in items:
        raw = it.Name or ""
        lines = [l for l in raw.split("\n") if l.strip()]
        out.append({
            "name": lines[0] if lines else "",
            "last": lines[1] if len(lines) > 1 else "",
            "raw": raw,
        })
    return out

def read_chat(hwnd=None, limit=30, detect_side=True):
    """Read visible message bubbles from the currently open chat.
    Returns list of {kind, text, rect, side}.
    side: 'own' | 'other' | 'unknown' (via screenshot pixel analysis).
    Text bubbles: Name == text. Time rows appear as small ListItems like '12:52'."""
    hwnd = hwnd or find_wechat()
    ml = find_message_list(hwnd)
    if ml is None:
        return []
    items = []
    def ci(x):
        if getattr(x, "ControlTypeName", "") == "ListItemControl":
            items.append(x)
    _walk_all(ml, 0, ci, maxd=10)
    out = []
    for it in items[-limit:]:
        name = it.Name or ""
        r = it.BoundingRectangle
        kind = "text"
        if "\n" in name and ("文件" in name or ".pdf" in name or ".doc" in name or "微信电脑版" in name):
            kind = "file"
        elif name.replace(":", "").isdigit() and len(name) <= 5:
            kind = "time"
        elif "[图片]" in name:
            kind = "image"
        elif "[聊天记录]" in name:
            kind = "history"
        out.append({
            "kind": kind,
            "text": name,
            "rect": (r.left, r.top, r.right, r.bottom),
            "side": "unknown",
        })
    if detect_side and out:
        _annotate_sides(ml, out)
    return out


def _annotate_sides(ml, out):
    """Annotate own/other via screenshot: own bubble is green (#3x) on the
    right, other's bubble is dark grey on the left (deep theme).
    Fallback: bubble center x position."""
    try:
        from PIL import ImageGrab
    except Exception:
        return
    lr = ml.BoundingRectangle
    try:
        img = ImageGrab.grab(bbox=(lr.left, lr.top, lr.right, lr.bottom)).convert("RGB")
    except Exception:
        return
    W, H = img.size
    if W <= 0 or H <= 0:
        return
    BG = (30, 30, 31)
    def close(c1, c2, tol=12):
        return all(abs(a - b) <= tol for a, b in zip(c1, c2))
    def classify(rect):
        ry = (rect[1] + rect[3]) // 2 - lr.top
        if ry < 0 or ry >= H:
            return "unknown"
        step = 4
        runs = []
        in_run = False
        start = 0
        acc = [0, 0, 0]
        n = 0
        def flush(x):
            nonlocal in_run, acc, n
            if in_run:
                runs.append((start, x, tuple(v // max(n, 1) for v in acc)))
                in_run = False
                acc = [0, 0, 0]
                n = 0
        for x in range(0, W, step):
            c = img.getpixel((x, ry))
            if not close(c, BG):
                if not in_run:
                    in_run = True
                    start = x
                acc[0] += c[0]; acc[1] += c[1]; acc[2] += c[2]
                n += 1
            else:
                flush(x)
        flush(W)
        if not runs:
            return "unknown"
        main = max(runs, key=lambda s: s[1] - s[0])
        a, b, c = main
        if b - a < 10:
            return "unknown"
        # green bubble => own (WeChat deep theme own-bubble color)
        if c[1] > c[0] + 25 and c[1] > c[2] + 25:
            return "own"
        cx = (a + b) / 2
        if cx < W * 0.45:
            return "other"
        if cx > W * 0.55:
            return "own"
        return "unknown"
    for m in out:
        m["side"] = classify(m["rect"])
        if m["kind"] == "time":
            m["side"] = "unknown"

def current_chat_name(hwnd=None):
    """Read the big title label of the open chat (contact or group name)."""
    hwnd = hwnd or find_wechat()
    c = _walk(_root(hwnd), 0, lambda c: c if c.AutomationId == "content_view.top_content_view.title_h_view.left_v_view.left_content_v_view.left_ui_.big_title_line_h_view.current_chat_name_label" else None)
    if c is None: return None
    return c.Name or None

# ---------------------------------------------------------------- send
def open_chat_by_click(hwnd, name, timeout=6.0):
    """直接在会话列表里点击打开会话（不经过搜索框）。"""
    force_foreground(hwnd)
    sl = find_session_list(hwnd)
    if sl is None:
        return False
    t0 = time.time()
    while time.time() - t0 < timeout:
        items = []
        def ci(x):
            if getattr(x, "ControlTypeName", "") == "ListItemControl":
                items.append(x)
        _walk_all(sl, 0, ci, maxd=10)
        for it in items:
            nm = it.Name or ""
            if nm.split("\n")[0] == name:
                r = it.BoundingRectangle
                click((r.left + r.right) / 2, (r.top + r.bottom) / 2)
                time.sleep(1.5)
                return True
        time.sleep(0.5)
    return False

def open_chat(hwnd, contact, timeout=6.0):
    """搜索框输入对象，点击搜出来的对象（绝不点搜一搜）。Returns chat page rect."""
    force_foreground(hwnd)
    se = find_search_edit(hwnd)
    if se is None: raise RuntimeError("search edit not found")
    se.SetFocus(); time.sleep(0.3)
    se.GetValuePattern().SetValue(contact)
    t0 = time.time()
    item = None
    while time.time() - t0 < timeout:
        item = find_search_result(hwnd, contact)
        if item is not None: break
        time.sleep(0.4)
    if item is None: raise RuntimeError(f"search result for {contact!r} not found")
    r = item.BoundingRectangle
    click((r.left + r.right) / 2, (r.top + r.bottom) / 2)
    time.sleep(1.0)
    cp = find_chat_page(hwnd)
    if cp is None: raise RuntimeError("chat page not found after opening chat")
    return cp

def send_text(contact, text):
    """打开会话（优先会话列表点击，找不到才搜索）并发送文字。Returns True.
    发送方式：真实剪贴板 + Ctrl+V 粘贴，粘贴后强制回读验证；
    验证失败重试一次，仍失败才回退逐字打字并大声告警。"""
    gap = time.time() - _last_send_ts[0]
    if gap < MIN_SEND_GAP_S:
        time.sleep(MIN_SEND_GAP_S - gap)
    hwnd = find_wechat()
    cp = find_chat_page(hwnd)
    cur = current_chat_name(hwnd) if cp is not None else None
    if cp is None or cur != contact:
        ok = open_chat_by_click(hwnd, contact)
        if ok:
            cp = find_chat_page(hwnd)
        else:
            cp = open_chat(hwnd, contact)
    if cp is None:
        raise RuntimeError(f"cannot open chat with {contact!r}")
    force_foreground(hwnd)
    # 点击输入框，坐标带随机抖动，更像真人
    ix = (cp[0] + cp[2]) / 2 + random.randint(-14, 14)
    iy = cp[3] - 90 + random.randint(-6, 6)
    click(ix, iy)
    time.sleep(random.uniform(0.35, 0.6))
    ok = False
    try:
        ok = paste_verified(text)
    except Exception as e:
        print("paste error:", e)
    if not ok:
        # 重试一次：重新点输入框再粘
        try:
            click(ix, iy)
            time.sleep(0.4)
            ok = paste_verified(text)
        except Exception as e:
            print("paste retry error:", e)
    if not ok:
        print("!! PASTE FAILED TWICE — fallback to typing (injection risk, investigate!)")
        type_unicode(text)
        time.sleep(0.4)
    time.sleep(random.uniform(0.6, 1.2))  # 粘贴后到回车前的人性化停顿
    key(0x0D)  # Enter sends in WeChat PC default
    time.sleep(0.8)
    _last_send_ts[0] = time.time()
    return True

if __name__ == "__main__":
    import json
    hwnd = find_wechat()
    print("== sessions ==")
    for s in list_sessions(hwnd):
        print(json.dumps(s, ensure_ascii=False))
    print("== current chat ==")
    print("name:", current_chat_name(hwnd))
    for m in read_chat(hwnd, limit=15):
        print(json.dumps(m, ensure_ascii=False))
