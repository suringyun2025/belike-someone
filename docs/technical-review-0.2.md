# 0.2.0 技术评审与决策记录

记录本次升级中每个关键判断的依据、取舍与被否定的方案。目的是让后来者能质疑结论，
而不是只看到"已经这样做了"。

## 一、判断依据的来源分层

| 来源 | 用于 | 可信度处理 |
| --- | --- | --- |
| Agent Skills 官方规范（agentskills.io/specification） | SKILL.md 字段约束、目录约定、渐进式披露 | 直接采用；给出具体数值限制 |
| skills-ref 源码与 README（Apache-2.0） | 校验器实际行为 | 确认它比较目录名与 `name`，据此修正自带校验 |
| SQLAlchemy / Alembic / FastAPI 官方文档 | 迁移、依赖注入、生命周期 | 直接采用 |
| 第三方对比文章（sqlite-vec vs pgvector） | 向量后端选型 | 多篇交叉；结论一致才采纳 |
| 独立架构评审（外部 LLM） | 优先级排序、遗漏项 | 逐条质疑；只采纳能自证的部分 |

**未采纳的结论举例**：评审建议引入 `claimed_by / heartbeat_at / attempt / max_attempts /
cancel_requested_at / error_code` 六个字段。实际只加了 `worker_id / lease_expires_at /
lease_epoch` 三个——`attempt` 已由 `StageRun.attempt` 承担，`max_attempts` 与
`cancel_requested_at` 当前无消费方（`cancel_requested` 布尔已够用），
`error_code` 在阶段级已有 `run.error`，过早拆分只会增加空字段。

## 二、任务队列：为什么不用 Celery / Redis

**问题**：原实现 `SELECT ... WHERE status='queued' LIMIT 1` 后 `UPDATE`，
两个 worker 可先后读到同一行。单进程侥幸安全，`uvicorn --workers 4` 即暴露。

**候选方案对比**：

| 方案 | 优点 | 否决理由 |
| --- | --- | --- |
| 引入 Redis + Celery | 成熟、生态好 | 新增 broker 运维；任务状态与业务数据跨库，暂停/取消无法单事务完成；当前量级（百到千级）用不上 |
| `SELECT FOR UPDATE SKIP LOCKED` | PostgreSQL 标准做法 | SQLite 不支持，会迫使单机模式换库 |
| `UPDATE ... RETURNING` | 单语句原子 | SQLite 3.35+ 才有，旧库与部分嵌入式构建缺失 |
| **条件 UPDATE + rowcount 判定** | 两种数据库行为一致 | 需一次额外查询取 epoch，成本可忽略 |

**采纳**：条件 `UPDATE`，以 `rowcount == 1` 判定抢占成功。SQLite 靠单写者、
PostgreSQL 靠行锁，语义相同。

**补充发现的缺陷**：仅原子抢占不足。worker A 卡在模型调用中、租约过期、worker B 接管，
A 恢复后会覆盖 B 的结果。这是评审提到但原始实现完全缺失的一层。

**解决**：`lease_epoch` 围栏令牌。每次抢占递增，所有写入以当前 epoch 为条件；
A 恢复后发现 epoch 变化即抛 `LeaseLostError` 并停止写入。心跳线程在模型调用期间续租，
避免单个长阶段被误判失效。

**未做**：不承诺"恰好一次"。数据库提交与第三方 LLM 请求之间无法原子化，
重复调用可能发生。已实现的是"阶段级幂等"：输入哈希未变且结果完整时复用 checkpoint。
文档中明确写为 at-least-once。

## 三、迁移：为什么需要处理遗留库

**问题**：0.1.0 用 `create_all` 建表，没有 `alembic_version`。直接跑基线迁移会
`table already exists` 失败。

**候选方案**：

| 方案 | 否决理由 |
| --- | --- |
| 要求用户手动 `alembic stamp` | 升级路径不能依赖用户读文档；出错即在真实数据上演 |
| 删库重建 | 直接丢用户数据，不可接受 |
| **启动时自动检测并 stamp** | 需要可靠的检测条件 |

**检测条件**：`projects` 表存在 且 `alembic_version` 不存在或为空。
后者是关键——Alembic 首次连接会创建空版本表，若只看"表是否存在"会漏判。
这个 bug 在首次实现时就出现了，靠实机验证发现。

**迁移内容拆分**：`0001_baseline` 覆盖全新库的完整 schema；`0002` 只做增量
（租约列、`skill_versions` 表），并用 `inspect` 守卫以保持幂等。这样遗留库
`stamp 0001` 后只需跑 `0002`。

**验证**：4 个测试覆盖空库基线、遗留库升级（断言数据保留）、重复 upgrade、downgrade。
downgrade 时发现索引先于列删除会导致 batch 重建失败，已修正顺序。

