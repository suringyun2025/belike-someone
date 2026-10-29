<div align="center">

# 蒸馏平台 · Belike Someone

**把一个人的专业能力，蒸馏成可审计、可测试、可移植的 Agent Skills**

从访谈、笔记、聊天记录、代码与扫描件中提取方法、决策规则与表达风格；
每条结论都能追溯到原文位置，经人工审核后才编译成技能包。

[![在线体验](https://img.shields.io/badge/在线体验-who--is--spy.online-0f766e?style=for-the-badge)](https://who-is-spy.online)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![Tests](https://img.shields.io/badge/tests-95%20passed-brightgreen)](#测试)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

</div>

---

## 在线体验

**https://who-is-spy.online**

填你自己的模型 Endpoint 与 API Key 即可进入，不需要注册。

> 服务器只有 2 核 1.9GB，所以**一次只服务一个人**，每人默认 30 分钟。
> 有人在用时提交会进入队列，页面显示位次与预计等待；轮到你时自动进入。
> 你的 Key 与上传的资料在体验结束、超时或服务重启时**一并删除**。

支持的四类端点：

| 协议 | 典型服务 |
| --- | --- |
| OpenAI Chat Completions | DeepSeek、Qwen、硅基流动、vLLM、Ollama |
| OpenAI Responses | OpenAI 新版接口 |
| Anthropic Messages | Claude |
| Gemini generateContent | Google Gemini |

---

## 核心功能

### 证据化蒸馏，而不是写一段提示词

常规做法是用一段文字描述某个人，但无法验证它说得对不对。这里改成**可追溯的流水线**：

```
上传资料 → 解析分块 → 抽取断言 → 定位证据 → 人工审核 → 编译 Skill
```

每条断言都记录来源的**页码、标题与字符区间**，因此任何进入 Skill 的规则都能回答：
来自哪份文件哪一段、是原文直述还是模型推断、谁批准了它。

六类能力维度分开抽取，避免「风格」和「专业判断」混为一谈：

`专业能力` · `决策方式` · `工作流程` · `表达风格` · `边界原则` · `知识领域`

### 异构资料接入

PDF、DOCX、XLSX、Markdown、HTML、CSV、JSON/JSONL、聊天记录、20 种编程语言扩展名。
扫描件与图片走 OCR（RapidOCR），音视频走 ASR（faster-whisper）——都是可选依赖，
未安装时明确标记而不是静默失败。

### 一个资料块出错，不必删掉整份文件

PDF 里有一页 OCR 识别错了？排除那一块即可。排除后它不再进入模型请求与向量索引，
并在审计日志留痕。

### 编译成标准 Agent Skills

输出 `SKILL.md + references/ + evals/`，对齐 [Agent Skills](https://agentskills.io/) 规范，
并用官方 `skills-ref` 校验。每次编译写入不可变版本快照，可对比两版之间的逐行差异与断言增删。

> 内容没变时不会虚增版本号——按 `SKILL.md` 的哈希判断。

### 用模型评测模型

LLM-as-judge 从四个维度打分：任务完成、证据忠实、人格保真、边界合规。
触发判断单独统计准确率。生成模型与评审模型可以分开选。

### 跑得住的小服务器

蒸馏是重任务，并发两个就会把 1.9GB 内存拖进 swap。所以：

- **全局并发上限 + 单用户上限**，超出的任务排队而不是被拒绝
- **内存地板**：可用内存低于阈值时暂不启动新任务，等它回升
- **排队位次可见**：前端显示「第 N 位 · 预计 M 分钟」，而不是转不完的圈
- 任务级暂停、恢复、取消、重试；崩溃后按租约恢复，停顿的 worker 无法覆盖新结果

### 默认安全

- 模型 Key 加密存储，接口只返回「已配置」与掩码，明文永不回传
- 导出包默认只含短引用与哈希，不含原文全文；导出前扫描密钥与 PII
- 用户填写的 Endpoint 做 SSRF 校验：拒绝内网、本机、链路本地与保留网段
- ZIP 解压防路径穿越与压缩炸弹，上传分片流式落盘并前置限流

---

## 本地部署

### 前置条件

- Python **3.12**（由 [uv](https://docs.astral.sh/uv/) 管理）
- Node.js `^20.19.0 || >=22.12.0`（Vite 7 要求）
- pnpm

```bash
git clone https://github.com/suringyun2025/belike-someone.git
cd belike-someone

uv python install 3.12
uv sync --project apps/api
pnpm install --dir apps/web
```

### 启动

```bash
# 终端 1：API + 内置 Worker
uv run --project apps/api uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000

# 终端 2：前端
pnpm --dir apps/web dev
```

打开 http://127.0.0.1:5173 ，API 文档在 http://127.0.0.1:8000/docs 。

本地模式默认**无需登录**：只监听 `127.0.0.1`，数据留在本机。

### 五分钟跑通

1. 点 **创建示例项目** → 已有两份虚构资料
2. 在「模型与 API」填入你的 Endpoint（不配置也能跑，会退化为离线启发式抽取）
3. 点 **开始蒸馏**，观察 10 个阶段的实时进度
4. 在「审核收件箱」逐条看断言与证据，批准或驳回
5. 点 **编译 Skills**，再做 LLM 评测
6. 在「导出」下载人物包 ZIP

### 可选能力

```bash
# 语义检索：本地 BGE 中文嵌入模型（fastembed/ONNX，512 维）
uv run --project apps/api python scripts/fetch_embedding_model.py

# OCR：扫描 PDF 与图片
uv sync --project apps/api --extra ocr

# ASR：音视频转录
uv sync --project apps/api --extra asr
```

未安装模型时向量检索自动回退到哈希向量，功能可用但召回质量下降；OCR/ASR 会标记
`needs_ocr` / `needs_asr`，不会静默失败。

---

## 部署成公开体验站

体验站与本地版是**同一份代码**，通过环境变量切换：
`DISTILL_SANDBOX=true` 之后，系统变成「一个座位、访客自带 Key、用完即销毁」。

```bash
DISTILL_SANDBOX=true
DISTILL_SANDBOX_VISIT_MINUTES=30     # 单次体验时长
DISTILL_SANDBOX_HTTPS_ONLY=true      # 只接受 https 端点
DISTILL_SANDBOX_MAX_PROJECTS=3
DISTILL_MAX_CONCURRENT_JOBS=1        # 小服务器必须为 1
DISTILL_MIN_FREE_MB=280              # 内存地板
DISTILL_SECRET_KEY=<稳定的随机串>     # 换了它，历史密文就无法解密
```

生命周期：访客提交端点 → 服务端**真实调用一次**验证可用 → 占用座位或排队 →
到期 / 主动结束 / 服务重启时删除其全部数据（资料、断言、Skill、导出包、Key、账号）。

`deploy/` 下有 systemd 单元、nginx 配置（TLS、HSTS、CSP、登录接口限流、SSE 不缓冲）
与 Docker Compose 编排。生产实例使用的是 systemd + nginx。

---

## 技术栈

| 层 | 选型 |
| --- | --- |
| 后端 | FastAPI 0.115 · SQLAlchemy 2.0 · Alembic · SQLite / PostgreSQL |
| 检索 | sqlite-vec · bge-small-zh-v1.5（fastembed ONNX，512 维） |
| 前端 | React 19 · Vite 7 · Tailwind 3 · TanStack Query |
| 解析 | pypdf · python-docx · openpyxl · BeautifulSoup · RapidOCR · faster-whisper |

**刻意没有引入的东西**：Redis、Celery、Kubernetes。队列就是数据库表，
在单机规模下这些中间件只会增加故障面，不会提高可靠性。

---

## 测试

```bash
uv run --project apps/api pytest apps/api/tests    # 95 passed
pnpm --dir apps/web build                          # tsc + vite build
```

重点覆盖「错了很难发现」的地方：越权访问、并发抢占与租约、迁移幂等与回滚、
重复蒸馏、体验座位的排队与销毁、SSRF 拦截。

---

## 安全边界

- 本地模式只监听 `127.0.0.1`，无登录；**不要直接暴露到公网**
- 体验站每位访客的数据在会话结束时删除，但**磁盘上的残留扇区不由本系统负责**
- 自动脱敏基于正则，不是绝对保证，导出前请人工复核
- 资料中的提示注入不会获得工具执行权限，但不能排除模型输出被污染
- **不在防护范围**：主机被 root 攻陷、数据库文件被直接读取
- 真实人物资料必须具备合法授权；导出包包含「AI 辅助，非本人撰写/背书」声明

---

## 项目结构

```text
apps/api/app/
  sandbox.py         体验座位：排队、晋升、销毁
  pipeline.py        10 阶段蒸馏、证据定位、Skills 编译、打包
  parsers.py         文档/聊天/代码/OCR/ASR 解析与分块
  llm.py             四种协议的适配器与错误映射
  judge.py           LLM-as-judge 评分与聚合
  vector_store.py    BGE 嵌入、sqlite-vec 索引与语义检索
  worker.py          并发准入、租约围栏、崩溃恢复
  routers/           项目、资料、任务、审核、检索、Skills、导出、体验
apps/web/            React 工作台
deploy/              systemd / nginx / Docker 编排
docs/                部署手册与安全设计
```

---

## 文档

- [部署与运维](docs/deployment.md)
- [多用户与隔离设计](docs/multiuser-security.md)
- [技术评审记录](docs/technical-review-0.2.md)

---

## 许可

[MIT](LICENSE)