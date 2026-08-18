# -*- coding: utf-8 -*-
"""wxbot 控制台面板（单文件，无第三方依赖）

- 只依赖 Python 标准库：python wxbot_panel.py 即用，默认 http://127.0.0.1:7932
- 启动面板【不会】启动 bot；bot 的启动/停止/重启/暂停全部由面板人工触发
- 能力：运行状态总览、实时运行流水、全链路决策日志（含完整提示词）、
  人格切换（配置热加载，免重启）、限频/冷却等参数快改、提示词预览
"""
import json, os, re, subprocess, sys, time, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "wxbot_config.json")
OUT_LOG = os.path.join(BASE, "wxbot_out.log")
ERR_LOG = os.path.join(BASE, "wxbot_err.log")
CALL_LOG = os.path.join(BASE, "wxbot_call.log")
PAUSE_FILE = os.path.join(BASE, "wxbot.pause")
PID_FILE = os.path.join(BASE, "wxbot_panel_bot.pid")
PREVIEW_MD = os.path.join(BASE, "prompt_preview.md")
PORT = 7932

# 允许从面板修改的配置键（白名单，路径用 . 分隔）
EDITABLE_KEYS = {
    "reply.rate_limit.max": int,
    "reply.rate_limit.window_s": int,
    "reply.unlimited_group_interval_s": None,  # 特殊处理：[min,max]
    "reply.candidate_count": int,
    "reply.candidate_window_s": int,
    "llm.temperature": float,
}

# ---------------------------------------------------------------- 基础工具

def _read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _tail(path, n=200):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        return lines[-n:]
    except Exception:
        return []


# ---------------------------------------------------------------- bot 进程管理

def _panel_pid():
    try:
        with open(PID_FILE, "r") as f:
            return int(f.read().strip())
    except Exception:
        return 0


def _pid_alive(pid):
    if not pid:
        return False
    r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
    return str(pid) in r.stdout


def _find_external_bot():
    """扫本机 python 进程里 cmdline 含 wxbot.py 的（非面板拉起的也算）。"""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" "
             "| Where-Object {$_.CommandLine -like '*wxbot.py*'} "
             "| Select-Object -ExpandProperty ProcessId"],
            capture_output=True, text=True, timeout=15).stdout
        for tok in out.split():
            if tok.isdigit():
                return int(tok)
    except Exception:
        pass
    return 0


def bot_status():
    pid = _panel_pid()
    if pid and _pid_alive(pid):
        return {"running": True, "pid": pid, "source": "panel"}
    ext = _find_external_bot()
    if ext:
        return {"running": True, "pid": ext, "source": "external"}
    return {"running": False, "pid": 0, "source": "none"}


