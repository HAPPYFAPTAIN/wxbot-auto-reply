/**
 * wxbot-gui frontend: load config, edit, save, view status/logs.
 */

interface Cfg {
  enabled: boolean;
  poll_interval_seconds: number;
  reply: {
    private: { enabled: boolean; min_delay_s: number; max_delay_s: number; cooldown_s?: number;
      allow?: string[]; deny?: string[];
      quiet_hours?: { enabled: boolean; start: string; end: string; allow_contacts: string[] } };
    group: { enabled: boolean; require_mention: boolean; min_delay_s: number; max_delay_s: number; mention_names: string[];
      allow?: string[]; deny?: string[] };
    context_messages?: number | Record<string, number>;
    unlimited_groups: string[];
    unlimited_group_interval_s: number;
    max_sentences: number;
    sentence_delay_s: number[];
    allow_contacts: string[];
    deny_contacts: string[];
    max_reply_chars: number;
    personas?: {
      enabled: boolean; dir?: string; default?: string;
      per_group?: Record<string, string>; per_contact?: Record<string, string>;
      definitions?: Record<string, string>;
      behaviors?: Record<string, Record<string, number>>;
    };
  };
  llm: {
    base_url: string;
    model: string;
    api_key_env: string;
    temperature: number;
    max_tokens: number;
    context_window?: number;
  };
  context?: { compression?: { enabled?: boolean; mode?: string; percent?: number; tokens?: number; keep_recent?: number; trim_chars?: number } };
  memory?: { enabled?: boolean; every_n_replies?: number; long_term_chars?: number; daily_chars?: number };
  stickers?: { enabled: boolean; catalog?: string };
  [k: string]: any;
}

interface StickerItem {
  index: number;
  file: string;
  label: string;
  desc?: string;
  emotion?: string;
  keywords?: string[];
}

const $ = <T extends HTMLElement = HTMLInputElement>(id: string) => document.getElementById(id) as T;

// ---------------- theme ----------------
function initTheme() {
  const saved = localStorage.getItem("wxbot-theme");
  const theme = saved || (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  document.documentElement.setAttribute("data-theme", theme);
  $("themeToggle").textContent = theme === "dark" ? "☀️" : "🌙";
}
$("themeToggle").addEventListener("click", () => {
  const cur = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", cur);
  localStorage.setItem("wxbot-theme", cur);
  $("themeToggle").textContent = cur === "dark" ? "☀️" : "🌙";
});
initTheme();

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
  ($("priv_enabled") as HTMLInputElement).checked = !!c.reply.private.enabled;
  $("priv_min").value = String(c.reply.private.min_delay_s);
  $("priv_max").value = String(c.reply.private.max_delay_s);
  $("priv_cooldown").value = String(c.reply.private.cooldown_s ?? 0);
  const qh = c.reply.private.quiet_hours || { enabled: false, start: "23:30", end: "07:30", allow_contacts: [] };
  ($("qh_enabled") as HTMLInputElement).checked = !!qh.enabled;
  $("qh_start").value = qh.start || "23:30";
  $("qh_end").value = qh.end || "07:30";
  ($("qh_allow") as HTMLTextAreaElement).value = (qh.allow_contacts || []).join("\n");
  const ps = c.reply.personas || { enabled: true };
  $("persona_dir").value = ps.dir || "personas";
  $("persona_default").value = ps.default || "";
  ($("persona_per_group") as HTMLTextAreaElement).value =
    Object.entries(ps.per_group || {}).map(([k, v]) => `${k}:${v}`).join("\n");
  ($("persona_per_contact") as HTMLTextAreaElement).value =
    Object.entries(ps.per_contact || {}).map(([k, v]) => `${k}:${v}`).join("\n");
  ($("priv_allow") as HTMLTextAreaElement).value = (c.reply.private.allow || []).join("\n");
  ($("priv_deny") as HTMLTextAreaElement).value = (c.reply.private.deny || []).join("\n");
  ($("grp_allow") as HTMLTextAreaElement).value = (c.reply.group.allow || []).join("\n");
  ($("grp_deny") as HTMLTextAreaElement).value = (c.reply.group.deny || []).join("\n");
  const cm = c.reply.context_messages ?? 8;
  $("ctx_messages").value = String(typeof cm === "object" ? (cm.default ?? 8) : cm);
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
  $("ctx_window").value = String(c.llm.context_window ?? 32000);
  const cc = c.context?.compression || {};
  ($("cc_enabled") as HTMLInputElement).checked = !!cc.enabled;
  $("cc_mode").value = cc.mode || "percent";
  $("cc_percent").value = String(cc.percent ?? 60);
  $("cc_tokens").value = String(cc.tokens ?? 4000);
  $("cc_keep").value = String(cc.keep_recent ?? 4);
  $("cc_trim").value = String(cc.trim_chars ?? 60);
  const mem = c.memory || {};
  ($("mem_enabled") as HTMLInputElement).checked = mem.enabled !== false;
  $("mem_every").value = String(mem.every_n_replies ?? 5);
  ($("stickers_enabled") as HTMLInputElement).checked = !!c.stickers?.enabled;
}

