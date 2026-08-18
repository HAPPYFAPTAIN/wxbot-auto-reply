"""wxbot_weflow.py — WeFlow HTTP API 客户端（读消息专用）。

WeFlow（hicccc77/WeFlow）是一个本地微信聊天记录查看/导出工具，
通过 HTTP API 提供只读能力：会话列表、联系人、群成员、消息历史、SSE 新消息推送。

本模块只负责「读」，**发消息仍走 wxmini2.py 的 UIA 自动化**（WeFlow 无发送接口）。

对接方式：
    Authorization: Bearer <token>
    （配置里 httpApiToken 是 safe: 加密存储，明文 token 在 WeFlow 设置界面可见）

用法：
    from wxbot_weflow import WeFlowClient
    wf = WeFlowClient()                      # 自动从 wxbot_config.json 的 weflow 段读取
    wf.health()
    for s in wf.sessions():
        ...
    msgs = wf.messages(talker="xxx@chatroom", limit=30)

输出结构对齐 wxmini2.py：
    sessions()  ≈  list_sessions()  →  [{username, displayName, sessionType, unreadCount, lastTimestamp, last}]
    messages()  ≈  read_chat()      →  [{kind, text, side, sender, ts, raw}]
"""

import json
import os
import threading
import time
import urllib.error
import urllib.request

try:
    import sseclient  # type: ignore  # 可选：更优雅的 SSE 解析
except ImportError:
    sseclient = None

DEFAULT_BASE_URL = "http://127.0.0.1:5031"

# 微信 DB localType → 语义（与 read_chat 的 kind 对齐）
LOCAL_TYPE_KIND = {
    1: "text",      # 文本
    3: "image",     # 图片
    34: "voice",    # 语音
    43: "video",    # 视频
    47: "emoji",    # 表情/贴纸
    48: "location", # 位置
    49: "appmsg",   # 文件/链接/引用/小程序
    10000: "system",  # 系统消息（进群、撤回提示等）
    10002: "revoke",  # 撤回
}


def load_weflow_cfg():
    """从项目 wxbot_config.json 的 weflow 段读取配置（不存在则用默认值+环境变量）。"""
    cfg = {}
    for p in ("wxbot_config.json",
              os.path.join(os.path.dirname(os.path.abspath(__file__)), "wxbot_config.json")):
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    cfg = json.load(f).get("weflow", {}) or {}
                break
            except Exception:
                cfg = {}
                break
    base_url = cfg.get("base_url") or os.environ.get("WEFLOW_BASE_URL") or DEFAULT_BASE_URL
    token = cfg.get("token") or os.environ.get("WEFLOW_TOKEN") or ""
    return {"base_url": base_url.rstrip("/"), "token": token}


class WeFlowError(Exception):
    """WeFlow API 调用失败。"""


