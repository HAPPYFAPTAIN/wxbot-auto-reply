# -*- coding: utf-8 -*-
"""wxbot_send.py — 微信 4.1.x 新版发消息模块（适配「输入防御」机制）。

背景：微信 4.1.11.24 升级后：
  1. 不再向 UIA 暴露控件树（窗口 descendants 只有 2~3 个空 Pane，
     wxauto4 的会话列表/搜索框/消息控件全部消失）
  2. 检测并防御 pyautogui 的键鼠模拟（任意 pyautogui 输入会导致微信窗口被关闭）

实测可行的混合策略（来源：已验证的业务通报工作流项目 wechat_bot.py）：
  - 导航阶段（激活窗口 + Ctrl+F 打开搜索框）：pyautogui 可用（微信此时不防御）
  - 输入阶段（搜索框输入群名、消息输入框粘贴正文、回车发送）：
    必须用 uiautomation 库的 UIA 原生操作（GetFocusedControl + SendKeys），
    走 UIA 文本注入通道，微信不防御

依赖（Python 3.11 环境已装）：pywinauto uiautomation pyautogui pyperclip pillow pywin32

用法：
    from wxbot_send import send_text
    send_text("文件传输助手", "你好")     # 兼容 wxmini2.send_text 的签名
"""

import os
import sys
import time
import threading

import ctypes
import pyautogui
import pyperclip  # noqa: F401  (保留，部分流程会用到)
import uiautomation as auto
import win32clipboard
import win32con
import win32gui
from pywinauto import Desktop

WECHAT_WINDOW_CLASS = "Qt51514QWindowIcon"
_uia_desktop = Desktop(backend="uia")
_wechat_lock = threading.Lock()


def _get_wechat_hwnd():
    """获取微信主窗口句柄（找不到返回 None）。"""
    return win32gui.FindWindow(WECHAT_WINDOW_CLASS, None)


def _get_wechat_uia_window(hwnd=None):
    if hwnd is None:
        hwnd = _get_wechat_hwnd()
    if not hwnd:
        return None
    try:
        return _uia_desktop.window(handle=hwnd)
    except Exception:
        return None


def _pin_wechat_topmost():
    hwnd = _get_wechat_hwnd()
    if hwnd:
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW)


def _unpin_wechat_topmost():
    hwnd = _get_wechat_hwnd()
    if hwnd:
        win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)


def _activate_wechat_window(attempts=5):
    """激活微信窗口到前台（处理最小化/后台状态）。成功返回 True。"""
    hwnd = _get_wechat_hwnd()
    if not hwnd:
        return False
    if not win32gui.IsWindow(hwnd):
        return False
    try:
        rect = win32gui.GetWindowRect(hwnd)
        if rect[0] <= -30000:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.5)
    except Exception:
        return False
    for _ in range(attempts):
        if not win32gui.IsWindow(hwnd):
            return False
        try:
            ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)  # Alt down
            ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)  # Alt up
            time.sleep(0.1)
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            time.sleep(0.3)
            continue
        time.sleep(0.8)
        if win32gui.GetForegroundWindow() == hwnd:
            return True
    return False


# ---------------- 输入防御绕过（UIA 原生通道） ----------------

def _is_wechat_alive():
    """校验微信窗口是否仍存活且焦点在微信内，防止微信关闭后误发到别的窗口。"""
    try:
        hwnd = _get_wechat_hwnd()
        if not hwnd or not win32gui.IsWindow(hwnd):
            return False
        focused = auto.GetFocusedControl()
        if focused is None:
            return False
        top = focused
        for _ in range(20):
            try:
                parent = top.GetParentControl()
                if parent is None or not parent.Exists(0, 0):
                    break
                if parent.ClassName == WECHAT_WINDOW_CLASS or parent.Name == "微信":
                    return True
                top = parent
            except Exception:
                break
        return win32gui.GetForegroundWindow() == hwnd
    except Exception:
        return False


def _set_clipboard_text_unicode(text):
    """CF_UNICODETEXT 设置剪贴板（支持 emoji 等 4 字节字符）。"""
    try:
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        data = text.encode("utf-16-le") + b"\x00\x00"
        win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, data)
        win32clipboard.CloseClipboard()
        return True
    except Exception:
        try:
            win32clipboard.CloseClipboard()
        except Exception:
            pass
        return False


