/**
 * wxbot-gui server: REST API + static frontend for controlling wxbot settings.
 * - GET  /api/config          read merged config (defaults + wxbot_config.json)
 * - PUT  /api/config          write wxbot_config.json (body = full config json)
 * - GET  /api/status          wxbot process status
 * - POST /api/restart         restart wxbot (kill old python wxbot.py, start new -u)
 * - POST /api/stop            stop wxbot (kill python wxbot.py)
 * - POST /api/start           start wxbot (spawn python -u wxbot.py)
 * - GET  /api/logs?n=200      tail wxbot_out.log
 */
import express from "express";
import { exec, spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WS = path.resolve(__dirname, "..");
const CONFIG_PATH = path.join(WS, "wxbot_config.json");
const OUT_LOG = path.join(WS, "wxbot_out.log");
const ERR_LOG = path.join(WS, "wxbot_err.log");
const PY = "C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python311\\python.exe";
const WXBOT = path.join(WS, "wxbot.py");
const PORT = 7931;

const DEFAULT_CONFIG: any = {
  enabled: true,
  poll_interval_seconds: 45,
  reply: {
    private: { enabled: true, min_delay_s: 8.0, max_delay_s: 15.0, cooldown_s: 60,
      allow: [] as string[], deny: [] as string[],
      quiet_hours: { enabled: false, start: "23:30", end: "07:30", allow_contacts: [] } },
    group: { enabled: true, require_mention: true, min_delay_s: 10.0, max_delay_s: 20.0, mention_names: ["爱而不恨"],
      allow: [] as string[], deny: [] as string[] },
    unlimited_groups: ["【官方】DeepSeek交流34群"],
    unlimited_group_interval_s: 90,
    max_sentences: 4,
    sentence_delay_s: [1.0, 2.5],
    allow_contacts: [],
    deny_contacts: ["公众号", "服务号", "文件传输助手", "折叠的聊天", "微信团队"],
    max_reply_chars: 300,
    personas: {
      enabled: true,
      dir: "personas",
      default: "",
      per_group: { "【官方】DeepSeek交流34群": "wen" },
      per_contact: {},
      definitions: { "wen": "personas/wen.md" },
      behaviors: {
        "_default": { sticker: 0.15, emoji: 0.15, at: 0.2, image: 0.1, quote: 0.2 },
        "wen": { sticker: 0.3, emoji: 0.25, at: 0.4, image: 0.15, quote: 0.4 },
      },
    },
  },
  llm: {
    base_url: "https://api.kimi.com/coding/v1",
    model: "k3-256k",
    api_key_env: "KIMI_API_KEY",
    temperature: 0.9,
    max_tokens: 400,
  },
  vision: {
    enabled: true,
    base_url: "https://opencode.ai/zen/go/v1",
    model: "mimo-v2.5",
    api_key_env: "OPENCODE_API_KEY",
    max_tokens: 300,
    fallbacks: [
      { base_url: "https://fast.clawapi.store/v1", model: "gpt-5.6-sol", api_key_env: "CLAWAPI_API_KEY" },
      { base_url: "http://100.112.4.126:1234/v1", model: "xxn/qwen3.5-9b-uncensored-hauhaucs-aggressive", api_key: "lm-studio", local: true, timeout: 60, max_tokens: 500 },
    ],
  },
  images: {
    enabled: true,
    dir: path.join(WS, "wxbot_images"),
  },
  stickers: {
    enabled: true,
    catalog: path.join(WS, "wxbot_images", "stickers", "catalog.json"),
  },
  files: {
    max_chars: 1500,
  },
  state_file: path.join(WS, "wxbot_state.json"),
  own_nicknames: ["爱而不恨"],
};

function mergeConfig(user: any): any {
  const merge = (base: any, override: any): any => {
    if (!override || typeof override !== "object" || Array.isArray(override)) return override;
    const result = { ...(base || {}) };
    for (const [key, value] of Object.entries(override)) {
      result[key] = value && typeof value === "object" && !Array.isArray(value)
        ? merge(result[key], value)
        : value;
    }
    return result;
  };
  return merge(JSON.parse(JSON.stringify(DEFAULT_CONFIG)), user || {});
}

function atomicWriteJson(file: string, value: any): void {
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(value, null, 1), "utf-8");
  fs.renameSync(tmp, file);
}