class WeFlowClient:
    def __init__(self, base_url=None, token=None, timeout=15):
        c = load_weflow_cfg()
        self.base_url = (base_url or c["base_url"] or DEFAULT_BASE_URL).rstrip("/")
        self.token = token if token is not None else c["token"]
        self.timeout = timeout

    # ---------- 基础 ----------
    def _request(self, method, path, body=None, raw=False, timeout=None):
        url = self.base_url + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", "Bearer " + self.token)
        req.add_header("Content-Type", "application/json")
        # raw=True 用于 SSE 长连接：绝不自动超时；普通请求默认 self.timeout
        to = None if raw else (timeout if timeout is not None else self.timeout)
        try:
            with urllib.request.urlopen(req, timeout=to) as r:
                if raw:
                    return r
                return json.loads(r.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                detail = ""
            raise WeFlowError(f"WeFlow {method} {path} HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise WeFlowError(f"WeFlow {method} {path} 连接失败: {e.reason}") from e

    def health(self):
        """GET /health → {"status":"ok"}"""
        try:
            r = self._request("GET", "/health")
            return r.get("status") == "ok"
        except WeFlowError:
            return False

    # ---------- 会话 / 联系人 ----------
    def sessions(self):
        """GET /api/v1/sessions → [{username, displayName, sessionType, unreadCount, lastTimestamp, last}]"""
        data = self._request("GET", "/api/v1/sessions")
        out = []
        for s in data.get("sessions", []):
            out.append({
                "username": s.get("username", ""),
                "displayName": s.get("displayName", ""),
                "sessionType": s.get("sessionType", ""),
                "unreadCount": s.get("unreadCount", 0),
                "lastTimestamp": s.get("lastTimestamp", 0),
                "last": "",  # 会话列表没有消息预览字段；如需预览请调 messages()
            })
        return out

    def contacts(self):
        """GET /api/v1/contacts → [{username, displayName, nickname, type}]"""
        data = self._request("GET", "/api/v1/contacts")
        return data.get("contacts", [])

    def group_members(self, chatroom_id):
        """GET /api/v1/group-members?talker=<chatroomId> → [{wxid, displayName, nickname, avatarUrl}]"""
        import urllib.parse
        data = self._request("GET", "/api/v1/group-members?talker=" + urllib.parse.quote(chatroom_id))
        return data.get("members", [])

    # ---------- 消息 ----------
    def messages(self, talker, limit=30, before=None):
        """POST /api/v1/messages {talker, limit} → 标准化消息列表。

        返回 [{kind, text, side, sender, ts, raw}]，对齐 wxmini2.read_chat()：
            kind: text/image/voice/video/emoji/location/appmsg/system/revoke/unknown
            side: "own" | "other"（isSend==1 为 own）
            ts:   秒级 Unix 时间戳
        """
        body = {"talker": talker, "limit": int(limit)}
        if before:
            body["before"] = int(before)
        data = self._request("POST", "/api/v1/messages", body)
        out = []
        for m in data.get("messages", []):
            lt = m.get("localType", 0)
            is_send = m.get("isSend", 0)
            out.append({
                "kind": LOCAL_TYPE_KIND.get(lt, "unknown"),
                "text": m.get("content", ""),
                "side": "own" if is_send == 1 else "other",
                "sender": m.get("senderUsername", ""),
                "ts": m.get("createTime", 0),
                "raw": m.get("rawContent", ""),
                "localId": m.get("localId", 0),
                "serverId": m.get("serverId", ""),
                "localType": lt,
            })
        return out

    # ---------- SSE 主动推送 ----------
    def push_messages(self, on_message=None, on_revoke=None, on_error=None, stop_event=None):
        """GET /api/v1/push/messages (SSE 长连接)，阻塞式监听新消息。

        注意：连接建立后服务端会先**回放**最近的消息（message.new），
        之后持续推送新消息——去重/防重逻辑要自行按 ts/rawid 过滤。

        回调签名：
            on_message(msg: dict)   # message.new 事件（字段见 WeFlow 设置：event/sessionId/
                                    # sessionType/rawid/avatarUrl/sourceName/groupName?/content/timestamp）
            on_revoke(rev: dict)    # message.revoke 事件
        stop_event: threading.Event，set() 后优雅退出。
        """
        import http.client
        import urllib.parse

        # urllib 对 SSE 流有缓冲问题（BufferedReader 会攒满才返回），
        # 这里直接用 http.client 逐行读取，保证每条事件及时送达。
        u = urllib.parse.urlsplit(self.base_url)
        host, port = u.hostname, u.port or (443 if u.scheme == "https" else 80)
        path = "/api/v1/push/messages?access_token=" + urllib.parse.quote(self.token)
        headers = {"Authorization": "Bearer " + self.token, "Accept": "text/event-stream"}

        ev_stop = stop_event or threading.Event()
        while not ev_stop.is_set():
            conn = None
            try:
                if u.scheme == "https":
                    import ssl
                    conn = http.client.HTTPSConnection(host, port, timeout=None, context=ssl.create_default_context())
                else:
                    conn = http.client.HTTPConnection(host, port, timeout=None)
                conn.request("GET", path, headers=headers)
                resp = conn.getresponse()
                for ev, data in _parse_sse_manual(resp):
                    if ev_stop.is_set():
                        break
                    self._dispatch_sse(ev, data, on_message, on_revoke)
            except Exception as e:
                if on_error:
                    on_error(e)
                ev_stop.wait(3)  # 断线重连
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass

    @staticmethod
    def _dispatch_sse(event, data, on_message, on_revoke):
        if not data or not event:
            return
        try:
            obj = json.loads(data)
        except Exception:
            return
        if event == "message.new" and on_message:
            on_message(obj)
        elif event == "message.revoke" and on_revoke:
            on_revoke(obj)

    # ---------- 便捷工具 ----------
    def resolve_session_key(self, name_or_username):
        """把显示名/username 解析为可用的 talker key（username）。"""
        for s in self.sessions():
            if s["username"] == name_or_username or s["displayName"] == name_or_username:
                return s["username"]
        return name_or_username


def _parse_sse_manual(fp):
    """无 sseclient 依赖时的简易 SSE 解析器：yield (event, data)。"""
    event = None
    data_lines = []
    for raw in fp:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line:
            if event or data_lines:
                yield event, "\n".join(data_lines)
            event = None
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())


if __name__ == "__main__":
    # 自测：python -X utf8 wxbot_weflow.py [token]
    import sys

    tok = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("WEFLOW_TOKEN", "")
    wf = WeFlowClient(token=tok)
    print("health:", wf.health())
    if not wf.health():
        print("WeFlow API 不可达：确认已开启 设置→API 服务→启动服务")
        sys.exit(1)
    ss = wf.sessions()
    print(f"会话数: {len(ss)}")
    for s in ss[:10]:
        print(f'  [{s["sessionType"]:7s}] {s["username"][:28]:30s} {s["displayName"]}  unread={s["unreadCount"]}')
    if ss:
        key = ss[0]["username"]
        print(f"\n=== 读取 {ss[0]['displayName']} 最近消息 ===")
        for m in wf.messages(key, limit=5):
            print(f'  [{m["kind"]:7s}/{m["side"]}] {m["sender"][:16]:18s} {m["text"][:60]!r}')
