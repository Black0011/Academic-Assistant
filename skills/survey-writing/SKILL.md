---
name: survey-writing
description: >-
  Generate structured literature survey reports from reading notes and findings.
  Use when concluding a research investigation, producing a comparison table,
  summarising findings, or identifying research gaps.
domain: survey
triggers:
  - write survey
  - 综述写作
  - literature review
version: "1.0.0"
---
# Survey Writing — 综述写作

> 核心引用原则来自 orchestra-research/ml-paper-writing，适配为调研综述场景。

## 与 survey-table skill 的关系

- **survey-table** 负责单篇论文分析和方向级调研报告（"论文表格 + 分类总结"格式）
- **survey-writing** 负责更深度的综述报告（多方向交叉分析、研究趋势、研究空白）
- 二者共享 `data/survey/paper-table.md` 主表作为论文事实来源
- 写综述时必须先检查主表是否已包含相关论文，优先从主表提取信息

## 综述结构

```
1. 引言（问题背景 + 调研范围 + 为什么重要）
2. 论文调研表格（直接引用 paper-table.md 中对应方向的行）
3. 分类总结（按方法类型归类，说明每类方案的核心思路、适用场景、代表工作）
4. 综合分析（方案对比 + 互补关系 + 落地建议）
5. 研究趋势与开放问题
6. 结论（核心发现总结 + 建议的研究方向）
```

## 写作流程

### Step 1: 从 paper-table.md 和 findings.md 提取骨架

- `data/survey/paper-table.md`：论文事实的权威来源，从中提取对比表和论文信息
- `data/survey/findings.md`：调研过程中的发现和思考，从中提取叙事主线

### Step 2: 构建叙事主线

综述不是论文笔记的堆砌——它是一个有观点的故事。

**确定主线**："这个领域从 A 发展到 B，目前面临 C 的挑战，有 D、E、F 三类方法在尝试解决，其中 D 最有前景因为..."

如果写不出这句话，说明外环反思还不够深入，回到 autoresearch 的外环。

### Step 3: 分类总结表

按方案类型（如规则式、生成式、混合式、模型学习式等）对论文进行归类：

```markdown
| 方案类型 | 介绍 | 适用场景 |
|---------|------|---------|
| 类型A | 该类方法的共性思路概述 | 适合什么场景 |
| 类型B | ... | ... |
```

再按任务/场景维度总结各自关注的重点指标和评估方法。

### Step 4: 综合分析与研究空白

从分类总结中识别：
- **方法空白**：哪些组合没人尝试过？
- **场景空白**：哪些应用场景被忽视？
- **评估空白**：现有评估是否充分？是否有被遗漏的维度？
- **理论空白**：经验方法有效但缺乏理论解释？

给出综合判断：
- 当前最主流/最有前景的方案方向
- 各方案之间的互补关系
- 落地建议（成本、效果、工程复杂度的平衡）

### Step 5: 写作

按综述结构逐节写作，确保：

- **每一段**都有明确的论点，不只是陈述
- **每个引用**都有出处（论文 ID 或 DOI），禁止凭记忆引用
- **关键数字**直接引用原文数据，不要近似或凭印象
- **过渡段**连接各节，让读者理解为什么从 A 话题转到 B 话题

## 引用铁律

**永远不要凭记忆生成引用。** 所有引用必须：
1. 来自 `data/survey/paper-table.md` 主表中的论文
2. 来自实际读过的论文笔记（`data/survey/notes/`）
3. 或来自 API 可验证的检索结果

如果不确定某篇论文是否存在，标记为 `[CITATION NEEDED]` 而非编造。

## 输出格式

默认输出 Markdown。如需要可转为 LaTeX。

综述报告存入 `data/survey/report.md`，与 `findings.md` 并列但性质不同：
- `data/survey/paper-table.md`：论文调研总表，所有优秀论文的结构化记录
- `data/survey/findings.md`：演进中的工作笔记，随时更新
- `data/survey/report.md`：面向读者的完成品，结构化叙事
