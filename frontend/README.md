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

## 可选的前端 Docker 开发

```powershell
docker compose -f compose.dev.yml up --build --watch
```

打开 <http://localhost:3000/login>。停止时按 `Ctrl+C`，再运行 `docker compose -f compose.dev.yml down`。此配置只启动前端 B，不启动后端、PostgreSQL 或 Redis。

## 接口与模式

- 工作台的浏览器请求走同源 `/internal/session` 和 `/internal/workbench/*`。生产 Nginx 把 `/api/` 转给后端，因此前端内部路由不能使用 `/api/` 前缀。
- `GEO_API_MODE=mock` 仅在非生产环境启用演示账号和数据。生产构建始终使用真实接口模式，不接受 `demo/demo`。
- 真实模式使用服务端变量 `GEO_API_URL` 连接后端。本机运行后端可设为 `http://localhost:8000`（默认）；前端开发容器默认使用 `http://host.docker.internal:8000`；生产容器默认使用 `http://api:8000`。
- 后端认证由 `POST /api/v1/auth/login` 和 `GET /api/v1/auth/me` 提供；当前仓库的后端尚未交付这些接口。登录令牌字段暂按 `data.access_token` 读取，必须以真实响应确认。没有有效后端认证时，真实模式不会显示工作台。
- 浏览器收到 401 或令牌错误码会清除前端会话并回登录页；`project_forbidden`、`insufficient_role` 等 403 错误按 `error.code` 显示权限提示。准确返回值仍需联调确认。
- 项目和线索已预留真实接口适配；审核、统计、监测、FAQ、素材及上传等业务接口未完成或未联调时不显示演示数据，也不会假装保存成功。

## 当前页面

工作概览、项目管理、监测任务、内容审核、线索管理、FAQ 编辑、素材管理、操作日志和组件规范。演示模式有醒目标识；FAQ 与素材页面的交互只供前端审查，不能作为真实发布或上传使用。

## 检查

```powershell
pnpm lint
pnpm build
```
