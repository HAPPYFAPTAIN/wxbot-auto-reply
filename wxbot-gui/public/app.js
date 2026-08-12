"use strict";
(() => {
  // public/app.ts
  var $ = (id) => document.getElementById(id);
  function initTheme() {
    const saved = localStorage.getItem("wxbot-theme");
    const theme = saved || (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    document.documentElement.setAttribute("data-theme", theme);
    $("themeToggle").textContent = theme === "dark" ? "\u2600\uFE0F" : "\u{1F319}";
  }
  $("themeToggle").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", cur);
    localStorage.setItem("wxbot-theme", cur);
    $("themeToggle").textContent = cur === "dark" ? "\u2600\uFE0F" : "\u{1F319}";
  });
  initTheme();
  var cfg = null;
  function toast(msg, ok = true) {
    const t = $("toast");
    t.textContent = msg;
    t.style.background = ok ? "#1e4d2c" : "#4d1e1e";
    t.style.color = ok ? "#53d27a" : "#e05555";
    t.style.display = "block";
    setTimeout(() => t.style.display = "none", 2600);
  }
  async function api(path, method = "GET", body) {
    const res = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : void 0,
      body: body ? JSON.stringify(body) : void 0
    });
    if (!res.ok) throw new Error(`${method} ${path} -> ${res.status}`);
    const ct = res.headers.get("content-type") || "";
    return ct.includes("json") ? res.json() : res.text();
  }
  function fill(c) {
    cfg = c;
    $("enabled").checked = !!c.enabled;
    $("poll_interval_seconds").value = String(c.poll_interval_seconds ?? 45);
    $("priv_enabled").checked = !!c.reply.private.enabled;
    $("priv_min").value = String(c.reply.private.min_delay_s);
    $("priv_max").value = String(c.reply.private.max_delay_s);
    $("priv_cooldown").value = String(c.reply.private.cooldown_s ?? 0);
    const qh = c.reply.private.quiet_hours || { enabled: false, start: "23:30", end: "07:30", allow_contacts: [] };
    $("qh_enabled").checked = !!qh.enabled;
    $("qh_start").value = qh.start || "23:30";
    $("qh_end").value = qh.end || "07:30";
    $("qh_allow").value = (qh.allow_contacts || []).join("\n");
    const ps = c.reply.personas || { enabled: true };
    $("persona_dir").value = ps.dir || "personas";
    $("persona_default").value = ps.default || "";
    $("persona_per_group").value = Object.entries(ps.per_group || {}).map(([k, v]) => `${k}:${v}`).join("\n");
    $("persona_per_contact").value = Object.entries(ps.per_contact || {}).map(([k, v]) => `${k}:${v}`).join("\n");
    $("priv_allow").value = (c.reply.private.allow || []).join("\n");
    $("priv_deny").value = (c.reply.private.deny || []).join("\n");
    $("grp_allow").value = (c.reply.group.allow || []).join("\n");
    $("grp_deny").value = (c.reply.group.deny || []).join("\n");
    const cm = c.reply.context_messages ?? 8;
    $("ctx_messages").value = String(typeof cm === "object" ? cm.default ?? 8 : cm);
    $("grp_min").value = String(c.reply.group.min_delay_s);
    $("grp_max").value = String(c.reply.group.max_delay_s);
    $("sent_min").value = String(c.reply.sentence_delay_s?.[0] ?? 1);
    $("sent_max").value = String(c.reply.sentence_delay_s?.[1] ?? 2.5);
    $("max_sentences").value = String(c.reply.max_sentences ?? 4);
    $("max_reply_chars").value = String(c.reply.max_reply_chars ?? 300);
    $("unlim_interval").value = String(c.reply.unlimited_group_interval_s ?? 90);
    $("unlimited_groups").value = (c.reply.unlimited_groups || []).join("\n");
    $("deny_contacts").value = (c.reply.deny_contacts || []).join("\n");
    $("llm_base_url").value = c.llm.base_url;
    $("llm_model").value = c.llm.model;
    $("llm_key_env").value = c.llm.api_key_env;
    $("llm_temp").value = String(c.llm.temperature);
    $("llm_max_tokens").value = String(c.llm.max_tokens);
    $("ctx_window").value = String(c.llm.context_window ?? 32e3);
    const cc = c.context?.compression || {};
    $("cc_enabled").checked = !!cc.enabled;
    $("cc_mode").value = cc.mode || "percent";
    $("cc_percent").value = String(cc.percent ?? 60);
    $("cc_tokens").value = String(cc.tokens ?? 4e3);
    $("cc_keep").value = String(cc.keep_recent ?? 4);
    $("cc_trim").value = String(cc.trim_chars ?? 60);
    const mem = c.memory || {};
    $("mem_enabled").checked = mem.enabled !== false;
    $("mem_every").value = String(mem.every_n_replies ?? 5);
    $("stickers_enabled").checked = !!c.stickers?.enabled;
  }
  function collect() {
    if (!cfg) throw new Error("config not loaded");
    const c = JSON.parse(JSON.stringify(cfg));
    c.enabled = $("enabled").checked;
    c.poll_interval_seconds = Number($("poll_interval_seconds").value) || 45;
    c.reply.private.enabled = $("priv_enabled").checked;
    c.reply.private.min_delay_s = Number($("priv_min").value);
    c.reply.private.max_delay_s = Number($("priv_max").value);
    c.reply.private.cooldown_s = Number($("priv_cooldown").value) || 0;
    c.reply.private.quiet_hours = {
      enabled: $("qh_enabled").checked,
      start: $("qh_start").value.trim() || "23:30",
      end: $("qh_end").value.trim() || "07:30",
      allow_contacts: $("qh_allow").value.split("\n").map((s) => s.trim()).filter(Boolean)
    };
    const parseMap = (v) => {
      const out = {};
      for (const line of v.split("\n")) {
        const m = line.match(/^(.+?)[:：](.+)$/);
        if (m) out[m[1].trim()] = m[2].trim();
      }
      return out;
    };
    if (!c.reply.personas) c.reply.personas = { enabled: true };
    c.reply.personas.dir = $("persona_dir").value.trim() || "personas";
    c.reply.personas.default = $("persona_default").value.trim();
    c.reply.personas.per_group = parseMap($("persona_per_group").value);
    c.reply.personas.per_contact = parseMap($("persona_per_contact").value);
    if (!c.reply.personas.behaviors) c.reply.personas.behaviors = {};
    c.reply.personas.behaviors[behaviorTarget] = {
      at: Number($("beh_at").value) / 100,
      emoji: Number($("beh_emoji").value) / 100,
      sticker: Number($("beh_sticker").value) / 100,
      image: Number($("beh_image").value) / 100,
      quote: Number($("beh_quote").value) / 100
    };
    const toList = (id) => $(id).value.split("\n").map((s) => s.trim()).filter(Boolean);
    c.reply.private.allow = toList("priv_allow");
    c.reply.private.deny = toList("priv_deny");
    c.reply.group.allow = toList("grp_allow");
    c.reply.group.deny = toList("grp_deny");
    const cmv = Math.max(1, Math.min(1e3, Number($("ctx_messages").value) || 8));
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
    c.reply.unlimited_groups = $("unlimited_groups").value.split("\n").map((s) => s.trim()).filter(Boolean);
    c.reply.deny_contacts = $("deny_contacts").value.split("\n").map((s) => s.trim()).filter(Boolean);
    c.llm.base_url = $("llm_base_url").value.trim();
    c.llm.model = $("llm_model").value.trim();
    c.llm.api_key_env = $("llm_key_env").value.trim();
    c.llm.temperature = Number($("llm_temp").value);
    c.llm.max_tokens = Number($("llm_max_tokens").value);
    c.llm.context_window = Math.max(1e3, Number($("ctx_window").value) || 32e3);
    c.context = {
      compression: {
        enabled: $("cc_enabled").checked,
        mode: $("cc_mode").value,
        percent: Math.max(5, Math.min(95, Number($("cc_percent").value) || 60)),
        tokens: Math.max(100, Number($("cc_tokens").value) || 4e3),
        keep_recent: Math.max(1, Math.min(50, Number($("cc_keep").value) || 4)),
        trim_chars: Math.max(10, Math.min(500, Number($("cc_trim").value) || 60))
      }
    };
    c.memory = {
      ...c.memory || {},
      enabled: $("mem_enabled").checked,
      every_n_replies: Math.max(1, Math.min(100, Number($("mem_every").value) || 5))
    };
    c.stickers = { ...c.stickers || {}, enabled: $("stickers_enabled").checked };
    return c;
  }
  async function loadConfig() {
    try {
      const c = await api("/api/config");
      fill(c);
    } catch (e) {
      toast(`\u914D\u7F6E\u52A0\u8F7D\u5931\u8D25: ${e}`, false);
    }
  }
  async function saveConfig() {
    try {
      const body = collect();
      const r = await api("/api/config", "PUT", body);
      if (r.ok) {
        toast("\u5DF2\u4FDD\u5B58 \u2705\uFF08\u91CD\u542F wxbot \u540E\u751F\u6548\uFF09");
        setDirty(false);
      } else toast(`\u4FDD\u5B58\u5931\u8D25: ${r.error}`, false);
    } catch (e) {
      toast(`\u4FDD\u5B58\u5931\u8D25: ${e}`, false);
    }
  }
  var paramsDirty = false;
  function setDirty(v) {
    paramsDirty = v;
    $("btnSaveTop").disabled = !v;
  }
  function watchDirty() {
    const skip = /* @__PURE__ */ new Set(["persona_content", "persona_select", "logs"]);
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
        b.textContent = `\u8FD0\u884C\u4E2D pid ${s.pids.join(",")}`;
        b.className = "badge on";
      } else {
        b.textContent = "\u672A\u8FD0\u884C";
        b.className = "badge off";
      }
    } catch {
      $("procBadge").textContent = "\u72B6\u6001\u672A\u77E5";
    }
  }
  async function restart() {
    if (!confirm("\u786E\u5B9A\u91CD\u542F wxbot\uFF1F\uFF08\u4F1A\u5148\u6740\u6389\u65E7\u8FDB\u7A0B\u518D\u542F\u52A8\uFF09")) return;
    try {
      const r = await api("/api/restart", "POST");
      toast(r.ok ? `\u5DF2\u91CD\u542F pid ${r.pid}` : "\u91CD\u542F\u5931\u8D25", r.ok);
      setTimeout(refreshStatus, 1500);
    } catch (e) {
      toast(`\u91CD\u542F\u5931\u8D25: ${e}`, false);
    }
  }
  async function stopWxbot() {
    if (!confirm("\u786E\u5B9A\u505C\u6B62 wxbot\uFF1F\uFF08\u4F1A\u6740\u6389\u8FD0\u884C\u4E2D\u7684\u8FDB\u7A0B\uFF09")) return;
    try {
      const r = await api("/api/stop", "POST");
      toast(r.ok ? "\u5DF2\u505C\u6B62 \u2705" : `\u4ECD\u6709\u8FDB\u7A0B\u6B8B\u7559: ${(r.stillRunning || []).join(",")}`, r.ok);
      refreshStatus();
    } catch (e) {
      toast(`\u505C\u6B62\u5931\u8D25: ${e}`, false);
    }
  }
  async function startWxbot() {
    try {
      const r = await api("/api/start", "POST");
      toast(r.ok ? `\u5DF2\u542F\u52A8 pid ${r.pid}` : `\u542F\u52A8\u5931\u8D25: ${r.error}`, r.ok);
      setTimeout(refreshStatus, 1500);
    } catch (e) {
      toast(`\u542F\u52A8\u5931\u8D25: ${e}`, false);
    }
  }
  async function refreshLogs() {
    try {
      const text = await api("/api/logs?n=200");
      const el = $("logs");
      el.textContent = text || "\uFF08\u6682\u65E0\u65E5\u5FD7\uFF09";
      el.scrollTop = el.scrollHeight;
    } catch {
    }
  }
  for (const id of ["llm_base_url", "llm_model", "llm_key_env"]) {
    $(id).addEventListener("input", () => {
      $("llmLight").className = "light";
      $("llmTestResult").textContent = "\u53C2\u6570\u5DF2\u6539\uFF0C\u5EFA\u8BAE\u91CD\u65B0\u6D4B\u8BD5";
    });
  }
  async function testLlm() {
    const light = $("llmLight");
    const out = $("llmTestResult");
    light.className = "light busy";
    out.textContent = "\u6D4B\u8BD5\u4E2D\u2026";
    $("btnLlmTest").disabled = true;
    try {
      const r = await api("/api/llm/test", "POST", {
        base_url: $("llm_base_url").value.trim(),
        model: $("llm_model").value.trim(),
        api_key_env: $("llm_key_env").value.trim()
      });
      if (r.ok) {
        light.className = "light on";
        out.textContent = `\u2705 \u901A\u8DEF\u6B63\u5E38 \xB7 ${r.latency_ms}ms${r.reply ? ` \xB7 \u6A21\u578B\u56DE\u300C${r.reply}\u300D` : ""}`;
      } else {
        light.className = "light off";
        out.textContent = `\u274C ${r.error || "\u5931\u8D25"}${r.latency_ms != null ? ` \xB7 ${r.latency_ms}ms` : ""}`;
      }
    } catch (e) {
      light.className = "light off";
      out.textContent = `\u274C \u6D4B\u8BD5\u63A5\u53E3\u62A5\u9519: ${e}`;
    } finally {
      $("btnLlmTest").disabled = false;
    }
  }
  var stickerRefreshing = false;
  async function loadStickers() {
    const grid = $("stickerGrid");
    const status = $("stickersStatus");
    try {
      const r = await api("/api/stickers");
      stickerRefreshing = !!r.refreshing;
      const cat = r.catalog;
      if (!cat || !cat.stickers || !cat.stickers.length) {
        grid.innerHTML = '<div class="hint">\uFF08\u8FD8\u6CA1\u6709\u8D34\u7EB8\u76EE\u5F55\uFF0C\u70B9\u300C\u91CD\u65B0\u626B\u63CF\u300D\u4ECE\u5FAE\u4FE1\u91CC\u6293\u53D6\u5EFA\u6863\uFF09</div>';
        status.textContent = "";
        return;
      }
      status.textContent = `\u5171 ${cat.count ?? cat.stickers.length} \u5F20\uFF0C\u66F4\u65B0\u4E8E ${cat.updated ?? "\u672A\u77E5"}${r.refreshing ? "\uFF08\u6B63\u5728\u91CD\u65B0\u626B\u63CF\u2026\uFF09" : ""}`;
      grid.innerHTML = cat.stickers.map((s) => {
        const img = s.file ? `/api/stickers/img/${s.file.split("/").pop()}` : "";
        const kw = (s.keywords || []).join(" / ");
        return `<div class="sticker-card" title="${s.desc || ""}">
          <div class="idx">#${s.index}</div>
          ${img ? `<img src="${img}" alt="${s.label}">` : ""}
          <div class="lbl">${s.label || ""}</div>
          <div class="kw">${kw}</div>
        </div>`;
      }).join("");
    } catch (e) {
      status.textContent = `\u8D34\u7EB8\u76EE\u5F55\u52A0\u8F7D\u5931\u8D25: ${e}`;
    }
  }
  async function refreshStickers() {
    if (!confirm("\u91CD\u65B0\u626B\u63CF\u4F1A\u64CD\u4F5C\u5FAE\u4FE1\u6253\u5F00\u8868\u60C5\u9762\u677F\u622A\u56FE + vision \u5EFA\u6863\uFF0C\u7EA6 1 \u5206\u949F\u3002\u671F\u95F4\u522B\u52A8\u5FAE\u4FE1\u7A97\u53E3\uFF0C\u7EE7\u7EED\uFF1F")) return;
    try {
      const r = await api("/api/stickers/refresh", "POST");
      if (!r.ok) {
        toast(`\u626B\u63CF\u542F\u52A8\u5931\u8D25: ${r.error}`, false);
        return;
      }
      toast("\u5DF2\u5F00\u59CB\u626B\u63CF\uFF0C\u7A0D\u5019\u2026");
      stickerRefreshing = true;
      let tries = 0;
      const timer = setInterval(async () => {
        tries++;
        await loadStickers();
        if (!stickerRefreshing || tries > 40) {
          clearInterval(timer);
          stickerRefreshing = false;
          toast("\u8D34\u7EB8\u76EE\u5F55\u5DF2\u66F4\u65B0 \u2705");
          loadStickers();
        }
      }, 3e3);
    } catch (e) {
      toast(`\u626B\u63CF\u5931\u8D25: ${e}`, false);
    }
  }
  $("btnStickersReload").addEventListener("click", loadStickers);
  $("btnStickersRefresh").addEventListener("click", refreshStickers);
  var behaviorTarget = "_default";
  function currentPersonaName() {
    return $("persona_select").value || "";
  }
  var dirModalPath = "";
  async function openDirModal() {
    dirModalPath = $("persona_dir").value.trim() || "";
    $("dirModal").style.display = "flex";
    await browseDir();
  }
  async function browseDir() {
    try {
      const r = await api(`/api/fs/browse?path=${encodeURIComponent(dirModalPath)}`);
      dirModalPath = r.path;
      $("dirModalPath").textContent = r.path;
      const list = $("dirList");
      if (!r.dirs.length) {
        list.innerHTML = '<div class="hint" style="padding:20px">\uFF08\u6B64\u6587\u4EF6\u5939\u4E0B\u6CA1\u6709\u5B50\u6587\u4EF6\u5939\uFF09</div>';
      } else {
        list.innerHTML = r.dirs.map((d) => `<div style="display:flex; align-items:center; gap:8px; padding:9px 12px; border-radius:8px; cursor:pointer;"
             class="dir-item" data-path="${d.path.replace(/"/g, "&quot;")}">
             \u{1F4C1} <span style="flex:1">${d.name}</span>
           </div>`).join("");
        list.querySelectorAll(".dir-item").forEach(
          (el) => el.addEventListener("click", async () => {
            dirModalPath = el.dataset.path || "";
            await browseDir();
          })
        );
      }
    } catch (e) {
      toast(`\u76EE\u5F55\u8BFB\u53D6\u5931\u8D25: ${e}`, false);
    }
  }
  $("dirModalUp").addEventListener("click", async () => {
    try {
      const r = await api(`/api/fs/browse?path=${encodeURIComponent(dirModalPath)}`);
      dirModalPath = r.parent;
      await browseDir();
    } catch {
    }
  });
  $("dirModalCancel").addEventListener("click", () => {
    $("dirModal").style.display = "none";
  });
  $("dirModalPick").addEventListener("click", async () => {
    $("persona_dir").value = dirModalPath;
    $("dirModal").style.display = "none";
    await scanPersonas();
  });
  async function scanPersonas() {
    try {
      if (cfg) {
        await api("/api/config", "PUT", collect());
        setDirty(false);
      }
    } catch {
    }
    const sel = $("persona_select");
    const behSel = $("behavior_target");
    const prev = sel.value;
    try {
      const r = await api("/api/personas");
      const files = r.files || [];
      sel.innerHTML = files.length ? files.map((f) => `<option value="${f.name}">${f.name}</option>`).join("") : '<option value="">\uFF08\u76EE\u5F55\u91CC\u6CA1\u6709 .md \u4EBA\u683C\u6587\u4EF6\uFF09</option>';
      if (prev && files.some((f) => f.name === prev)) sel.value = prev;
      behSel.innerHTML = '<option value="_default">_default\uFF08\u6240\u6709\u4EBA\u683C\u9ED8\u8BA4\uFF09</option>' + files.map((f) => `<option value="${f.name}">${f.name}</option>`).join("");
      if ([...behSel.options].some((o) => o.value === behaviorTarget)) behSel.value = behaviorTarget;
      behaviorTarget = behSel.value;
      fillBehaviorSliders();
      if (currentPersonaName()) await loadPersonaFile(currentPersonaName());
      else $("persona_content").value = "";
    } catch (e) {
      toast(`\u4EBA\u683C\u76EE\u5F55\u8BFB\u53D6\u5931\u8D25: ${e}`, false);
    }
  }
  async function loadPersonaFile(name) {
    try {
      const r = await api(`/api/personas/file/${encodeURIComponent(name)}`);
      $("persona_content").value = r.content || "";
    } catch (e) {
      $("persona_content").value = "";
      toast(`\u4EBA\u683C\u6587\u4EF6\u8BFB\u53D6\u5931\u8D25: ${e}`, false);
    }
  }
  async function savePersona() {
    const name = currentPersonaName();
    if (!name) {
      toast("\u5148\u9009\u62E9\u6216\u65B0\u5EFA\u4E00\u4E2A\u4EBA\u683C", false);
      return;
    }
    const content = $("persona_content").value;
    try {
      const r = await api(`/api/personas/file/${encodeURIComponent(name)}`, "PUT", { content });
      if (r.ok) toast(`\u4EBA\u683C\u300C${name}\u300D\u5DF2\u4FDD\u5B58 \u2705\uFF08\u7ACB\u5373\u751F\u6548\uFF09`);
      else toast(`\u4FDD\u5B58\u5931\u8D25: ${r.error}`, false);
    } catch (e) {
      toast(`\u4FDD\u5B58\u5931\u8D25: ${e}`, false);
    }
  }
  async function newPersona() {
    const name = prompt("\u65B0\u4EBA\u683C\u7684\u540D\u5B57\uFF08\u6587\u4EF6\u540D = \u540D\u5B57.md\uFF0C\u4E2D\u6587\u82F1\u6587\u90FD\u884C\uFF09:");
    if (!name || !name.trim()) return;
    const n = name.trim();
    const template = `# ${n} \u4EBA\u683C

## \u8BF4\u8BDD\u98CE\u683C
- \uFF08\u8FD9\u91CC\u5199 TA \u600E\u4E48\u8BF4\u8BDD\uFF1A\u53E3\u5934\u7985\u3001\u53E5\u5F0F\u3001\u8BED\u6C14\uFF09

## \u884C\u4E3A\u4E60\u60EF
- \uFF08\u4EC0\u4E48\u65F6\u5019@\u4EBA\u3001\u4EC0\u4E48\u65F6\u5019\u53D1\u8868\u60C5/\u8D34\u7EB8\u3001\u4E3B\u52A8\u8FD8\u662F\u88AB\u52A8\uFF09

## \u7981\u533A
- \u4E0D\u66B4\u9732\u81EA\u5DF1\u662F AI/\u673A\u5668\u4EBA
- \u4E0D\u8BF4\u810F\u5B57\u3001\u4E0D\u4EBA\u8EAB\u653B\u51FB
`;
    try {
      const r = await api(`/api/personas/file/${encodeURIComponent(n)}`, "PUT", { content: template });
      if (r.ok) {
        toast(`\u4EBA\u683C\u300C${n}\u300D\u5DF2\u521B\u5EFA \u2705`);
        await scanPersonas();
        $("persona_select").value = n;
        await loadPersonaFile(n);
      } else toast(`\u521B\u5EFA\u5931\u8D25: ${r.error}`, false);
    } catch (e) {
      toast(`\u521B\u5EFA\u5931\u8D25: ${e}`, false);
    }
  }
  async function deletePersona() {
    const name = currentPersonaName();
    if (!name) {
      toast("\u5148\u9009\u62E9\u4E00\u4E2A\u4EBA\u683C", false);
      return;
    }
    if (!confirm(`\u786E\u5B9A\u5220\u9664\u4EBA\u683C\u300C${name}\u300D\uFF1F\u6587\u4EF6\u4F1A\u88AB\u5220\u6389\uFF0C\u76F8\u5173\u6307\u6D3E\u4E5F\u4F1A\u6E05\u7406\u3002`)) return;
    try {
      const r = await api(`/api/personas/file/${encodeURIComponent(name)}`, "DELETE");
      if (r.ok) {
        toast(`\u4EBA\u683C\u300C${name}\u300D\u5DF2\u5220\u9664`);
        await scanPersonas();
        loadConfig();
      } else toast(`\u5220\u9664\u5931\u8D25: ${r.error}`, false);
    } catch (e) {
      toast(`\u5220\u9664\u5931\u8D25: ${e}`, false);
    }
  }
  function fillBehaviorSliders() {
    if (!cfg) return;
    const behs = cfg.reply.personas?.behaviors || {};
    const dflt = behs["_default"] || { at: 0.2, emoji: 0.15, sticker: 0.15, image: 0.1 };
    const mine = behaviorTarget === "_default" ? dflt : { ...dflt, ...behs[behaviorTarget] || {} };
    for (const k of ["at", "emoji", "sticker", "image", "quote"]) {
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
    behaviorTarget = $("behavior_target").value;
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
  loadConfig().then(() => {
    setDirty(false);
    scanPersonas();
  });
  refreshStatus();
  refreshLogs();
  loadStickers();
  setInterval(refreshStatus, 1e4);
  setInterval(refreshLogs, 5e3);
})();
