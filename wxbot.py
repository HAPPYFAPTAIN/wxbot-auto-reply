# -*- coding: utf-8 -*-
"""wxbot: WeChat auto read + reply daemon (hand-rolled UIA via wxmini2).

Design:
- Poll session_list every poll_interval_seconds
- Detect new inbound: compare per-conversation last-message fingerprint
- Open conversation, read latest bubbles, find the last message not sent by us
- Reply policy from config (private always / group only with @mention)
- Delay before replying (human-like random), then send via UIA
- State persisted to state_file so restarts don't duplicate replies

Config: wxbot_config.json next to this file.
"""
import json, os, sys, time, random, re, hashlib
import unicodedata
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wxmini2 as wx
import wxbot_files
import wxbot_memory
import wxbot_context

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "wxbot_config.json")
DEFAULT_CONFIG = {
    "enabled": True,
    "poll_interval_seconds": 5,
    "reply": {
        "private": {"enabled": True, "min_delay_s": 8.0, "max_delay_s": 15.0,
                    "cooldown_s": 60, "allow": [], "deny": [],
                    "quiet_hours": {"enabled": False, "start": "23:30", "end": "07:30", "allow_contacts": []}},
        "group": {"enabled": True, "require_mention": True, "min_delay_s": 2.0, "max_delay_s": 5.0,
                  "mention_names": ["爱而不恨"], "allow": [], "deny": []},
        "unlimited_groups": ["【官方】DeepSeek交流34群"],
        "unlimited_group_interval_s": 0,
        "context_messages": {"default": 8, "【官方】DeepSeek交流34群": 30},
        "group_persona": {},
        "max_sentences": 4,
        "sentence_delay_s": [8.0, 8.0],
        "allow_contacts": [],
        "deny_contacts": ["公众号", "服务号", "文件传输助手", "折叠的聊天", "微信团队"],
        "max_reply_chars": 300,
        "personas": {
            "enabled": True,
            "dir": "personas",
            "default": "",
            "per_group": {
                "【官方】DeepSeek交流34群": "wen"
            },
            "per_contact": {},
            "definitions": {
                "wen": "personas/wen.md"
            },
            "behaviors": {
                "_default": {"sticker": 0.15, "emoji": 0.15, "at": 0.2, "image": 0.1, "quote": 0.2},
                "wen": {"sticker": 0.3, "emoji": 0.25, "at": 0.4, "image": 0.15, "quote": 0.4}
            }
        }
    },
    "llm": {
        "base_url": "https://opencode.ai/zen/go/v1",
        "model": "deepseek-v4-flash",
        "api_key_env": "OPENCODE_API_KEY",
        "temperature": 0.9,
        "max_tokens": 400,
        "context_window": 32000,
        "fallbacks": [
            {"base_url": "https://fast.clawapi.store/v1", "model": "gpt-5.6-sol", "api_key_env": "CLAWAPI_API_KEY"}
        ]
    },
    "vision": {
        "enabled": True,
        "base_url": "https://opencode.ai/zen/go/v1",
        "model": "mimo-v2.5",
        "api_key_env": "OPENCODE_API_KEY",
        "max_tokens": 300,
        "fallbacks": [
            {"base_url": "https://fast.clawapi.store/v1", "model": "gpt-5.6-sol", "api_key_env": "CLAWAPI_API_KEY"}
        ]
    },
    "images": {
        "enabled": True,
        "dir": os.path.join(BASE, "wxbot_images")
    },
    "stickers": {
        "enabled": True,
        "catalog": os.path.join(BASE, "wxbot_images", "stickers", "catalog.json")
    },
    "context": {
        "compression": {
            "enabled": False,
            "mode": "percent",       # percent | tokens
            "percent": 60,
            "tokens": 4000,
            "keep_recent": 4,
            "trim_chars": 60
        }
    },
    "memory": {
        "enabled": True,
        "every_n_replies": 5,
        "long_term_chars": 1200,
        "daily_chars": 800
    },
    "state_file": os.path.join(BASE, "wxbot_state.json"),
    "own_nicknames": ["爱而不恨"]
}

def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user = json.load(f)
            for k, v in user.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        except Exception as e:
            print("config load error:", e)
    return cfg

def fingerprint(name, text):
    return hashlib.md5(f"{name}|{text}".encode("utf-8")).hexdigest()

class State:
    def __init__(self, path):
        self.path = path
        self.data = {"seen": {}, "replied_to": {}, "sent": []}
        self._load()
    def _load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self.data = {
                    "seen": loaded.get("seen", {}),
                    "replied_to": loaded.get("replied_to", {}),
                    "sent": loaded.get("sent", []),
                }
        except Exception:
            self.data = {"seen": {}, "replied_to": {}, "sent": []}
    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
        except Exception as e:
            print("state save error:", e)
    def is_seen(self, name, text):
        fp = fingerprint(name, text)
        return self.data["seen"].get(name) == fp
    def mark_seen(self, name, text):
        self.data["seen"][name] = fingerprint(name, text)
    def replied_to(self, name, text):
        fps = self.data.get("replied_to", {}).get(name, [])
        return fingerprint(name, text) in fps
    def mark_replied(self, name, text):
        fps = self.data.setdefault("replied_to", {}).setdefault(name, [])
        fps.append(fingerprint(name, text))
        self.data["replied_to"][name] = fps[-40:]
    def last_reply_ts(self, name):
        return self.data.get("reply_ts", {}).get(name, 0)
    def mark_reply_ts(self, name):
        self.data.setdefault("reply_ts", {})[name] = time.time()
    def recently_sent(self, name, text, window_s=120):
        now = time.time()
        for s in self.data["sent"]:
            if s["name"] == name and s["text"] == text and now - s["ts"] < window_s:
                return True
        return False
    def record_sent(self, name, text):
        self.data["sent"].append({"name": name, "text": text, "ts": time.time()})
        self.data["sent"] = self.data["sent"][-50:]