function collect(): Cfg {
  if (!cfg) throw new Error("config not loaded");
  const c: Cfg = JSON.parse(JSON.stringify(cfg));
  c.enabled = ($("enabled") as HTMLInputElement).checked;
  c.poll_interval_seconds = Number($("poll_interval_seconds").value) || 45;
  c.reply.private.enabled = ($("priv_enabled") as HTMLInputElement).checked;
  c.reply.private.min_delay_s = Number($("priv_min").value);
  c.reply.private.max_delay_s = Number($("priv_max").value);
  c.reply.private.cooldown_s = Number($("priv_cooldown").value) || 0;
  c.reply.private.quiet_hours = {
    enabled: ($("qh_enabled") as HTMLInputElement).checked,
    start: $("qh_start").value.trim() || "23:30",
    end: $("qh_end").value.trim() || "07:30",
    allow_contacts: ($("qh_allow") as HTMLTextAreaElement).value.split("\n").map((s) => s.trim()).filter(Boolean),
  };
  // 人格系统
  const parseMap = (v: string): Record<string, string> => {
    const out: Record<string, string> = {};
    for (const line of v.split("\n")) {
      const m = line.match(/^(.+?)[:：](.+)$/);
      if (m) out[m[1].trim()] = m[2].trim();
    }
    return out;
  };
  if (!c.reply.personas) c.reply.personas = { enabled: true };
  c.reply.personas.dir = $("persona_dir").value.trim() || "personas";
  c.reply.personas.default = $("persona_default").value.trim();
  c.reply.personas.per_group = parseMap(($("persona_per_group") as HTMLTextAreaElement).value);
  c.reply.personas.per_contact = parseMap(($("persona_per_contact") as HTMLTextAreaElement).value);
  if (!c.reply.personas.behaviors) c.reply.personas.behaviors = {};
  c.reply.personas.behaviors[behaviorTarget] = {
    at: Number($("beh_at").value) / 100,
    emoji: Number($("beh_emoji").value) / 100,
    sticker: Number($("beh_sticker").value) / 100,
    image: Number($("beh_image").value) / 100,
    quote: Number($("beh_quote").value) / 100,
  };
  const toList = (id: string) => ($(id) as HTMLTextAreaElement).value.split("\n").map((s) => s.trim()).filter(Boolean);
  c.reply.private.allow = toList("priv_allow");
  c.reply.private.deny = toList("priv_deny");
  c.reply.group.allow = toList("grp_allow");
  c.reply.group.deny = toList("grp_deny");
  const cmv = Math.max(1, Math.min(1000, Number($("ctx_messages").value) || 8));
  if (typeof c.reply.context_messages === "object" && c.reply.context_messages) {
    c.reply.context_messages.default = cmv;
  } else {
    c.reply.context_messages = cmv;
  }
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
  c.llm.context_window = Math.max(1000, Number($("ctx_window").value) || 32000);
  c.context = {
    compression: {
      enabled: ($("cc_enabled") as HTMLInputElement).checked,
      mode: ($("cc_mode") as HTMLSelectElement).value,
      percent: Math.max(5, Math.min(95, Number($("cc_percent").value) || 60)),
      tokens: Math.max(100, Number($("cc_tokens").value) || 4000),
      keep_recent: Math.max(1, Math.min(50, Number($("cc_keep").value) || 4)),
      trim_chars: Math.max(10, Math.min(500, Number($("cc_trim").value) || 60)),
    },
  };
  c.memory = {
    ...(c.memory || {}),
    enabled: ($("mem_enabled") as HTMLInputElement).checked,
    every_n_replies: Math.max(1, Math.min(100, Number($("mem_every").value) || 5)),
  };
  c.stickers = { ...(c.stickers || {}), enabled: ($("stickers_enabled") as HTMLInputElement).checked };
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
    if (r.ok) {
      toast("已保存 ✅（重启 wxbot 后生效）");
      setDirty(false);
    } else toast(`保存失败: ${r.error}`, false);
  } catch (e) {
    toast(`保存失败: ${e}`, false);
  }
}