def _uia_paste_text(text, clear=True):
    """UIA 原生粘贴文本到当前焦点控件（微信不防御 UIA 通道）。"""
    try:
        if not _is_wechat_alive():
            return False
        focused = auto.GetFocusedControl()
        if focused is None:
            return False
        if clear:
            focused.SendKeys("{Ctrl}a", waitTime=0.15)
        if not _set_clipboard_text_unicode(text):
            return False
        focused.SendKeys("{Ctrl}v", waitTime=0.5)
        return True
    except Exception:
        return False


def _uia_press_enter():
    try:
        if not _is_wechat_alive():
            return False
        focused = auto.GetFocusedControl()
        if focused is None:
            return False
        focused.SendKeys("{Enter}", waitTime=0.3)
        return True
    except Exception:
        return False


def _uia_sendkeys(keys, wait_time=0.5, timeout=5.0):
    """带超时保护的 UIA SendKeys（@ 选人下拉等场景，防止卡死霸占焦点）。"""
    if not _is_wechat_alive():
        return False
    result = {"done": False}

    def _worker():
        try:
            auto.GetFocusedControl().SendKeys(keys, waitTime=wait_time)
        except Exception:
            pass
        finally:
            result["done"] = True

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return result["done"]


# ---------------- 发送流程 ----------------

def _navigate_to_chat(target, log=None):
    """Ctrl+F 搜索导航到目标聊天（会话列表不可读时的可行路径）。"""
    log = log or (lambda s: None)
    if not _activate_wechat_window():
        log("微信窗口未找到或激活失败")
        return False
    hwnd = _get_wechat_hwnd()
    if not hwnd:
        return False
    w = _get_wechat_uia_window(hwnd)
    if not w:
        log("UIA 窗口获取失败")
        return False
    # set_focus —— 实测是让微信进入搜索框的关键一步
    try:
        w.set_focus()
        time.sleep(1.0)
    except Exception as e:
        log(f"set_focus 异常: {e}")
    # Ctrl+F 打开搜索框（导航阶段，pyautogui 不被防御）
    try:
        pyautogui.hotkey("ctrl", "f")
        time.sleep(1.5)
    except Exception as e:
        log(f"Ctrl+F 异常: {e}")
        return False
    # UIA 输入群名（输入阶段必须用 UIA）
    ok = False
    for retry in range(3):
        if _uia_paste_text(target, clear=True):
            ok = True
            break
        log(f"UIA输入群名失败(第{retry + 1}次)，重试")
        time.sleep(1)
    if not ok:
        log("UIA输入群名失败")
        return False
    time.sleep(2.5)
    if not _uia_press_enter():
        log("UIA回车失败")
        return False
    time.sleep(2.0)
    log(f"已导航到 → {target}")
    return True


def _set_clipboard_image_dib(img_path):
    """把图片放到剪贴板（CF_DIB）。GIF/动图取第一帧（静态发送，动画丢失可接受）。"""
    from PIL import Image
    import io
    img = Image.open(img_path)
    try:
        img.seek(0)
    except Exception:
        pass
    img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "BMP")
    dib = buf.getvalue()[14:]  # DIB = BMP 去掉 14 字节文件头
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib)
    finally:
        win32clipboard.CloseClipboard()
    return True


def send_image(contact, img_path, log=None):
    """发送图片/贴纸到指定联系人/群。返回 True/False。

    流程：导航进群 → 图片上剪贴板(CF_DIB) → 焦点输入框 Ctrl+V → 等加载 → 回车。
    """
    log = log or (lambda s: print(f"[send] {s}"))
    with _wechat_lock:
        _pin_wechat_topmost()
        try:
            if not _navigate_to_chat(contact, log):
                log(f"导航失败 -> {contact}")
                return False
            if not _is_wechat_alive():
                log("微信窗口已关闭，图片发送中止")
                return False
            _set_clipboard_image_dib(img_path)
            focused = auto.GetFocusedControl()
            if focused is None:
                log("无焦点输入框")
                return False
            focused.SendKeys("{Ctrl}v", waitTime=0.8)
            time.sleep(1.5)  # 等图片在输入框里加载完成
            if not _is_wechat_alive():
                log("粘贴后微信已关闭")
                return False
            if not _uia_press_enter():
                log("回车发送失败")
                return False
            time.sleep(1.0)
            log(f"图片发送成功 -> {contact} ({os.path.basename(img_path)})")
            return True
        except Exception as e:
            log(f"图片发送异常: {e}")
            return False
        finally:
            _unpin_wechat_topmost()


