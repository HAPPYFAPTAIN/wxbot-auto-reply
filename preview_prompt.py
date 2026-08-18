# -*- coding: utf-8 -*-
"""提示词预览：按当前群里真实消息，走与线上完全相同的代码路径组装
system + user 提示词，落盘到 prompt_preview.md。不调 LLM、不发送、不动 state。

用法：python preview_prompt.py [群名关键词] [--window=分钟]
  默认"34群"；--window 可临时放宽候选窗口（仅预览用，线上仍是10分钟），
  用于群里安静时也能看到带候选的完整提示词结构。
"""
import os, sys, time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wxbot

OUT = os.path.join(wxbot.BASE, "prompt_preview.md")


def main():
    keyword = "34群"
    for a in sys.argv[1:]:
        if a.startswith("--window="):
            pass
        else:
            keyword = a
    cfg = wxbot.load_config()
    for a in sys.argv[1:]:
        if a.startswith("--window="):
            cfg["reply"]["candidate_window_s"] = int(float(a.split("=", 1)[1]) * 60)
            print(f"预览专用：候选窗口临时放宽到 {cfg['reply']['candidate_window_s']}s")

    # 找群
    wf = wxbot._wf(cfg)
    target = None
    for s in wf.sessions():
        disp = s.get("displayName") or s.get("username", "")
        if keyword in disp:
            target = (disp, s.get("username", ""))
            break
    if not target:
        print(f"没找到含「{keyword}」的会话")
        return
    name, username = target
    print(f"目标群: {name}")

    # 与 poll_once 相同的读取与筛选
    ctx_cfg = cfg["reply"].get("context_messages", 8)
    ctx_n = int(ctx_cfg.get(name, ctx_cfg.get("default", 8))) if isinstance(ctx_cfg, dict) else int(ctx_cfg)
    msgs = wxbot._read_chat_weflow(cfg, name, username, max(ctx_n, 5))
    other_kinds = ("text", "image", "file", "appmsg", "emoji", "voice", "video", "location")
    other_bubbles = [m for m in msgs if m["side"] == "other" and m["kind"] in other_kinds]

    cand, target_text = wxbot.format_group_candidates(cfg, username, other_bubbles)
    if not cand:
        print("候选窗口内无真人新消息——线上此时会闭嘴 [SKIP]")
    incoming = wxbot.candidates_incoming(target_text) if cand else "(无候选)"

    # 与 poll_once 完全相同的上下文组装（共享函数，含倒序修复）
    ctx_lines = wxbot.build_ctx_lines(msgs, ctx_n, newest_first=True)

    # 拦截 LLM 调用与审计日志：只捕获提示词，不外发、不写 call.log
    captured = {}
    def fake_llm_call(cfg_, system, user_content):
        captured["system"] = system
        captured["user"] = user_content
        return "[SKIP]"
    wxbot._llm_call = fake_llm_call
    wxbot._log_call = lambda *a, **kw: None

    wxbot.llm_reply(cfg, name, incoming, context=ctx_lines, is_group=True)

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(f"# 提示词预览（{ts}）\n\n")
        f.write(f"- 群：{name}\n- 候选数：{len(cand)}｜上下文条数：{len(ctx_lines)}\n")
        f.write(f"- system 长度：{len(captured.get('system',''))} 字符｜user 长度：{len(captured.get('user',''))} 字符\n\n")
        f.write("=" * 30 + " SYSTEM " + "=" * 30 + "\n\n")
        f.write(captured.get("system", "(未捕获)") + "\n\n")
        f.write("=" * 30 + " USER " + "=" * 30 + "\n\n")
        f.write(captured.get("user", "(未捕获)") + "\n")
    print(f"已写入 {OUT}")
    print(f"system {len(captured.get('system',''))} 字符 / user {len(captured.get('user',''))} 字符 / 候选 {len(cand)} 条")


if __name__ == "__main__":
    main()
