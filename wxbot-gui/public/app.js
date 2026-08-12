"use strict";
(() => {
  // public/app.ts
  var $ = (id) => document.getElementById(id);
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
    $("priv_min").value = String(c.reply.private.min_delay_s);
    $("priv_max").value = String(c.reply.private.max_delay_s);
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
  }
  function collect() {
    if (!cfg) throw new Error("config not loaded");
    const c = JSON.parse(JSON.stringify(cfg));
    c.enabled = $("enabled").checked;
    c.poll_interval_seconds = Number($("poll_interval_seconds").value) || 45;
    c.reply.private.min_delay_s = Number($("priv_min").value);
    c.reply.private.max_delay_s = Number($("priv_max").value);
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
      if (r.ok) toast("\u5DF2\u4FDD\u5B58 \u2705\uFF08\u91CD\u542F wxbot \u540E\u751F\u6548\uFF09");
      else toast(`\u4FDD\u5B58\u5931\u8D25: ${r.error}`, false);
    } catch (e) {
      toast(`\u4FDD\u5B58\u5931\u8D25: ${e}`, false);
    }
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
  async function refreshLogs() {
    try {
      const text = await api("/api/logs?n=200");
      const el = $("logs");
      el.textContent = text || "\uFF08\u6682\u65E0\u65E5\u5FD7\uFF09";
      el.scrollTop = el.scrollHeight;
    } catch {
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
  setInterval(refreshStatus, 1e4);
  setInterval(refreshLogs, 5e3);
})();