# ---------------------------------------------------------------- http
def _http_post_json(url, payload, api_key, timeout=60):
    """POST JSON，返回解析后的 dict。
    优先 curl_cffi（Chrome TLS 指纹，绕 Cloudflare 1010 ban）；没有就退回 urllib。"""
    try:
        from curl_cffi import requests as creq
        resp = creq.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            impersonate="chrome",
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except ImportError:
        pass
    import urllib.request
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))

# ---------------------------------------------------------------- llm
# ---------------------------------------------------------------- vision & images
def _load_api_key(key_env):
    api_key = os.environ.get(key_env)
    if api_key:
        return api_key
    try:
        oc = os.path.expanduser("~/.openclaw/openclaw.json")
        if not os.path.exists(oc):
            oc = "F:/OpenClaw/.openclaw/openclaw.json"
        with open(oc, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return (data.get("env") or {}).get(key_env, "")
    except Exception:
        return ""

def vision_describe(cfg, image_path):
    """调 MiMo v2.5 识图：返回图片内容简述（中文，一两句）。失败返回 None。"""
    vcfg = cfg.get("vision", {}) or {}
    if not vcfg.get("enabled", True):
        return None
    api_key = _load_api_key(vcfg.get("api_key_env", "OPENCODE_API_KEY"))
    if not api_key:
        print("vision: no api key")
        return None
    import base64, urllib.request
    ext = os.path.splitext(image_path)[1].lower().lstrip(".") or "png"
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp"}.get(ext, "image/png")
    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
    except Exception as e:
        print("vision read image error:", e)
        return None
    url = vcfg["base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": vcfg["model"],
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "用一两句中文描述这张图片的内容（什么人/什么东西/什么场景/图上有什么文字），简洁直白，不要评价。"},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }],
        "temperature": 0.3,
        "max_tokens": vcfg.get("max_tokens", 300),
    }
    try:
        data = _http_post_json(url, payload, api_key, timeout=60)
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print("vision llm error:", e)
    # fallbacks：主识图通道挂了逐个试备用
    for fb in vcfg.get("fallbacks", []) or []:
        try:
            fb_key = _load_api_key(fb.get("api_key_env", ""))
            if not fb_key:
                continue
            fb_url = fb["base_url"].rstrip("/") + "/chat/completions"
            fb_payload = dict(payload, model=fb["model"])
            data = _http_post_json(fb_url, fb_payload, fb_key, timeout=60)
            print(f"[vision] fallback ok: {fb['model']}")
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"vision fallback {fb.get('model')} error:", e)
    return None

def grab_bubble_image(rect, save_dir):
    """截取聊天气泡区域的图片，保存到临时文件，返回路径。"""
    from PIL import ImageGrab
    os.makedirs(save_dir, exist_ok=True)
    l, t, r, b = rect
    if r - l < 10 or b - t < 10:
        return None
    img = ImageGrab.grab(bbox=(l, t, r, b))
    path = os.path.join(save_dir, f"bubble_{int(time.time()*1000)}.png")
    img.save(path)
    return path

def pick_image(cfg, keyword=""):
    """从图片库挑一张图：keyword 匹配文件名优先，否则随机。返回路径或 None。"""
    icfg = cfg.get("images", {}) or {}
    if not icfg.get("enabled", True):
        return None
    d = icfg.get("dir") or os.path.join(BASE, "wxbot_images")
    if not os.path.isdir(d):
        return None
    exts = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
    pool = []
    for root, _dirs, files in os.walk(d):
        for fn in files:
            if fn.lower().endswith(exts):
                pool.append(os.path.join(root, fn))
    if not pool:
        return None
    kw = (keyword or "").strip().lower()
    if kw:
        hit = [p for p in pool if kw in os.path.basename(p).lower()]
        if hit:
            return random.choice(hit)
    return random.choice(pool)

# ---------------------------------------------------------------- custom stickers (爱心收藏)
_STICKER_CACHE = {"mtime": 0.0, "items": []}

def load_sticker_catalog(cfg):
    """读 stickers/catalog.json，带 mtime 缓存。返回 sticker dict 列表（可能为空）。"""
    scfg = cfg.get("stickers", {}) or {}
    if not scfg.get("enabled", True):
        return []
    path = scfg.get("catalog") or os.path.join(BASE, "wxbot_images", "stickers", "catalog.json")
    try:
        mt = os.path.getmtime(path)
        if mt == _STICKER_CACHE["mtime"]:
            return _STICKER_CACHE["items"]
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("stickers") or []
        _STICKER_CACHE["mtime"] = mt
        _STICKER_CACHE["items"] = items
        return items
    except Exception as e:
        print("sticker catalog load error:", e)
        return []

def sticker_prompt_line(items):
    """生成给 LLM 看的贴纸清单一行：'1=捂耳朵拒绝/2=捂嘴偷笑/...'"""
    return "/".join(f"{s['index']}={s.get('label','')}" for s in items)

def resolve_sticker(items, token):
    """把 [STICKER:x] 的 x 解析成贴纸编号：数字直接用；否则按 label/关键词/desc 模糊匹配。"""
    t = (token or "").strip()
    if not t or not items:
        return None
    if t.isdigit():
        n = int(t)
        return n if any(s["index"] == n for s in items) else None
    tl = t.lower()
    best = None
    for s in items:
        hay = [s.get("label", ""), s.get("emotion", ""), s.get("desc", "")] + (s.get("keywords") or [])
        for h in hay:
            hl = (h or "").lower()
            if tl and (tl in hl or hl in tl and len(hl) >= 2):
                return s["index"]  # 第一个命中就用（目录是人工排过序的）
        if best is None and tl in (s.get("desc", "").lower()):
            best = s["index"]
    return best

