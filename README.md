# GEO 系统（广州基地首期）

按《广州基地GEO系统开发方案》与《技术方案》搭建的开发仓库。

```
geo-system/
├── frontend/          # Next.js + TypeScript（A 负责）
├── backend/           # FastAPI（B 负责）
│   ├── app/           # main / api / core / db / models / worker
│   └── scripts/       # seed.py 初始化数据
├── migrations/        # Alembic 迁移脚本（C 负责）
├── docs/              # 数据库结构说明、接口契约草案
├── docker-compose.yml # PostgreSQL 16 + Redis 7
├── alembic.ini        # 迁移配置（脚本目录指向 migrations/）
├── .env.example
└── README.md
```

## 一、本机环境（已验证）

| 项 | 版本 | 说明 |
| --- | --- | --- |
| Docker Desktop | 29.9.3 | 必须先启动 Desktop，否则 `docker` 命令连不上引擎 |
| PostgreSQL | `postgres:16`（容器） | **映射到 5433**，见下方端口说明 |
| Redis | `redis:7`（容器） | 6379 |
| Python | 3.12.9 | `.python-version` 锁定 3.12 |
| Node.js | 22.x LTS | `.nvmrc` 锁定 22 |
| pnpm | 12.x | 前端包管理器，lock 文件为 `pnpm-lock.yaml` |

## 二、首次初始化（三条命令）

```powershell
# 1) 环境变量与依赖服务
Copy-Item .env.example .env      # 本机 .env 已生成，PostgreSQL 端口用 5433
docker compose up -d

# 2) 后端与数据库
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd ..
.\backend\.venv\Scripts\alembic.exe upgrade head
cd backend
.\.venv\Scripts\python.exe scripts\seed.py

# 3) 前端
cd ..\frontend
pnpm install
```

## 三、日常启动

```powershell
# 依赖服务（每次开机后）
docker compose up -d

# 后端 API（仓库根目录）
.\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --app-dir backend

# Celery Worker（Windows 必须 --pool=solo）
cd backend
.\.venv\Scripts\celery.exe -A app.worker.celery_app worker --pool=solo --loglevel=info

# 前端
cd frontend
pnpm dev
```

验证：

| 地址 | 期望结果 |
| --- | --- |
| <http://localhost:8000/health> | `{"status":"ok","service":"geo-api","env":"dev"}` |
| <http://localhost:8000/health/db> | `{"status":"ok","database":"ok"}` |
| <http://localhost:8000/health/redis> | `{"status":"ok","redis":"ok"}` |
| <http://localhost:8000/docs> | Swagger 文档 |
| <http://localhost:3000> | Next.js 首页 200 |

## 四、数据库

- 结构说明与数据字典：[docs/数据库结构说明.md](docs/数据库结构说明.md)
- 接口契约草案（待 A/B 评审）：[docs/API契约草案.md](docs/API契约草案.md)
- 迁移命令（仓库根目录执行）：

```powershell
.\backend\.venv\Scripts\alembic.exe upgrade head
.\backend\.venv\Scripts\alembic.exe current
.\backend\.venv\Scripts\alembic.exe check            # 必须返回 No new upgrade operations
.\backend\.venv\Scripts\alembic.exe revision --autogenerate -m "描述"
```

- 迁移必须可回滚：`downgrade base` → `upgrade head` 已实测能重建全库（33 张业务表 / 96 索引 / 80 外键 / 32 枚举约束）。
- 种子数据可重复执行，只补缺失不覆盖改动；默认管理员 `geo_admin / geo-admin-dev`，**生产前必须改**。

## 五、端口说明

| 端口 | 用途 | 备注 |
| --- | --- | --- |
| 5433 | PostgreSQL（容器） | 本机原生 PostgreSQL 16 服务占用 5432，容器改用 5433，`DATABASE_URL` 已指向 5433 |
| 6379 | Redis | 本机无原生 Redis，直接用 |
| 8000 | 后端 API | |
| 3000 | 前端 | |

若三人中有人本机 5432 空闲，可在自己的 `.env` 里把 `POSTGRES_PORT` 改回 5432，并同步 `DATABASE_URL`；数据库镜像版本不变，不影响一致性。

## 六、已踩过的坑（照此处理，别再重复排查）

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `failed to connect to the docker API` | Docker Desktop 未启动 | 先启动 Docker Desktop，等引擎就绪 |
| 容器起不来，日志报端口占用 | 本机原生 PostgreSQL 占 5432 | 容器映射 5433，或停掉本机 PG 服务 |
| `ModuleNotFoundError: packaging` | kombu 5.4 的 redis 传输隐式依赖 | requirements 已显式锁 `packaging==24.2`、`kombu==5.4.0` |
| passlib 哈希抛 `password cannot be longer than 72 bytes` | passlib 1.7.4 不兼容 bcrypt ≥ 4.1 | requirements 已锁 `bcrypt==4.0.1` |
| Celery 启动后任务不执行 | Windows 默认 prefork 池不可用 | 必须加 `--pool=solo` |
| 前端首次 `next dev` 卡住 | 首次下载 `@next/swc` 原生包（约 36MB） | 等下载完成，属正常现象 |

## 七、协作约定

- 密钥只进 `.env`，不提交仓库、不写进代码。
- 依赖版本通过 lock 文件锁定并提交；`requirements.txt` 全部精确版本。
- `main` 分支保持可运行，功能开发走独立分支。
- 数据库结构变更由 C 统一管理，迁移脚本评审后合入。
- AI 生成的代码必须人工检查、测试、集成，以可运行闭环为交付标准。