function readConfig(): any {
  try {
    if (fs.existsSync(CONFIG_PATH)) {
      return mergeConfig(JSON.parse(fs.readFileSync(CONFIG_PATH, "utf-8")));
    }
  } catch (e) {
    console.error("config read error:", e);
  }
  return mergeConfig(null);
}

function runPS(cmd: string): Promise<string> {
  return new Promise((resolve) => {
    exec(`powershell -NoProfile -Command "${cmd.replace(/"/g, '\\"')}"`, { timeout: 30000 }, (err, stdout, stderr) => {
      if (err) {
        console.error("[ps]", cmd.slice(0, 120), "->", stderr || err.message);
      }
      resolve(err ? `ERR: ${stderr || err.message}` : stdout.trim());
    });
  });
}

const escapedWxbot = WXBOT.replace(/'/g, "''");
const PS_MATCH = `Where-Object { $_.CommandLine -like '*${escapedWxbot}*' }`;
const PS_STATUS =
  `Get-CimInstance Win32_Process -Filter "Name like 'python%'" | ${PS_MATCH} | Select-Object -ExpandProperty ProcessId`;
const PS_KILL =
  `Get-CimInstance Win32_Process -Filter "Name like 'python%'" | ${PS_MATCH} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }`;

async function findPids(): Promise<number[]> {
  const out = await runPS(PS_STATUS);
  return out
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter((s) => /^\d+$/.test(s))
    .map(Number);
}

function spawnWxbot(): number {
  const out = fs.openSync(OUT_LOG, "a");
  const err = fs.openSync(ERR_LOG, "a");
  const child = spawn(PY, ["-u", WXBOT], {
    detached: true,
    stdio: ["ignore", out, err],
    windowsHide: true,
  });
  if (!child.pid) throw new Error("wxbot 进程启动失败：未获得 PID");
  child.unref();
  return child.pid;
}

const app = express();
app.use(express.json({ limit: "1mb" }));
app.use(express.static(path.join(__dirname, "public")));

app.get("/api/config", (_req, res) => {
  res.json(readConfig());
});

app.put("/api/config", (req, res) => {
  try {
    const body = req.body;
    if (!body || typeof body !== "object") {
      res.status(400).json({ ok: false, error: "bad body" });
      return;
    }
    atomicWriteJson(CONFIG_PATH, body);
    res.json({ ok: true });
  } catch (e: any) {
    res.status(500).json({ ok: false, error: String(e) });
  }
});

app.get("/api/status", async (_req, res) => {
  const pids = await findPids();
  res.json({ running: pids.length > 0, pids });
});

app.post("/api/stop", async (_req, res) => {
  await runPS(PS_KILL);
  await new Promise((r) => setTimeout(r, 800));
  const pids = await findPids();
  res.json({ ok: pids.length === 0, stillRunning: pids });
});

app.post("/api/start", async (_req, res) => {
  const existing = await findPids();
  if (existing.length > 0) {
    res.status(409).json({ ok: false, error: `已在运行 pid ${existing.join(",")}` });
    return;
  }
  const pid = spawnWxbot();
  await new Promise((r) => setTimeout(r, 1500));
  res.json({ ok: true, pid });
});

app.post("/api/restart", async (_req, res) => {
  await runPS(PS_KILL);
  await new Promise((r) => setTimeout(r, 800));
  const pid = spawnWxbot();
  await new Promise((r) => setTimeout(r, 1500));
  res.json({ ok: true, pid });
});

app.get("/api/logs", (req, res) => {
  const n = Math.min(parseInt(String(req.query.n || "200"), 10) || 200, 1000);
  let text = "";
  try {
    const chunks: string[] = [];
    if (fs.existsSync(OUT_LOG)) chunks.push(fs.readFileSync(OUT_LOG, "utf-8"));
    if (fs.existsSync(ERR_LOG)) {
      const stderr = fs.readFileSync(ERR_LOG, "utf-8").trim();
      if (stderr) chunks.push(`[stderr]\n${stderr}`);
    }
    text = chunks.join("\n").split(/\r?\n/).slice(-n).join("\n");
  } catch (e) {
    text = `log read error: ${e}`;
  }
  res.type("text/plain; charset=utf-8").send(text);
});

// ---------------- custom stickers (爱心收藏表情包) ----------------
const STICKERS_DIR = path.join(WS, "wxbot_images", "stickers");
const STICKERS_CATALOG = path.join(STICKERS_DIR, "catalog.json");
const STICKERS_REFRESH_LOG = path.join(WS, "wxbot_stickers.log");
let stickerRefreshPid: number | null = null;

function readStickerCatalog(): any {
  try {
    if (fs.existsSync(STICKERS_CATALOG)) {
      return JSON.parse(fs.readFileSync(STICKERS_CATALOG, "utf-8"));
    }
  } catch (e) {
    console.error("sticker catalog read error:", e);
  }
  return null;
}

app.get("/api/stickers", (_req, res) => {
  const cat = readStickerCatalog();
  const cfg = readConfig();
  res.json({
    enabled: !!cfg.stickers?.enabled,
    refreshing: stickerRefreshPid !== null,
    catalog: cat,
  });
});

app.get("/api/stickers/img/:file", (req, res) => {
  const f = String(req.params.file || "");
  if (!/^\d{2}\.png$/.test(f)) {
    res.status(400).json({ ok: false, error: "bad file" });
    return;
  }
  const p = path.join(STICKERS_DIR, f);
  if (!fs.existsSync(p)) {
    res.status(404).end();
    return;
  }
  res.type("image/png").send(fs.readFileSync(p));
});

app.post("/api/stickers/refresh", (_req, res) => {
  if (stickerRefreshPid !== null) {
    res.status(409).json({ ok: false, error: "refresh already running" });
    return;
  }
  const out = fs.openSync(STICKERS_REFRESH_LOG, "a");
  const child = spawn(PY, ["-X", "utf8", path.join(WS, "wxbot_stickers.py"), "--refresh"], {
    detached: true,
    stdio: ["ignore", out, out],
    windowsHide: true,
  });
  stickerRefreshPid = child.pid ?? null;
  child.on("exit", () => { stickerRefreshPid = null; });
  child.unref();
  res.json({ ok: true, pid: child.pid });
});

app.get("/api/stickers/refresh_log", (_req, res) => {
  let text = "";
  try {
    if (fs.existsSync(STICKERS_REFRESH_LOG)) {
      const lines = fs.readFileSync(STICKERS_REFRESH_LOG, "utf-8").split(/\r?\n/);
      text = lines.slice(-60).join("\n");
    }
  } catch { /* ignore */ }
  res.type("text/plain; charset=utf-8").send(text);
});

// ---------------- personas (人格管理) ----------------
function personaDir(): string {
  const cfg = readConfig();
  const d = cfg.reply?.personas?.dir || "personas";
  return path.isAbsolute(d) ? d : path.join(WS, d);
}

function safePersonaName(raw: string): string | null {
  const n = String(raw || "").replace(/\.md$/i, "");
  return /^[\w\u4e00-\u9fa5\-]{1,40}$/.test(n) ? n : null;
}

// ---------------- folder browser（人格目录选择器） ----------------
app.get("/api/fs/browse", (req, res) => {
  let p = String(req.query.path || "");
  try {
    if (!p) p = WS;
    const st = fs.statSync(p);
    if (!st.isDirectory()) p = path.dirname(p);
    const parent = path.dirname(p);
    const dirs: { name: string; path: string }[] = [];
    for (const f of fs.readdirSync(p)) {
      try {
        const fp = path.join(p, f);
        if (fs.statSync(fp).isDirectory()) dirs.push({ name: f, path: fp });
      } catch { /* skip */ }
    }
    dirs.sort((a, b) => a.name.localeCompare(b.name, "zh"));
    res.json({ path: p, parent, dirs });
  } catch (e: any) {
    res.status(400).json({ ok: false, error: String(e?.message || e) });
  }
});

app.get("/api/personas", (_req, res) => {
  const dir = personaDir();
  const files: any[] = [];
  try {
    if (fs.existsSync(dir)) {
      for (const f of fs.readdirSync(dir)) {
        if (!f.toLowerCase().endsWith(".md")) continue;
        const st = fs.statSync(path.join(dir, f));
        files.push({ name: f.replace(/\.md$/i, ""), file: f, size: st.size, mtime: st.mtimeMs });
      }
    }
  } catch (e) {
    console.error("persona scan error:", e);
  }
  files.sort((a, b) => a.name.localeCompare(b.name, "zh"));
  const cfg = readConfig();
  res.json({ dir, files, personas: cfg.reply?.personas || {} });
});

app.get("/api/personas/file/:name", (req, res) => {
  const n = safePersonaName(req.params.name);
  if (!n) { res.status(400).json({ ok: false, error: "bad name" }); return; }
  const p = path.join(personaDir(), `${n}.md`);
  if (!p.startsWith(personaDir()) || !fs.existsSync(p)) {
    res.status(404).json({ ok: false, error: "not found" });
    return;
  }
  res.json({ ok: true, name: n, content: fs.readFileSync(p, "utf-8") });
});

app.put("/api/personas/file/:name", (req, res) => {
  const n = safePersonaName(req.params.name);
  if (!n) { res.status(400).json({ ok: false, error: "bad name" }); return; }
  const content = String(req.body?.content ?? "");
  if (!content.trim()) { res.status(400).json({ ok: false, error: "empty content" }); return; }
  const dir = personaDir();
  fs.mkdirSync(dir, { recursive: true });
  const p = path.join(dir, `${n}.md`);
  if (!p.startsWith(dir)) { res.status(400).json({ ok: false, error: "bad path" }); return; }
  fs.writeFileSync(p, content, "utf-8");
  res.json({ ok: true, name: n, size: Buffer.byteLength(content, "utf-8") });
});

app.delete("/api/personas/file/:name", (req, res) => {
  const n = safePersonaName(req.params.name);
  if (!n) { res.status(400).json({ ok: false, error: "bad name" }); return; }
  const p = path.join(personaDir(), `${n}.md`);
  if (!p.startsWith(personaDir()) || !fs.existsSync(p)) {
    res.status(404).json({ ok: false, error: "not found" });
    return;
  }
  fs.unlinkSync(p);
  // 顺手清理指派引用（避免悬空人格名）
  try {
    const cfg = readConfig();
    const ps = cfg.reply?.personas || {};
    for (const k of Object.keys(ps.per_group || {})) if (ps.per_group[k] === n) delete ps.per_group[k];
    for (const k of Object.keys(ps.per_contact || {})) if (ps.per_contact[k] === n) delete ps.per_contact[k];
    if (ps.default === n) ps.default = "";
    if (ps.behaviors) delete ps.behaviors[n];
    if (ps.definitions) delete ps.definitions[n];
    fs.writeFileSync(CONFIG_PATH, JSON.stringify(cfg, null, 1), "utf-8");
  } catch (e) {
    console.error("persona cleanup error:", e);
  }
  res.json({ ok: true });
});

// ---------------- llm connectivity test ----------------
function resolveApiKey(envName: string): string {
  if (envName && process.env[envName]) return process.env[envName]!;
  try {
    const oc = path.resolve(WS, "..", "openclaw.json");
    const data = JSON.parse(fs.readFileSync(oc, "utf-8"));
    return (data?.env?.[envName] as string) || "";
  } catch {
    return "";
  }
}

app.post("/api/llm/test", async (req, res) => {
  const { base_url, model, api_key_env } = req.body || {};
  if (!base_url || !model) {
    res.status(400).json({ ok: false, error: "base_url 和 model 必填" });
    return;
  }
  const key = resolveApiKey(String(api_key_env || ""));
  if (!key) {
    res.json({ ok: false, error: `找不到 API key：环境变量 ${api_key_env} 未设置，openclaw.json 的 env 段里也没有` });
    return;
  }
  const url = String(base_url).replace(/\/+$/, "") + "/chat/completions";
  const t0 = Date.now();
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 20000);
  try {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${key}` },
      body: JSON.stringify({
        model,
        messages: [{ role: "user", content: "ping，只回复一个字" }],
        max_tokens: 32,
      }),
      signal: ctrl.signal,
    });
    const ms = Date.now() - t0;
    const text = await r.text();
    if (!r.ok) {
      res.json({ ok: false, latency_ms: ms, error: `HTTP ${r.status}: ${text.slice(0, 200)}` });
      return;
    }
    let snippet = "";
    try {
      snippet = String(JSON.parse(text)?.choices?.[0]?.message?.content ?? "").slice(0, 30);
    } catch { /* ignore */ }
    res.json({ ok: true, latency_ms: ms, reply: snippet });
  } catch (e: any) {
    const msg = e?.name === "AbortError" ? "超时（20s 无响应）" : String(e?.message || e);
    res.json({ ok: false, latency_ms: Date.now() - t0, error: msg.slice(0, 200) });
  } finally {
    clearTimeout(timer);
  }
});

app.listen(PORT, "127.0.0.1", () => {
  console.log(`wxbot-gui listening on http://127.0.0.1:${PORT}`);
});