# ---------------------------------------------------------------- personas & behavior knobs
DEFAULT_BEHAVIOR = {"sticker": 0.15, "emoji": 0.15, "at": 0.2, "image": 0.1, "quote": 0.2}
BEHAVIOR_KEYS = ("sticker", "emoji", "at", "image", "quote")

def _personas_cfg(cfg):
    return (cfg.get("reply", {}) or {}).get("personas", {}) or {}

def persona_for_conversation(cfg, name, is_group):
    """按群/联系人映射 → 默认人格。返回人格名（可能为空）。"""
    pcfg = _personas_cfg(cfg)
    if not pcfg.get("enabled", True):
        return ""
    if is_group:
        pname = (pcfg.get("per_group", {}) or {}).get(name)
    else:
        pname = (pcfg.get("per_contact", {}) or {}).get(name)
    return pname or pcfg.get("default", "") or ""

def resolve_persona_path(pcfg, pname):
    """definitions 显式映射优先，否则按 dir/<pname>.md 找。"""
    if not pname:
        return None
    p = (pcfg.get("definitions", {}) or {}).get(pname)
    if p:
        return p if os.path.isabs(p) else os.path.join(BASE, p)
    d = pcfg.get("dir") or "personas"
    d = d if os.path.isabs(d) else os.path.join(BASE, d)
    p = os.path.join(d, f"{pname}.md")
    return p if os.path.exists(p) else None

def behavior_for(cfg, pname):
    """该人格的行为旋钮：sticker/emoji/at/image 各 0~1。人格值 > _default > 内置默认。"""
    beh = (_personas_cfg(cfg).get("behaviors", {}) or {})
    dflt = beh.get("_default", {}) or {}
    mine = (beh.get(pname, {}) or {}) if pname else {}
    out = {}
    for k in BEHAVIOR_KEYS:
        v = mine.get(k, dflt.get(k, DEFAULT_BEHAVIOR[k]))
        try:
            v = float(v)
        except Exception:
            v = DEFAULT_BEHAVIOR[k]
        out[k] = max(0.0, min(1.0, v))
    return out

def _roll(freq):
    """按频率掷骰子：True=放行。"""
    return random.random() < max(0.0, min(1.0, freq))

def in_quiet_hours(qh):
    """免打扰时段判断，支持跨夜（如 23:30-07:30）。"""
    if not qh or not qh.get("enabled"):
        return False
    def _parse(s, dflt):
        try:
            h, m = str(s).split(":")[:2]
            return int(h) * 60 + int(m)
        except Exception:
            return dflt
    start = _parse(qh.get("start", "23:30"), 23 * 60 + 30)
    end = _parse(qh.get("end", "07:30"), 7 * 60 + 30)
    import datetime
    now = datetime.datetime.now().hour * 60 + datetime.datetime.now().minute
    if start <= end:
        return start <= now < end
    return now >= start or now < end

def llm_reply(cfg, conversation, inbound_text, context=None, is_group=True):
    """Generate a reply with an OpenAI-compatible chat completions API.

    输入缓存：system 前缀（base.md + 能力清单 + 行为偏好 + 人格 + 记忆）按
    (人格文件mtime, 记忆mtime, 贴纸目录mtime, model) 组合键缓存，不变就不重建；
    provider 侧（如 DeepSeek 上下文缓存）也因此能命中稳定的前缀。
    """
    api_key = _api_key(cfg)
    if not api_key:
        return "（回复生成失败：无 API key）"

    pname = persona_for_conversation(cfg, conversation, is_group)
    beh = behavior_for(cfg, pname)
    ppath = resolve_persona_path(_personas_cfg(cfg), pname) if pname else None

    sys_key = wxbot_context.system_cache_key(
        cfg, pname,
        wxbot_context.mtime_of(ppath or ""),
        wxbot_context.memory_mtimes(cfg, conversation),
        wxbot_context.mtime_of((cfg.get("stickers") or {}).get("catalog", "")),
    )
    if wxbot_context._SYS_CACHE["key"] == sys_key and wxbot_context._SYS_CACHE["text"]:
        system = wxbot_context._SYS_CACHE["text"]
    else:
        system = _build_system(cfg, conversation, inbound_text, is_group, pname, beh, ppath)
        wxbot_context._SYS_CACHE["key"] = sys_key
        wxbot_context._SYS_CACHE["text"] = system

    if context:
        ctx = "\n".join(context)
        user_content = (
            f"这是「{conversation}」里最近的聊天记录（我=张宇轩这边发的，对方=别人发的）：\n{ctx}\n\n"
            f"请针对最后一条对方消息，以主人朋友的身份自然回复一句：\n{inbound_text}"
        )
    else:
        user_content = f"这是{conversation}里的新消息，请以主人朋友的身份自然回复：\n{inbound_text}"
    return _llm_call(cfg, system, user_content)


_FALLBACK_BASE = (
    "你是顾笙满，微信上的一个 AI 私人伙伴。你在替你的主人张宇轩打理微信自动回复。"
    "回复要求：口语化、自然、有温度，像真人发微信，不要客套、不要长段落、不要用'作为AI'这类话。"
    "短句为主。用简体中文。句尾不要带句号。"
    "注意上下文：回复要接得上前面的聊天内容，不要答非所问。"
    "想分几句发就把每句单独一行，最多 4 句。"
    "你也可以选择不加入讨论：如果这条消息不值得接话（纯表情、无意义灌水、别人聊得正好不想插嘴、"
    "接不上话），就只回复 [SKIP] 两个字符，别的什么都不要说。"
)
_BASE_CACHE = {"mtime": 0.0, "text": None}


