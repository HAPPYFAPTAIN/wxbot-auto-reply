# -*- coding: utf-8 -*-
"""
wxbot_memory.py — 类 OpenClaw(Qwenpaw) 风格的对话级记忆系统 + workspace 隔离。

目录结构（每个对话对象/群聊一个独立 workspace，互相隔离）：

    workspaces/
      <对话slug>-<hash8>/
        MEMORY.md            # 长期记忆（人工/周期整理，注入 system prompt）
        memory/
          YYYY-MM-DD.md      # 每日笔记（自动提取追加，注入最近的）
        files/               # 该对话收到的文件副本（预留）
        notes/               # 其他杂项（预留）

- slug：对话名清洗（去非法字符）+ sha1 前 8 位防重名/防撞
- 注入：MEMORY.md 前 long_term_chars 字 + 今天/昨天日记各前 daily_chars 字
- 提取：每 N 轮回复用 LLM 从最近聊天提炼事实，追加到当日 memory/YYYY-MM-DD.md
"""
import os, re, json, time, hashlib, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
WS_ROOT = os.path.join(BASE, "workspaces")

DEFAULTS = {
    "enabled": True,
    "every_n_replies": 5,       # 每 N 轮成功回复做一次记忆提取
    "long_term_chars": 1200,    # MEMORY.md 注入上限
    "daily_chars": 800,         # 每日笔记注入上限
    "extract_max_msgs": 20,     # 提取时参考的最近消息条数
}


def _slug(name):
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", name or "").strip()[:40]
    h = hashlib.sha1((name or "").encode("utf-8")).hexdigest()[:8]
    return f"{s}-{h}" if s else h


def workspace_for(name):
    """对话 workspace 目录（不存在则建骨架）。返回路径。"""
    d = os.path.join(WS_ROOT, _slug(name))
    os.makedirs(os.path.join(d, "memory"), exist_ok=True)
    os.makedirs(os.path.join(d, "files"), exist_ok=True)
    os.makedirs(os.path.join(d, "notes"), exist_ok=True)
    mem = os.path.join(d, "MEMORY.md")
    if not os.path.exists(mem):
        with open(mem, "w", encoding="utf-8") as f:
            f.write(f"# {name} 的长期记忆\n\n（还没有内容，随着聊天自动积累）\n")
    return d


def _read(path, max_chars):
    try:
        with open(path, "r", encoding="utf-8") as f:
            t = f.read().strip()
        return t[:max_chars] + ("\n…（截断）" if len(t) > max_chars else "") if t else ""
    except Exception:
        return ""


def memory_inject(cfg, name):
    """读该对话的长期记忆 + 近两天日记，返回注入 system prompt 的文本（可能为空）。"""
    mcfg = (cfg.get("memory") or {})
    if not mcfg.get("enabled", True):
        return ""
    ws = workspace_for(name)
    parts = []
    lt = _read(os.path.join(ws, "MEMORY.md"), int(mcfg.get("long_term_chars", DEFAULTS["long_term_chars"])))
    if lt and "还没有内容" not in lt:
        parts.append(f"【长期记忆】\n{lt}")
    today = datetime.date.today()
    for delta in (0, 1):
        d = today - datetime.timedelta(days=delta)
        p = os.path.join(ws, "memory", f"{d.isoformat()}.md")
        t = _read(p, int(mcfg.get("daily_chars", DEFAULTS["daily_chars"])))
        if t:
            parts.append(f"【{d.isoformat()} 笔记】\n{t}")
    if not parts:
        return ""
    return "\n\n【关于这个对话/对方的记忆（供参考，别生硬复述）】\n" + "\n\n".join(parts)


def should_extract(state, name, every_n):
    """state 里按对话计回复轮数，到 N 的倍数返回 True。"""
    try:
        counts = state.data.setdefault("memory_extract_count", {})
        n = int(counts.get(name, 0)) + 1
        counts[name] = n
        return every_n > 0 and n % every_n == 0
    except Exception:
        return False


def extract_prompt(name, ctx_lines):
    conv = "\n".join(ctx_lines[-DEFAULTS["extract_max_msgs"]:])
    return (
        f"这是微信对话「{name}」最近的聊天记录（我= bot 方，对方= 别人）：\n{conv}\n\n"
        "请提炼值得长期记住的事实，要求：\n"
        "- 只写新出现的、以后聊天用得上的信息（对方透露的偏好/计划/状态/关系/约定/重要事件）\n"
        "- 每条一行，以「- 」开头，不超过 8 条；没有值得记的就只回复 NONE\n"
        "- 不要复述闲聊，不要评价，不要写对话时间"
    )


def store_extraction(name, text):
    """把提取结果追加到当日笔记。返回是否写入。"""
    text = (text or "").strip()
    if not text or text.upper().startswith("NONE"):
        return False
    lines = [l for l in text.splitlines() if l.strip().startswith("-")]
    if not lines:
        return False
    ws = workspace_for(name)
    d = datetime.date.today().isoformat()
    p = os.path.join(ws, "memory", f"{d}.md")
    header = f"# {name} · {d}\n\n" if not os.path.exists(p) else ""
    with open(p, "a", encoding="utf-8") as f:
        if header:
            f.write(header)
        f.write(f"\n## {datetime.datetime.now().strftime('%H:%M')} 自动提取\n" + "\n".join(lines) + "\n")
    return True
