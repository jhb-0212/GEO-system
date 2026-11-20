# GEO 系统（广州基地首期）

按《广州基地GEO系统技术方案》《广州基地GEO系统开发方案》搭建的开发仓库。

```
geo-system/
├── frontend/           # Next.js + TypeScript（A 负责）
├── backend/            # FastAPI（B 负责，C 提供数据层、RBAC 与隔离基座）
│   ├── app/
│   │   ├── api/        # 路由 + deps 薄适配层 + 统一响应
│   │   ├── core/       # 配置、错误信封、安全、能力矩阵（permissions.py）
│   │   ├── services/   # 领域服务：access（权限判定）、audit、project_scope、outbox
│   │   ├── schemas/    # 请求模型（projects/members/leads/content/publishing）
│   │   ├── models/     # SQLAlchemy 模型
│   │   └── main.py / worker.py
│   ├── scripts/        # seed.py、import_legacy.py、audit_schema.py
│   ├── tests/          # 结构、隔离、RBAC、业务回归（512 passed）
│   └── Dockerfile
├── migrations/         # Alembic 迁移脚本（C 负责）
├── deploy/             # 生产编排、Nginx、备份恢复脚本
├── docs/               # 数据库结构说明、核对表、DDL、契约、迁移、部署、测试
├── docker-compose.yml  # 本地开发：PostgreSQL 16 + Redis 7
├── alembic.ini
├── .env.example
└── README.md
```

## 一、本机环境（已验证）

| 项 | 版本 | 说明 |
| --- | --- | --- |
| Docker Desktop | 29.9.3 | 必须先启动 Desktop，否则 `docker` 连不上引擎 |
| Docker Compose | v5.7.0 | |
| PostgreSQL | `postgres:16`（容器 16.15） | **映射到 5433**，见第五节 |
| Redis | `redis:7`（容器） | 6379 |
| Python | 3.12.9 | `.python-version` 锁定 3.12 |
| Node.js | 24.22.2 | `.nvmrc` 锁定 24 |
| pnpm | 12.15.0 | 前端包管理器，lock 文件为 `pnpm-lock.yaml` |

## 二、首次初始化

```powershell
Copy-Item .env.example .env
docker compose up -d

cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd ..
.\backend\.venv\Scripts\alembic.exe upgrade head
cd backend
.\.venv\Scripts\python.exe scripts\seed.py --technical-baseline

cd ..\frontend
pnpm install
```

## 三、日常启动

```powershell
docker compose up -d

# 后端 API（仓库根目录）
.\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload

# Celery Worker（Windows 必须 --pool=solo；Linux/生产 compose 用 --concurrency=4）
cd backend
.\.venv\Scripts\celery.exe -A app.worker.celery_app worker --pool=solo --loglevel=info

# Celery Beat（另开一个终端；只起 worker 不会触发定时调度和 outbox 消费）
.\.venv\Scripts\celery.exe -A app.worker.celery_app beat --loglevel=info

# 前端
cd frontend
pnpm dev
```

验证：

| 地址 | 期望 |
| --- | --- |
| <http://localhost:8000/health> | `{"status":"ok","service":"geo-api","env":"dev"}` |
| <http://localhost:8000/health/db> | `{"status":"ok","database":"ok"}` |
| <http://localhost:8000/health/redis> | `{"status":"ok","redis":"ok"}` |
| <http://localhost:8000/docs> | Swagger |
| <http://localhost:3000> | Next.js 首页 200 |

> 浏览器登录用 `POST /api/v1/auth/login`（`username` + `password`）取 Bearer 令牌；本地脚本验收也可用 `backend\scripts\dev_token.py --username geo_admin`（仅 `APP_ENV=dev/local/test` 可用），随后依次验证 `POST /api/v1/projects`（系统管理员 `project.create`）、`GET /api/v1/projects/{id}/leads`、`GET /api/v1/projects/{id}/channels/export`（`export.data`，写入审计）。项目 id 用 `GET /api/v1/projects` 动态取，不要写死——`seed` 重建库会重新生成 UUID。

## 四、数据层与交付文档

| 文档 | 内容 |
| --- | --- |
| [docs/数据库结构说明.md](docs/数据库结构说明.md) | 44 张表设计、隔离规则、6 角色能力矩阵、索引与迁移工作流 |
| [docs/表结构核对表.md](docs/表结构核对表.md) | 从库内实时生成的逐表核对表（项目 id / 索引 / CHECK / 唯一约束） |
| [docs/数据库DDL.sql](docs/数据库DDL.sql) | `pg_dump --schema-only` 导出的建库脚本 |
| [docs/API契约.md](docs/API契约.md) | 端点骨架、6 角色能力矩阵、错误与成功信封、状态机约束 |
| [docs/冻结基线.md](docs/冻结基线.md) | 冻结 commit、Alembic head、文件指纹、评审证据表、冻结后规则 |
| [docs/历史数据迁移方案.md](docs/历史数据迁移方案.md) | 分批导入、映射表、数量核对、回滚 |
| [docs/部署交付清单.md](docs/部署交付清单.md) | 生产编排、Nginx/HTTPS、上线步骤、安全检查清单 |
| [docs/生产部署执行清单.md](docs/生产部署执行清单.md) | 真实主机部署执行模板（环境登记、上线前必查、验收取证、恢复与回滚），未执行 |
| [docs/备份恢复演练记录.md](docs/备份恢复演练记录.md) | 备份与还原演练结果、RPO/RTO 建议 |
| [docs/测试报告.md](docs/测试报告.md) | 自动化测试、结构断言、执行计划、未覆盖项 |
| [docs/GEO指标口径.md](docs/GEO指标口径.md) | 有效回答、mention rate、citation share、SOV、prompt coverage、freshness、failure rate 与自动采集链 |
| [docs/业务链路验收用例.md](docs/业务链路验收用例.md) | 11.2 业务链路验收脚本（草稿，A/B 补齐 P0 端点后执行） |
| [docs/系统管理员使用说明.md](docs/系统管理员使用说明.md) | 管理员操作手册：建项目、授成员、能力矩阵、审计与导出、备份恢复、常见故障 |
| [docs/DEV_ENV.md](docs/DEV_ENV.md) | 团队开发环境配置说明（Node 24、pnpm、PostgreSQL 5433、Redis、启动与验收步骤） |
| [docs/交付验收对照表.md](docs/交付验收对照表.md) | 技术方案 11.4 十项交付验收的逐项状态与差距 |
| [docs/交付包清单.md](docs/交付包清单.md) | 交付包构成：仓库内交付物、仓库外随包文件、运行期产物与复核命令 |

