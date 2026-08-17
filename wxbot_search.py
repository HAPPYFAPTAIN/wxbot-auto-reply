# -*- coding: utf-8 -*-
"""On-demand Zhihu CLI search for reply grounding."""
import json
import os
import re
import subprocess


_SEARCH_RE = re.compile(r"^\s*\[SEARCH:(global|zhihu)\|(.{2,160})\]\s*$", re.S)


def parse_search_request(text):
    m = _SEARCH_RE.fullmatch(text or "")
    if not m:
        return None
    query = re.sub(r"\s+", " ", m.group(2)).strip()
    return (m.group(1), query) if query else None


def search(cfg, scope, query):
    scfg = cfg.get("search") or {}
    if not scfg.get("enabled", False):
        return ""
    cli = os.path.expandvars(scfg.get("zhihu_cli", ""))
    if not cli or not os.path.isfile(cli):
        return ""
    scope = scope if scope in ("global", "zhihu") else "global"
    count = max(1, min(5, int(scfg.get("count", 3))))
    timeout_s = max(5, min(60, int(scfg.get("timeout_s", 20))))
    cmd = [cli, "search", scope, "--query", query, "--count", str(count),
           "--timeout", f"{timeout_s}s"]
    if scope == "global":
        cmd.extend(["--search-db", scfg.get("search_db", "all")])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout_s + 5, check=False,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if proc.returncode != 0 or not proc.stdout.strip():
            return ""
        data = json.loads(proc.stdout)
        items = ((data.get("Data") or {}).get("Items") or [])
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return ""
    lines = []
    for item in items[:count]:
        title = re.sub(r"\s+", " ", str(item.get("Title") or "")).strip()
        text = re.sub(r"\s+", " ", str(item.get("ContentText") or "")).strip()
        url = str(item.get("Url") or "").strip()
        if not title and not text:
            continue
        snippet = text[:300] + ("…" if len(text) > 300 else "")
        lines.append(f"- {title}\n  {snippet}\n  来源：{url}")
    return "\n".join(lines)
