# GEO 前端 B · 内部工作台

本目录是内部工作台前端，与后续公开品牌站（前端 A）独立。当前后端登录接口尚未交付，默认只在本机 Docker 演示前端交互。

## Docker 开发

在本目录运行：

```powershell
docker compose -f compose.dev.yml up --build --watch
```

打开 <http://localhost:3000>，演示账号和密码均为 `demo`。保存前端文件后，Compose Watch 会同步到容器并触发 Next.js 热更新。首次构建需要下载 Node 24、pnpm 12.15.0 和项目依赖。停止时按 `Ctrl+C`，再运行：

```powershell
docker compose -f compose.dev.yml down
```

后台运行可用 `docker compose -f compose.dev.yml up -d --build`，查看日志用 `docker compose -f compose.dev.yml logs -f workbench`。后台运行不会自动启动文件同步；开发时使用上面的 `--watch` 命令。

此配置只启动前端 B，不会启动或修改后端、PostgreSQL、Redis。端口仅绑定本机 `127.0.0.1:3000`。

## 后端接入边界

- 页面通过 `lib/workbench/client.ts` 调用同源 `/api/workbench`，不直接访问数据库或拼接后端地址。
- `GEO_API_MODE=mock` 时使用服务端演示数据；数据只供前端开发，重启容器可能重置。
- 后端交付后，将 `GEO_API_MODE` 改为 `live`，并设置服务端变量 `GEO_API_URL`。后端在宿主机运行时，Docker Desktop 使用 `http://host.docker.internal:8000`；后端若进入同一 Compose 网络，改为其服务名地址。
- `lib/workbench/backend.ts` 集中解析后端的 `{data, meta}` 与 `{error}` 信封，并传递 Bearer 令牌。当前可对接已实现的项目列表与线索接口；统计、审核查询等未实现接口不会伪装成真实数据。
- `app/api/session/route.ts` 在演示模式提供开发登录。真实模式调用 `/api/v1/auth/login`，但该端点尚未实现，登录响应中的令牌字段仍需和后端确认。真实认证与服务端授权上线前必须联调验证。

## 现有页面

工作概览、项目管理、监测任务、内容审核、线索管理、操作日志和组件规范。组件规范展示按钮、标签、表单、文件选择等基础交互；文件选择在演示模式不会上传。

---

以下为 Next.js 初始化项目的原始说明。

This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
