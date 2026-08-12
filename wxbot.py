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

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "wxbot_config.json")
DEFAULT_CONFIG = {
    "enabled": True,
    "poll_interval_seconds": 5,
    "reply": {
        "private": {"enabled": True, "min_delay_s": 8.0, "max_delay_s": 15.0},
        "group": {"enabled": True, "require_mention": True, "min_delay_s": 2.0, "max_delay_s": 5.0,
                  "mention_names": ["爱而不恨"]},
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
            "default": "",
            "per_group": {
                "【官方】DeepSeek交流34群": "wen"
            },
            "definitions": {
                "wen": "personas/wen.md"
            }
        }
    },
    "llm": {
        "base_url": "https://opencode.ai/zen/go/v1",
        "model": "deepseek-v4-flash",
        "api_key_env": "OPENCODE_API_KEY",
        "temperature": 0.9,
        "max_tokens": 400
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

# ---------------------------------------------------------------- llm
def llm_reply(cfg, conversation, inbound_text, context=None):
    """Generate a reply with an OpenAI-compatible chat completions API."""
    key_env = cfg["llm"].get("api_key_env", "DEEPSEEK_API_KEY")
    api_key = os.environ.get(key_env) or cfg.get("api_key")
    if not api_key:
        # try loading from openclaw.json env
        try:
            oc = os.path.expanduser("~/.openclaw/openclaw.json")
            if not os.path.exists(oc):
                oc = "F:/OpenClaw/.openclaw/openclaw.json"
            with open(oc, "r", encoding="utf-8") as f:
                data = json.load(f)
            api_key = (data.get("env") or {}).get(key_env, "")
        except Exception:
            api_key = ""
    if not api_key:
        return "（回复生成失败：无 API key）"

    import urllib.request
    url = cfg["llm"]["base_url"].rstrip("/") + "/chat/completions"
    system = (
        "你是顾笙满，微信上的一个 AI 私人伙伴。你在替你的主人张宇轩打理微信自动回复。"
        "回复要求：口语化、自然、有温度，像真人发微信，不要客套、不要长段落、不要用'作为AI'这类话。"
        "短句为主。用简体中文。句尾不要带句号。"
        "注意上下文：回复要接得上前面的聊天内容，不要答非所问。"
        "想分几句发就把每句单独一行，最多 4 句。"
        "你也可以选择不加入讨论：如果这条消息不值得接话（纯表情、无意义灌水、别人聊得正好不想插嘴、"
        "接不上话），就只回复 [SKIP] 两个字符，别的什么都不要说。"
    )
    persona = (cfg.get("reply", {}).get("group_persona", {}) or {}).get(conversation, "")
    if persona:
        system += persona
    # ---- 人格系统：按群/默认注入蒸馏人格（如温先生） ----
    personas_cfg = cfg.get("reply", {}).get("personas", {}) or {}
    if personas_cfg.get("enabled", True):
        pname = (personas_cfg.get("per_group", {}) or {}).get(conversation) or personas_cfg.get("default", "")
        pfile = (personas_cfg.get("definitions", {}) or {}).get(pname, "")
        if pname and pfile:
            ppath = pfile if os.path.isabs(pfile) else os.path.join(BASE, pfile)
            try:
                with open(ppath, "r", encoding="utf-8") as pf:
                    ptext = pf.read().strip()
                if ptext:
                    system += f"\n\n【当前人格：{pname}】请严格按照以下人格描述说话（这是你的扮演设定，优先级高于上面的一般要求）：\n{ptext}"
                    print(f"[persona] {conversation} -> {pname}")
            except Exception as e:
                print(f"persona load error ({pname}):", e)
    if context:
        ctx = "\n".join(context)
        user_content = (
            f"这是「{conversation}」里最近的聊天记录（我=张宇轩这边发的，对方=别人发的）：\n{ctx}\n\n"
            f"请针对最后一条对方消息，以主人朋友的身份自然回复一句：\n{inbound_text}"
        )
    else:
        user_content = f"这是{conversation}里的新消息，请以主人朋友的身份自然回复：\n{inbound_text}"
    payload = {
        "model": cfg["llm"]["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content}
        ],
        "temperature": cfg["llm"]["temperature"],
        "max_tokens": cfg["llm"]["max_tokens"],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        reply = data["choices"][0]["message"]["content"].strip()
        return reply[:cfg["reply"]["max_reply_chars"]]
    except Exception as e:
        print("llm error:", e)
        return None


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

def poll_once(cfg, state, hwnd):
    """One poll cycle. Returns list of (conversation, text) replied."""
    replied = []
    try:
        sessions = wx.list_sessions(hwnd)
    except Exception as e:
        print("list_sessions error:", e)
        return replied

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

        # open the conversation and read fresh bubbles (with side detection)
        try:
            ok = wx.open_chat_by_click(hwnd, name)
            if not ok:
                continue
            time.sleep(0.8)
            msgs = wx.read_chat(hwnd, limit=15, detect_side=True)
        except Exception as e:
            print(f"open/read {name} error:", e)
            continue

        # find the last TEXT bubble sent by the OTHER side (not own, not wxbot echo)
        candidates = [m["text"] for m in msgs if m["kind"] == "text" and m["side"] == "other"]
        if not candidates:
            # nothing from the other side visible => nothing to reply to
            print(f"[poll] {name} skip: no other-side text")
            state.mark_seen(name, last or "")
            state.save()
            continue
        target_text = candidates[-1]
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
        ctx_cfg = cfg["reply"].get("context_messages", 8)
        if isinstance(ctx_cfg, dict):
            ctx_n = int(ctx_cfg.get(name, ctx_cfg.get("default", 8)))
        else:
            ctx_n = int(ctx_cfg)
        ctx_lines = []
        for m in msgs[-ctx_n:]:
            if m["kind"] != "text":
                continue
            who = "我" if m["side"] == "own" else "对方"
            ctx_lines.append(f"{who}: {m['text'][:100]}")

        # generate reply（群消息带上发送者昵称+目标标注，模型据此决定是否开火）
        if sender:
            tag = "【对线目标: 是，按特别规则反击】" if is_target else "【普通群友: 必须礼貌友善、积极帮助】"
            incoming = f"【发送者昵称: {sender}】{tag}{target_text}"
        elif is_group:
            incoming = f"【发送者: 不确定，按普通群友礼貌友善对待】{target_text}"
        else:
            incoming = target_text
        reply = llm_reply(cfg, name, incoming, context=ctx_lines)
        if not reply:
            state.mark_seen(name, last)
            state.save()
            continue
        if reply.strip().startswith("[SKIP]") and is_target:
            # 对线目标的发言绝不允许 SKIP：强制重新生成，必须反击
            print(f"[poll] {name} target msg must not SKIP, regenerating")
            reply = llm_reply(cfg, name, incoming + "\n（系统提示：这是对线目标的发言，你必须反击，绝不许回 [SKIP]）", context=ctx_lines)
            if not reply:
                state.mark_seen(name, last)
                state.save()
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
        for i, sent in enumerate(sentences):
            try:
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
            state.save()
            replied.append((name, reply))

    return replied

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
        replied = poll_once(cfg, state, hwnd)
        print(f"[once] replied {len(replied)} conversation(s)")
        return
    while True:
        try:
            replied = poll_once(cfg, state, hwnd)
            if replied:
                print(f"replied {len(replied)} conversation(s)")
        except Exception as e:
            print("poll error:", e)
        time.sleep(cfg["poll_interval_seconds"])

if __name__ == "__main__":
    main()
