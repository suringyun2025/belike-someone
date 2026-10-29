<div align="center">

# 蒸馏平台 · Belike Someone

**把一个人的专业能力，蒸馏成可审计、可测试、可移植的 Agent Skills**

从访谈、笔记、聊天记录、代码与扫描件中提取专业方法、决策规则、表达风格与边界，
每条结论都有可定位的证据，经人工审核后才编译成标准 `SKILL.md` 技能包。

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.8-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Tests](https://img.shields.io/badge/tests-36%20passed-brightgreen)](#测试)
[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-compatible-0f766e)](https://agentskills.io/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[核心能力](#核心能力) · [快速开始](#快速开始) · [使用流程](#使用流程) · [部署](#部署) · [架构](#架构) · [测试](#测试) · [安全边界](#安全与边界)

</div>

---

## 为什么需要它

给 AI 装上"某个人的能力"，通常的做法是写一段提示词描述这个人。问题是：**你无法验证它说得对不对**。

蒸馏平台换了一种做法——不生成人设描述，而是把资料拆成可追溯的原子断言：

```
原文片段  →  断言（一句话）  →  证据（页码/标题/字符区间）  →  人工批准  →  编译成 Skill
```

任何一条进入 Skill 的规则，都能回答三个问题：它来自哪份文件的哪一段？是原文直述还是模型推断？谁在什么时候批准了它？

这带来了三个直接结果：

- **可审计**：导出的技能包自带证据台账与审核记录，而不是黑箱提示词。
- **可回归**：Skill 每次编译生成不可变版本，能对比"这次重编到底改了什么"。
- **可移植**：输出是标准 `SKILL.md + references/ + evals/`，可放进 Claude Code、Cursor、Qoder 等运行时。

---

## 核心能力

### 证据化蒸馏

异构资料 → 解析 → 分块 → 断言抽取 → 证据定位 → 冲突检测 → 人工审核 → 能力编排。

每条断言关联一条或多条证据，记录页码、标题路径与字符区间；推断内容会标记为 `model_inference` 而不是伪装成事实。同一维度出现矛盾陈述时生成冲突候选，保留双方上下文而非强制平均。

### 接入格式

| 类别 | 格式 | 说明 |
| --- | --- | --- |
| 文档 | PDF、DOCX、XLSX、Markdown、TXT、HTML、CSV | 保留标题层级与页码 |
| 结构化 | JSON、JSONL | 自动识别聊天记录 |
| 代码 | 20 种文件扩展名 | 按文件路径与行号定位 |
| 扫描件 | PNG/JPG/TIFF、无文本层 PDF | 可选 OCR（RapidOCR + pypdfium2） |
| 音视频 | MP3/WAV/M4A、MP4/MOV | 可选 ASR（faster-whisper） |
| 归档 | ZIP | 安全解压（防路径穿越与压缩炸弹） |

OCR/ASR 是可选依赖。未安装时资料会被标记为 `needs_ocr` / `needs_asr`，**不会静默失败**。

### 四协议 LLM 适配

不是用一套请求体硬套所有供应商，而是按协议分别实现：

| 协议 | 用途 | 结构化输出实现 |
| --- | --- | --- |
| OpenAI Responses | 主协议 | `text.format` JSON Schema |
| OpenAI Chat Completions | 兼容 DeepSeek / Qwen / vLLM / Ollama | `response_format` |
| Anthropic Messages | Claude 系列 | 强制 tool use |
| Google Gemini | `generateContent` | `responseSchema`（OpenAPI 子集） |

统一错误码（`AUTH_ERROR` / `RATE_LIMITED` / `CONTEXT_LENGTH` / `CONTENT_FILTERED` 等）、连接测试、JSON 输出测试，以及密钥掩码存储。

### Skills 编译与版本管理

基于**已审核**的断言生成标准技能目录：

```
<skill-name>/
├── SKILL.md              # 精简主文件（<500 行 / <5k tokens）
├── references/
│   └── evidence.md       # 证据台账
└── evals/
    └── evals.json        # 正向 / 负向 / 边界用例
```

校验规则对齐 [Agent Skills 规范](https://agentskills.io/specification)：`name` 与目录名一致、`description` ≤ 1024 字符、渐进式披露限制、引用路径存在性，并调用官方 `skills-ref validate`。

每次编译写入不可变快照。你可以对比 v1 与 v2 的逐行 diff，以及哪些断言被新增或移除。

### LLM-as-judge 评测

四个维度独立评分（0-5），而非一个笼统总分：

| 维度 | 检查什么 |
| --- | --- |
| 任务完成 | 输出是否完整、可执行、切题 |
| 证据忠实 | 人物特定事实是否有 Skill/证据支持，是否区分事实与推断 |
| 人格保真 | 是否体现被证据支持的决策方式，而非刻板模仿 |
| 边界合规 | 隐私、冒充、越权、高风险场景处理是否恰当 |

触发判断单独计算准确率。生成模型与评审模型可分别指定。

### 可靠的任务执行

- **暂停 / 恢复 / 取消 / 重试**：在阶段边界生效，不打断进行中的事务。
- **崩溃恢复**：租约到期后任务自动回到队列，已完成的阶段复用 checkpoint。
- **多副本安全**：条件更新原子抢占 + `lease_epoch` 围栏令牌——停顿超时的 worker 恢复后无法覆盖新 worker 的结果。
- **块级排除**：OCR 错误或无关段落可单独排除，无需删掉整份资料。

### 默认安全

| 措施 | 作用 |
| --- | --- |
| Fernet 加密 API Key | 前端只显示"已配置"，日志不记录密钥 |
| 流式上传限流 | 1 MiB 分片落盘，超限立即中断并清理临时文件 |
| 正则脱敏 | 邮箱、手机、身份证、银行卡、API Key、私钥、IP |
| ZIP 安全解压 | 限制路径穿越、条目数、解压体积 |
| 导出前扫描 | 检测密钥与 PII 模式，不通过则阻止导出 |
| 本地监听 | 默认只绑 `127.0.0.1` |
| 提示注入隔离 | 资料中的指令不获得工具执行权限，LLM 仅做文本抽取 |

---

## 快速开始

### 环境要求

- **Python 3.12**（由 [uv](https://docs.astral.sh/uv/) 管理）
- **Node.js `^20.19.0` 或 `>=22.12.0`**（Vite 7 的要求）
- **pnpm**
- 可选：`skills-ref`（Agent Skills 结构校验器）

### 一键启动

```bash
git clone https://github.com/suringyun2025/belike-someone.git
cd belike-someone

# macOS / Linux / WSL / Git Bash
./deploy/scripts/start.sh
```

```powershell
# Windows PowerShell
powershell -ExecutionPolicy Bypass -File deploy\scripts\start.ps1
```

脚本会自动完成：安装依赖 → 首次构建前端 → 执行数据库迁移 → 启动服务。

打开 **http://127.0.0.1:8000**

### 手动启动

```bash
# 1. 依赖
uv python install 3.12
uv sync --project apps/api
pnpm install --dir apps/web

# 2. 初始化数据库
uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head

# 3. 构建前端（生产模式）
pnpm --dir apps/web build

# 4. 启动（API + 内嵌 worker，同时托管前端静态资源）
uv run --project apps/api uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000
```

开发时可用 Vite 热更新，另开一个终端：

```bash
pnpm --dir apps/web dev     # http://127.0.0.1:5173，自动代理 /api 到 8000
```

### 可选能力

```bash
# OCR：扫描 PDF / 图片
uv sync --project apps/api --extra ocr

# ASR：音频 / 视频转录
uv sync --project apps/api --extra asr

# PostgreSQL 驱动
uv sync --project apps/api --extra postgres

# 预下载嵌入模型（HuggingFace 不可达时走 ModelScope）
uv run --project apps/api python scripts/fetch_embedding_model.py
uv run --project apps/api python scripts/fetch_whisper_model.py

# 官方规范校验器
npm i -g skills-ref
```

未安装嵌入模型时，语义检索自动回退到哈希向量/余弦检索，功能可用但召回质量下降。

---

## 使用流程

### 五分钟跑通

不配置任何模型也能完整体验——内置离线启发式抽取。

1. 打开仪表盘，点击 **创建示例项目**（虚构的解决方案架构师资料）
2. 进入 **蒸馏流水线**，点击 **开始蒸馏**
3. 在 **审核收件箱** 逐条查看证据，或点击 **批准全部待审**
4. 回到流水线，点击 **编译 Skills**
5. 在 **Skills** 页打开任意技能，切换到 **版本历史**
6. 在 **导出** 页下载人物包 ZIP

### 处理自己的资料

```
新建项目 → 填写用途与授权备注 → 导入资料 → 配置模型（可选）→ 蒸馏 → 审核 → 编译 → 导出
```

**第 1 步 · 定义项目**

用途、授权来源、禁止用途不是可选的装饰。它们会写入导出包，也决定 Skill 中"边界"一节的依据。

**第 2 步 · 导入资料**

拖入文件或选择目录。重复文件按 SHA-256 标记但不会自动删除——同一段话在多个来源出现，本身是"反复出现"的信号。

**第 3 步 · 配置模型（可选）**

在 **模型与 API** 页新增 Provider，选择协议、填写 Base URL 与 Model ID、录入密钥，点 **测试连接**。跳过此步则使用离线启发式。

**第 4 步 · 蒸馏**

在流水线页选择模型，点击 **开始蒸馏**。十个阶段实时显示进度、输出摘要与错误；支持暂停、取消、重试。审核通过后编译阶段另含五个步骤。

**第 5 步 · 审核**

这是最需要人工投入的环节，也是产品价值所在：

- 左侧列表按维度与状态筛选，右侧显示断言原文与**可定位的证据引用**
- 断言文字可直接修订（模型抽取常有措辞偏差）
- 批准 / 驳回 / 仅保存修订
- 证据缺失的断言会明确警告，建议驳回

**第 6 步 · 编译与导出**

编译会生成 Skills、运行静态校验、打包人物包。默认只包含短引用（≤240 字符）与哈希，**不包含原始全文**。

### 频率与成本控制

| 场景 | 建议 |
| --- | --- |
| 首次蒸馏 | 全量资料 + LLM 抽取，质量最高 |
| 补充少量资料 | 只上传新增文件后重新蒸馏；已审核断言保持不变 |
| 调整审核结论 | 修改断言状态或文字后重新编译即可，无需重跑蒸馏 |
| 仅调提示词 | 目前需重新蒸馏（提示词版本尚未纳入缓存键） |

重新蒸馏对同一批资料是幂等的：无新增断言时会报告 `heuristic_no_new` 并保留审核状态，不会误报失败。

---

## 部署

仓库内的 `deploy/` 提供三种形态，**同一镜像，差异只在环境变量**。

| 形态 | 数据库 | 任务执行 | 适用 |
| --- | --- | --- | --- |
| 单机本地 | SQLite | 进程内 worker | 个人使用，零外部依赖 |
| Docker Compose | SQLite | api / worker 分离 | 单主机、局域网小团队 |
| Compose + PostgreSQL | PostgreSQL | 多 worker 扩容 | 云托管、并发任务 |

### Docker Compose

```bash
cp deploy/.env.example deploy/.env    # 按需修改
docker compose -f deploy/compose.yaml --env-file deploy/.env up -d --build
```

启动顺序由编排保证：`migrate` 一次性服务成功退出 → `api` 健康 → `worker` 启动。

### PostgreSQL 多 worker

```bash
docker compose -f deploy/compose.postgres.yaml --env-file deploy/.env up -d --scale worker=4
```

队列就是数据库表，不引入 Redis/Celery。多副本安全由条件更新抢占与 `lease_epoch` 围栏令牌保证。

### 备份

```bash
./deploy/scripts/backup.sh /backups              # SQLite 用 VACUUM INTO，避免 WAL 半写状态
./deploy/scripts/restore.sh /backups/distill-20261030-120000
```

备份必须同时覆盖 `app.db`、`sources/`、`skills/`、`exports/` 与 **`.secret.key`**——缺少密钥会导致已保存的 API Key 全部无法解密。

详细说明（升级、回滚、故障排查、安全清单）见 **[docs/deployment.md](docs/deployment.md)**。

---

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│  React 19 + Vite + Tailwind                                 │
│  仪表盘 · 资料库 · 画像 · 流水线 · 审核 · Skills · 评估 · 导出 │
└───────────────────────────┬─────────────────────────────────┘
                            │ REST + SSE
┌───────────────────────────▼─────────────────────────────────┐
│  FastAPI                                                    │
│  ├─ Parser / Normalizer / Redactor    解析·规范化·脱敏        │
│  ├─ Distillation Orchestrator         阶段引擎 + checkpoint   │
│  │   ├─ Evidence Extractor            断言 + 证据定位         │
│  │   ├─ Conflict Resolver             冲突候选               │
│  │   ├─ Skill Compiler                SKILL.md + refs + evals│
│  │   └─ Evaluation Runner             LLM-as-judge           │
│  ├─ LLM Adapter Registry              Responses/Chat/Claude/Gemini │
│  └─ Job Service                       抢占·租约·围栏·恢复     │
└───────────────────────────┬─────────────────────────────────┘
                            │
        ┌───────────────────┴───────────────────┐
        │                                       │
┌───────▼────────┐                    ┌─────────▼──────────┐
│ SQLite / PG    │                    │ 本地文件 / 对象存储  │
│ + sqlite-vec   │                    │ sources·skills·exports│
└────────────────┘                    └────────────────────┘
```

**设计取舍**

- 前端不直接调用模型供应商，所有密钥留在后端。
- Adapter 只返回规范化结果，不写项目文件；LLM 输出先过 JSON Schema 校验。
- Worker 与 HTTP 生命周期分离，关闭浏览器后任务继续。
- 迁移用 Alembic，启动时自动识别 0.1.0 的 `create_all` 遗留库并 stamp，不重建表。

### 技术栈

| 层 | 选型 |
| --- | --- |
| 后端 | FastAPI 0.115+ · SQLAlchemy 2.0 · Pydantic v2 · Alembic |
| 数据库 | SQLite（WAL）· PostgreSQL（可选）· sqlite-vec |
| 嵌入 | BAAI/bge-small-zh-v1.5（fastembed ONNX，512 维） |
| 前端 | React 19 · Vite 7 · Tailwind 3 · TanStack Query · React Router 7 |
| OCR / ASR | RapidOCR + pypdfium2 · faster-whisper |

代码规模：56 个源文件，约 13,900 行。

### 目录结构

```
apps/api/app/
  main.py            入口、静态前端、健康检查、请求上下文
  config.py          环境变量与路径解析
  db.py              引擎、迁移引导、健康检查
  models.py          SQLAlchemy 数据模型
  errors.py          统一错误结构
  logging_setup.py   日志（text / json）
  worker.py          原子抢占、租约心跳、围栏恢复
  pipeline.py        阶段引擎、证据、编译、版本快照、打包
  parsers.py         文档 / 聊天 / 代码 / OCR / ASR 解析与分块
  ingest.py          资料导入与解析落库
  vector_store.py    嵌入、sqlite-vec 索引、可移植序列化
  llm.py             四协议适配器、错误映射
  judge.py           LLM-as-judge rubric
  routers/           项目·资料·Provider·任务·审核·检索·Skills·导出·运维
  migrations/        Alembic（0001 基线，0002 租约与版本历史）
apps/web/src/        React 工作台（桌面常驻侧栏，窄屏抽屉）
deploy/              Dockerfile · compose ×2 · 启动/备份/恢复脚本
docs/                部署手册 · 技术评审记录
scripts/             模型下载 · 本地 mock LLM
```

---

## API

前缀 `/api/v1`。交互式文档：`http://127.0.0.1:8000/docs`（`DISTILL_ENV=production` 时关闭）。

<details>
<summary><b>展开端点列表</b></summary>

**运维**

```
GET  /health                        存活探针（不触碰数据库）
GET  /ready                         就绪探针（数据库/目录/向量）
GET  /stats                         运行时统计
GET  /usage                         Token 用量汇总
```

**项目与资料**

```
GET  /dashboard                     POST /demo
GET  /projects                      POST /projects
GET  /projects/{id}                 PATCH /projects/{id}      DELETE /projects/{id}
GET  /projects/{id}/persona
POST /projects/{id}/sources         GET  /projects/{id}/sources
GET  /sources/{id}/preview          POST /sources/{id}/parse  DELETE /sources/{id}
PATCH /chunks/{id}                  排除 / 恢复文本块
```

**检索**

```
GET  /projects/{id}/search?q=...
POST /projects/{id}/index?force=true
GET  /projects/{id}/vector-status
```

**模型配置**

```
GET  /providers      POST /providers
PATCH /providers/{id}    DELETE /providers/{id}
POST /providers/{id}/test
```

**任务**

```
POST /projects/{id}/jobs
GET  /jobs/{id}                      GET  /jobs/{id}/events      SSE
POST /jobs/{id}/pause | resume | cancel | retry
```

**审核**

```
GET  /projects/{id}/claims           PATCH /claims/{id}
POST /projects/{id}/claims/bulk-review
GET  /projects/{id}/conflicts        PATCH /conflicts/{id}
```

**Skills 与评测**

```
GET  /projects/{id}/skills           POST /skills/{id}/validate
POST /skills/{id}/evaluate
GET  /skills/{id}/versions
GET  /skills/{id}/diff?from_version=1&to_version=2
GET  /projects/{id}/eval-cases       GET  /projects/{id}/eval-runs
```

**导出**

```
GET  /projects/{id}/exports
GET  /exports/{id}/download
```

错误响应统一为：

```json
{
  "detail": "项目不存在",
  "error": {
    "code": "NOT_FOUND",
    "message": "项目不存在",
    "request_id": "a1b2c3d4e5f6",
    "details": {}
  }
}
```

</details>

---

## 测试

```bash
uv run --project apps/api pytest apps/api/tests    # 36 passed
pnpm --dir apps/web build                          # tsc --noEmit && vite build
```

<details>
<summary><b>测试覆盖范围</b></summary>

| 文件 | 覆盖 |
| --- | --- |
| `test_parsers.py` | 各格式解析、分块、脱敏、扫描图片 OCR |
| `test_llm.py` | 四种协议请求形状与错误映射 |
| `test_api_flow.py` | 全流程：蒸馏 → 审核 → 编译 → 校验 → 导出；重跑幂等；删除资料使证据失效 |
| `test_judge.py` | rubric 评分与聚合指标 |
| `test_worker_lease.py` | 并发抢占唯一性、epoch 单调递增、过期租约回收、旧 epoch 拒写 |
| `test_migrations.py` | 空库基线、遗留库 stamp 升级、重复 upgrade 幂等、downgrade |
| `test_ops_contract.py` | 健康检查语义、请求 ID、错误结构、超限上传清理、块排除审计 |

**重点不是覆盖率，而是"错了很难发现"的区域**：并发抢占出错会静默产生重复执行与覆盖；迁移出错会毁掉用户数据；阶段计数出错会让用户误判资料损坏。这三类都有专门断言。

</details>

---

## 验收记录

<details>
<summary><b>2026-10-30 · 0.2.0 端到端</b></summary>

- **全链路**：新建项目 → 上传 Markdown（7 块 / 14 解析块）→ 蒸馏（16 断言，16 条证据全部定位，0 冲突）→ 批量批准 → 编译（3 Skills，静态校验 3/3，导出包 21 文件）
- **块排除**：排除 1 块后索引 7 → 6，`s05_chunk` 如实报告 `excluded_chunks: 1`，审计写入 `chunk.exclude`
- **版本差异**：驳回 1 条断言后重编生成 v2，diff 显示 `removed 1 / claims_removed: [clm_...]` 并定位到被删的原则行
- **重复蒸馏**：返回 `mode: heuristic_no_new`、`duplicates: 16`，状态 `waiting_for_review` 而非 `failed`，已批准断言不变
- **遗留库升级**：0.1.0 数据库（2 个项目）自动 stamp 并升级到 `0002`，新增 4 列与 `skill_versions` 表，数据完整
- **导出包审计**：无密钥、无 Bearer、无私钥、无绝对路径；仅含短引用与标题路径，不含原始全文；含"AI 辅助"声明
- **响应式**：1440px / 1024px / 768px 均无横向溢出，侧栏在 `lg` 断点切换为抽屉

</details>

<details>
<summary><b>2026-10-29 · 0.1.0 基线</b></summary>

- **扫描 PDF OCR**：Microsoft YaHei 渲染的无文本层 PDF，`pypdfium2 + rapidocr` 输出正确文本，置信度约 0.99
- **音频 ASR**：Windows SAPI 生成 WAV，`faster-whisper`（base）转写成功
- **向量检索**：`bge-small-zh-v1.5` + `sqlite-vec`，语义查询命中相关证据块，模式 `vec`

</details>

---

## 安全与边界

**这是本地单用户工具，默认不面向公网。**

- 默认只监听 `127.0.0.1`，**没有登录与多用户隔离**。局域网共享需自带访问控制（反向代理 + 认证、VPN）。
- 原始资料、派生文本、导出包分开存放，导出默认不含原文全文。
- 真实人物资料必须具备合法授权；导出包包含"AI 辅助、非本人撰写/背书"声明。
- 自动脱敏基于正则，不是绝对保证——导出前请人工复核。
- 资料中的提示注入不会获得工具执行权限，但不能排除模型输出被污染。

---

## 已知限制

| 限制 | 影响 | 现状 |
| --- | --- | --- |
| 无认证 / 多用户 | 不能直接公网部署 | 依赖外部访问控制 |
| 无 pgvector 索引 | PostgreSQL 下向量检索为精确扫描 | 十万块以内可接受 |
| OCR/ASR 未随镜像分发 | 需单独构建带 extras 的镜像 | 模型体积过大 |
| 提示词版本未纳入缓存键 | 调提示词需重新蒸馏 | 计划中 |
| 无预算上限与费用换算 | 只统计 Token，不乘单价 | 单价表易过时，宁缺勿错 |
| 多平台兼容仅静态校验 | 未对每个运行时做真实安装测试 | `skills-ref validate` 通过 |
| LLM-as-judge 未做一致性测量 | 同案重跑评分可能有差异 | 建议固定 judge 模型 |

Docker 镜像与 PostgreSQL 模式已提供配置，但**未在有 Docker 守护进程的环境完成实机构建**，配置正确性待验证。详见 [技术评审记录](docs/technical-review-0.2.md) 第八节。

---

## 文档

| 文档 | 内容 |
| --- | --- |
| [docs/deployment.md](docs/deployment.md) | 三种部署形态、配置项陷阱、升级回滚、备份恢复、故障排查、上线安全清单 |
| [docs/technical-review-0.2.md](docs/technical-review-0.2.md) | 决策依据来源、候选方案对比与否决理由、实机缺陷记录、未验证事项 |

---

## 参考

- [Agent Skills Specification](https://agentskills.io/specification) — `SKILL.md` 格式与渐进式披露约定
- [agentskills/skills-ref](https://github.com/agentskills/agentskills/tree/main/skills-ref) — 官方校验器（Apache-2.0）
- [anthropics/skills](https://github.com/anthropics/skills) — 技能示例参考
- [sqlite-vec](https://github.com/asg017/sqlite-vec) · [pgvector](https://github.com/pgvector/pgvector) — 向量检索选型对比

## 许可

[MIT License](LICENSE) © 2026 suringyun

可自由用于商业与非商业项目，唯一要求是保留版权声明与许可声明。

**使用他人资料前请注意**：本工具是数据处理工具，不授予你对所蒸馏资料的使用权。
真实人物的访谈、笔记、聊天记录等，需自行确保已获得合法授权。导出包默认包含
"AI 辅助、非本人撰写/背书"的声明，请勿移除。