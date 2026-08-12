# -*- coding: utf-8 -*-
"""
wxbot_context.py — 输入缓存 + 自动上下文压缩。

1) 词元估算 est_tokens(text)：
   - CJK 字符 ≈ 1 token/字；ASCII 词 ≈ 1 token/4 字符（启发式，不用 tiktoken 免依赖）
2) 压缩 compress(lines, budget_tokens, keep_recent)：
   - 两阶段：超预算先对旧消息逐条截断（每条 ≤ trim_chars）→ 还不够就把最旧的整条丢弃
   - 丢弃时记一条 `[更早 N 条消息已省略]` 占位
3) 预算 budget_tokens(cfg)：
   - mode="percent" → llm.context_window * percent
   - mode="tokens"  → 固定 tokens 数
   - 默认关（budget=0 表示不压缩）
4) 输入缓存：
   - build_system(cfg, ...) 按 (persona, 能力清单版本, 记忆注入) 组合键缓存 system 文本
   - persona 文件按 mtime 失效；记忆注入按 workspace MEMORY/日记 mtime 失效
"""
import os, re, time, hashlib, datetime

_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")
_WORD = re.compile(r"[A-Za-z0-9_]+")


def est_tokens(text):
    """启发式词元估算：CJK 每字 1 token，拉丁词每词约 1.3 token。"""
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    words = len(_WORD.findall(text))
    other = len(text) - cjk - sum(len(w) for w in _WORD.findall(text))
    return int(cjk + words * 1.3 + other * 0.35)


def budget_tokens(cfg):
    """返回压缩预算（token 数）。0 = 不启用压缩。"""
    cc = (cfg.get("context") or {}).get("compression") or {}
    if not cc.get("enabled"):
        return 0
    mode = cc.get("mode", "percent")
    try:
        if mode == "tokens":
            return max(0, int(cc.get("tokens", 4000)))
        window = int((cfg.get("llm") or {}).get("context_window", 32000) or 32000)
        pct = float(cc.get("percent", 60))
        return max(0, int(window * pct / 100))
    except Exception:
        return 0


def compress(lines, budget, keep_recent=4, trim_chars=60):
    """按预算压缩上下文行列表。返回 (新行列表, dropped_count)。
    lines: ['我: xxx', '对方: xxx'] 由新到旧？——调用方保证 msgs 顺序为旧→新，
    此处按最后 keep_recent 条保留，其余视预算截断/丢弃。"""
    if budget <= 0 or not lines:
        return lines, 0
    # lines 是旧→新；最近的在末尾
    n = len(lines)
    recent = lines[-keep_recent:]
    old = lines[:-keep_recent]
    if est_tokens("\n".join(recent)) > budget:
        # 预算太小，连最近都保不住：直接截最近每条
        out = [_trunc_line(l, trim_chars) for l in recent]
        return out, n - len(out)
    # 第一步：逐条截断旧消息
    trimmed = [_trunc_line(l, trim_chars) for l in old]
    if est_tokens("\n".join(trimmed + recent)) <= budget:
        return trimmed + recent, 0
    # 第二步：从最旧开始丢弃，直到达标
    keep = []
    dropped = 0
    used = est_tokens("\n".join(recent))
    for l in reversed(trimmed):  # 从较新的旧消息往回保
        t = est_tokens(l)
        if used + t <= budget:
            keep.append(l)
            used += t
        else:
            dropped += 1
    keep.reverse()
    out = keep + recent
    if dropped:
        out.insert(0, f"[更早 {dropped} 条消息已省略]")
    return out, dropped


def _trunc_line(line, chars):
    if len(line) <= chars:
        return line
    return line[:chars] + "…"


# ---------------- 输入缓存 ----------------
_SYS_CACHE = {"key": None, "text": None}


def system_cache_key(cfg, pname, pfile_mtime, mem_mtime, sticker_mtime):
    return hashlib.md5(
        f"{pname}|{pfile_mtime}|{mem_mtime}|{sticker_mtime}|{cfg.get('llm',{}).get('model')}".encode()
    ).hexdigest()


def mtime_of(path):
    try:
        return os.path.getmtime(path)
    except Exception:
        return 0.0


def memory_mtimes(cfg, name):
    """该对话 workspace 记忆相关文件的最新 mtime（用于缓存失效）。"""
    try:
        import wxbot_memory
        ws = wxbot_memory.workspace_for(name)
        mt = mtime_of(os.path.join(ws, "MEMORY.md"))
        d = datetime.date.today()
        for delta in (0, 1):
            p = os.path.join(ws, "memory", f"{(d - datetime.timedelta(days=delta)).isoformat()}.md")
            mt = max(mt, mtime_of(p))
        return mt
    except Exception:
        return 0.0
