# wxbot

微信 PC 版自动读消息 + 自动回复守护进程（纯 UI 自动化，不碰协议）。

基于微信 4.1.x PC 客户端，用 UIA（UI Automation）+ 模拟点击读消息、发消息，
再调用 OpenAI 兼容 LLM 接口生成回复。不注入、不改协议，风险相对可控。

## 架构

```
wxbot.py       主守护进程：轮询会话 → 检测新消息 → 打开会话读气泡 → LLM 生成 → 分句发送
wxmini.py      UIA 基础库（找窗口、搜索联系人、点击、打字发送）
wxmini2.py     UIA 扩展库（会话列表、读聊天气泡、左右侧判断、发送）
wxbot-gui/     本地 Web 控制台（Express + TS）：改配置、看状态、重启、看日志
wxbot_config.example.json   配置样例（复制为 wxbot_config.json 使用）
```

## 工作流程

1. 每 `poll_interval_seconds` 秒轮询一次微信会话列表
2. 对比每条会话的最后一条消息指纹，发现新消息
3. 打开会话，读取最近气泡，找到「对方发的最后一条文字」
4. 群聊按 `[有人@我]` 标记或白名单决定是否回复
5. LLM 生成回复（可返回 `[SKIP]` 表示不值得回）
6. 按真人节奏延时，分句逐条发送

## 配置

复制 `wxbot_config.example.json` 为 `wxbot_config.json` 后修改：

- `llm.base_url` / `llm.model`：任意 OpenAI 兼容接口
- `llm.api_key_env`：API key 从环境变量读取（不写进配置文件）
- `reply.group.mention_names` / `own_nicknames`：你的微信昵称
- `reply.unlimited_groups`：无需 @ 也自动回复的群（慎用）

## 运行

```bash
python wxbot.py            # 常驻运行
python wxbot.py --once     # 只跑一轮（调试用）
```

GUI（可选）：

```bash
cd wxbot-gui
npm install
npm run build   # esbuild 打包 public/app.ts -> public/app.js
npm start       # http://127.0.0.1:7931
```

## 依赖

- Python 3.11+
- Windows + 微信 PC 4.1.x（登录态）
- comtypes（UIA 绑定）

## 安全提示

- 以「真人身份」自动回复意味着会对外发声，请自行控制回复范围
  （白名单/黑名单/延时/概率都在配置里）
- API key 一律走环境变量，别写进配置文件或代码
- 本仓库已去除个人敏感信息，部署前请自行替换 `YOUR_*` 占位符
