# 部署与运维

同一份代码与同一镜像支持三种形态。差异只在环境变量与编排文件，不存在分支版本。

| 形态 | 数据库 | 任务执行 | 适用场景 |
| --- | --- | --- | --- |
| 单机本地 | SQLite | API 进程内 worker | 个人使用；零外部依赖 |
| Docker Compose | SQLite | api / worker 分离 | 单主机、局域网小团队 |
| Compose + PostgreSQL | PostgreSQL | 多 worker 水平扩容 | 云托管、并发任务 |

## 1. 单机本地

```bash
# macOS / Linux / WSL / Git Bash
./deploy/scripts/start.sh

# Windows PowerShell
powershell -ExecutionPolicy Bypass -File deploy\scripts\start.ps1
```

脚本依次执行：安装依赖 → 首次构建前端 → `alembic upgrade head` → 启动 uvicorn。
默认监听 `127.0.0.1:8000`，通过 `DISTILL_BIND` / `DISTILL_PORT` 修改。

## 2. Docker Compose（SQLite）

```bash
cp deploy/.env.example deploy/.env
# 编辑 deploy/.env：至少确认 DISTILL_BIND 与 DISTILL_INLINE_WORKER=false
docker compose -f deploy/compose.yaml --env-file deploy/.env up -d --build
docker compose -f deploy/compose.yaml logs -f api
```

启动顺序由 `depends_on` 保证：

```
migrate (一次性, 成功退出) → api (healthy) → worker
```

三个关键点：

- **`migrate` 独立成服务**。让每个 API 进程在启动时各跑一次迁移会争抢 DDL 锁，
  且失败表现为运行期报错而不是部署失败。一次性服务让失败暴露在部署阶段。
- **`api` 关闭内嵌 worker**（`DISTILL_INLINE_WORKER=false`）。否则 API 进程与
  `worker` 服务会同时消费同一队列，虽然租约能防重复执行，但会浪费连接与内存。
- **健康检查打 `/ready` 而不是 `/health`**。前者校验数据库连接、可写目录与向量后端，
  依赖不可用时能被正确判定为不健康并停止接流量。

### 局域网团队使用

```bash
DISTILL_BIND=0.0.0.0
```

**前提是已有访问控制。** 当前版本没有登录与多用户隔离：任何能访问端口的人都可以
上传资料、读取全部证据、导出人物包。请置于可信网络，并在前面加反向代理与认证
（如 Nginx + OAuth2 Proxy、Tailscale、内网 VPN）。不要把 `0.0.0.0` 直接暴露到公网。

## 3. PostgreSQL（多 worker）

```bash
cp deploy/.env.example deploy/.env
# 必填 POSTGRES_PASSWORD；不要用默认值
docker compose -f deploy/compose.postgres.yaml --env-file deploy/.env up -d --scale worker=4
```

镜像需要包含 PostgreSQL 驱动。构建时加 `--build-arg DISTILL_EXTRAS=postgres`，
或在 `compose.postgres.yaml` 的 `build.args` 中设置；`pyproject.toml` 已声明
`postgres` 可选依赖（`psycopg[binary]`）。

### 为什么不需要 Redis / Celery

队列就是 `jobs` 表。多副本安全由两个机制保证：

1. **原子抢占**：`UPDATE jobs SET status='running' ... WHERE id=? AND status='queued'`，
   只有一个事务看到 `rowcount == 1`。SQLite（单写者）与 PostgreSQL（行锁）都成立，
   不依赖 `RETURNING` 或 `FOR UPDATE SKIP LOCKED`。
2. **围栏令牌**：`lease_epoch` 每次抢占递增。所有阶段写入都以当前 epoch 为条件，
   停顿超时的旧 worker 恢复后发现 epoch 变化即停止写入，无法覆盖新 worker 的结果。

心跳线程在模型调用期间持续续租，避免单个长阶段被误判为失效。

选择这套方案而非消息队列的理由：任务量级在数百到数千，数据库轮询的开销远低于
引入 broker 的运维成本；且任务状态与业务数据同库，暂停/取消/重试可在一个事务里完成。
当观测到队列表争用或轮询成为瓶颈时再考虑替换。

### 向量检索的降级

PostgreSQL 模式下 sqlite-vec 不可用，检索自动回退到对 `chunk_embeddings` 的精确
余弦扫描。中文资料规模在十万块以内通常可接受（单次查询数十毫秒）。如需 pgvector：

1. 在 `db` 服务中启用 `pgvector/pgvector` 镜像；
2. 新增迁移创建 `vector(512)` 列与 HNSW 索引；
3. 在 `vector_store.py` 增加 `pgvector` 后端实现（`VectorIndex` 接口边界已就位）。

向量以裸 float32 小端存储，`dim` 与 `model` 同表记录，迁移时按
`len(blob) == dim * 4` 校验即可。

## 4. 配置项

完整清单见 `deploy/.env.example`。必须理解的几项：