def bot_start():
    st = bot_status()
    if st["running"]:
        return False, f"bot 已在运行 (PID {st['pid']})"
    out = open(OUT_LOG, "w", encoding="utf-8")
    err = open(ERR_LOG, "w", encoding="utf-8")
    p = subprocess.Popen(
        ["python", "-u", "wxbot.py"], cwd=BASE,
        stdout=out, stderr=err,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    with open(PID_FILE, "w") as f:
        f.write(str(p.pid))
    return True, f"已启动 PID {p.pid}"


def bot_stop():
    st = bot_status()
    if not st["running"]:
        return False, "bot 未在运行"
    subprocess.run(["taskkill", "/F", "/PID", str(st["pid"])], capture_output=True)
    try:
        os.remove(PID_FILE)
    except OSError:
        pass
    return True, f"已停止 PID {st['pid']}"


# ---------------------------------------------------------------- 配置/统计

def today_stats():
    today = time.strftime("%Y-%m-%d")
    stats = {"llm": 0, "send_ok": 0, "skip": 0, "pick": 0, "gate_closed": 0, "last_ts": ""}
    try:
        with open(CALL_LOG, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.startswith('{"ts": "' + today):
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                ev = d.get("event", "")
                if ev in stats:
                    stats[ev] += 1
                stats["last_ts"] = d.get("ts", stats["last_ts"])
    except Exception:
        pass
    return stats


def persona_info():
    cfg = _read_json(CONFIG_PATH, {}) or {}
    p = (((cfg.get("reply") or {}).get("personas")) or {})
    names = set(p.get("definitions", {}) or {})
    pdir = os.path.join(BASE, p.get("dir") or "personas")
    try:
        for fn in os.listdir(pdir):
            if fn.endswith(".md"):
                names.add(fn[:-3])
    except Exception:
        pass
    return {
        "list": sorted(names),
        "default": p.get("default", ""),
        "per_group": p.get("per_group", {}) or {},
        "enabled": p.get("enabled", True),
    }


def set_persona(group, persona):
    cfg = _read_json(CONFIG_PATH, {}) or {}
    p = cfg.setdefault("reply", {}).setdefault("personas", {})
    if group:
        p.setdefault("per_group", {})[group] = persona
    else:
        p["default"] = persona
    _write_json(CONFIG_PATH, cfg)  # bot 每轮轮询前热加载，自动生效
    return True


def edit_config(key, value):
    if key not in EDITABLE_KEYS:
        return False, f"不允许修改 {key}"
    cfg = _read_json(CONFIG_PATH, {}) or {}
    parts = key.split(".")
    node = cfg
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    if key == "reply.unlimited_group_interval_s":
        nums = [int(x) for x in re.split(r"[,，\s~\-]+", str(value)) if x.strip()]
        if len(nums) == 1:
            value = nums[0]              # 标量 = 固定冷却
        elif len(nums) >= 2:
            value = nums[:2]             # [min,max] = 随机区间
        else:
            return False, "冷却格式: 90 或 240,420"
    else:
        try:
            value = EDITABLE_KEYS[key](value)
        except Exception:
            return False, f"{key} 类型应为 {EDITABLE_KEYS[key].__name__}"
    node[parts[-1]] = value
    _write_json(CONFIG_PATH, cfg)
    return True, "ok"


# ---------------------------------------------------------------- API

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, data, code=200, ctype="application/json"):
        body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if "json" in ctype or "html" in ctype else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        path = u.path
        if path == "/" or path == "/index.html":
            return self._send(HTML.encode("utf-8"), ctype="text/html")
        if path == "/api/status":
            st = bot_status()
            cfg = _read_json(CONFIG_PATH, {}) or {}
            return self._send({
                "bot": st,
                "paused": os.path.exists(PAUSE_FILE),
                "model": (cfg.get("llm") or {}).get("model", ""),
                "temperature": (cfg.get("llm") or {}).get("temperature"),
                "persona": persona_info(),
                "rate_limit": ((cfg.get("reply") or {}).get("rate_limit")) or {},
                "cooldown": (cfg.get("reply") or {}).get("unlimited_group_interval_s"),
                "candidate_count": (cfg.get("reply") or {}).get("candidate_count"),
                "stats": today_stats(),
            })
        if path == "/api/logs":
            n = int(q.get("tail", [200])[0])
            return self._send({"lines": _tail(OUT_LOG, n)})
        if path == "/api/calllog":
            n = int(q.get("tail", [60])[0])
            events = []
            for line in _tail(CALL_LOG, n * 3):
                try:
                    events.append(json.loads(line))
                except Exception:
                    continue
            return self._send({"events": events[-n:]})
        if path == "/api/config":
            return self._send(_read_json(CONFIG_PATH, {}) or {})
        if path == "/api/preview_md":
            try:
                with open(PREVIEW_MD, "r", encoding="utf-8") as f:
                    return self._send({"md": f.read()})
            except Exception as e:
                return self._send({"md": f"(读取失败: {e})"})
        return self._send({"error": "not found"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        ln = int(self.headers.get("Content-Length", 0) or 0)
        body = {}
        if ln:
            try:
                body = json.loads(self.rfile.read(ln).decode("utf-8"))
            except Exception:
                pass
        if u.path == "/api/control":
            act = (body or {}).get("action", "")
            if act == "start":
                ok, msg = bot_start()
            elif act == "stop":
                ok, msg = bot_stop()
            elif act == "restart":
                bot_stop()
                time.sleep(2)
                ok, msg = bot_start()
            elif act == "pause":
                open(PAUSE_FILE, "w").write(str(time.time()))
                ok, msg = True, "已暂停（只读不回）"
            elif act == "resume":
                try:
                    os.remove(PAUSE_FILE)
                except OSError:
                    pass
                ok, msg = True, "已恢复"
            else:
                ok, msg = False, f"未知动作 {act}"
            return self._send({"ok": ok, "msg": msg, "bot": bot_status(), "paused": os.path.exists(PAUSE_FILE)})
        if u.path == "/api/persona":
            set_persona((body or {}).get("group", ""), (body or {}).get("persona", ""))
            return self._send({"ok": True, "persona": persona_info()})
        if u.path == "/api/config/edit":
            ok, msg = edit_config((body or {}).get("key", ""), (body or {}).get("value"))
            return self._send({"ok": ok, "msg": msg})
        if u.path == "/api/preview":
            win = (body or {}).get("window", "")
            cmd = [sys.executable, "-X", "utf8", os.path.join(BASE, "preview_prompt.py")]
            if win:
                cmd.append(f"--window={win}")
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=BASE)
                return self._send({"ok": r.returncode == 0, "out": (r.stdout or "")[-2000:]})
            except Exception as e:
                return self._send({"ok": False, "out": str(e)})
        return self._send({"error": "not found"}, 404)


# ---------------------------------------------------------------- 前端页面

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>wxbot 控制台</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--fg:#e6edf3;--dim:#8b949e;--acc:#58a6ff;--ok:#3fb950;--warn:#d29922;--bad:#f85149}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--fg);font:14px/1.6 "Microsoft YaHei",system-ui,sans-serif;padding:16px;max-width:1200px;margin:0 auto}
h1{font-size:18px;margin-bottom:12px}
h2{font-size:14px;color:var(--dim);margin:0 0 8px;font-weight:600}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px;margin-bottom:14px}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.dot{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:6px}
.dot.on{background:var(--ok);box-shadow:0 0 6px var(--ok)}
.dot.off{background:var(--bad)}
.dot.pause{background:var(--warn)}
button{background:#21262d;border:1px solid var(--border);color:var(--fg);border-radius:6px;padding:6px 14px;cursor:pointer;font-size:13px}
button:hover{border-color:var(--acc)}
button.primary{background:#1f6feb;border-color:#1f6feb;color:#fff}
button.danger{background:#da3633;border-color:#da3633;color:#fff}
select,input{background:#0d1117;border:1px solid var(--border);color:var(--fg);border-radius:6px;padding:5px 8px;font-size:13px}
input{width:80px}
.stat{display:inline-block;background:#0d1117;border:1px solid var(--border);border-radius:6px;padding:4px 10px;margin-right:8px;font-size:12px}
.stat b{color:var(--acc);font-size:15px;margin-left:4px}
#log{background:#010409;border:1px solid var(--border);border-radius:8px;padding:10px;height:280px;overflow-y:auto;font:12px/1.5 Consolas,monospace;white-space:pre-wrap;color:#a5d6a7}
.ev{border:1px solid var(--border);border-radius:8px;padding:8px 10px;margin-bottom:8px;font-size:12.5px}
.ev .t{color:var(--dim);font-size:11px;margin-right:8px}
.ev .kind{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;margin-right:8px}
.k-llm{background:#1f6feb33;color:#79b8ff}.k-send_ok{background:#3fb95033;color:#3fb950}.k-skip{background:#8b949e33;color:#8b949e}
.k-pick{background:#d2992233;color:#d29922}.k-candidates,.k-system{background:#bc8cff33;color:#bc8cff}
.k-gate_closed,.k-pick_invalid,.k-pick_missing{background:#f8514933;color:#f85149}
.ev pre{background:#010409;border-radius:6px;padding:8px;margin-top:6px;white-space:pre-wrap;max-height:400px;overflow-y:auto;font-size:11.5px;color:#a5d6a7}
details summary{cursor:pointer;color:var(--acc);font-size:11.5px}
.dim{color:var(--dim)}
.lbl{font-size:12px;color:var(--dim);margin-right:4px}
hr{border:none;border-top:1px solid var(--border);margin:10px 0}
</style>
</head>
<body>
<h1>🤖 wxbot 控制台 <span class="dim" style="font-size:12px">7932</span></h1>

<div class="card">
  <h2>运行状态</h2>
  <div class="row" style="margin-bottom:10px">
    <span id="lamp"><span class="dot off"></span>检测中</span>
    <span class="stat">模型<b id="model">-</b></span>
    <span class="stat">默认人格<b id="personaNow">-</b></span>
    <span class="stat">主动限频<b id="rateNow">-</b></span>
    <span class="stat">冷却<b id="cdNow">-</b></span>
  </div>
  <div class="row">
    <button class="primary" onclick="ctl('start')">▶ 启动</button>
    <button class="danger" onclick="ctl('stop')">⏹ 停止</button>
    <button onclick="ctl('restart')">🔄 重启</button>
    <button id="pauseBtn" onclick="togglePause()">⏸ 暂停</button>
    <span class="stat">今日 回复<b id="sReply">0</b></span>
    <span class="stat">跳过<b id="sSkip">0</b></span>
    <span class="stat">闸门拦截<b id="sGate">0</b></span>
    <span class="stat dim" id="sLast"></span>
  </div>
</div>

<div class="card">
  <h2>人格与参数（热加载，免重启）</h2>
  <div class="row" style="margin-bottom:8px">
    <span class="lbl">34群人格</span>
    <select id="personaSel" onchange="setPersona()"></select>
    <span class="lbl">限频(条/10分钟)</span><input id="rateMax" type="number" min="0" max="50">
    <span class="lbl">冷却(秒,区间)</span><input id="cdRange" style="width:110px" placeholder="240,420">
    <span class="lbl">候选条数</span><input id="candN" type="number" min="1" max="10">
    <span class="lbl">温度</span><input id="temp" type="number" step="0.1" min="0" max="2" style="width:60px">
    <button onclick="saveCfg()">💾 保存参数</button>
    <span id="cfgMsg" class="dim"></span>
  </div>
  <div class="row">
    <button onclick="genPreview()">🔍 生成当前提示词预览</button>
    <span class="lbl">窗口(分钟)</span><input id="pvWin" type="number" style="width:60px" placeholder="10">
    <span id="pvMsg" class="dim"></span>
  </div>
</div>

<div class="card">
  <h2>运行流水（实时）</h2>
  <div id="log"></div>
</div>

<div class="card">
  <h2>决策链日志（含完整提示词，点击展开）</h2>
  <div id="events"></div>
</div>

<script>
let personaList = [];
async function j(url, opt){ const r = await fetch(url, opt); return r.json(); }
function esc(s){ return String(s??'').replace(/[&<>]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }

async function refresh(){
  try{
    const s = await j('/api/status');
    const b = s.bot;
    const lamp = document.getElementById('lamp');
    if(b.running){
      lamp.innerHTML = `<span class="dot ${s.paused?'pause':'on'}"></span>${s.paused?'已暂停':'运行中'} PID ${b.pid}（${b.source==='panel'?'面板拉起':'外部启动'}）`;
    } else lamp.innerHTML = '<span class="dot off"></span>已停止';
    document.getElementById('pauseBtn').textContent = s.paused ? '▶ 恢复' : '⏸ 暂停';
    model.textContent = s.model;
    personaNow.textContent = Object.values(s.persona.per_group||{})[0] || s.persona.default || '-';
    rateNow.textContent = (s.rate_limit.max??'-') + '条/' + Math.round((s.rate_limit.window_s||0)/60) + '分钟';
    cdNow.textContent = Array.isArray(s.cooldown) ? s.cooldown.join('~')+'s' : (s.cooldown||'-');
    sReply.textContent = s.stats.send_ok; sSkip.textContent = s.stats.skip; sGate.textContent = s.stats.gate_closed;
    sLast.textContent = '最后活动 ' + (s.stats.last_ts||'无');
    if(!personaList.length){
      personaList = s.persona.list;
      const sel = document.getElementById('personaSel');
      const curP = Object.values(s.persona.per_group||{})[0] || s.persona.default;
      sel.innerHTML = personaList.map(p=>`<option ${p===curP?'selected':''}>${p}</option>`).join('');
      rateMax.value = s.rate_limit.max ?? 3;
      cdRange.value = Array.isArray(s.cooldown) ? s.cooldown.join(',') : (s.cooldown||'');
      candN.value = s.candidate_count ?? 3;
      if(s.temperature != null) temp.value = s.temperature;
    }
  }catch(e){}
}

async function ctl(a){ const r = await j('/api/control',{method:'POST',body:JSON.stringify({action:a})}); if(!r.ok) alert(r.msg); refresh(); }
async function togglePause(){
  const paused = document.getElementById('pauseBtn').textContent.includes('恢复');
  await j('/api/control',{method:'POST',body:JSON.stringify({action: paused?'resume':'pause'})}); refresh();
}
async function setPersona(){
  await j('/api/persona',{method:'POST',body:JSON.stringify({group:Object.keys(s.persona.per_group||{})[0]||'',persona:personaSel.value})});
  cfgMsg.textContent = '人格已切换（下轮生效）'; setTimeout(()=>cfgMsg.textContent='',3000);
}
async function saveCfg(){
  const edits = [
    ['reply.rate_limit.max', rateMax.value],
    ['reply.candidate_count', candN.value],
  ];
  if(temp.value !== '') edits.push(['llm.temperature', temp.value]);
  if(cdRange.value) edits.push(['reply.unlimited_group_interval_s', cdRange.value]);
  for(const [k,v] of edits){
    const r = await j('/api/config/edit',{method:'POST',body:JSON.stringify({key:k,value:v})});
    if(!r.ok){ cfgMsg.textContent = k+': '+r.msg; return; }
  }
  cfgMsg.textContent = '已保存（下轮生效）'; setTimeout(()=>cfgMsg.textContent='',3000); refresh();
}
async function genPreview(){
  pvMsg.textContent = '生成中（约10-30秒）…';
  const r = await j('/api/preview',{method:'POST',body:JSON.stringify({window:pvWin.value})});
  pvMsg.textContent = r.ok ? '已生成，见项目目录 prompt_preview.md' : '失败: '+r.out.slice(-200);
}

let lastLog = '';
async function tickLog(){
  try{
    const d = await j('/api/logs?tail=200');
    const t = d.lines.join('\n');
    if(t !== lastLog){
      lastLog = t;
      const el = document.getElementById('log');
      el.textContent = t || '(暂无日志)';
      el.scrollTop = el.scrollHeight;
    }
  }catch(e){}
}

const KIND = ['candidates','system','llm','pick','send_ok','skip','gate_closed','pick_invalid','pick_missing','send_partial'];
async function tickEvents(){
  try{
    const d = await j('/api/calllog?tail=60');
    const el = document.getElementById('events');
    el.innerHTML = d.events.slice().reverse().map(e=>{
      const k = e.event||'?';
      let body = '';
      if(k==='llm'){
        body = `<div><b>回复:</b> ${esc(e.reply||'')}</div>`;
        if(e.user) body += `<details><summary>完整 user 提示词（${(e.user||'').length}字符）</summary><pre>${esc(e.user)}</pre></details>`;
        if(e.sys) body += `<div class="dim">system指纹: ${e.sys}（同指纹的 system 见最近的 system 事件）</div>`;
      } else if(k==='system'){
        body = `<details><summary>system prompt 全文（${e.chars||''}字符, persona=${esc(e.persona||'')}）</summary><pre>${esc(e.system||'')}</pre></details>`;
      } else if(k==='pick'){
        body = `<div>选中候选 #${esc(JSON.stringify(e.pick))}: ${esc((e.picked||[]).join? e.picked.join(' ｜ ') : e.picked)}</div>`;
      } else if(k==='candidates'){
        body = `<details><summary>${e.n||0} 条候选</summary><pre>${esc((e.cand||[]).join('\n'))}</pre></details>`;
      } else if(k==='send_ok'){
        body = `<div>已发出 ${e.n_sent||''} 句: ${esc((e.sentences||[]).join(' / '))}</div>`;
      } else {
        body = `<div class="dim">${esc(JSON.stringify(e)).slice(0,300)}</div>`;
      }
      return `<div class="ev"><span class="t">${esc(e.ts||'')}</span><span class="kind k-${k}">${k}</span>${body}</div>`;
    }).join('') || '<div class="dim">暂无事件</div>';
  }catch(e){}
}

refresh(); tickLog(); tickEvents();
setInterval(refresh, 4000);
setInterval(tickLog, 3000);
setInterval(tickEvents, 5000);
</script>
</body>
</html>
"""


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"wxbot 控制台: http://127.0.0.1:{PORT}  （启动面板不会启动 bot）")
    srv.serve_forever()


if __name__ == "__main__":
    main()
