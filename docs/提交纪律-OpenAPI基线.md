# 提交纪律：改接口必须同步 OpenAPI 基线

**一条规则**：只要提交里动了路由、请求/响应 schema、或任何会被 `app.openapi()` 反映的代码，
就必须在同一次提交里带上 `docs/openapi.json` 的重导结果。
不允许“先提代码、下一次再补基线”——那样中间那次 CI 必红，通知会持续打扰，也掩盖真实回归。

## 一条命令搞定

在 `backend` 目录执行：

```powershell
.\.venv\Scripts\python.exe scripts\export_openapi.py
```

它会做两件事：

1. 按固定口径（`json.dumps(..., ensure_ascii=False, indent=2) + "\n"`）重写 `docs/openapi.json`；
2. 打印实测三元组（paths / operations / schemas），供提交说明和排障引用。

提交前自检：

```powershell
.\.venv\Scripts\python.exe scripts\export_openapi.py --check
```

`--check` 不写文件，出现下列任一情况都会非零退出：

- `MISSING`：`docs/openapi.json` 不存在；
- `DRIFT`：文件与实时导出不一致（并打印实测三元组）。

## CI 侧校验

`backend-ci.yml` 的 `Verify OpenAPI baseline` 只执行一条命令：

```bash
python scripts/export_openapi.py --check
```

它逐字节比对 `docs/openapi.json` 与 `app.openapi()`——防止手改或漏导。
CI 不再维护第二组路径/操作/schema 数字，因此不存在“文件跟着接口变了但期望值忘了改”的第二处漂移。

## 已踩过的坑（历史）

- `c7dc979`、`9ce510b`、`2f842c3` 三次红灯都是同一类：接口/基线改了，期望值或文件没跟上；
- `2ca2de1` 新增 `GET /stats/sources` 后基线变为 88/112/260，但旧 CI 常量仍是 87/111/258，
  该提交的 CI 直接报「基线不一致：88/112/260，期望 87/111/258」，下一个提交修好才绿；
- 以上是 2026-11 早期双维护机制的历史记录；当前已收口为单文件逐字节校验。

## 边界

- 三元组只用于日志和提交说明，不是业务断言；接口增删属正常演进，改基线文件即可，但必须同提交；
- 迁移脚本、纯前端改动、纯文档改动不触发 `app.openapi()` 变化，无需重导；
- 并行会话各自改接口时，以**最后一次提交前**的实测为准，避免互相覆盖基线。
