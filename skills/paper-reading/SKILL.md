---
name: paper-reading
description: >-
  Structured paper reading with three-pass method and standardised YAML notes.
  Use when reading a paper for a literature survey, extracting key claims, or
  building connections between papers.
domain: research
triggers:
  - read paper
  - 精读
  - structured reading
version: "1.0.0"
---
# Paper Reading — 结构化论文阅读

## 三遍阅读法

### 第一遍：扫读（5 分钟）

**目标**：判断这篇论文是否值得精读。

阅读内容：
1. 标题 + 摘要
2. 引言的最后一段（通常是贡献列表）
3. 所有章节标题
4. 图表（看图表 caption，不看正文）
5. 结论

**第一遍后决策**：
- 高相关 → 进入第二遍
- 中等相关 → 记录摘要级笔记，暂不精读
- 低相关 → 跳过，记录"已看，不相关"

### 第二遍：精读（30-60 分钟）

**目标**：理解论文的核心方法和主要结论。

逐节阅读，重点关注：
- **方法部分**：核心算法/模型是什么？与前人工作的关键区别？
- **实验部分**：基线是什么？主指标结果如何？消融实验说明了什么？
- **图表**：每个图表在说明什么观点？

**第二遍后**：能向同行用 2-3 句话解释这篇论文的核心贡献。

### 第三遍：批判性阅读（仅对关键论文）

**目标**：达到可以复现/挑战的理解深度。

- 质疑每个假设：作者的前提成立吗？
- 检查实验设计：有没有遗漏的基线？评估指标合理吗？
- 思考局限性：作者没说的局限是什么？
- 联系其他论文：这篇论文如何扩展/矛盾/补充已读的其他论文？

## 笔记模板

每篇论文生成一份 YAML 笔记，存入 `data/survey/notes/{paper-id}.yaml`：

```yaml
paper_id: "arxiv:2501.12345"
title: "论文标题"
authors: ["作者1", "作者2"]
year: 2025
venue: "ICML"
institution: "MIT"
reading_date: "2025-03-17"
reading_depth: "pass2"  # pass1 | pass2 | pass3
local_pdf: "papers/25-MIT-ICML-主题.pdf"  # 如果已下载

# === 核心内容 ===
problem: |
  这篇论文要解决什么问题？为什么这个问题重要？
method: |
  核心方法/算法是什么？关键创新点在哪里？
  与前人工作的最大区别是什么？
key_results: |
  主要实验结果（数字）。
  相比基线提升了多少？在什么条件下？
limitations: |
  作者承认的局限性 + 我发现的局限性。

# === 关键主张与证据 ===
claims:
  - claim: "方法 X 在任务 Y 上超越了所有基线"
    evidence: "Table 2, 在 3 个 benchmark 上平均提升 5.2%"
    strength: "strong"  # strong | moderate | weak
  - claim: "组件 Z 是性能提升的关键"
    evidence: "消融实验 Table 3, 去掉 Z 后性能下降 8%"
    strength: "strong"

# === 论文间关联 ===
connections:
  - paper_id: "arxiv:2401.xxxxx"
    relation: "extends"      # extends | contradicts | complements | builds_on | competes
    note: "在其基础上增加了多任务学习"
  - paper_id: "arxiv:2312.xxxxx"
    relation: "contradicts"
    note: "该论文认为 A 有效，但本文的实验表明 A 在大规模场景下失效"

# === 个人评价 ===
my_assessment: |
  对这篇论文的整体评价。
  对我的调研有什么价值？哪些想法可以借鉴？
tags: ["multi-task RL", "robot manipulation", "policy routing"]
importance: "high"  # high | medium | low

# === 记忆进化系统字段（由 PaperMemory 自动填入，勿手工修改）===
context: ""
  # LLM 自动生成的一句话领域定位，例如：
  # "基于 agentic verifier 的多模态 RL 框架，解决 reward hacking 问题"
  # 首次由 PaperMemory.add_paper_note() 调用 analyze_content() 填入；
  # 进化时可被 update_neighbor 动作更新。

links: []
  # 自动建立的关联论文列表，格式与 connections 相同（paper_id 字符串）
  # 由 PaperMemory 进化逻辑填入；与手工 connections 并列，互不覆盖。
  # 示例：["arxiv:2603.00724", "arxiv:2501.12948"]

retrieval_count: 0
  # 本论文被 PaperMemory.search_papers() 命中的累计次数，
  # 用于后续识别高价值论文。

evolution_history: []
  # 进化事件记录，每次由 PaperMemory 自动追加，格式：
  # - timestamp: "202604101430"
  #   action: "strengthen"          # strengthen | update_neighbor
  #   triggered_by: "deepseek-r1"   # 触发本次进化的论文（不含扩展名）
  #   detail: "建立与 arxiv:2501.12948 的连接"
```

## 笔记质量标准

**好笔记**：
- `method` 字段让没读过论文的人能理解核心思路
- `claims` 列出了可验证的具体主张，不是模糊描述
- `connections` 与已读论文建立了明确关系
- `my_assessment` 包含批判性思考，不只是摘要复述

**差笔记**：
- 只是摘要的翻译
- 没有具体数字和实验结果
- 没有与其他论文的关联
- 没有个人批判性评价

## 读多少篇？

| 调研深度 | 核心论文 | 相关论文 | 浏览论文 |
|---------|---------|---------|---------|
| 快速了解 | 3-5 篇 (pass2) | 5-10 篇 (pass1) | 10-20 篇 (标题+摘要) |
| 标准综述 | 10-15 篇 (pass2-3) | 15-25 篇 (pass1-2) | 30-50 篇 (标题+摘要) |
| 深度综述 | 20+ 篇 (pass2-3) | 30+ 篇 (pass1-2) | 50+ 篇 (标题+摘要) |
