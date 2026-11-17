# 提交纪律：改接口必须同步 OpenAPI 基线

**一条规则**：只要提交里动了路由、请求/响应 schema、或任何会被 `app.openapi()` 反映的代码，
就必须在同一次提交里带上 `docs/openapi.json` 的重导结果和 CI 计数三元组。
不允许“先提代码、下一次再补基线”——那样中间那次 CI 必红，通知会持续打扰，也掩盖真实回归。

## 一条命令搞定

在 `backend` 目录执行：

```powershell
.\.venv\Scripts\python.exe scripts\export_openapi.py
```

它会做三件事：

1. 按 CI 同口径（`json.dumps(..., ensure_ascii=False, indent=2) + "\n"`）重写 `docs/openapi.json`；
2. 计算实测三元组（paths / operations / schemas），并把 `.github/workflows/backend-ci.yml`
   里的 `!= (a, b, c)` 与「期望 a/b/c」文案一并改成实测值；
3. 打印 `CI_COUNTS 已同步 → x/y/z`。

提交前自检：

```powershell
.\.venv\Scripts\python.exe scripts\export_openapi.py --check
```

`--check` 不写文件，出现下列任一情况都会非零退出：

- `MISSING`：`docs/openapi.json` 不存在；
- `DRIFT`：文件与实时导出不一致（并打印实测三元组）；
- `CI_COUNTS 不一致`：基线文件已更新，但 `backend-ci.yml` 期望值还是旧的。

可选本地钩子（只影响本机，不强制全组）：

```powershell
Set-Content .git\hooks\pre-commit "cd backend; .venv/Scripts/python.exe scripts/export_openapi.py --check" -Encoding utf8
```

## CI 侧校验

`backend-ci.yml` 的 `Verify OpenAPI baseline` 做两件事，缺一不可：

1. 逐字节比对 `docs/openapi.json` 与 `app.openapi()`——防止手改或漏导；
2. 断言三元组等于 `backend-ci.yml` 里的常量——防止“文件跟着接口变了但期望值忘了改”。

## 已踩过的坑

- `c7dc979`、`9ce510b`、`2f842c3` 三次红灯都是同一类：接口/基线改了，期望值或文件没跟上；
- `2ca2de1` 新增 `GET /stats/sources` 后基线变为 88/112/260，但期望值仍是 87/111/258，
  该提交的 CI 直接报「基线不一致：88/112/260，期望 87/111/258」，下一个提交修好才绿；
- `--help`/`--no-ci-sync` 只用于排障，正常提交不要带 `--no-ci-sync`。

## 边界

- 三元组不是业务断言，只是防漂移的看门狗；接口增删属正常演进，改数值即可，但必须同提交；
- 迁移脚本、纯前端改动、纯文档改动不触发 `app.openapi()` 变化，无需重导；
- 并行会话各自改接口时，以**最后一次提交前**的实测为准，避免互相覆盖计数。
