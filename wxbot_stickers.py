# -*- coding: utf-8 -*-
"""
wxbot_stickers.py — 微信「爱心」自定义表情包的目录构建/刷新工具。

用法：
    python -X utf8 wxbot_stickers.py --refresh

流程：
  1. UIA 打开表情面板 → 切「自定义表情」tab → 枚举贴纸格子 → 逐格截图存 wxbot_images/stickers/NN.png
  2. 调 wxbot.vision_describe（mimo 主 / clawapi 备）逐张生成 label+desc+keywords
  3. 写 wxbot_images/stickers/catalog.json（wxbot 运行时带 mtime 缓存读取）

GUI 的「重新扫描」按钮就是 spawn 这个脚本。运行期间会抢微信窗口焦点，几秒就完事。
"""
import sys, io, os, re, json, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wxmini2 as w
import wxbot
from PIL import ImageGrab

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "wxbot_images", "stickers")

DESCRIBE_PROMPT = (
    "这是一张微信自定义表情包贴纸。用中文简洁输出三行，严格按此格式：\n"
    "label: 4-8字简短名称（如 捂耳朵拒绝 / 企鹅锤头）\n"
    "desc: 一句话画面内容（角色/动作/图上文字）\n"
    "keywords: 3-5个中文检索关键词，逗号分隔（情绪/用途/画面主体，如 嘲讽,偷笑,看戏）"
)


def shoot_stickers():
    """打开表情面板截取自定义表情所有格子，返回 [(index, path, rect), ...]"""
    os.makedirs(OUT, exist_ok=True)
    hwnd = w.find_wechat()
    w.force_foreground(hwnd)
    time.sleep(0.4)
    cp = w.find_chat_page(hwnd)
    if cp is None:
        raise RuntimeError("no chat page; open a chat first")
    w.click(cp[0] + w._EMOJI_BTN_DX, cp[3] - w._EMOJI_BTN_DY)
    pop = w.wait_emoticon_popover(timeout=4.0)
    if pop is None:
        raise RuntimeError("emoticon popover not found")
    time.sleep(0.5)
    tp = w._emoji_tab_pos(pop, w._CUSTOM_TAB)
    if tp is None:
        w.key(0x1B)
        raise RuntimeError(f"tab {w._CUSTOM_TAB!r} not found")
    w.click(tp[0], tp[1])
    time.sleep(1.2)
    btns = w.list_custom_sticker_buttons(pop)
    if not btns:
        w.key(0x1B)
        raise RuntimeError("no sticker buttons found")
    shots = []
    for i, (l, t, r, b) in enumerate(btns, 1):
        pad = 4
        img = ImageGrab.grab(bbox=(l + pad, t + pad, r - pad, b - pad))
        p = os.path.join(OUT, f"{i:02d}.png")
        img.save(p)
        shots.append((i, p, [l, t, r, b]))
        print(f"[stickers] shot #{i} -> {p}")
    w.key(0x1B)
    return shots


def parse_describe(text):
    """解析 vision 输出的 label/desc/keywords 三行。"""
    out = {"label": "", "desc": "", "keywords": []}
    for line in (text or "").splitlines():
        m = re.match(r"\s*(label|desc|keywords)\s*[:：]\s*(.+?)\s*$", line, re.I)
        if not m:
            continue
        k, v = m.group(1).lower(), m.group(2)
        if k == "label":
            out["label"] = v
        elif k == "desc":
            out["desc"] = v
        elif k == "keywords":
            out["keywords"] = [x.strip() for x in re.split(r"[,，、/]", v) if x.strip()]
    return out


def refresh_catalog():
    cfg = wxbot.load_config()
    shots = shoot_stickers()
    stickers = []
    for i, path, rect in shots:
        desc = {"label": f"贴纸{i}", "desc": "", "keywords": []}
        try:
            text = wxbot.vision_describe(cfg, path)
            if text:
                parsed = parse_describe(text)
                if parsed["label"]:
                    desc = parsed
        except Exception as e:
            print(f"[stickers] vision error #{i}: {e}")
        stickers.append({
            "index": i,
            "file": f"stickers/{i:02d}.png",
            "label": desc["label"],
            "desc": desc["desc"],
            "emotion": "",
            "keywords": desc["keywords"],
            "rect": rect,
        })
        print(f"[stickers] #{i} {desc['label']} | {desc['desc'][:40]}")
        time.sleep(0.5)
    catalog = {
        "tab": w._CUSTOM_TAB,
        "count": len(stickers),
        "updated": time.strftime("%Y-%m-%d %H:%M"),
        "note": "微信「爱心」收藏表情包，index 1 起，行优先从左到右；运行时按同样顺序枚举格子点击",
        "stickers": stickers,
    }
    cpath = os.path.join(OUT, "catalog.json")
    with open(cpath, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=1)
    print(f"[stickers] catalog written: {cpath} ({len(stickers)} stickers)")
    return catalog


if __name__ == "__main__":
    if "--refresh" in sys.argv:
        refresh_catalog()
    else:
        print("usage: python -X utf8 wxbot_stickers.py --refresh")