常用命令（仓库根目录）：

```powershell
.\backend\.venv\Scripts\alembic.exe upgrade head
.\backend\.venv\Scripts\alembic.exe check      # 必须返回 No new upgrade operations
cd backend; .\.venv\Scripts\python.exe -m pytest tests -q
cd backend; .\.venv\Scripts\python.exe scripts\audit_schema.py           # 结构变更后重新生成核对表
cd backend; .\.venv\Scripts\python.exe scripts\audit_schema.py --check   # 必须与 docs/表结构核对表.md 无 diff
cd backend; .\.venv\Scripts\python.exe scripts\audit_capability.py --strict  # 链路能力矩阵必须 44 表 / 缺口 0
```

数据库现状：44 张表 = **36 张带 `project_id` 的项目业务表（含 `import_batches`）+ 7 张系统级表（`users`、`roles`、`permissions`、`role_permissions`、`projects`、`ai_engines`、`ai_engine_entries`）+ 1 张迁移元数据表（`alembic_version`）**；141 索引、110 外键、41 条表级 CHECK（`pg_constraint contype='c'` 总数为 41，全部挂在表上）。逐表归属以 `docs/表结构核对表.md` 为准（由 `backend/scripts/audit_schema.py` 从库生成）。
迁移链：完整顺序、分支与合并以 `alembic history --verbose` 为准；当前 head 为 `l2d3e4f5a6b7`。

## 五、端口说明

| 端口 | 用途 | 备注 |
| --- | --- | --- |
| 5433 | PostgreSQL（容器） | **团队统一端口**：`.env.example`、`docker-compose.yml` 默认值、`config.py` 默认值都是 5433，避开本机原生 PostgreSQL 占用的 5432 |
| 6379 | Redis | |
| 8000 | 后端 API | |
| 3000 | 前端 | |

> 三处必须一致：`.env` 的 `POSTGRES_PORT`、`DATABASE_URL` 的端口、`docker-compose.yml` 的 `${POSTGRES_PORT:-5433}`。不要各自改成 5432——一旦端口分叉，最坏情况是连上本机原生库而不自知，迁移会打到错误的库上。

## 六、生产部署

生产用 `deploy/docker-compose.prod.yml`：数据库与 Redis 不映射宿主机端口，只有 Nginx 暴露 80/443，密码与密钥全部外部注入。`migrate` 是一次性服务，自动跑 `alembic upgrade head` + 基础种子 + 15 平台目录 + 4 个扩展 API 入口（后两者幂等且默认停用），api/worker 等它成功后再启动。完整步骤见 [docs/部署交付清单.md](docs/部署交付清单.md)，本机真机验证结果见该文件第八节。

备份与恢复演练：

```powershell
# Windows
.\deploy\scripts\backup_db.ps1
.\deploy\scripts\restore_drill.ps1 -BackupFile .\deploy\backups\geo-<时间戳>.dump
```

```bash
# Linux
APP_ENV=prod bash ./deploy/scripts/backup_db.sh
```

## 七、已踩过的坑

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `failed to connect to the docker API` | Docker Desktop 未启动 | 先启动 Desktop，等引擎就绪 |
| 容器起不来，日志报端口占用 | 本机 5433 也被占用 | 换一个空闲端口，并把 `POSTGRES_PORT` 与 `DATABASE_URL` 同步改 |
| `ModuleNotFoundError: packaging` | kombu redis 传输隐式依赖 | 已锁 `packaging==24.2`、`kombu==5.4.0` |
| passlib 抛 `password cannot be longer than 72 bytes` | passlib 1.7.4 与 bcrypt ≥4.1 不兼容 | 已锁 `bcrypt==4.0.1` |
| Celery 任务不执行 | Windows 默认 prefork 池不可用 | 加 `--pool=solo` |
| 首次 `next dev` 卡住 | 下载 `@next/swc` 原生包（约 36MB） | 等下载完成 |
| 迁移里缺少枚举 CHECK | SQLAlchemy 2.0 `Enum` 默认 `create_constraint=False` | `str_enum()` 已开启，重新生成 |
| 循环外键没建 | autogenerate 跳过 `use_alter` | 手工 `op.create_foreign_key`，downgrade 用 `IF EXISTS` |

## 八、协作约定

- 密钥只进 `.env`，不提交仓库、不写进代码；生产用 `deploy/.env.prod`，不进仓库。
- 依赖版本通过 lock 文件锁定并提交；`requirements.txt` 全部精确版本。
- `main` 分支保持可运行，功能开发走独立分支。
- 数据库结构变更由 C 统一管理，迁移脚本评审后合入；合入前跑 `alembic check` 与 `pytest`。
- AI 生成的代码必须人工检查、测试、集成，以可运行闭环为交付标准。