// ---------------- dirty tracking（改动后顶部保存按钮亮起） ----------------
let paramsDirty = false;
function setDirty(v: boolean) {
  paramsDirty = v;
  ($("btnSaveTop") as HTMLButtonElement).disabled = !v;
}

function watchDirty() {
  // 人格文件内容有自己的保存按钮，不参与参数脏跟踪
  const skip = new Set(["persona_content", "persona_select", "logs"]);
  document.querySelectorAll("main input, main textarea, main select").forEach((el) => {
    if (skip.has(el.id)) return;
    el.addEventListener("input", () => setDirty(true));
    el.addEventListener("change", () => setDirty(true));
  });
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

async function stopWxbot() {
  if (!confirm("确定停止 wxbot？（会杀掉运行中的进程）")) return;
  try {
    const r = await api("/api/stop", "POST");
    toast(r.ok ? "已停止 ✅" : `仍有进程残留: ${(r.stillRunning || []).join(",")}`, r.ok);
    refreshStatus();
  } catch (e) {
    toast(`停止失败: ${e}`, false);
  }
}

async function startWxbot() {
  try {
    const r = await api("/api/start", "POST");
    toast(r.ok ? `已启动 pid ${r.pid}` : `启动失败: ${r.error}`, r.ok);
    setTimeout(refreshStatus, 1500);
  } catch (e) {
    toast(`启动失败: ${e}`, false);
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

// ---------------- llm test ----------------
for (const id of ["llm_base_url", "llm_model", "llm_key_env"]) {
  $(id).addEventListener("input", () => {
    $("llmLight").className = "light";
    $("llmTestResult").textContent = "参数已改，建议重新测试";
  });
}

async function testLlm() {
  const light = $("llmLight");
  const out = $("llmTestResult");
  light.className = "light busy";
  out.textContent = "测试中…";
  ($("btnLlmTest") as HTMLButtonElement).disabled = true;
  try {
    const r = await api("/api/llm/test", "POST", {
      base_url: $("llm_base_url").value.trim(),
      model: $("llm_model").value.trim(),
      api_key_env: $("llm_key_env").value.trim(),
    });
    if (r.ok) {
      light.className = "light on";
      out.textContent = `✅ 通路正常 · ${r.latency_ms}ms${r.reply ? ` · 模型回「${r.reply}」` : ""}`;
    } else {
      light.className = "light off";
      out.textContent = `❌ ${r.error || "失败"}${r.latency_ms != null ? ` · ${r.latency_ms}ms` : ""}`;
    }
  } catch (e) {
    light.className = "light off";
    out.textContent = `❌ 测试接口报错: ${e}`;
  } finally {
    ($("btnLlmTest") as HTMLButtonElement).disabled = false;
  }
}

// ---------------- stickers ----------------
let stickerRefreshing = false;

async function loadStickers() {
  const grid = $("stickerGrid");
  const status = $("stickersStatus");
  try {
    const r = await api("/api/stickers");
    stickerRefreshing = !!r.refreshing;
    const cat = r.catalog;
    if (!cat || !cat.stickers || !cat.stickers.length) {
      grid.innerHTML = '<div class="hint">（还没有贴纸目录，点「重新扫描」从微信里抓取建档）</div>';
      status.textContent = "";
      return;
    }
    status.textContent = `共 ${cat.count ?? cat.stickers.length} 张，更新于 ${cat.updated ?? "未知"}${r.refreshing ? "（正在重新扫描…）" : ""}`;
    grid.innerHTML = (cat.stickers as StickerItem[])
      .map((s) => {
        const img = s.file ? `/api/stickers/img/${s.file.split("/").pop()}` : "";
        const kw = (s.keywords || []).join(" / ");
        return `<div class="sticker-card" title="${s.desc || ""}">
          <div class="idx">#${s.index}</div>
          ${img ? `<img src="${img}" alt="${s.label}">` : ""}
          <div class="lbl">${s.label || ""}</div>
          <div class="kw">${kw}</div>
        </div>`;
      })
      .join("");
  } catch (e) {
    status.textContent = `贴纸目录加载失败: ${e}`;
  }
}

async function refreshStickers() {
  if (!confirm("重新扫描会操作微信打开表情面板截图 + vision 建档，约 1 分钟。期间别动微信窗口，继续？")) return;
  try {
    const r = await api("/api/stickers/refresh", "POST");
    if (!r.ok) {
      toast(`扫描启动失败: ${r.error}`, false);
      return;
    }
    toast("已开始扫描，稍候…");
    stickerRefreshing = true;
    let tries = 0;
    const timer = setInterval(async () => {
      tries++;
      await loadStickers();
      if (!stickerRefreshing || tries > 40) {
        clearInterval(timer);
        stickerRefreshing = false;
        toast("贴纸目录已更新 ✅");
        loadStickers();
      }
    }, 3000);
  } catch (e) {
    toast(`扫描失败: ${e}`, false);
  }
}

$("btnStickersReload").addEventListener("click", loadStickers);
$("btnStickersRefresh").addEventListener("click", refreshStickers);

// ---------------- personas ----------------
let behaviorTarget = "_default";

function currentPersonaName(): string {
  return ($("persona_select") as HTMLSelectElement).value || "";
}

// ---------------- folder picker modal ----------------
let dirModalPath = "";

async function openDirModal() {
  dirModalPath = $("persona_dir").value.trim() || "";
  ($("dirModal") as HTMLElement).style.display = "flex";
  await browseDir();
}

async function browseDir() {
  try {
    const r = await api(`/api/fs/browse?path=${encodeURIComponent(dirModalPath)}`);
    dirModalPath = r.path;
    $("dirModalPath").textContent = r.path;
    const list = $("dirList");
    if (!r.dirs.length) {
      list.innerHTML = '<div class="hint" style="padding:20px">（此文件夹下没有子文件夹）</div>';
    } else {
      list.innerHTML = r.dirs
        .map((d: any) =>
          `<div style="display:flex; align-items:center; gap:8px; padding:9px 12px; border-radius:8px; cursor:pointer;"
             class="dir-item" data-path="${d.path.replace(/"/g, "&quot;")}">
             📁 <span style="flex:1">${d.name}</span>
           </div>`)
        .join("");
      list.querySelectorAll(".dir-item").forEach((el) =>
        el.addEventListener("click", async () => {
          dirModalPath = (el as HTMLElement).dataset.path || "";
          await browseDir();
        })
      );
    }
  } catch (e) {
    toast(`目录读取失败: ${e}`, false);
  }
}

$("dirModalUp").addEventListener("click", async () => {
  try {
    const r = await api(`/api/fs/browse?path=${encodeURIComponent(dirModalPath)}`);
    dirModalPath = r.parent;
    await browseDir();
  } catch { /* ignore */ }
});
$("dirModalCancel").addEventListener("click", () => {
  ($("dirModal") as HTMLElement).style.display = "none";
});
$("dirModalPick").addEventListener("click", async () => {
  $("persona_dir").value = dirModalPath;
  ($("dirModal") as HTMLElement).style.display = "none";
  await scanPersonas();
});

async function scanPersonas() {
  // 先把目录写回配置（否则服务端还按旧目录扫描）
  try {
    if (cfg) { await api("/api/config", "PUT", collect()); setDirty(false); }
  } catch { /* 静默，扫描照样试 */ }
  const sel = $("persona_select") as HTMLSelectElement;
  const behSel = $("behavior_target") as HTMLSelectElement;
  const prev = sel.value;
  try {
    const r = await api("/api/personas");
    const files: { name: string }[] = r.files || [];
    sel.innerHTML = files.length
      ? files.map((f) => `<option value="${f.name}">${f.name}</option>`).join("")
      : '<option value="">（目录里没有 .md 人格文件）</option>';
    if (prev && files.some((f) => f.name === prev)) sel.value = prev;
    behSel.innerHTML =
      '<option value="_default">_default（所有人格默认）</option>' +
      files.map((f) => `<option value="${f.name}">${f.name}</option>`).join("");
    if ([...behSel.options].some((o) => o.value === behaviorTarget)) behSel.value = behaviorTarget;
    behaviorTarget = behSel.value;
    fillBehaviorSliders();
    if (currentPersonaName()) await loadPersonaFile(currentPersonaName());
    else ($("persona_content") as HTMLTextAreaElement).value = "";
  } catch (e) {
    toast(`人格目录读取失败: ${e}`, false);
  }
}

async function loadPersonaFile(name: string) {
  try {
    const r = await api(`/api/personas/file/${encodeURIComponent(name)}`);
    ($("persona_content") as HTMLTextAreaElement).value = r.content || "";
  } catch (e) {
    ($("persona_content") as HTMLTextAreaElement).value = "";
    toast(`人格文件读取失败: ${e}`, false);
  }
}

async function savePersona() {
  const name = currentPersonaName();
  if (!name) { toast("先选择或新建一个人格", false); return; }
  const content = ($("persona_content") as HTMLTextAreaElement).value;
  try {
    const r = await api(`/api/personas/file/${encodeURIComponent(name)}`, "PUT", { content });
    if (r.ok) toast(`人格「${name}」已保存 ✅（立即生效）`);
    else toast(`保存失败: ${r.error}`, false);
  } catch (e) {
    toast(`保存失败: ${e}`, false);
  }
}

async function newPersona() {
  const name = prompt("新人格的名字（文件名 = 名字.md，中文英文都行）:");
  if (!name || !name.trim()) return;
  const n = name.trim();
  const template = `# ${n} 人格\n\n## 说话风格\n- （这里写 TA 怎么说话：口头禅、句式、语气）\n\n## 行为习惯\n- （什么时候@人、什么时候发表情/贴纸、主动还是被动）\n\n## 禁区\n- 不暴露自己是 AI/机器人\n- 不说脏字、不人身攻击\n`;
  try {
    const r = await api(`/api/personas/file/${encodeURIComponent(n)}`, "PUT", { content: template });
    if (r.ok) {
      toast(`人格「${n}」已创建 ✅`);
      await scanPersonas();
      ($( "persona_select") as HTMLSelectElement).value = n;
      await loadPersonaFile(n);
    } else toast(`创建失败: ${r.error}`, false);
  } catch (e) {
    toast(`创建失败: ${e}`, false);
  }
}

async function deletePersona() {
  const name = currentPersonaName();
  if (!name) { toast("先选择一个人格", false); return; }
  if (!confirm(`确定删除人格「${name}」？文件会被删掉，相关指派也会清理。`)) return;
  try {
    const r = await api(`/api/personas/file/${encodeURIComponent(name)}`, "DELETE");
    if (r.ok) {
      toast(`人格「${name}」已删除`);
      await scanPersonas();
      loadConfig();
    } else toast(`删除失败: ${r.error}`, false);
  } catch (e) {
    toast(`删除失败: ${e}`, false);
  }
}

// ---------------- behavior sliders ----------------
function fillBehaviorSliders() {
  if (!cfg) return;
  const behs = cfg.reply.personas?.behaviors || {};
  const dflt = behs["_default"] || { at: 0.2, emoji: 0.15, sticker: 0.15, image: 0.1 };
  const mine = behaviorTarget === "_default" ? dflt : { ...dflt, ...(behs[behaviorTarget] || {}) };
  for (const k of ["at", "emoji", "sticker", "image", "quote"] as const) {
    const v = Math.round((mine[k] ?? dflt[k] ?? 0) * 100);
    $(`beh_${k}`).value = String(v);
    $(`beh_${k}_v`).textContent = `${v}%`;
  }
}

for (const k of ["at", "emoji", "sticker", "image", "quote"]) {
  $(`beh_${k}`).addEventListener("input", () => {
    $(`beh_${k}_v`).textContent = `${$(`beh_${k}`).value}%`;
  });
}
$("behavior_target").addEventListener("change", () => {
  behaviorTarget = ($( "behavior_target") as HTMLSelectElement).value;
  fillBehaviorSliders();
});
$("persona_select").addEventListener("change", () => {
  const n = currentPersonaName();
  if (n) loadPersonaFile(n);
});
$("btnPersonaScan").addEventListener("click", openDirModal);
$("btnPersonaSave").addEventListener("click", savePersona);
$("btnPersonaNew").addEventListener("click", newPersona);
$("btnPersonaDelete").addEventListener("click", deletePersona);

$("btnSave").addEventListener("click", saveConfig);
$("btnSaveTop").addEventListener("click", saveConfig);
$("btnLlmTest").addEventListener("click", testLlm);
$("btnRestart").addEventListener("click", restart);
$("btnStop").addEventListener("click", stopWxbot);
$("btnStart").addEventListener("click", startWxbot);
$("btnRefresh").addEventListener("click", () => {
  loadConfig().then(() => setDirty(false));
  refreshStatus();
  refreshLogs();
});

watchDirty();
loadConfig().then(() => { setDirty(false); scanPersonas(); });
refreshStatus();
refreshLogs();
loadStickers();
setInterval(refreshStatus, 10000);
setInterval(refreshLogs, 5000);
