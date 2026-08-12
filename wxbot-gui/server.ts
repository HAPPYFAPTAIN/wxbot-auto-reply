/**
 * wxbot-gui server: REST API + static frontend for controlling wxbot settings.
 * - GET  /api/config          read merged config (defaults + wxbot_config.json)
 * - PUT  /api/config          write wxbot_config.json (body = full config json)
 * - GET  /api/status          wxbot process status
 * - POST /api/restart         restart wxbot (kill old python wxbot.py, start new -u)
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
    private: { enabled: true, min_delay_s: 8.0, max_delay_s: 15.0 },
    group: { enabled: true, require_mention: true, min_delay_s: 10.0, max_delay_s: 20.0, mention_names: ["爱而不恨"] },
    unlimited_groups: ["【官方】DeepSeek交流34群"],
    unlimited_group_interval_s: 90,
    max_sentences: 4,
    sentence_delay_s: [1.0, 2.5],
    allow_contacts: [],
    deny_contacts: ["公众号", "服务号", "文件传输助手", "折叠的聊天", "微信团队"],
    max_reply_chars: 300,
    personas: {
      enabled: true,
      default: "",
      per_group: { "【官方】DeepSeek交流34群": "wen" },
      definitions: { "wen": "personas/wen.md" },
    },
  },
  llm: {
    base_url: "https://api.kimi.com/coding/v1",
    model: "k3-256k",
    api_key_env: "KIMI_API_KEY",
    temperature: 0.9,
    max_tokens: 400,
  },
  state_file: path.join(WS, "wxbot_state.json"),
  own_nicknames: ["爱而不恨"],
};

function mergeConfig(user: any): any {
  const cfg: any = JSON.parse(JSON.stringify(DEFAULT_CONFIG));
  if (!user) return cfg;
  for (const [k, v] of Object.entries(user)) {
    if (v && typeof v === "object" && !Array.isArray(v) && typeof cfg[k] === "object" && !Array.isArray(cfg[k])) {
      cfg[k] = { ...cfg[k], ...(v as any) };
    } else {
      cfg[k] = v;
    }
  }
  return cfg;
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
      resolve(err ? `ERR: ${stderr || err.message}` : stdout.trim());
    });
  });
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
    fs.writeFileSync(CONFIG_PATH, JSON.stringify(body, null, 1), "utf-8");
    res.json({ ok: true });
  } catch (e: any) {
    res.status(500).json({ ok: false, error: String(e) });
  }
});

app.get("/api/status", async (_req, res) => {
  const out = await runPS(
    `Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -like '*wxbot.py*' } | Select-Object -ExpandProperty ProcessId`
  );
  const pids = out
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter((s) => /^\d+$/.test(s));
  res.json({ running: pids.length > 0, pids });
});

app.post("/api/restart", async (_req, res) => {
  await runPS(
    `Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -like '*wxbot.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }`
  );
  await new Promise((r) => setTimeout(r, 800));
  const out = fs.openSync(OUT_LOG, "a");
  const err = fs.openSync(ERR_LOG, "a");
  const child = spawn(PY, ["-u", WXBOT], {
    detached: true,
    stdio: ["ignore", out, err],
    windowsHide: true,
  });
  child.unref();
  await new Promise((r) => setTimeout(r, 1500));
  res.json({ ok: true, pid: child.pid });
});

app.get("/api/logs", (req, res) => {
  const n = Math.min(parseInt(String(req.query.n || "200"), 10) || 200, 1000);
  let text = "";
  try {
    if (fs.existsSync(OUT_LOG)) {
      const lines = fs.readFileSync(OUT_LOG, "utf-8").split(/\r?\n/);
      text = lines.slice(-n).join("\n");
    }
  } catch (e) {
    text = `log read error: ${e}`;
  }
  res.type("text/plain; charset=utf-8").send(text);
});

app.listen(PORT, () => {
  console.log(`wxbot-gui listening on http://127.0.0.1:${PORT}`);
});
