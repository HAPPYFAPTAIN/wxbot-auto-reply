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
    const skip = /* @__PURE__ */ new Set(["persona_content", "persona_select", "logView", "callList"]);
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
  var LOG_STATE = {
    cursor: 0,
    // 运行日志已读行号游标
    callCursor: 0,
    // 调用日志已读游标
    follow: true,
    // 跟随滚动
    tab: "runtime"
  };
  function tagClassOf(tag, line) {
    const t = tag.toLowerCase();
    if (/error|exception|traceback|fail/i.test(t)) return "err";
    if (/send|发送|nav|navigate/i.test(t)) return "send";
    if (/llm|model|reply/i.test(t)) return "llm";
    if (/vision|识图/i.test(t)) return "vision";
    if (/ok|成功|ready/i.test(t)) return "ok";
    if (/warn|skip|降级|跳过|retry|fallback/i.test(t)) return "warn";
    if (/poll|changed|mention|weflow/i.test(t)) return "poll";
    return "info";
  }
  function lineLevel(line) {
    if (/error|exception|traceback|failed|失败|异常/i.test(line)) return "lv-err";
    if (/warn|skip|降级|跳过|retry|fallback|超时/i.test(line)) return "lv-warn";
    if (/send ok|发送成功|已发送|回复了|replied/i.test(line)) return "lv-ok";
    if (/sticker catalog|load error/i.test(line)) return "lv-warn";
    return "";
  }
  async function refreshLogs() {
    if (LOG_STATE.tab !== "runtime") return;
    try {
      const data = await api(`/api/logs?format=json&since=${LOG_STATE.cursor}`);
      if (!data || !Array.isArray(data.lines) || data.lines.length === 0) {
        if (LOG_STATE.cursor === 0) {
          const view2 = $("logView");
          view2.innerHTML = `<div class="empty-tip">\uFF08\u6682\u65E0\u65E5\u5FD7 \u2014\u2014 \u542F\u52A8 wxbot \u540E\u8FD9\u91CC\u4F1A\u5B9E\u65F6\u6EDA\u52A8\uFF09</div>`;
        }
        return;
      }
      const view = $("logView");
      if (view.querySelector(".empty-tip")) view.innerHTML = "";
      const q = $("logSearch").value.trim().toLowerCase();
      data.lines.forEach((ln, i) => {
        const row = document.createElement("div");
        row.className = "log-line";
        const num = document.createElement("span");
        num.className = "ln";
        num.textContent = String(LOG_STATE.cursor + i + 1);
        const body = document.createElement("span");
        body.className = "body";
        const m = ln.match(/^(\d{2}:\d{2}:\d{2})\s+\[([^\]]+)\]/);
        if (m) {
          const tm = document.createElement("span");
          tm.className = "ts";
          tm.textContent = m[1];
          const tag = document.createElement("span");
          tag.className = `tag t-${tagClassOf(m[2], ln)}`;
          tag.textContent = `[${m[2]}]`;
          body.appendChild(tag);
          body.appendChild(document.createTextNode(ln.slice(m[0].length)));
          row.appendChild(num);
          row.appendChild(tm);
        } else {
          body.textContent = ln;
          row.appendChild(num);
        }
        row.appendChild(body);
        const lv = lineLevel(ln);
        if (lv) row.classList.add(lv);
        if (q && !ln.toLowerCase().includes(q)) row.classList.add("filtered");
        view.appendChild(row);
      });
      LOG_STATE.cursor += data.lines.length;
      updateLogCount();
      if (LOG_STATE.follow) view.scrollTop = view.scrollHeight;
    } catch {
    }
  }
  function applyLogFilter() {
    const q = $("logSearch").value.trim().toLowerCase();
    const rows = document.querySelectorAll("#logView .log-line");
    let shown = 0;
    rows.forEach((r) => {
      const hit = !q || (r.textContent || "").toLowerCase().includes(q);
      r.classList.toggle("filtered", !hit);
      if (hit) shown++;
    });
    $("logCount").textContent = `${shown}/${LOG_STATE.cursor} \u884C`;
  }
  function updateLogCount() {
    $("logCount").textContent = `${LOG_STATE.cursor} \u884C`;
  }
  function toggleLogFollow() {
    LOG_STATE.follow = !LOG_STATE.follow;
    const btn = $("logFollow");
    if (LOG_STATE.follow) {
      btn.textContent = "\u23F8 \u6682\u505C\u8DDF\u968F";
      $("logLiveBadge").textContent = "\u25CF LIVE";
      $("logLiveBadge").className = "badge on";
      const v = $("logView");
      v.scrollTop = v.scrollHeight;
    } else {
      btn.textContent = "\u25B6 \u6062\u590D\u8DDF\u968F";
      $("logLiveBadge").textContent = "\u275A\u275A PAUSED";
      $("logLiveBadge").className = "badge off";
    }
  }
  function copyLogs() {
    const rows = document.querySelectorAll("#logView .log-line:not(.filtered)");
    const text = Array.from(rows).map((r) => r.textContent || "").join("\n");
    if (!text) return;
    navigator.clipboard?.writeText(text).then(() => toast(`\u5DF2\u590D\u5236 ${rows.length} \u884C\u65E5\u5FD7`, true));
  }
  function clearLogs() {
    $("logView").innerHTML = "";
    LOG_STATE.cursor = 0;
    updateLogCount();
    refreshLogs();
  }
  function parseCandLine(line) {
    const m = line.match(/^\d+\.\s*(.*)$/);
    const rest = m ? m[1] : line;
    const agoM = rest.match(/^（([^）]*)）/);
    const ago = agoM ? agoM[1] : "";
    let after = agoM ? rest.slice(agoM[0].length) : rest;
    let nick = "";
    const nickM = after.match(/^@([^\s:：]+)/);
    if (nickM) {
      nick = nickM[1];
      after = after.slice(nickM[0].length);
    }
    return { ago, nick, text: after.replace(/^[:：]\s*/, "").trim() };
  }
  function renderCallCard(ev) {
    const list = $("callList");
    if (list.querySelector(".empty-tip")) list.innerHTML = "";
    const card = document.createElement("div");
    card.className = "call-card";
    const time = ev.ts ? ev.ts.slice(11, 19) : "";
    const dot = { candidates: "#0a84ff", llm: "#64d2ff", send_ok: "#30d158", send_partial: "#ffd60a", raw: "#98989d", error: "#ff453a" }[ev.event] || "#98989d";
    const typeLabel = {
      candidates: "\u5019\u9009\u6D88\u606F",
      llm: "LLM \u56DE\u590D",
      send_ok: "\u53D1\u9001\u6210\u529F",
      send_partial: "\u90E8\u5206\u53D1\u9001",
      raw: "\u539F\u59CB\u884C",
      error: "\u9519\u8BEF"
    };
    let sum = "";
    if (ev.event === "candidates") sum = `${ev.name || ""} \xB7 ${ev.n || 0} \u6761\u5019\u9009`;
    else if (ev.event === "llm") sum = `${ev.model || ""} \xB7 ${(ev.reply || "").slice(0, 36)}${(ev.reply || "").length > 36 ? "\u2026" : ""}`;
    else if (ev.event === "send_ok") sum = `${ev.name || ""} \xB7 \u53D1\u9001 ${ev.n_sent || 0}/${(ev.sentences || []).length} \u53E5`;
    else if (ev.event === "send_partial") sum = `${ev.name || ""} \xB7 \u90E8\u5206\u6210\u529F ${ev.n_ok}/${ev.n_total}`;
    else sum = (ev.message || ev.raw || "").slice(0, 50);
    const head = document.createElement("div");
    head.className = "call-head";
    head.innerHTML = `
    <span class="dot" style="background:${dot}"></span>
    <span class="c-type">${typeLabel[ev.event] || ev.event}</span>
    <span class="c-time">${time}</span>
    <span class="c-sum"></span>
    <span class="chev">\u25B6</span>`;
    head.querySelector(".c-sum").textContent = sum;
    head.addEventListener("click", () => card.classList.toggle("open"));
    const body = document.createElement("div");
    body.className = "call-body";
    if (ev.event === "candidates") {
      body.innerHTML = `<div class="cb-row"><div class="cb-k">\u4F1A\u8BDD</div><div class="cb-v"><span class="cb-badge b-cand">${ev.n || 0} \u6761\u5019\u9009</span>${ev.name || ""}</div></div>`;
      const wrap = document.createElement("div");
      wrap.className = "cb-row";
      wrap.innerHTML = `<div class="cb-k">\u5019\u9009</div>`;
      const v = document.createElement("div");
      v.className = "cb-v";
      (ev.cand || []).forEach((c) => {
        const p = parseCandLine(c);
        const item = document.createElement("div");
        item.className = "cand-item";
        item.innerHTML = `<span class="c-ago">${p.ago ? "(" + p.ago + ") " : ""}</span><span class="c-who">@${p.nick || "?"}</span> <span class="c-txt">${escapeHtml(p.text)}</span>`;
        v.appendChild(item);
      });
      wrap.appendChild(v);
      body.appendChild(wrap);
    } else if (ev.event === "llm") {
      body.innerHTML = `<div class="cb-row"><div class="cb-k">\u4F1A\u8BDD</div><div class="cb-v"><span class="cb-badge b-llm">${ev.model || ""}</span>${ev.name || ""} \xB7 \u4E0A\u4E0B\u6587 ${ev.ctx_lines ?? "-"} \u6761${ev.search ? ` \xB7 \u68C0\u7D22: ${ev.search}` : ""}</div></div>`;
      const rw = document.createElement("div");
      rw.className = "cb-row";
      rw.innerHTML = `<div class="cb-k">\u56DE\u590D</div>`;
      const box = document.createElement("div");
      box.className = "llm-box";
      box.innerHTML = `<span class="r-role">mimo \u5B9E\u9645\u8F93\u51FA\uFF1A</span>
${escapeHtml(ev.reply || "")}`;
      rw.appendChild(box);
      body.appendChild(rw);
      if (ev.inbound) {
        const iw = document.createElement("div");
        iw.className = "cb-row";
        iw.innerHTML = `<div class="cb-k">\u8F93\u5165</div>`;
        const ibox = document.createElement("div");
        ibox.className = "llm-box";
        ibox.style.opacity = ".7";
        ibox.textContent = ev.inbound.slice(0, 300) + (ev.inbound.length > 300 ? "\u2026" : "");
        iw.appendChild(ibox);
        body.appendChild(iw);
      }
    } else if (ev.event === "send_ok" || ev.event === "send_partial") {
      const ok = ev.event === "send_ok";
      const badge = ok ? '<span class="cb-badge b-ok">\u5168\u90E8\u53D1\u9001</span>' : `<span class="cb-badge b-partial">${ev.n_ok}/${ev.n_total} \u90E8\u5206</span>`;
      body.innerHTML = `<div class="cb-row"><div class="cb-k">\u4F1A\u8BDD</div><div class="cb-v">${badge}${ev.name || ""}</div></div>`;
      const sw = document.createElement("div");
      sw.className = "cb-row";
      sw.innerHTML = `<div class="cb-k">\u5185\u5BB9</div>`;
      const box = document.createElement("div");
      box.className = "llm-box";
      box.textContent = (ev.sentences || []).join("\n\u2500\u2500\u2500\n");
      sw.appendChild(box);
      body.appendChild(sw);
    } else {
      body.innerHTML = `<div class="cb-row"><div class="cb-v" style="text-align:left">${escapeHtml(ev.message || ev.raw || JSON.stringify(ev))}</div></div>`;
    }
    card.appendChild(head);
    card.appendChild(body);
    list.appendChild(card);
    while (list.children.length > 100) list.removeChild(list.firstChild);
  }
  function escapeHtml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  async function refreshCallLog() {
    if (LOG_STATE.tab !== "call") return;
    try {
      const data = await api(`/api/calllog?since=${LOG_STATE.callCursor}&n=100`);
      if (!data || !data.events || data.events.length === 0) {
        if (LOG_STATE.callCursor === 0) {
          $("callList").innerHTML = `<div class="empty-tip">\uFF08\u6682\u65E0\u8C03\u7528\u8BB0\u5F55 \u2014\u2014 bot \u6BCF\u6B21\u52A8\u8111\u56DE\u590D\u540E\u8FD9\u91CC\u4F1A\u51FA\u73B0\u300C\u5019\u9009\u2192LLM\u2192\u53D1\u9001\u300D\u5168\u94FE\u8DEF\u5361\u7247\uFF09</div>`;
        }
        return;
      }
      data.events.forEach(renderCallCard);
      LOG_STATE.callCursor = data.cursor;
    } catch {
    }
  }
  function copyCallLogs() {
    const cards = document.querySelectorAll("#callList .call-card");
    const lines = [];
    cards.forEach((c) => {
      const t = c.querySelector(".c-time")?.textContent || "";
      const ty = c.querySelector(".c-type")?.textContent || "";
      lines.push(`[${t}] ${ty}: ${c.querySelector(".c-sum")?.textContent || ""}`);
    });
    if (lines.length) navigator.clipboard?.writeText(lines.join("\n")).then(() => toast(`\u5DF2\u590D\u5236 ${lines.length} \u6761\u8C03\u7528\u8BB0\u5F55`, true));
  }
  function switchLogTab(tab) {
    LOG_STATE.tab = tab;
    $("tabRuntime").classList.toggle("active", tab === "runtime");
    $("tabCall").classList.toggle("active", tab === "call");
    $("logView").style.display = tab === "runtime" ? "" : "none";
    $("callView").style.display = tab === "call" ? "" : "none";
    $("logSearch").style.display = tab === "runtime" ? "" : "none";
    $("logCount").style.display = tab === "runtime" ? "" : "none";
    if (tab === "runtime") refreshLogs();
    else refreshCallLog();
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
    refreshCallLog();
  });
  $("tabRuntime").addEventListener("click", () => switchLogTab("runtime"));
  $("tabCall").addEventListener("click", () => switchLogTab("call"));
  $("logSearch").addEventListener("input", applyLogFilter);
  $("logFollow").addEventListener("click", toggleLogFollow);
  $("logCopy").addEventListener("click", copyLogs);
  $("logClear").addEventListener("click", clearLogs);
  $("callCopy").addEventListener("click", copyCallLogs);
  var logViewEl = $("logView");
  logViewEl.addEventListener("scroll", () => {
    if (!LOG_STATE.follow) return;
    const atBottom = logViewEl.scrollTop + logViewEl.clientHeight >= logViewEl.scrollHeight - 40;
    if (!atBottom) toggleLogFollow();
  });
  watchDirty();
  loadConfig().then(() => {
    setDirty(false);
    scanPersonas();
  });
  refreshStatus();
  refreshLogs();
  refreshCallLog();
  loadStickers();
  setInterval(refreshStatus, 1e4);
  setInterval(refreshLogs, 2e3);
  setInterval(refreshCallLog, 5e3);
})();