def _base_prompt(cfg):
    """读 prompts/base.md（底层文档，mtime 缓存），缺失时用内置兜底。"""
    p = os.path.join(BASE, "prompts", "base.md")
    mt = wxbot_context.mtime_of(p)
    if mt != _BASE_CACHE["mtime"]:
        try:
            with open(p, "r", encoding="utf-8") as f:
                t = f.read().strip()
            _BASE_CACHE["mtime"] = mt
            _BASE_CACHE["text"] = t or None
        except Exception:
            _BASE_CACHE["mtime"] = mt
            _BASE_CACHE["text"] = None
    return _BASE_CACHE["text"] or _FALLBACK_BASE


def _build_system(cfg, conversation, inbound_text, is_group, pname, beh, ppath):
    """组装 system prompt：base → 能力清单 → 行为偏好 → 人格 → 记忆。"""
    system = _base_prompt(cfg)
    sticker_items = load_sticker_catalog(cfg)
    if sticker_items:
        system += (
            "\n特殊能力："
            "① 想 @ 群里的某个人（仅群聊）：把回复第一句以「@昵称 」（昵称+空格）开头，机器人会真的 @ 那个人（只在第一句有效）；"
            "② 想发一张图片/表情包：单独占一行写 [IMG:关键词]，机器人会从图片库挑一张文件名含关键词的图发出去，关键词可省略写成 [IMG] 随机挑；"
            "②b 想发微信自带表情：单独占一行写 [EMOJI:表情名]，如 [EMOJI:旺柴]、[EMOJI:捂脸]、[EMOJI:偷笑]、[EMOJI:鄙视]；"
            "②c 想发微信「爱心」收藏里的自定义表情包贴纸：单独占一行写 [STICKER:编号或关键词]，"
            f"可选贴纸：{sticker_prompt_line(sticker_items)}；贴纸适合收尾、表达情绪或嘲讽，一条回复最多用一张；"
            "③ 对方发来图片时你能看到图片内容的描述（以[对方发来一张图片：…]形式给出）；"
            "对方发来文件时你能直接读到文件内容（以[对方发来一个文件「文件名」内容如下：…]形式给出），据此自然回应，别问「发的什么文件」。"
        )
    # ---- 行为旋钮（@ 频率只在群聊有意义） ----
    hints = [
        _freq_hint("发微信表情", beh["emoji"]),
        _freq_hint("发贴纸", beh["sticker"]),
        _freq_hint("发图片", beh["image"]),
        _freq_hint("引用对方消息回复", beh["quote"]),
    ]
    if is_group:
        hints.insert(0, _freq_hint("@人", beh["at"]))
    system += (
        "\n行为偏好：" + "、".join(hints) + "。严格按这个频率决定用不用对应能力，频率低就绝大多数时候纯文字回复。"
        "想引用对方那条消息再回复：把回复第一句以「[Q] 」（大写Q+空格）开头，机器人会引用那条消息再发这句话；"
    )
    # ---- 人格系统 ----
    personas_cfg = _personas_cfg(cfg)
    if personas_cfg.get("enabled", True) and pname and ppath:
        try:
            with open(ppath, "r", encoding="utf-8") as pf:
                ptext = pf.read().strip()
            if ptext:
                system += f"\n\n【当前人格：{pname}】请严格按照以下人格描述说话（这是你的扮演设定，优先级高于上面的一般要求）：\n{ptext}"
                print(f"[persona] {conversation} -> {pname}")
                # 人格模式下：覆盖普通群友的礼貌标签，避免模型被带出戏
                inbound_text = inbound_text.replace("【普通群友: 必须礼貌友善、积极帮助】", "【群友：按当前人格应对】")
                inbound_text = inbound_text.replace("【发送者: 不确定，按普通群友礼貌友善对待】", "【发送者：按当前人格应对】")
        except Exception as e:
            print(f"persona load error ({pname}):", e)
    # ---- 记忆注入（workspace 隔离，按对话独立） ----
    mem = wxbot_memory.memory_inject(cfg, conversation)
    if mem:
        system += "\n" + mem
    return system


def _freq_hint(label, v):
    if v <= 0:
        return f"{label}别用"
    if v < 0.12:
        return f"{label}极少用（约{v:.0%}）"
    if v < 0.3:
        return f"{label}偶尔用（约{v:.0%}）"
    return f"{label}很爱用（约{v:.0%}）"


def _api_key(cfg):
    """从环境变量 → openclaw.json env 取 API key。"""
    key_env = cfg["llm"].get("api_key_env", "DEEPSEEK_API_KEY")
    api_key = os.environ.get(key_env) or cfg.get("api_key")
    if api_key:
        return api_key
    try:
        oc = os.path.expanduser("~/.openclaw/openclaw.json")
        if not os.path.exists(oc):
            oc = "F:/OpenClaw/.openclaw/openclaw.json"
        with open(oc, "r", encoding="utf-8") as f:
            data = json.load(f)
        return (data.get("env") or {}).get(key_env, "")
    except Exception:
        return ""


def _memory_extract(cfg, name, ctx_lines):
    """记忆提取：用 LLM 从最近聊天提炼事实，写入该对话 workspace 的当日笔记。"""
    try:
        pname = persona_for_conversation(cfg, name, True)
        ppath = resolve_persona_path(_personas_cfg(cfg), pname) if pname else None
        _sys = _build_system(cfg, name, "", True, pname, behavior_for(cfg, pname), ppath)
        _ext = _llm_call(cfg, _sys, wxbot_memory.extract_prompt(name, ctx_lines))
        if _ext:
            ok = wxbot_memory.store_extraction(name, _ext)
            if ok:
                print(f"[memory] {name} facts extracted")
            return ok
    except Exception as e:
        print("memory extract error:", e)
    return False


