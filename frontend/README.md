# GEO 工作台（前端 B）

这是 GEO 系统的内部工作台，位于现有 Next.js 项目 `frontend/`。公开站 A 以后与工作台共用一个域名；当前根路径暂时进入 `/workbench`，公开站页面尚未开发。

## 本机运行

使用仓库根目录 `.nvmrc` 指定的 Node.js 24 和 `frontend/package.json` 指定的 pnpm 12.15.0：

```powershell
cd D:\git_program\GEO-system\frontend
pnpm install --frozen-lockfile
$env:GEO_API_MODE = 'mock'
pnpm dev
```

打开 <http://localhost:3000/login>，演示账号与密码均为 `demo`。本机演示不需要后端或 Docker。演示记录仅用于检查页面，刷新或重启后可能重置，不会写入真实数据库。FAQ 编辑、上下架和素材信息编辑只影响当前页面；文件选择不会上传。

真实接口联调先在仓库根目录执行 `alembic upgrade head`，按后端 README 启动 PostgreSQL、Redis 和 FastAPI，再在 `frontend/` 运行 `pnpm dev`（不设置 `GEO_API_MODE=mock`）。登录账号必须是已加入项目的活跃用户；项目 ID、角色与能力码从 `/api/v1/auth/me` 获取，不写死在前端。

需要编辑、审核、线索客服或只读视角时，可在**本地开发/测试环境**给 `GEO_DEV_EDITOR_PASSWORD`、`GEO_DEV_REVIEWER_PASSWORD`、`GEO_DEV_LEAD_OPS_PASSWORD`、`GEO_DEV_VIEWER_PASSWORD` 中所需的变量赋值，再从 `backend/` 执行 `python scripts/seed_dev_accounts.py gz-base`。脚本仅补缺失用户/成员关系，不覆盖现有密码或角色；密码不进入仓库。

## 可选的前端 Docker 开发

```powershell
docker compose -f compose.dev.yml up --build --watch
```

打开 <http://localhost:3000/login>。停止时按 `Ctrl+C`，再运行 `docker compose -f compose.dev.yml down`。此配置只启动前端 B，不启动后端、PostgreSQL 或 Redis。

## 接口与模式

- 工作台的浏览器请求走同源 `/internal/session` 和 `/internal/workbench/*`。生产 Nginx 把 `/api/` 转给后端，因此前端内部路由不能使用 `/api/` 前缀。
- `GEO_API_MODE=mock` 仅在非生产环境启用演示账号和数据。生产构建始终使用真实接口模式，不接受 `demo/demo`。
- 真实模式使用服务端变量 `GEO_API_URL` 连接后端。本机运行后端可设为 `http://localhost:8000`（默认）；前端开发容器默认使用 `http://host.docker.internal:8000`；生产容器默认使用 `http://api:8000`。
- 后端认证由 `POST /api/v1/auth/login` 和 `GET /api/v1/auth/me` 提供。登录令牌从 `data.access_token` 读取，仅存入 HttpOnly 同源会话 Cookie；工作台按 `/me` 返回的项目与能力码展示入口。
- 浏览器收到 401 或令牌错误码会清除前端会话并回登录页；403/404/409 按后端错误信封显示提示。
- 项目和线索已预留真实接口适配。若线索接口返回 403，工作台其他页面继续加载；线索区显示无权限，不把无权限误写成 0 条。
- 监测页在真实模式下调用轮次列表、新建轮次和批量生成接口；按 `complete`、`skipped_reason` 与各计数字段显示实际结果，不把部分生成当作成功。开发库的 6 道基线题需先激活，才能生成完整 24 条任务。
- 渠道页在真实模式下支持分页列表、只读详情、新建和编辑；详情展示备注、启停、别名及引用覆盖情况，编辑前从详情回显全部字段。统计页读取总览、分引擎、分问题指标，支持 CSV 导出；空分母显示 `--`。
- 题库页支持题目属性、问法版本和目标词关联；样本与引用页支持只读回看、按 `evidence.read` 下载证据文件、按 `evidence.review` 复核和未知域名队列；内容审核页可写草稿、提交、读取正文和审批历史；发布页可登记账号、建任务、记录尝试、回填回执与核实未知状态。同一项目的发布批次键保存在浏览器本地，重复提交会复用任务；确需新一轮发布时点击“新建批次”。操作日志展示当前项目最近 20 条授权可见记录。真实模式中的每个写入均走后端能力码门禁。
- AI 平台入口页读取平台与入口分页列表；系统管理员可新建平台、维护入口并手动测试连接。凭据表单只收服务端环境变量名，不收 API Key 明文；后端继续执行系统级 `engine.manage` 授权。
- FAQ、素材及上传等尚未接入的业务操作在真实模式下不显示演示数据，也不会假装保存成功。线索只读状态及项目权限以 `/me` 为准。

## 当前页面

工作概览、项目管理、监测轮次/任务、题库与目标词、样本与引用、渠道、统计、内容审核、内容发布、线索管理、FAQ 编辑、素材管理、操作日志、AI 平台入口和组件规范。演示模式有醒目标识；FAQ 与素材页面的交互只供前端审查，不能作为真实发布或上传使用。

## 检查

```powershell
pnpm lint
pnpm build
```
