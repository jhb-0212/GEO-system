# B5/B6 草稿归档（2026-11-13）

## 来源

- 分支：`feat/b5b6-review` @ `d00b7e2`
- 工单：B5 样本回看复核；B6 引用复核 / 未知域名队列
- 归档内容为该分支已落地的修订版快照（非早期草稿）。

## 文件对照

| 归档路径 | 运行代码原路径 |
| --- | --- |
| `app/api/citations.py` | `backend/app/api/citations.py` |
| `app/schemas/citations.py` | `backend/app/schemas/citations.py` |
| `tests/test_sample_review.py` | `backend/tests/test_sample_review.py` |
| `tests/test_citations_review.py` | `backend/tests/test_citations_review.py` |

## 用途与边界

- 本目录仅作存档追溯，不参与后端运行，也不被 pytest 收集（测试固定从 `backend/tests` 收集）。
- 运行代码以 `backend/app`、`backend/tests` 正式路径为准；后续修改请改正式路径，不要改本归档副本。
- 早期草稿另存于 `git stash@{0}`（tracked 5 个文件，未含本目录这 4 个新文件）；stash 只可 `drop`，不可 `pop`——弹回当前分支会冲突并复制出重复代码。