| 变量 | 作用 | 误配后果 |
| --- | --- | --- |
| `DISTILL_INLINE_WORKER` | 是否在 API 进程内跑 worker | 与独立 worker 重复消费 |
| `DISTILL_WORKER_LEASE_SECONDS` | 租约时长 | 小于单阶段耗时会导致任务被接管 |
| `DISTILL_BIND` | 监听地址 | `0.0.0.0` 且无认证即为公网暴露 |
| `DISTILL_DATA_DIR` / `DISTILL_EXPORT_DIR` | 持久化目录 | 未挂载卷则重建容器丢数据 |
| `DISTILL_DATABASE_URL` | 留空用 SQLite | 指向错误库会导致找不到迁移版本 |
| `DISTILL_ENV` | `production` 关闭 `/docs` | 生产环境暴露 API 文档 |

## 5. 升级

```bash
# 1. 备份（务必先做）
./deploy/scripts/backup.sh /backups

# 2. 拉取新代码，重建镜像
docker compose -f deploy/compose.yaml --env-file deploy/.env build

# 3. 迁移在启动时自动执行；观察结果
docker compose -f deploy/compose.yaml --env-file deploy/.env up -d
docker compose -f deploy/compose.yaml logs migrate
```

从 0.1.0 升级会被自动识别：该版本用 `create_all` 建表、没有 `alembic_version`。
启动逻辑检测到"有业务表但无版本记录"时先 `stamp` 基线，再执行增量迁移，
**不会重建表，不会丢数据**。已在包含 2 个项目的真实库上验证。

### 回滚

```bash
# 数据库回退一个版本
docker compose -f deploy/compose.yaml exec api alembic downgrade -1

# 完整回滚：还原备份
./deploy/scripts/restore.sh /backups/distill-20261030-120000
```

注意：`downgrade` 只回退 schema，不会恢复被新版本写入的数据。
生产回滚应以备份还原为准。

## 6. 备份与恢复

```bash
./deploy/scripts/backup.sh /backups           # 生成 /backups/distill-<时间戳>/
./deploy/scripts/restore.sh /backups/distill-20261030-120000
```

备份内容与原因：

| 内容 | 为什么必须备份 |
| --- | --- |
| `app.db` | 项目、断言、证据、版本历史。用 `VACUUM INTO` 而非文件复制，避免 WAL 下的半写状态 |
| `sources/` | 原始资料，数据库只存路径 |
| `skills/` | 编译产物目录 |
| `exports/` | 已生成的导出包 |
| `.secret.key` | **解密 API Key 的唯一凭据**。丢失后所有 Provider 需重新录入 |

恢复脚本会先给当前库留一份 `.pre-restore-<时间戳>` 兜底，再覆盖。
恢复后需执行 `alembic upgrade head` 让 schema 追平。

`restore.sh` 在覆盖前要求输入 `yes`；自动化场景设 `DISTILL_FORCE=yes`。

## 7. 故障排查

**服务起不来，日志停在迁移**
`alembic_version` 与代码版本不匹配。检查 `DISTILL_DATABASE_URL` 是否指向预期库。

**`/ready` 返回 503**
响应体 `checks` 会指出具体组件：`database` 连不上、`data_dir`/`export_dir` 不可写、
或 `vector` 降级。注意 `vector` 降级不会导致 503，只有数据库与目录问题会。

**任务一直 `queued`**
没有 worker 在跑。检查 `DISTILL_INLINE_WORKER` 或 `worker` 服务日志。

**任务卡在 `running` 且不结束**
租约到期后会被自动回收。若频繁发生，说明 `DISTILL_WORKER_LEASE_SECONDS`
小于实际阶段耗时，调大该值。

**检索结果不准**
`/ready` 的 `vector.backend` 若为 `hash-ngram`，说明嵌入模型未加载，正在使用
哈希向量兜底。执行 `uv run --project apps/api python scripts/fetch_embedding_model.py`
预置模型。

**中文乱码**
容器 locale 已固定 UTF-8；若挂载了外部卷中的旧文件，确认文件本身编码
（解析器会依次尝试 utf-8-sig / utf-8 / gb18030 / big5）。

## 8. 安全清单

上线前逐项确认：

- [ ] `DISTILL_BIND` 不是 `0.0.0.0`，或前面有认证代理
- [ ] `DISTILL_ENV=production`（关闭 `/docs`）
- [ ] `POSTGRES_PASSWORD` 已改为强密码
- [ ] `deploy/.env` 与 `.env` 未提交到 Git
- [ ] `.secret.key` 已纳入备份且权限为 0600
- [ ] 数据卷挂载到持久化存储，不是容器可写层
- [ ] 若有真实人物资料，已获得合法授权并记录在项目定义中
- [ ] 导出前人工确认无未授权隐私内容

## 9. 当前限制

- 无内置认证与多用户隔离；团队使用依赖外部访问控制。
- 未实现项目级预算上限与费用换算（只统计 Token，不乘单价）。
- pgvector 索引尚未接入，PostgreSQL 下向量检索为精确扫描。
- OCR/ASR 需单独构建带 extras 的镜像，模型不随镜像分发。
- 多平台兼容性仅通过 `skills-ref` 静态校验，未对每个 Agent 运行时做真实安装测试。