def send_text(contact, text, log=None):
    """发送文字消息到指定联系人/群。返回 True/False。

    兼容 wxmini2.send_text(contact, text) 签名。
    流程：激活窗口 → Ctrl+F 搜索 → UIA 粘贴群名 → 回车进群 →
         UIA 粘贴正文 → 回车发送。每步校验微信存活防误发。
    """
    log = log or (lambda s: print(f"[send] {s}"))
    with _wechat_lock:
        _pin_wechat_topmost()
        try:
            if not _navigate_to_chat(contact, log):
                log(f"导航失败 -> {contact}")
                return False
            if not _is_wechat_alive():
                log("微信窗口已关闭，发送中止")
                return False
            if not _uia_paste_text(text, clear=True):
                log("正文粘贴失败")
                return False
            time.sleep(0.5)
            if not _uia_press_enter():
                log("回车发送失败")
                return False
            time.sleep(1.0)
            log(f"文字发送成功 -> {contact}")
            return True
        finally:
            _unpin_wechat_topmost()


def send_text_at(contact, at_name, text, log=None):
    """群聊里真 @ 成员再发正文。返回 True/False。

    流程：导航进群 → 输入框敲 @ → 粘贴昵称搜索 → 回车选中第一人 →
         空格 → 粘贴正文 → 回车发送。每步校验微信存活。
    """
    log = log or (lambda s: print(f"[send] {s}"))
    with _wechat_lock:
        _pin_wechat_topmost()
        try:
            if not _navigate_to_chat(contact, log):
                log(f"导航失败 -> {contact}")
                return False
            if not _is_wechat_alive():
                log("微信窗口已关闭，@发送中止")
                return False
            # 敲 @ 触发选人下拉
            if not _uia_sendkeys("@", wait_time=1.0, timeout=4.0):
                log("输入@失败/超时")
                return False
            time.sleep(1.2)
            if not _is_wechat_alive():
                log("输入@后微信已关闭")
                return False
            # 粘贴昵称搜索（不能 clear，保留刚输入的 @）
            if not _uia_paste_text(at_name, clear=False):
                log(f"@昵称输入失败: {at_name}")
                return False
            time.sleep(1.0)
            if not _is_wechat_alive():
                log("搜昵称后微信已关闭")
                return False
            # 回车选中第一个搜索结果
            if not _uia_sendkeys("{Enter}", wait_time=0.3, timeout=4.0):
                log("选人回车失败/超时")
                return False
            time.sleep(0.5)
            # 空格分隔 + 正文（正文不清空，保留 @ 选择结果）
            _uia_sendkeys(" ", wait_time=0.2, timeout=3.0)
            time.sleep(0.2)
            if not _is_wechat_alive():
                log("微信已关闭")
                return False
            if not _uia_paste_text(text, clear=False):
                log("正文粘贴失败")
                return False
            time.sleep(0.5)
            if not _uia_press_enter():
                log("回车发送失败")
                return False
            time.sleep(1.0)
            log(f"@发送成功 -> {contact} @{at_name}")
            return True
        finally:
            _unpin_wechat_topmost()


def health_check():
    """微信窗口是否存在。"""
    hwnd = _get_wechat_hwnd()
    return bool(hwnd and win32gui.IsWindow(hwnd))


if __name__ == "__main__":
    # 自测：python -X utf8 wxbot_send.py "文件传输助手" "测试消息"
    target = sys.argv[1] if len(sys.argv) > 1 else "文件传输助手"
    text = sys.argv[2] if len(sys.argv) > 2 else f"[wxbot_send 自测] {time.strftime('%H:%M:%S')}"
    print(f"health_check: {health_check()}")
    ok = send_text(target, text)
    print(f"发送结果: {'✅ 成功' if ok else '❌ 失败'}")
