# GEO-system

广州基地 GEO 运营管理系统。

## 技术栈

- 公开品牌站：Next.js
- 内部工作台：React + TypeScript
- 后端：Python FastAPI
- 数据库：PostgreSQL 16
- 缓存与队列：Redis 7
- 异步任务：Celery

## 快速开始

```bash
# 启动依赖服务
docker compose up -d

# 后端
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# 前端
cd frontend
pnpm install
pnpm dev
```

## 目录结构

```
geo-system/
├── frontend/          # Next.js + React
├── backend/           # FastAPI
├── migrations/        # 数据库迁移脚本
├── docker-compose.yml
├── .env.example
└── README.md
```
