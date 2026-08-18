# -*- coding: utf-8 -*-
"""build_sticker_catalog.py — 从微信本地贴纸存储直接建目录（无 UIA）。

源头：D:\\weixin\\xwechat_files\\Emojis\\<md5>.gif|png（收藏贴纸的本地缓存，
WeChat4.0 明文存放）。每张取首帧 → vision 生成 label/desc/keywords →
写 wxbot_images/stickers/catalog.json（wxbot 运行时读取 + 面板可查看）。

用法：python -X utf8 build_sticker_catalog.py
"""
import base64
import json
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wxbot
from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = r"D:\weixin\xwechat_files\Emojis"
OUT_DIR = os.path.join(BASE, "wxbot_images", "stickers")
CATALOG = os.path.join(OUT_DIR, "catalog.json")
TMP = os.path.join(BASE, "tmp", "sticker_frames")

PROMPT = (
    "这是一张微信自定义表情包贴纸。用中文简洁输出三行，严格按此格式：\n"
    "label: 4-8字简短名称（如 捂耳朵拒绝 / 企鹅锤头）\n"
    "desc: 一句话画面内容（角色/动作/图上文字）\n"
    "keywords: 3-5个中文检索关键词，逗号分隔（情绪/用途/画面主体，如 嘲讽,偷笑,看戏）"
)


def first_frame(path):
    """GIF/动图取首帧存临时 jpg，返回路径。"""
    os.makedirs(TMP, exist_ok=True)
    img = Image.open(path)
    try:
        img.seek(0)
    except Exception:
        pass
    img = img.convert("RGB")
    if max(img.size) > 512:
        s = 512 / max(img.size)
        img = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))))
    out = os.path.join(TMP, os.path.basename(path) + ".jpg")
    img.save(out, "JPEG", quality=85)
    return out


def describe(cfg, img_path):
    """用 vision 链 + 贴纸专用 prompt 生成 label/desc/keywords。"""
    vcfg = cfg.get("vision", {}) or {}
    with open(img_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    payload = {
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ],
        }],
    }
    for i, attempt in enumerate([vcfg] + list(vcfg.get("fallbacks", []) or [])):
        try:
            key = attempt.get("api_key") or wxbot._load_api_key(attempt.get("api_key_env", ""))
            if not key:
                continue
            url = attempt["base_url"].rstrip("/") + "/chat/completions"
            p = dict(payload, model=attempt["model"])
            p["max_tokens"] = int(attempt.get("max_tokens", vcfg.get("max_tokens", 300)))
            data = wxbot._http_post_json(url, p, key, timeout=int(attempt.get("timeout", 45)))
            text = wxbot._vision_content(data)
            if text:
                return text
        except Exception as e:
            print(f"  vision {attempt.get('model')} error: {e}")
    return None


def parse_describe(text):
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


def main():
    cfg = wxbot.load_config()
    os.makedirs(OUT_DIR, exist_ok=True)
    files = sorted(
        (os.path.join(SRC, fn) for fn in os.listdir(SRC)
         if fn.lower().endswith((".gif", ".png", ".jpg", ".jpeg", ".webp"))),
        key=lambda p: os.path.getmtime(p),
    )
    print(f"发现 {len(files)} 张贴纸源文件")
    stickers = []
    for i, path in enumerate(files, 1):
        desc = {"label": f"贴纸{i}", "desc": "", "keywords": []}
        try:
            frame = first_frame(path)
            text = describe(cfg, frame)
            if text:
                parsed = parse_describe(text)
                if parsed["label"]:
                    desc = parsed
        except Exception as e:
            print(f"  #{i} 处理异常: {e}")
        stickers.append({
            "index": i,
            "file": path,                      # 发送用：直接读源文件
            "label": desc["label"],
            "desc": desc["desc"],
            "emotion": "",
            "keywords": desc["keywords"],
        })
        print(f"  #{i} {desc['label']} | {desc['desc'][:40]} | {','.join(desc['keywords'])}")
        time.sleep(0.4)
    catalog = {
        "source": "wechat_local_emojis_dir",
        "count": len(stickers),
        "updated": time.strftime("%Y-%m-%d %H:%M"),
        "note": "微信本地贴纸存储直读（无UIA）；file 为源文件绝对路径，发送走剪贴板DIB粘贴",
        "stickers": stickers,
    }
    with open(CATALOG, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=1)
    print(f"catalog written: {CATALOG} ({len(stickers)} stickers)")


if __name__ == "__main__":
    main()