def _llm_call(cfg, system, user_content):
    """发一次 chat completions，返回文本（或 None）。
    主通道挂了按 llm.fallbacks 链逐个试（跟 vision 一个套路），全挂才返回 None。"""
    lcfg = cfg["llm"]
    attempts = [{
        "base_url": lcfg["base_url"],
        "model": lcfg["model"],
        "_key": _api_key(cfg),
    }]
    for fb in lcfg.get("fallbacks", []) or []:
        attempts.append({
            "base_url": fb["base_url"],
            "model": fb["model"],
            "_key": _load_api_key(fb.get("api_key_env", "")),
        })
    for i, a in enumerate(attempts):
        if not a["_key"]:
            continue
        url = a["base_url"].rstrip("/") + "/chat/completions"
        payload = {
            "model": a["model"],
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content}
            ],
            "temperature": lcfg.get("temperature", 0.9),
            "max_tokens": lcfg.get("max_tokens", 400),
        }
        try:
            data = _http_post_json(url, payload, a["_key"], timeout=60)
            reply = data["choices"][0]["message"]["content"].strip()
            if i > 0:
                print(f"[llm] fallback ok: {a['model']}")
            return reply[:cfg["reply"].get("max_reply_chars", 300)]
        except Exception as e:
            print(f"llm error ({a['model']}):", e)
    return None


# ---------------------------------------------------------------- LLM 全局退避
# 所有通道都挂时进入退避：期间不开窗、不 mark_seen（网络恢复后自动重试漏掉的消息）
_LLM_BACKOFF = {"until": 0.0, "streak": 0, "logged": False}

def _llm_note_failure():
    _LLM_BACKOFF["streak"] += 1
    wait = min(300, 30 * _LLM_BACKOFF["streak"])
    _LLM_BACKOFF["until"] = time.time() + wait
    _LLM_BACKOFF["logged"] = False
    print(f"[llm] all channels down, backoff {wait:.0f}s")

def _llm_note_success():
    _LLM_BACKOFF["streak"] = 0
    _LLM_BACKOFF["until"] = 0.0
    _LLM_BACKOFF["logged"] = False

def normalize_nick(nick):
    """Strip Unicode combining/enclosing marks so '温⃞先⃞生⃞' becomes '温先生'."""
    return "".join(
        ch for ch in unicodedata.normalize("NFKC", nick or "")
        if not unicodedata.category(ch).startswith("M")
    )


def parse_sender(preview):
    """Extract sender nickname from group session preview like '[2条] 昵称: 内容' or '[有人@我] 昵称: 内容'."""
    t = re.sub(r"^\[\d+条\]\s*", "", preview or "")
    t = re.sub(r"^\[有人@我\]\s*", "", t)
    m = re.match(r"^([^\s:：\[\]]{1,30})[:：]", t)
    return normalize_nick(m.group(1)) if m else None


def split_sentences(text, max_n=4):
    """Split a reply into sentences/lines for multi-message sending, cap at max_n."""
    parts = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        segs = re.split(r"(?<=[。！？!?~…])", line)
        for s in segs:
            s = s.strip()
            if not s:
                continue
            if all(ch in "。，、！？~…,.!? " for ch in s):
                continue
            parts.append(s)
    return parts[:max_n]

# ---------------------------------------------------------------- core
def is_group_conversation(name, sessions):
    """Heuristic: group names often contain 群/聊/室 or match a session whose
    last line includes '消息免打扰'. Fallback: not in known private contacts."""
    if any(k in name for k in ("群", "交流", "业主", "培训", "班")):
        return True
    for s in sessions:
        if s["name"] == name and ("消息免打扰" in s.get("raw", "")):
            return True
    return False

def mentioned_me(text, cfg):
    for n in cfg["reply"]["group"]["mention_names"] + cfg.get("own_nicknames", []):
        if n and n in text:
            return True
    return False

# UIA 错误日志节流：同一种错只打首条，之后每 20 次报一次计数
_UIA_ERR = {"msg": None, "count": 0}

def _log_uia_error(e):
    msg = str(e)
    if msg != _UIA_ERR["msg"]:
        if _UIA_ERR["count"] > 1:
            print(f"list_sessions error: (上一条重复了 {_UIA_ERR['count']} 次)")
        _UIA_ERR["msg"] = msg
        _UIA_ERR["count"] = 1
        print("list_sessions error:", e)
    else:
        _UIA_ERR["count"] += 1
        if _UIA_ERR["count"] % 20 == 0:
            print(f"list_sessions error: (已连续 {_UIA_ERR['count']} 次) {msg[:60]}")


