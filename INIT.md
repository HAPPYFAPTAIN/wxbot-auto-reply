# wxbot 项目初始化文档（INIT.md）

> 微信自动回复机器人 + 人格扮演 + 记忆系统 + 管理控制台
> 最后更新：2026-08-12 · 仓库：https://github.com/HAPPYFAPTAIN/wxbot-auto-reply.git

---

## 1. 项目是什么

wxbot 是一个跑在 Windows 上的微信自动回复机器人：

- **手写 UIA 自动化**驱动微信 PC 版 4.x（不用官方 API，不注入 dll，纯界面级操作）
- 轮询会话列表 → 发现新消息 → 点开会话 → 读气泡 → LLM 生成回复 → 分句发送
- 支持**人格系统**：不同群/私聊可以指派不同人格（蒸馏自语料的 .md 文件）
- 支持**特殊能力**：真 @ 群成员、发图片、发微信表情、发「爱心」收藏贴纸、引用回复、识图、读文件
- 带**苹果风 Web 控制台**（暗夜/白天双主题）管理全部参数
- 带**对话级记忆系统**（类 Qwenpaw/OpenClaw 的 workspace 结构）

## 2. 快速开始

```bash
# 1. 启动控制台（会顺带拉起 wxbot）
cd wxbot-gui
node node_modules\tsx\dist\cli.mjs server.ts
# 浏览器打开 http://127.0.0.1:7931

# 2. 或直接命令行跑 bot
python -X utf8 wxbot.py
```

前提：PC 微信已登录且窗口不被藏起来；Python 3.11（有 curl_cffi）。

## 3. 目录结构

```
workspace/
├── wxbot.py               # 主程序：轮询/回复/人格/能力分发
├── wxmini2.py             # UIA 自动化库（发消息/@/图/表情/贴纸/引用/文件）
├── wxmini.py              # 旧版库（保留兼容）
├── wxbot_files.py         # 文件消息读取：找文件 + 按类型解析
├── wxbot_memory.py        # 记忆系统：workspace 骨架 + 注入 + 提取
├── wxbot_context.py       # 输入缓存 + 词元估算 + 上下文压缩
├── wxbot_stickers.py      # 贴纸目录重建（截图 + vision 建档）
├── personas/              # 人格文件（每个 .md = 一个人格，文件名即人格名）
│   └── wen.md             # 温先生（对线人格，示例）
├── prompts/
│   └── base.md            # 底层文档：所有对话共用的行为准则（可编辑）
├── workspaces/            # 对话级记忆（自动生成，不入 git）
│   └── <对话名-hash8>/
│       ├── MEMORY.md      # 长期记忆（注入 system prompt）
│       ├── memory/YYYY-MM-DD.md  # 每日笔记（自动提取）
│       ├── files/         # 预留：该对话文件副本
│       └── notes/         # 预留：杂项
├── wxbot_images/          # 图片库（发图用，文件名含关键词）
│   └── stickers/          # 爱心贴纸目录（NN.png + catalog.json）
├── wxbot-gui/             # Web 控制台（Express + TS，esbuild 打包）
│   ├── server.ts          # API + 配置读写 + 进程管理
│   └── public/            # 前端（app.ts → app.js）
├── wxbot_config.json      # 运行配置（脱敏版示例见 wxbot_config.example.json）
├── wxbot_state.json       # 运行状态（已读/已回/时间戳）
├── wxbot_out.log          # 运行日志
└── INIT.md                # 本文件
```

## 4. 核心概念

### 4.1 回复流程
1. 每 5 秒轮询会话列表，比对 last 消息指纹（state）
2. 黑名单/白名单/冷却/免打扰 → 决定是否处理
3. 点开会话 → 读最近气泡（带左右侧判定）→ 定位对方最后一条
4. 对方发图 → 截图 + vision 识图；对方发文件 → 本地找文件 + 解析内容
5. 组装上下文（可压缩）→ LLM 生成回复（system 带缓存）
6. 分句发送，每句按行为旋钮掷骰子决定 @/表情/贴纸/图片/引用
7. 每 N 轮回复做一次记忆提取（写入该对话 workspace）

### 4.2 人格系统
- `personas/<名字>.md` = 一个人格；`personas.dir` 可换目录
- 指派：`per_group`（群→人格）、`per_contact`（私聊→人格）、`default`（兜底）
- 人格内容注入 system prompt，优先级高于基础准则；改完即生效（实时读文件）

### 4.3 行为旋钮（每条 0~100%）
`behaviors.<人格名或_default>.<能力>`：at / emoji / sticker / image / quote
- 双重生效：prompt 写「@人偶尔用（约20%）」引导 + 发送时硬掷骰子节流
- @ 只对群聊生效；0% = 彻底禁用

### 4.4 上下文压缩
- `context.compression`：mode=percent（按 llm.context_window 百分比）或 tokens（固定词元）
- 两阶段：超预算先截断旧消息（trim_chars）→ 还不够丢最旧的，加省略标记
- 词元估算：CJK 每字 1、拉丁词每词 ~1.3（启发式，无依赖）

### 4.5 输入缓存
- system prompt（base + 能力清单 + 行为 + 人格 + 记忆）按组合键缓存：
  `(人格文件mtime, 记忆mtime, 贴纸目录mtime, model)`
- 命中则跳过重建；同时保持前缀稳定，让 DeepSeek 等 provider 的上下文缓存能命中

