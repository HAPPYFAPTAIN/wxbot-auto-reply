# -*- coding: utf-8 -*-
"""wxmini: WeChat 4.1.12 PC automation — send messages via UIA + clicks.

Usage:
    import wxmini
    wxmini.send_text("文件传输助手", "你好")

How it works (verified 2026-08-11 on Weixin 4.1.12.26):
1. Find window by title 微信 (class Qt51514QWindowIcon)
2. UIA: search EditControl (Name='搜索') -> SetFocus + ValuePattern.SetValue(contact)
3. UIA: results ListControl appears -> click ListItemControl with exact Name match
   (UIA BoundingRectangle = physical px; DPI ~150% so GetWindowRect coords differ — always click using UIA rects)
4. UIA: chat_message_page group rect -> click input area (bottom center) -> type via SendInput unicode -> Enter

Safety: text goes through search-box navigation; typing only happens after the
target chat is opened. Never blind-Enter without the chat page present.
"""
import sys, time, ctypes
import ctypes.wintypes as wt
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

u = ctypes.windll.user32
k32 = ctypes.windll.kernel32

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

def click(x, y):
    u.SetCursorPos(int(x), int(y)); time.sleep(0.12)
    u.mouse_event(2, 0, 0, 0, 0); time.sleep(0.06); u.mouse_event(4, 0, 0, 0, 0)

def find_wechat():
    hwnd = u.FindWindowW(None, "微信")
    if not hwnd:
        raise RuntimeError("WeChat window not found (is 微信 running?)")
    return hwnd

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

def _walk(c, d, fn):
    if d > 14: return None
    try:
        got = fn(c)
    except Exception:
        return None
    if got is not None: return got
    try: ch = c.GetChildren()
    except Exception: return None
    for x in ch:
        got = _walk(x, d + 1, fn)
        if got is not None: return got
    return None

def find_search_edit(hwnd):
    return _walk(_root(hwnd), 0, lambda c: c if (c.ControlTypeName == "EditControl" and c.Name == "搜索") else None)

def find_result_item(hwnd, name):
    return _walk(_root(hwnd), 0, lambda c: c if (c.ControlTypeName == "ListItemControl" and c.Name == name) else None)

def find_chat_page(hwnd):
    c = _walk(_root(hwnd), 0, lambda c: c if c.AutomationId == "chat_message_page" else None)
    if c is None: return None
    r = c.BoundingRectangle
    return (r.left, r.top, r.right, r.bottom)

def open_chat(hwnd, contact, timeout=6.0):
    """Search for contact and open the chat. Returns True on success."""
    force_foreground(hwnd)
    se = find_search_edit(hwnd)
    if se is None: raise RuntimeError("search edit not found")
    se.SetFocus(); time.sleep(0.3)
    se.GetValuePattern().SetValue(contact)
    t0 = time.time()
    item = None
    while time.time() - t0 < timeout:
        item = find_result_item(hwnd, contact)
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
    """Open chat with contact and send text. Returns True."""
    hwnd = find_wechat()
    cp = open_chat(hwnd, contact)
    force_foreground(hwnd)
    ix, iy = (cp[0] + cp[2]) / 2, cp[3] - 90
    click(ix, iy)
    time.sleep(0.4)
    type_unicode(text)
    time.sleep(0.4)
    key(0x0D)  # Enter to send (WeChat default: Enter sends)
    time.sleep(0.8)
    return True

if __name__ == "__main__":
    send_text("文件传输助手", "wxmini 库函数第二次测试")
    print("sent ok")