## 四、上传：内存炸弹的修复与边界

**问题**：`await upload.read()` 先整读进内存再判断大小。256 MB 上限在并发下
等于 256 MB × 并发数的内存占用。

**采纳**：1 MiB 分片流式落盘 + 累计校验，超限立即 `raise` 并删除临时文件。

**未采纳**：评审建议的 `aiofiles`。写入是本地磁盘、`UploadFile.file` 本身是
同步文件对象，引入 `aiofiles` 只会把同步 IO 包一层，增加依赖而无收益。
若未来接入对象存储，再在 `BlobStore` 边界替换。

**修复中发现的第二个 bug**：`finally` 只 `close()` 不 `unlink()`，超限时
临时文件残留。改为 `except BaseException: close + unlink`。
测试用"运行前后临时文件集合差集"断言，避免历史残留导致误判。

## 五、向量后端：解除硬绑定而非重写

**问题**：`sqlite_vec.serialize_float32()` 生成的字节与 sqlite-vec 内部格式耦合，
且 `vec_available()` 无条件查 `sqlite_master`，PostgreSQL 下必抛异常。

**采纳**：改为 `np.float32.tobytes()`（小端、可移植），`vec_available()` 在
非 SQLite 时直接返回 False。检索链路已有 cosine fallback，无需新代码。

**未采纳**：现在重写为 pgvector。理由：当前用户规模用不上 HNSW；精确扫描在
十万块以内可接受；`VectorIndex` 接口边界已就位，接入时只需实现后端。

**记录的数据契约**：`chunk_embeddings` 存 `dim`、`model`、`vector`(blob)。
迁移校验条件为 `len(blob) == dim * 4`。这三点是跨库可解释性的最小集合。

## 六、产品深化：为什么选这三件事

评审给出"若只能做三件"。最终落地的是两个半：

**1. Skill 版本历史与 diff**（完整落地）
理由：这是"能否相信一次重编是改进"的唯一证据。没有快照，`content` 被覆盖后
无法回答"上次批准的是什么"。实现为不可变 `skill_versions` + 按版本对比，
diff 同时报告行变化与断言增删。实机验证：驳回 1 条断言后重编，
diff 准确显示 `removed 1 / claims_removed: [clm_...]` 并定位到被删的原则行。

**2. 文本块级排除**（完整落地）
理由：OCR 错误、重复转载、无关段落会污染证据链。原实现只有源文件级删除，
粒度太粗——为一条坏段落删掉整份资料会丢失其余有效证据。
实现为 `PATCH /chunks/{id}`，排除后索引与抽取都跳过，并写审计。

**3. 可靠性可视化**（部分落地）
落地：`/health` 与 `/ready` 分离、运行时信息、Token 用量（不臆造未返回值）、
统一错误结构、请求 ID。
未落地：项目级预算上限、费用换算。理由：单价表需要维护且会过时，
在只有 Token 数的情况下乘一个可能错误的系数，不如不显示金额。

**明确不做**：资源管理面板、并发度调节 UI。当前瓶颈不在资源，加了只是负担。

## 七、验证方式：为什么大量依赖实机而非单测

单测能证明逻辑，不能证明集成。本次三个缺陷只有实机暴露：

1. **`already_parsed` 缺失**：单测不校验阶段日志文案，用户会看到"解析 0 份"误以为失败。
2. **重复蒸馏误报失败**：原测试只断言"断言数不变"，没断言"任务不应 failed"。
   已补强该测试。
3. **待审核徽章错算**：`claim_count - approved_count` 把已驳回算作待审。
   纯计算看不出问题，界面上"徽章 0 但列表 16 条"才暴露。

因此 `test_ops_contract.py` 专门锁定"文档承诺的行为"，`test_worker_lease.py`
锁定并发语义，`test_migrations.py` 锁定升级路径——三者都是"错了很难发现"的区域。

## 八、仍然不确定的事项

| 事项 | 现状 | 下一步 |
| --- | --- | --- |
| Docker 构建 | 本机 Docker 守护进程不可用，未完成实机构建 | 在有 Docker 的机器上 `docker build -f deploy/Dockerfile .` 并跑 compose 起停 |
| PostgreSQL 实跑 | 依赖与配置已就位，未连接真实 PG 验证 | 起动 `compose.postgres.yaml`，验证多 worker 抢占与迁移 |
| pgvector | 未接入 | 按 `docs/deployment.md` 第 3 节实现 |
| 多 Agent 运行时 | 仅 `skills-ref` 静态校验 | 至少在两个运行时做安装与触发测试 |
| LLM-as-judge 稳定性 | 已有多例验收，未做重复一致性测量 | 同案重复 3 次，统计评分方差 |
| 大文件解析 | 同步在 worker 内执行，无超时上限 | 为解析阶段加超时与资源限制 |