def poll_once(cfg, state, hwnd):
    """One poll cycle. Returns (replied, n_sessions)；n_sessions=-1 表示 list_sessions 异常。"""
    replied = []
    try:
        sessions = wx.list_sessions(hwnd)
        _UIA_ERR["msg"] = None
        _UIA_ERR["count"] = 0
    except Exception as e:
        _log_uia_error(e)
        return replied, -1

    for s in sessions:
        name = s["name"]
        last = s["last"]
        if not name:
            continue
        # 折叠的聊天/微信团队等是微信内置入口，不是真实会话，绝不能点开
        if name == "折叠的聊天" or name.startswith("折叠"):
            state.mark_seen(name, last or "")
            continue
        if name in cfg["reply"]["deny_contacts"]:
            continue
        if cfg["reply"]["allow_contacts"] and name not in cfg["reply"]["allow_contacts"]:
            continue
        # 分类型黑白名单：deny 优先；allow 非空 = 只回白名单
        _is_grp = is_group_conversation(name, sessions)
        _typed = cfg["reply"]["group"] if _is_grp else cfg["reply"]["private"]
        if name in (_typed.get("deny", []) or []):
            continue
        _allow = _typed.get("allow", []) or []
        if _allow and name not in _allow:
            continue
        if not last:
            continue
        # skip if we already handled this exact last message
        if state.is_seen(name, last):
            continue
        # skip if it's our own recent send (avoid echo loop)
        if state.recently_sent(name, last):
            state.mark_seen(name, last)
            state.save()
            continue

        print(f"[poll] {name} changed: {last[:40]}")

        is_group = is_group_conversation(name, sessions)
        unlimited = name in cfg["reply"].get("unlimited_groups", [])
        policy = cfg["reply"]["group"] if is_group else cfg["reply"]["private"]
        if not policy.get("enabled", True):
            state.mark_seen(name, last)
            state.save()
            continue

        # 私聊专属设置：冷却 + 免打扰时段
        if not is_group:
            pv = cfg["reply"]["private"]
            cd = float(pv.get("cooldown_s", 0) or 0)
            if cd > 0:
                since = time.time() - state.last_reply_ts(name)
                if since < cd:
                    print(f"[poll] {name} private cooldown {cd - since:.0f}s left")
                    state.mark_seen(name, last)
                    state.save()
                    continue
            qh = pv.get("quiet_hours", {}) or {}
            if in_quiet_hours(qh) and name not in (qh.get("allow_contacts", []) or []):
                print(f"[poll] {name} quiet hours, skip private reply")
                state.mark_seen(name, last)
                state.save()
                continue

        # 群聊：无限制群跳过 @ 检查；其余群看会话列表「[有人@我]」标记（折叠的群天然排除）
        if is_group and policy.get("require_mention", False) and not unlimited:
            raw = s.get("raw", "") or ""
            has_badge = ("[有人@我]" in raw) or ("[有人@我]" in last)
            print(f"[poll] {name} group badge={has_badge}")
            if not has_badge:
                state.mark_seen(name, last)
                state.save()
                continue

        # 无限制群：同一群回复间隔限制
        if is_group and unlimited:
            gap = cfg["reply"].get("unlimited_group_interval_s", 90)
            since = time.time() - state.last_reply_ts(name)
            if since < gap:
                print(f"[poll] {name} unlimited cooldown {gap - since:.0f}s left")
                state.mark_seen(name, last)
                state.save()
                continue

        # LLM 全局退避：网络全挂时不开窗、不标已读，等恢复后重试
        if time.time() < _LLM_BACKOFF["until"]:
            if not _LLM_BACKOFF["logged"]:
                print(f"[poll] llm backoff {_LLM_BACKOFF['until'] - time.time():.0f}s left，暂不回（消息保留待重试）")
                _LLM_BACKOFF["logged"] = True
            continue

        # 上下文条数先算好：只追溯这个要回复的窗口需要的条数，不做全量遍历
        ctx_cfg = cfg["reply"].get("context_messages", 8)
        if isinstance(ctx_cfg, dict):
            ctx_n = int(ctx_cfg.get(name, ctx_cfg.get("default", 8)))
        else:
            ctx_n = int(ctx_cfg)
        ctx_n = max(1, min(1000, ctx_n))  # 上限 1000 条

        # open the conversation and read fresh bubbles (with side detection)
        try:
            ok = wx.open_chat_by_click(hwnd, name)
            if not ok:
                continue
            time.sleep(0.8)
            msgs = wx.read_chat(hwnd, limit=max(ctx_n, 5), detect_side=True)
        except Exception as e:
            print(f"open/read {name} error:", e)
            continue

        # find the last bubble sent by the OTHER side (text 或图片或文件)
        other_bubbles = [m for m in msgs if m["side"] == "other" and m["kind"] in ("text", "image", "file")]
        if not other_bubbles:
            # 判边全灭时的兜底：用会话预览（群「昵称: 内容」/私聊直接是内容）匹配气泡定位对方消息
            prev = re.sub(r"^\[(\d+条|有人@我)\]\s*", "", last or "").strip()
            pm = re.match(r"^[^\s:：\[\]]{1,30}[:：](.*)$", prev)
            if is_group and pm:
                prev = pm.group(1).strip()
            if prev and not state.recently_sent(name, prev, window_s=86400 * 365):
                def _squash(s):
                    return re.sub(r"[\u2005\u2006\s]", "", s or "")
                sq = _squash(prev)
                # 多级匹配：全文 → 尾部 12 字 → 尾部 6 字（兼容预览与气泡里 @ 标签渲染差异）
                cands = [c for c in (sq, sq[-12:], sq[-6:]) if len(c) >= 2]
                for cand in cands:
                    hit = None
                    for m in reversed(msgs):
                        if m["kind"] in ("text", "image", "file") and cand in _squash(m["text"]):
                            hit = m
                            break
                    if hit:
                        hit["side"] = "other"
                        other_bubbles = [hit]
                        print(f"[poll] {name} side-detect fallback via preview")
                        break
        if not other_bubbles:
            print(f"[poll] {name} skip: no other-side msg")
            state.mark_seen(name, last or "")
            state.save()
            continue
        last_bubble = other_bubbles[-1]
        if last_bubble["kind"] == "image":
            # 对方发来图片：截图气泡 → MiMo 识图 → 描述作为回复对象
            target_text = "[对方发来一张图片]"
            try:
                shot = grab_bubble_image(last_bubble["rect"], os.path.join(BASE, "tmp", "vision"))
                if shot:
                    desc = vision_describe(cfg, shot)
                    if desc:
                        target_text = f"[对方发来一张图片：{desc}]"
                        print(f"[vision] {name}: {desc[:60]}")
            except Exception as e:
                print("vision pipeline error:", e)
        elif last_bubble["kind"] == "file":
            # 对方发来文件：从微信文件存储找文件 → 解析内容 → 作为回复对象
            fname = wxbot_files.filename_from_bubble(last_bubble["text"])
            target_text = f"[对方发来一个文件「{fname}」]"
            try:
                fpath = wxbot_files.find_file(fname)
                if fpath:
                    fcontent = wxbot_files.parse_file(fpath, max_chars=int(cfg.get("files", {}).get("max_chars", 1500)))
                    target_text = f"[对方发来一个文件「{fname}」，内容如下：\n{fcontent}]"
                    print(f"[file] {name}: {fname} parsed {len(fcontent)} chars")
                else:
                    target_text = f"[对方发来一个文件「{fname}」（本地还没下载完成，看不到内容）]"
                    print(f"[file] {name}: {fname} not found in storage")
            except Exception as e:
                print("file pipeline error:", e)
        else:
            target_text = last_bubble["text"]
        sender = parse_sender(last) if is_group else None
        # 配对校验：预览行「昵称: 内容」的内容必须跟我们要回复的气泡文本对得上，
        # 否则说明昵称-消息配对不可靠（预览发送者≠气泡发送者），宁可不给模型昵称，
        # 拿不准一律按普通群友处理，防止误伤友军
        if sender:
            pm = re.match(r"^[^\s:：\[\]]{1,30}[:：](.*)$",
                          re.sub(r"^\[(\d+条|有人@我)\]\s*", "", last or ""))
            preview_content = (pm.group(1) if pm else "").strip()
            if target_text[:20] not in preview_content and preview_content[:20] not in target_text:
                sender = None
        # 硬性标注对线目标：昵称同时包含 matcher 里所有关键词才算目标，否则一律群友
        matcher = (cfg["reply"].get("target_matcher", {}) or {}).get(name, {})
        must_all = [k.lower() for k in matcher.get("contains_all", [])]
        is_target = bool(sender) and bool(must_all) and all(k in sender.lower() for k in must_all)
        if state.replied_to(name, target_text):
            print(f"[poll] {name} skip: already replied to this msg")
            state.mark_seen(name, last)
            state.save()
            continue
        if state.recently_sent(name, target_text):
            state.mark_seen(name, last)
            state.save()
            continue

        # build context lines (recent messages with side markers) for the LLM
        ctx_lines = []
        for m in msgs[-ctx_n:]:
            who = "我" if m["side"] == "own" else "对方"
            if m["kind"] == "text":
                ctx_lines.append(f"{who}: {m['text'][:100]}")
            elif m["kind"] == "image":
                ctx_lines.append(f"{who}: [图片]")
            elif m["kind"] == "file":
                _fn = wxbot_files.filename_from_bubble(m.get("text", ""))
                ctx_lines.append(f"{who}: [文件{_fn}]")

        # 自动上下文压缩（预算按百分比或词元数；两阶段：截断旧消息→丢最旧）
        _budget = wxbot_context.budget_tokens(cfg)
        if _budget > 0:
            _cc = (cfg.get("context") or {}).get("compression") or {}
            ctx_lines, _dropped = wxbot_context.compress(
                ctx_lines, _budget,
                keep_recent=int(_cc.get("keep_recent", 4)),
                trim_chars=int(_cc.get("trim_chars", 60)),
            )
            if _dropped:
                print(f"[ctx] {name} compressed: dropped {_dropped} old lines")

        # generate reply（群消息带上发送者昵称+目标标注，模型据此决定是否开火）
        if sender:
            tag = "【对线目标: 是，按特别规则反击】" if is_target else "【普通群友: 必须礼貌友善、积极帮助】"
            incoming = f"【发送者昵称: {sender}】{tag}{target_text}"
        elif is_group:
            incoming = f"【发送者: 不确定，按普通群友礼貌友善对待】{target_text}"
        else:
            incoming = target_text
        reply = llm_reply(cfg, name, incoming, context=ctx_lines, is_group=is_group)
        if not reply:
            _llm_note_failure()
            continue  # 不 mark_seen：退避结束后重新捡回来回
        _llm_note_success()
        if reply.strip().startswith("[SKIP]") and is_target:
            # 对线目标的发言绝不允许 SKIP：强制重新生成，必须反击
            print(f"[poll] {name} target msg must not SKIP, regenerating")
            reply = llm_reply(cfg, name, incoming + "\n（系统提示：这是对线目标的发言，你必须反击，绝不许回 [SKIP]）", context=ctx_lines, is_group=is_group)
            if not reply:
                _llm_note_failure()
                continue
        if reply.strip().startswith("[SKIP]"):
            print(f"[poll] {name} model chose to SKIP")
            state.mark_seen(name, last)
            state.save()
            continue

        # human-like delay
        delay = random.uniform(policy.get("min_delay_s", 1.0), policy.get("max_delay_s", 4.0))
        print(f"[wxbot] reply to {name} in {delay:.1f}s: {reply[:50]}")
        time.sleep(delay)

        # 分句发送，一批最多 max_sentences 句，句间小随机停顿
        sentences = split_sentences(reply, cfg["reply"].get("max_sentences", 4))
        if not sentences:
            state.mark_seen(name, last)
            state.save()
            continue
        sd = cfg["reply"].get("sentence_delay_s", [1.0, 2.5])
        sent_ok = 0
        # 行为旋钮：按人格频率硬性节流（掷骰子，没中就退化为纯文字/跳过）
        beh = behavior_for(cfg, persona_for_conversation(cfg, name, is_group))
        for i, sent in enumerate(sentences):
            try:
                # [Q] 前缀：引用对方那条消息再回复（第一句有效，按 quote 频率节流）
                if i == 0:
                    q_m = re.match(r"^\[Q\]\s*(.+)$", sent.strip(), re.S)
                    if q_m and q_m.group(1).strip():
                        body = q_m.group(1).strip()
                        if _roll(beh["quote"]) and last_bubble.get("rect"):
                            print(f"[wxbot] quote reply to {name}")
                            try:
                                wx.quote_reply(name, last_bubble["rect"], body)
                                state.record_sent(name, body)
                                sent_ok += 1
                            except Exception as e:
                                print("quote reply error:", e)
                                wx.send_text(name, body)
                                state.record_sent(name, body)
                                sent_ok += 1
                        else:
                            wx.send_text(name, body)
                            state.record_sent(name, body)
                            sent_ok += 1
                        if i < len(sentences) - 1:
                            time.sleep(random.uniform(sd[0], sd[1]))
                        continue
                # [EMOJI:表情名] 标记：发微信表情
                em_m = re.match(r"^\[(?:EMOJI|表情):([^\]]+)\]$", sent.strip())
                if em_m:
                    if not _roll(beh["emoji"]):
                        print(f"[wxbot] emoji throttled ({beh['emoji']:.0%}): {em_m.group(1)}")
                        continue
                    print(f"[wxbot] send emoji to {name}: {em_m.group(1)}")
                    try:
                        wx.send_emoji(name, em_m.group(1).strip())
                        state.record_sent(name, f"[{em_m.group(1).strip()}]")
                        sent_ok += 1
                    except Exception as e:
                        print(f"send emoji error:", e)
                    if i < len(sentences) - 1:
                        time.sleep(random.uniform(sd[0], sd[1]))
                    continue
                # [STICKER:编号或关键词] 标记：发爱心收藏里的自定义贴纸
                st_m = re.match(r"^\[(?:STICKER|贴纸):([^\]]+)\]$", sent.strip())
                if st_m:
                    if not _roll(beh["sticker"]):
                        print(f"[wxbot] sticker throttled ({beh['sticker']:.0%}): {st_m.group(1)}")
                        continue
                    idx = resolve_sticker(load_sticker_catalog(cfg), st_m.group(1))
                    if idx:
                        print(f"[wxbot] send sticker to {name}: #{idx} ({st_m.group(1)})")
                        try:
                            wx.send_sticker(name, idx)
                            state.record_sent(name, f"[贴纸#{idx}]")
                            sent_ok += 1
                        except Exception as e:
                            print(f"send sticker error:", e)
                    else:
                        print(f"[wxbot] sticker not resolved: {st_m.group(1)}")
                    if i < len(sentences) - 1:
                        time.sleep(random.uniform(sd[0], sd[1]))
                    continue
                # [IMG:关键词] 标记：发图片而不是文字
                im_m = re.match(r"^\[IMG(?::([^\]]*))?\]$", sent.strip())
                if im_m:
                    if not _roll(beh["image"]):
                        print(f"[wxbot] image throttled ({beh['image']:.0%})")
                        continue
                    if cfg.get("images", {}).get("enabled", True):
                        img_path = pick_image(cfg, (im_m.group(1) or "").strip())
                        if img_path:
                            print(f"[wxbot] send image to {name}: {os.path.basename(img_path)}")
                            wx.send_image(name, img_path)
                            state.record_sent(name, f"[图片:{os.path.basename(img_path)}]")
                            sent_ok += 1
                    if i < len(sentences) - 1:
                        time.sleep(random.uniform(sd[0], sd[1]))
                    continue
                # 第一句若以 @昵称 开头 → 真 @ 该群成员
                if i == 0 and is_group:
                    at_m = re.match(r"^@([^\s，,]{1,20})[\s，,]+(.*)$", sent, re.S)
                    if at_m:
                        at_name, body = at_m.group(1), at_m.group(2).strip()
                        if body:
                            if not _roll(beh["at"]):
                                print(f"[wxbot] @ throttled ({beh['at']:.0%}): {at_name}")
                                wx.send_text(name, body)
                            else:
                                print(f"[wxbot] send with @: {at_name}")
                                wx.send_text_at(name, at_name, body)
                            state.record_sent(name, sent)
                            sent_ok += 1
                            if i < len(sentences) - 1:
                                time.sleep(random.uniform(sd[0], sd[1]))
                            continue
                wx.send_text(name, sent)
                state.record_sent(name, sent)
                sent_ok += 1
                if i < len(sentences) - 1:
                    time.sleep(random.uniform(sd[0], sd[1]))
            except Exception as e:
                print(f"send sentence to {name} error:", e)
                break
        if sent_ok:
            state.mark_replied(name, target_text)
            state.mark_reply_ts(name)
            state.mark_seen(name, last)
            # 记忆系统：每 N 轮做一次事实提取（workspace 隔离）
            mem_cfg = cfg.get("memory") or {}
            if mem_cfg.get("enabled", True) and wxbot_memory.should_extract(state, name, int(mem_cfg.get("every_n_replies", 5))):
                _memory_extract(cfg, name, ctx_lines)
            state.save()
            replied.append((name, reply))

    return replied, len(sessions)

