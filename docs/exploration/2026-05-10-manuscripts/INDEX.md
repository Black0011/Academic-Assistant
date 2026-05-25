# 探索归档 · Manuscript 后端解读（2026-05-10）

这是一份**探索性笔记**，不是面向用户的产品文档，也不会被自动同步到代码。

如果当前 manuscript 后端实现与下面的描述不一致，**以代码为准** —— 这份笔记
只反映 2026-05-10 当天 `backend/manuscripts/`、`backend/api/routers/manuscripts.py`
的状态，方便后续读者快速建立心智模型。最权威的入口仍然是：

- `PLAN.md`（架构总览）
- `backend/api/routers/manuscripts.py`（API 真源）
- `backend/manuscripts/bundle_storage.py`（文件系统真源）

## 文件清单

| 文件 | 一句话作用 |
|---|---|
| `README_MANUSCRIPTS.md` | 当时这一批笔记的入口 / 索引 |
| `MANUSCRIPT_FINDINGS_SUMMARY.md` | 5 条关键发现的总结 |
| `MANUSCRIPT_BACKEND_ANALYSIS.md` | 带行号的深度分析 |
| `MANUSCRIPT_QUICK_REFERENCE.md` | 给开发者的速查表 |
| `MANUSCRIPT_ENDPOINT_FLOW.txt` | ASCII 请求/响应流程图 |
| `MANUSCRIPT_ANALYSIS.md` + `_QUICK_REFERENCE.txt` | 同主题的早期版本 |

## 这份归档诞生的背景

`/api/manuscripts/{id}/tree` 返回**扁平**的 `ManuscriptFile[]`（path 是 POSIX
相对路径，没有 `is_dir` 字段，目录信息靠 `/` 切分隐式表达）。前端要做出
cursor / vscode 风格的折叠/展开树，就要在客户端把这个扁平列表重新拼成树
形结构 —— 这批笔记就是为了把后端那一侧吃透，才能写客户端的 `buildTree`。

最终落地的产物是 `BundleExplorer.tsx` 的递归树形浏览（commit `24677aa`）。
