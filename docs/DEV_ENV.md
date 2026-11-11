# DEV_ENV.md

> GEO 系统 团队开发环境部署手册（**以仓库冻结版为准**）
>
> 目标：3 人本地开发环境一致；PostgreSQL 16、Redis 7 由 Docker Compose 提供，前后端应用本机直接运行。
>
> 适用范围：广州基地 GEO 系统 3 人开发小组（前端 / 后端 / 数据库与交付）。
>
> 基线：`main` 分支冻结内容提交 `4499b20`，Alembic head `8d1e2f3a4b5c`；本手册所有命令与版本均取自仓库实际文件，与 `docs/冻结基线.md` 一致。

## 目录

- [一、前置安装](#一前置安装每位开发人员本机操作)
- [二、获取项目代码](#二获取项目代码)
- [三、生成本地环境变量文件](#三生成本地环境变量文件)
- [四、启动数据库与 Redis](#四启动数据库与-redis)
- [五、启动后端 FastAPI](#五启动后端-fastapi)
- [六、启动前端 Next.js](#六启动前端-nextjs)
- [七、环境验证（全员必须执行）](#七环境验证全员必须执行)
- [八、版本锁定规则](#八版本锁定规则)
- [九、常见问题速查](#九常见问题速查)
- [十、开发环境紧急重置](#十开发环境紧急重置)
- [十一、Git 提交规范](#十一git-提交规范)
- [十二、冻结版已知限制](#十二冻结版已知限制)

---

## 一、前置安装（每位开发人员本机操作）

| 工具 | 版本要求 | 依据 |
| ---- | ---- | ---- |
| Docker Desktop | 最新稳定版 | 运行 PostgreSQL 16、Redis 7 |
| Git | 最新版本 | 代码版本管理 |
| Node.js | **22.x**（22.23.2 为实测版本） | 根目录 `.nvmrc` = `22`；前端 Next.js 16.4.5 |
| Python | **3.12** | 根目录 `.python-version` = `3.12` |
| pnpm | 最新稳定版（实测 12.15.0） | 前端唯一包管理器，lock 文件为 `pnpm-lock.yaml` |
| 代码编辑器 | VSCode（可选） | 不作统一要求 |

> Node 版本必须 22.x：`.nvmrc` 与前端 `next@16.4.5` 已按此验证，用 20 会出现锁文件与原生包不一致。

## 二、获取项目代码

```bash
git clone https://github.com/jhb-0212/GEO-system.git
cd geo-system
git checkout main
```

> 确认项目根目录存在：`docker-compose.yml`、`.env.example`、`alembic.ini`、`backend/`、`frontend/`、`migrations/`、`docs/`。

```
geo-system/
├── backend/            # FastAPI + SQLAlchemy + Celery
├── frontend/           # Next.js + TypeScript
├── migrations/         # Alembic 迁移（C 负责）
├── deploy/             # 生产编排、Nginx、备份恢复脚本
├── docs/               # 结构说明、核对表、DDL、契约、测试报告、冻结基线
├── docker-compose.yml
├── alembic.ini
├── .env.example
└── README.md
```

## 三、生成本地环境变量文件

```bash
# Mac / Linux
cp .env.example .env
```

Windows 用资源管理器把 `.env.example` 复制一份改名为 `.env`。

> `.env` 只在本机使用，**禁止提交**。仓库只提交 `.env.example`，里面全是本地占位值。

`.env` 的真实变量名（后端 `app/core/config.py` 直接读这些，**不是** `DB_HOST/DB_USER` 那一套）：

```ini
# ---------- PostgreSQL（必须与 docker-compose.yml 对应） ----------
POSTGRES_USER=geo
POSTGRES_PASSWORD=geo_dev
POSTGRES_DB=geo
# 本机 5432 被原生 PostgreSQL 占用时改成 5433（本项目开发机就是 5433）
POSTGRES_PORT=5433

# 应用连接串，端口必须与 POSTGRES_PORT 一致
DATABASE_URL=postgresql+psycopg://geo:geo_dev@localhost:5433/geo

# ---------- Redis / Celery ----------
REDIS_PORT=6379
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# ---------- 应用 ----------
APP_ENV=dev
API_BASE_URL=http://localhost:8000
SECRET_KEY=dev-only-secret-key-change-in-prod

# ---------- 对象存储（首期可留空） ----------
S3_ENDPOINT=
S3_ACCESS_KEY=
S3_SECRET_KEY=
S3_BUCKET=geo-evidence
```

> 三个必须同步的值：`POSTGRES_PORT`、`DATABASE_URL` 里的端口、`docker-compose.yml` 读的 `${POSTGRES_PORT:-5432}`。只改其中一个会连不上库。

## 四、启动数据库与 Redis

> 命令在**仓库根目录**执行。

```bash
docker compose up -d
docker compose ps
```

两个容器（`geo-postgres`、`geo-redis`）状态为 `Up` 且 healthcheck 通过即完成。

实际文件与常见教程不同之处（以仓库文件为准）：

- 端口是变量：`${POSTGRES_PORT:-5432}:5432`，所以 `.env` 里写 5433 就映射 5433；
- 容器名固定 `geo-postgres` / `geo-redis`，备份脚本按这个名字找容器；
- PG 带 `pg_isready` healthcheck，Redis 带 `redis-cli ping` healthcheck；
- Redis 开启 `appendonly` 并挂 `redisdata` 卷，重启不丢队列数据；
- 两个服务都是 `restart: unless-stopped`。

**5432 被占用时**（本机装过 PostgreSQL 服务最常见）：

```powershell
netstat -ano | findstr :5432
```

确认被原生 PostgreSQL 占用后，把 `.env` 的 `POSTGRES_PORT` 与 `DATABASE_URL` 一起改成 5433，然后：

```bash
docker compose down
docker compose up -d
```

> 不要为了腾端口去停本机原生 PostgreSQL 服务（本项目开发机的选择就是不碰它）。

## 五、启动后端 FastAPI

```bash
cd backend

# 1. 虚拟环境（Python 3.12）
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. 依赖（开发环境两个文件都要装，pytest 在 requirements-dev.txt）
pip install -r requirements.txt -r requirements-dev.txt
```

**3. 建表 + 种子数据（回到仓库根目录执行）**

```powershell
# 仓库根目录
.\backend\.venv\Scripts\alembic.exe upgrade head
cd backend
.\.venv\Scripts\python.exe scripts\seed.py
```

```bash
# Mac / Linux 等价写法（仓库根目录）
backend/.venv/bin/alembic upgrade head
cd backend && .venv/bin/python scripts/seed.py
```

seed 期望输出（全新库）：

```
角色 +5，能力码 +22，角色能力映射 +52，引擎 +4，项目 gz-base（项目管理员成员 +1），渠道 +39，问题 +6，口径 +3
```

第二次执行应全部 `+0`（幂等）。**生产环境未设置 `SEED_ADMIN_PASSWORD` 时 seed 会拒绝建默认管理员，这是预期行为。**

**4. 启动 API（仓库根目录）**

```powershell
.\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

**5. Celery Worker（需要跑异步任务时，另开终端）**

```powershell
cd backend
.\.venv\Scripts\celery.exe -A app.worker.celery_app worker --pool=solo --loglevel=info
```

> Windows 必须 `--pool=solo`，默认 prefork 池在 Windows 不可用。

## 六、启动前端 Next.js

```bash
cd frontend
pnpm install
pnpm dev
```

访问 <http://localhost:3000>，首页返回 200。

> 首次 `pnpm dev` 会下载 `@next/swc` 原生包（约 36MB），卡住属正常，等下载完。
> 若 `pnpm install` 行为与队友不同：确认 `node -v` 是 22.x，再删 `node_modules` 用仓库 `pnpm-lock.yaml` 重装。

## 七、环境验证（全员必须执行）

### 7.1 服务自检（A/B/C 都要过）

| 检查 | 命令 | 期望 |
| --- | --- | --- |
| API 存活 | `curl http://localhost:8000/health` | `{"status":"ok","service":"geo-api","env":"dev"}` |
| 数据库 | `curl http://localhost:8000/health/db` | `{"status":"ok","database":"ok"}` |
| Redis | `curl http://localhost:8000/health/redis` | `{"status":"ok","redis":"ok"}` |
| 接口文档 | 浏览器打开 `http://localhost:8000/docs` | 20 条路径可见 |
| 前端 | 浏览器打开 `http://localhost:3000` | 页面正常 |

### 7.2 最小业务链路（当前冻结版的真实路径）

> `auth/login` 尚未实现（见第十二节），第 1 天验收用开发令牌脚本换取 Bearer 令牌，不绕过任何权限判断。

**第 1 步：取令牌**

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\dev_token.py --username geo_admin
```

输出一串 JWT。它只对 `APP_ENV=dev/local/test` 生效，非开发环境直接拒绝。

**第 2 步：建项目（系统管理员能力 `project.create`）**

```powershell
$TOKEN = "<上一步的输出>"
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/projects" `
  -Headers @{ Authorization = "Bearer $TOKEN" } `
  -ContentType "application/json" `
  -Body '{"code":"env-check","name":"环境验证项目","description":"Day-1 验收"}'
```

期望返回 `201` 或 `200`，响应体带新项目 `id`；用 `project_admin` 或 `editor` 的令牌调用必须 `403`。

**第 3 步：读回项目数据（项目成员能力）**

```powershell
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/v1/projects/8f082009-1306-49ce-8fbb-69ebc1a76cf4/leads" `
  -Headers @{ Authorization = "Bearer $TOKEN" }
```

期望 `200 {"data":[...]}`（`gz-base` 的线索列表，初始为空数组）。这一步证明"库连得上 + 成员授权 + 项目隔离"三条同时成立。

**第 4 步：导出并留痕（`export.data`）**

```powershell
Invoke-WebRequest -Method Get -Uri "http://localhost:8000/api/v1/projects/8f082009-1306-49ce-8fbb-69ebc1a76cf4/channels/export" `
  -Headers @{ Authorization = "Bearer $TOKEN" } -OutFile "channels.csv"
```

**第 5 步：确认审计写入**

```powershell
docker exec geo-postgres psql -U geo -d geo -c 'select action, actor_id, created_at from audit_logs order by created_at desc limit 3;'
```

期望能看到 `export` 记录；若第 2 步用错角色试过，还会有 `permission_denied` 之类拒绝记录。

> 以上五步全过，代表本机环境可用。三人中任一人跑不通，不进入第 2 天开发。

## 八、版本锁定规则

| 项目 | 锁文件 / 方式 | 仓库实际值 |
| ---- | ---- | ---- |
| Node.js | `.nvmrc` | `22` |
| Python | `.python-version` | `3.12` |
| Python 依赖 | `backend/requirements.txt` + `requirements-dev.txt` | 全部精确版本（`bcrypt==4.0.1`、`packaging==24.2`、`pytest==8.3.4`） |
| 前端依赖 | `frontend/pnpm-lock.yaml` | 已提交 |
| PostgreSQL | `docker-compose.yml` 镜像 | `postgres:16`（容器内 16.15） |
| Redis | `docker-compose.yml` 镜像 | `redis:7` |

> **不需要统一**：编辑器、Git 版本、操作系统、Docker Desktop 版本。
> **判断依据**：会改变程序运行结果的才锁版本。

## 九、常见问题速查

问题根源只有四类：**版本不一致、端口冲突、环境变量错误、Docker 异常**。

### 1. Docker

- `docker compose up -d` 失败：先确认 Docker Desktop 已启动（只装不开也会报 API 连接失败）。
- 容器起不来 / 日志报端口占用：`docker compose logs postgres`，多半是 5432 被本机原生 PostgreSQL 占用 → 改 5433（见第四节）。
- 连接被拒 `connection refused`：`docker compose ps` 确认 `Up` 且 healthy；核对 `.env` 账号 `geo/geo_dev` 与 `DATABASE_URL` 端口。
- Redis 报错：确认 `geo-redis` 为 `Up`，`REDIS_URL` 指向 `localhost:6379/0`。

### 2. 后端

- `pip install` 装完仍报 `ModuleNotFoundError`：确认已激活 `.venv`（提示符带 `(.venv)`），并装了 `requirements-dev.txt`。
- `passlib` 报 `password cannot be longer than 72 bytes`：`bcrypt` 版本被升级了，回到 `bcrypt==4.0.1`。
- `ModuleNotFoundError: packaging`：`packaging==24.2` 没装（kombu redis 传输的隐式依赖）。
- 迁移报错：必须在**仓库根目录**执行 `alembic`，`alembic.ini` 在根目录；不要手动改表。
- `alembic check` 应返回 `No new upgrade operations detected`，出现 diff 说明模型与库不一致，先找 C。
- Celery 任务不执行：Windows 忘了 `--pool=solo`。

### 3. 前端

- `pnpm install` 表现与队友不同：`node -v` 是否 22.x；删 `node_modules` 后用仓库 lock 重装。
- 热更新失效：Node 版本不对，或 Windows 文件监听受限，切回 `.nvmrc` 版本重启。

### 4. 环境变量与安全

- 密码密钥一律进 `.env`，代码里不写；`.gitignore` 已忽略 `.env`、`.env.local`、`deploy/.env.prod`、`deploy/backups/`、`*.dump`。
- 改了 `.env` 必须重启后端/前端，配置在启动时读取。
- 若误提交了 `.env`：立刻换密钥并清理 Git 历史，不要只删文件。

### 5. 团队协作

- "我本地能跑别人跑不起"：先 `git pull` 到最新 `main`，核对 `.nvmrc` / `.python-version` / lock 文件，再按第五节重建库（迁移 + seed），不要手改表。
- 合并后环境异常：前端重装依赖、后端重建 venv、库结构有变更就 `alembic upgrade head`。

### 6. 自查清单

- [ ] Docker Desktop 已启动，`docker compose ps` 两个容器 `Up`
- [ ] Python 3.12、Node 22
- [ ] 后端已激活 `.venv`，两个 requirements 都装过
- [ ] `.env` 的 `POSTGRES_PORT`、`DATABASE_URL` 端口、compose 映射三者一致（本机为 5433）
- [ ] 迁移到 head，`alembic check` 零漂移
- [ ] seed 跑过且第二次全 `+0`
- [ ] `/health`、`/health/db`、`/health/redis` 三个 200
- [ ] 第七节五步业务链路走通
- [ ] 没有使用本机系统 PostgreSQL / Redis 代替容器

## 十、开发环境紧急重置

> 仅限开发环境，会清空本地测试数据。

```bash
# 1. 销毁容器与数据卷
docker compose down -v

# 2. 拉取最新代码
git pull

# 3. 重启中间件
docker compose up -d

# 4. 重建后端虚拟环境
cd backend
rm -rf .venv                 # Windows 直接删 .venv 文件夹
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt

# 5. 重建数据库结构
cd ..                        # 回仓库根目录
.\backend\.venv\Scripts\alembic.exe upgrade head
cd backend
.\.venv\Scripts\python.exe scripts\seed.py

# 6. 前端依赖
cd ../frontend
rm -rf node_modules
git checkout pnpm-lock.yaml
pnpm install

# 7. 重新启动 API / Worker / 前端，按第七节复验
```

## 十一、Git 提交规范

需要提交：

- `docker-compose.yml`、`.env.example`、`.gitignore`、`alembic.ini`
- `backend/requirements.txt`、`backend/requirements-dev.txt`、`frontend/pnpm-lock.yaml`
- `migrations/`、`backend/app/`、`backend/tests/`、`frontend/`、`docs/`

严禁提交：

- `.env`、`.env.local`、`deploy/.env.prod`
- `backend/.venv/`、`frontend/node_modules/`、`frontend/.next/`
- `deploy/backups/`、`*.dump`、`backend/var/`（证据文件）

`.gitignore` 以仓库文件为准（已覆盖上述全部，另含 `pgdata/`、`redisdata/`、编辑器目录）。

## 十二、冻结版已知限制

1. **`auth/login` 未实现**：测试与第 1 天验收用 `backend/scripts/dev_token.py` 直签令牌；上线前必须补登录与令牌吊销（契约变更单 + 迁移评审）。
2. **未实现端点**：题库与关键词、监测轮次与复核、渠道写、发布回执/核实、统计看板与统计导出、项目/系统审计查询、`auth` 三个端点等，契约中保留并标注"未实现"，不得按已实现调用。
3. **压测未执行**：无 1000 RPS / 真实数据量压测报告，冻结版不含性能结论。
4. **生产部署未在真实主机验证**：`deploy/docker-compose.prod.yml`、Nginx、备份脚本仅在本地演练。
5. **历史迁移仅样例验证**：真实旧系统导出数据尚未入库。

以上与 `docs/冻结基线.md` 第七节一致；细节与风险以该文件为准。

---

*文档版本：V1.1（按仓库冻结版校正）｜ 适用项目：广州基地 GEO 系统 ｜ 维护：数据库与交付负责人（成员 C）*
