/**
 * wxbot-gui frontend: load config, edit, save, view status/logs.
 */

interface Cfg {
  enabled: boolean;
  poll_interval_seconds: number;
  reply: {
    private: { enabled: boolean; min_delay_s: number; max_delay_s: number };
    group: { enabled: boolean; require_mention: boolean; min_delay_s: number; max_delay_s: number; mention_names: string[] };
    unlimited_groups: string[];
    unlimited_group_interval_s: number;
    max_sentences: number;
    sentence_delay_s: number[];
    allow_contacts: string[];
    deny_contacts: string[];
    max_reply_chars: number;
  };
  llm: {
    base_url: string;
    model: string;
    api_key_env: string;
    temperature: number;
    max_tokens: number;
  };
  [k: string]: any;
}

const $ = <T extends HTMLElement = HTMLInputElement>(id: string) => document.getElementById(id) as T;

let cfg: Cfg | null = null;

function toast(msg: string, ok = true) {
  const t = $("toast");
  t.textContent = msg;
  t.style.background = ok ? "#1e4d2c" : "#4d1e1e";
  t.style.color = ok ? "#53d27a" : "#e05555";
  t.style.display = "block";
  setTimeout(() => (t.style.display = "none"), 2600);
}

async function api(path: string, method = "GET", body?: any): Promise<any> {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${method} ${path} -> ${res.status}`);
  const ct = res.headers.get("content-type") || "";
  return ct.includes("json") ? res.json() : res.text();
}

function fill(c: Cfg) {
  cfg = c;
  ($("enabled") as HTMLInputElement).checked = !!c.enabled;
  $("poll_interval_seconds").value = String(c.poll_interval_seconds ?? 45);
  $("priv_min").value = String(c.reply.private.min_delay_s);
  $("priv_max").value = String(c.reply.private.max_delay_s);
  $("grp_min").value = String(c.reply.group.min_delay_s);
  $("grp_max").value = String(c.reply.group.max_delay_s);
  $("sent_min").value = String(c.reply.sentence_delay_s?.[0] ?? 1.0);
  $("sent_max").value = String(c.reply.sentence_delay_s?.[1] ?? 2.5);
  $("max_sentences").value = String(c.reply.max_sentences ?? 4);
  $("max_reply_chars").value = String(c.reply.max_reply_chars ?? 300);
  $("unlim_interval").value = String(c.reply.unlimited_group_interval_s ?? 90);
  ($("unlimited_groups") as HTMLTextAreaElement).value = (c.reply.unlimited_groups || []).join("\n");
  ($("deny_contacts") as HTMLTextAreaElement).value = (c.reply.deny_contacts || []).join("\n");
  $("llm_base_url").value = c.llm.base_url;
  $("llm_model").value = c.llm.model;
  $("llm_key_env").value = c.llm.api_key_env;
  $("llm_temp").value = String(c.llm.temperature);
  $("llm_max_tokens").value = String(c.llm.max_tokens);
}

function collect(): Cfg {
  if (!cfg) throw new Error("config not loaded");
  const c: Cfg = JSON.parse(JSON.stringify(cfg));
  c.enabled = ($("enabled") as HTMLInputElement).checked;
  c.poll_interval_seconds = Number($("poll_interval_seconds").value) || 45;
  c.reply.private.min_delay_s = Number($("priv_min").value);
  c.reply.private.max_delay_s = Number($("priv_max").value);
  c.reply.group.min_delay_s = Number($("grp_min").value);
  c.reply.group.max_delay_s = Number($("grp_max").value);
  c.reply.sentence_delay_s = [Number($("sent_min").value), Number($("sent_max").value)];
  c.reply.max_sentences = Number($("max_sentences").value) || 4;
  c.reply.max_reply_chars = Number($("max_reply_chars").value) || 300;
  c.reply.unlimited_group_interval_s = Number($("unlim_interval").value) || 90;
  c.reply.unlimited_groups = ($("unlimited_groups") as HTMLTextAreaElement).value
    .split("\n").map((s) => s.trim()).filter(Boolean);
  c.reply.deny_contacts = ($("deny_contacts") as HTMLTextAreaElement).value
    .split("\n").map((s) => s.trim()).filter(Boolean);
  c.llm.base_url = $("llm_base_url").value.trim();
  c.llm.model = $("llm_model").value.trim();
  c.llm.api_key_env = $("llm_key_env").value.trim();
  c.llm.temperature = Number($("llm_temp").value);
  c.llm.max_tokens = Number($("llm_max_tokens").value);
  return c;
}

async function loadConfig() {
  try {
    const c = await api("/api/config");
    fill(c);
  } catch (e) {
    toast(`配置加载失败: ${e}`, false);
  }
}

async function saveConfig() {
  try {
    const body = collect();
    const r = await api("/api/config", "PUT", body);
    if (r.ok) toast("已保存 ✅（重启 wxbot 后生效）");
    else toast(`保存失败: ${r.error}`, false);
  } catch (e) {
    toast(`保存失败: ${e}`, false);
  }
}

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    const b = $("procBadge");
    if (s.running) {
      b.textContent = `运行中 pid ${s.pids.join(",")}`;
      b.className = "badge on";
    } else {
      b.textContent = "未运行";
      b.className = "badge off";
    }
  } catch {
    $("procBadge").textContent = "状态未知";
  }
}

async function restart() {
  if (!confirm("确定重启 wxbot？（会先杀掉旧进程再启动）")) return;
  try {
    const r = await api("/api/restart", "POST");
    toast(r.ok ? `已重启 pid ${r.pid}` : "重启失败", r.ok);
    setTimeout(refreshStatus, 1500);
  } catch (e) {
    toast(`重启失败: ${e}`, false);
  }
}

async function refreshLogs() {
  try {
    const text = await api("/api/logs?n=200");
    const el = $("logs");
    el.textContent = text || "（暂无日志）";
    el.scrollTop = el.scrollHeight;
  } catch {
    /* ignore */
  }
}

$("btnSave").addEventListener("click", saveConfig);
$("btnRestart").addEventListener("click", restart);
$("btnRefresh").addEventListener("click", () => {
  loadConfig();
  refreshStatus();
  refreshLogs();
});

loadConfig();
refreshStatus();
refreshLogs();
setInterval(refreshStatus, 10000);
setInterval(refreshLogs, 5000);