def main():
    cfg = load_config()
    if not cfg.get("enabled", True):
        print("wxbot disabled in config")
        return
    state = State(cfg["state_file"])
    hwnd = wx.find_wechat()
    print(f"wxbot started. hwnd={hwnd} interval={cfg['poll_interval_seconds']}s")
    # one-shot mode: python wxbot.py --once
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        replied, _n = poll_once(cfg, state, hwnd)
        print(f"[once] replied {len(replied)} conversation(s)")
        return
    uia_fail_streak = 0
    while True:
        try:
            replied, n_sessions = poll_once(cfg, state, hwnd)
            if replied:
                print(f"replied {len(replied)} conversation(s)")
        except Exception as e:
            print("poll error:", e)
            n_sessions = -1
        # UIA 自愈：直接用本轮 poll 的结果计数，不再重复调 list_sessions（少压 UIA 一倍）
        if n_sessions > 0:
            uia_fail_streak = 0
        else:
            uia_fail_streak += 1
        if uia_fail_streak >= 6:
            print("[wxbot] UIA unresponsive, restarting WeChat...")
            try:
                hwnd = wx.restart_wechat()
                print(f"[wxbot] WeChat restarted, hwnd={hwnd}")
            except Exception as e:
                print("restart_wechat error:", e)
            uia_fail_streak = 0
        time.sleep(cfg["poll_interval_seconds"])

if __name__ == "__main__":
    main()