### 4.6 记忆系统（类 Qwenpaw）
- 每个对话独立 workspace（见目录结构），互相隔离
- MEMORY.md（长期）+ memory/每日笔记（自动提取）注入 system
- 提取触发：每 `memory.every_n_replies` 轮回复，用 LLM 提炼新事实追加当日笔记

### 4.7 LLM 输出标记
| 标记 | 效果 |
|---|---|
| `@昵称 `（第一句开头） | 真 @ 群成员 |
| `[Q] 内容`（第一句） | 引用对方那条消息回复 |
| `[IMG:关键词]` | 从图片库发图（关键词匹配文件名） |
| `[EMOJI:表情名]` | 发微信表情 |
| `[STICKER:编号或关键词]` | 发「爱心」收藏贴纸 |
| `[SKIP]` | 本轮不回复 |

## 5. 配置文件参考（wxbot_config.json）

```jsonc
{
  "enabled": true,
  "poll_interval_seconds": 5,
  "reply": {
    "private": { "enabled": true, "min_delay_s": 8, "max_delay_s": 15,
      "cooldown_s": 60, "allow": [], "deny": [],
      "quiet_hours": { "enabled": false, "start": "23:30", "end": "07:30", "allow_contacts": [] } },
    "group": { "enabled": true, "require_mention": true, "min_delay_s": 2, "max_delay_s": 5,
      "mention_names": ["爱而不恨"], "allow": [], "deny": [] },
    "unlimited_groups": ["【官方】DeepSeek交流34群"],
    "unlimited_group_interval_s": 0,
    "context_messages": { "default": 8, "【官方】DeepSeek交流34群": 30 },
    "max_sentences": 4,
    "sentence_delay_s": [1.0, 2.5],
    "allow_contacts": [], "deny_contacts": ["公众号", "服务号", "文件传输助手", "折叠的聊天", "微信团队"],
    "max_reply_chars": 300,
    "personas": {
      "enabled": true, "dir": "personas", "default": "",
      "per_group": { "【官方】DeepSeek交流34群": "wen" }, "per_contact": {},
      "definitions": { "wen": "personas/wen.md" },
      "behaviors": {
        "_default": { "sticker": 0.15, "emoji": 0.15, "at": 0.2, "image": 0.1, "quote": 0.2 },
        "wen": { "sticker": 0.3, "emoji": 0.25, "at": 0.4, "image": 0.15, "quote": 0.4 }
      }
    }
  },
  "llm": { "base_url": "...", "model": "...", "api_key_env": "OPENCODE_API_KEY",
           "temperature": 0.9, "max_tokens": 400, "context_window": 32000 },
  "vision": { "base_url": "...", "model": "mimo-v2.5", "api_key_env": "OPENCODE_API_KEY",
              "fallbacks": [ { "base_url": "https://fast.clawapi.store/v1", "model": "gpt-5.6-sol", "api_key_env": "CLAWAPI_API_KEY" } ] },
  "images": { "enabled": true, "dir": "wxbot_images" },
  "stickers": { "enabled": true, "catalog": "wxbot_images/stickers/catalog.json" },
  "files": { "max_chars": 1500 },
  "context": { "compression": { "enabled": false, "mode": "percent", "percent": 60,
                "tokens": 4000, "keep_recent": 4, "trim_chars": 60 } },
  "memory": { "enabled": true, "every_n_replies": 5, "long_term_chars": 1200, "daily_chars": 800 },
  "own_nicknames": ["爱而不恨"]
}
```

API key 一律走环境变量或 `openclaw.json` 的 `env` 段（`api_key_env` 指定变量名）。

## 6. 控制台（wxbot-gui）API

- `GET/PUT /api/config` 读/写配置
- `GET /api/status`、`POST /api/start|stop|restart` 进程管理
- `GET /api/logs?n=200` 日志
- `GET /api/llm/test` 模型通路测试（按表单值真发请求，20s 超时）
- `GET /api/personas`、`GET/PUT/DELETE /api/personas/file/:name` 人格 CRUD（防目录穿越）
- `GET /api/fs/browse?path=` 文件夹浏览（人格目录选择器）
- `GET /api/stickers`、`GET /api/stickers/img/:file`、`POST /api/stickers/refresh` 贴纸管理
- 前端打包：`node node_modules\esbuild\bin\esbuild public/app.ts --bundle --outfile=public/app.js --format=iife`

## 7. 已知边界与踩坑

- **UIA 树会挂死**：频繁操作后读不到控件 → wxbot 自动 `restart_wechat()`（杀进程重启 + Enter 进登录页）
- **坐标必须现取**：微信窗口随时会被移动/缩放，点击前实时 `find_chat_page`，点完验证面板弹出
- **Cloudflare 1010**：Python urllib 被按 TLS 指纹 ban → 统一走 `_http_post_json`（curl_cffi impersonate=chrome）
- **不钉 hosts**：腾讯域名 IP 轮换，钉死必过期
- 自定义表情 tab 无滚动（ScrollPattern 不支持），当前正好 20 张
- 文件消息依赖微信自动下载到 `xwechat_files\<wxid>_xxxx\msg\file\YYYY-MM\`
- 引用回复对文件/图片气泡同样可用（右键菜单都有「引用」）

## 8. 开发与发布

- 改 GUI 前端：改 `public/app.ts` 后必须 esbuild 重新打包
- 改人格/基础文档：即时生效，无需重启
- 改配置/后端：保存后在控制台点「重启 wxbot」
- git：`git add -A && git commit && git push`（workspaces/、wxbot_images/、config/state/logs 均不入库）
