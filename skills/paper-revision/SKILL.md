---
name: paper-revision
description: >-
  Analyze a draft paper and user feedback to identify gaps, inconsistencies,
  and improvement opportunities. Generate section-by-section revision guidance
  with specific edits, restructuring suggestions, and writing improvements.
  Use when you have a paper draft and want to improve it iteratively, get
  detailed revision feedback, or address reviewer comments.
compatibility:
  upstream: paper-writing
  downstream: rebuttal-writer
domain: revision
triggers:
  - revise paper
  - improve paper
  - 论文修改
  - reviewer comments
version: "1.0.0"
---
# Paper Revision — 论文修改改进

你是论文修改助手。通过精读论文初稿和用户反馈，诊断问题、建议改进、生成详细修改指南。

## 核心原则

- **问题诊断优先**：不是简单的语法检查，而是结构、论证、实验设计层面的问题识别
- **建设性反馈**：每个问题都给出具体的修改方案和示例改写
- **分级改进**：区分"必改"（影响核心论证）、"应改"（学术严谨性）、"可选"（文笔提升）
- **保持原意**：改进不改变作者的核心想法，只是表达得更清晰、更有力

---

## 何时使用

**✅ 适用场景**
- 初稿完成后，需要整体评估和改进
- 收到导师/审稿人反馈，需要逐项解读并生成改进方案
- 特定章节有问题，需要诊断和修改指导
- 跨越多个修改轮次，需要跟踪和协调修改

**❌ 不适用场景**
- 论文刚开始写作阶段（用 paper-writing）
- 只需要语法检查（用专业编辑工具）
- 需要完全重写某一章节（用 paper-writing 的 section generation）

---

## 输入形式

### 形式 1：论文初稿 + 用户反馈

```yaml
draft_paper:
  file: "path/to/draft.pdf"  # 或 .docx, .md
  source: "writing_session_20240410"
user_feedback:
  feedback: "Introduction 太长，Related Work 与本文区分不清"
  focus_areas: ["introduction", "related_work"]
  revision_round: 1
```

### 形式 2：论文初稿 + 审稿意见

```yaml
draft_paper:
  file: "path/to/paper.pdf"
feedback:
  reviewer_comments:
    - comment_id: "R1-1"
      comment: "How does your method handle the multi-task setting differently from prior work?"
      section: "methodology"
    - comment_id: "R1-2"
      comment: "Table 3 is hard to read. Consider reformatting."
      section: "experiments"
  revision_deadline: "2024-04-20"
```

### 形式 3：纯论文初稿（自动诊断）

```yaml
draft_paper:
  file: "path/to/paper.pdf"
mode: "auto_diagnose"  # 自动识别常见问题
```

---

## 标准修改指南结构

修改指南包含 7 个部分，为每个部分提供具体修改建议：

### Part 1. Overall Assessment — 整体评估（1-2 页）

**内容**：
- **优点**：论文目前做得好的方面（至少 3 个）
- **主要问题**：影响学术贡献度的关键问题（优先级排序）
- **改进潜力**：修改后可达到的水平估计
- **时间预估**：完成全部修改所需时间

**格式示例**：
```
优点：
1. 核心想法新颖，多任务 RL 中动态路由是有意思的方向
2. 实验覆盖广泛（4 个环境），包括消融实验
3. 写作结构清晰，容易跟进

主要问题（按优先级）：
P1 - Related Work 与 Methodology 重复过多 → 建议合并并强化 Methodology 中的创新点
P1 - Experiments § 缺乏对失败 case 的分析 → 需要补充 negative results section
P2 - Abstract 不够具体 → 需要加入具体数字
```

### Part 2. Section-by-Section Analysis — 逐节分析（3-5 页）

对每个主要章节进行深度分析：

**格式（以 Introduction 为例）**：
```markdown
## Introduction

**当前状态**：
- 字数：500 words
- 主要观点：3 个
- 问题：开头铺垫太长，核心问题到第 3 段才出现

**具体问题**：

【问题 1】开头段落冗长
- 位置：Paragraph 1-2
- 问题描述：前两段都在讲背景，但都是标准知识，读者已知
- 修改方案：
  * 删除"Reinforcement learning has been widely used..."这样的概括
  * 直接从行业痛点开始："In complex robotic control, agents must..."
  * 预期效果：从 500 词减到 350 词，核心问题提前 50%

【问题 2】Gap analysis 不够尖锐
- 位置：Paragraph 3-4
- 问题描述：说了什么是 multi-task RL，但没有说清"为什么现有方法不行"
- 修改方案：
  * 补充一个反例或 motivating example
  * 加入数据对比："Previous methods suffer from X, showing Y% accuracy drop in..."
  * 引用一篇相关论文的失败 case
  
【问题 3】核心想法呈现不清晰
- 位置：Paragraph 5
- 问题描述：说了"dynamic routing"但没解释"为什么是 routing"而不是其他方案
- 修改方案：
  * 加入直觉解释："We hypothesize that..."
  * 配一个小图或流程图
  * 对比为什么 fixed routing 或 attention 不够

**修改后预期**：
- Introduction 长度：350 词（减少 30%）
- 核心问题露出：第 2 段（提前 1.5 段）
- 论文定位清晰度：提升到 9/10
```

### Part 3. Specific Edits — 具体编辑建议（2-4 页）

给出原文 + 修改版本 + 解释：

```markdown
### Edit 1: Abstract - 第 2 句

**原文**：
"We propose a novel framework for handling multi-task reinforcement learning."

**修改版**：
"We propose Dynamic Routing for Multi-Task RL (DR-MTRL), which adaptively selects task-specific policies and routing strategies, achieving X% improvement over fixed routing baselines on Y benchmark suite."

**解释**：
- 加入具体方法名称，便于引用
- 替换"novel framework"为具体描述
- 加入定量结果，提升论文可信度
```

### Part 4. Structural Recommendations — 结构调整建议（1-2 页）

```markdown
## 结构调整

### 建议 1: Related Work 和 Methodology 的边界
- 当前：Related Work 6 页，Methodology 4 页
- 问题：Related Work 中大量讨论该如何设计 routing，但这其实是 Methodology 的内容
- 建议：
  * 将 Related Work 压缩到 3 页，只保留代表性工作和差异分析
  * 将"现有 routing 方法"移到 Methodology 的开头，作为 motivation
  * 在 Methodology 中详细对比"我们的方案 vs. Prior Art X"

### 建议 2: 补充 Negative Results
- 当前：只展示成功的实验结果
- 建议：加入 1-2 个失败案例的分析
  * "当 X 条件下，方法性能下降，原因是..."
  * 帮助读者理解方法的适用范围
```

### Part 5. Evidence & Citation Gaps — 证据与引用缺口（1-2 页）

```markdown
## 证据缺口

### 缺口 1: Motivation 缺乏数据支撑
- 声称："Multi-task RL faces the challenge of task interference"
- 缺失：具体数据或引用来支撑这个声称
- 修改建议：
  * 引用 [CITE-Park2020] 的数据："Studies show Y% performance drop..."
  * 或加入自己的初步实验："Our preliminary experiment on Atari shows..."

### 缺口 2: Baseline 方法解释不足
- Baseline DR-Random 和 DR-Fixed 没有明确的伪代码或公式
- 修改建议：
  * 在 Methodology § 补充 Algorithm 1 (Random Routing) 和 Algorithm 2 (Fixed Routing)
  * 便于读者理解改进的基线
```

### Part 6. Writing & Clarity Improvements — 文笔与清晰度改进（1-2 页）

```markdown
## 文笔改进

### 问题 1: Jargon 过度使用
- 位置：Abstract, Methodology § 开头
- 问题：连续 3 句都以技术术语开头，非领域专家难以理解
- 改进：
  * 每个新术语第一次出现时加解释
  * 用"In other words, ..."模式重新表述一遍

### 问题 2: 被动语态过多
- 原文："The routing strategy was selected based on..."
- 改为："We select the routing strategy based on..."
- 效果：更直接、更有力

### 问题 3: 逻辑转折词不足
- 问题：段落间跳跃感强，逻辑链条断裂
- 改进：
  * 段尾加 summary 句
  * 段首加 transition 句
```

### Part 7. Revision Checklist — 修改检查清单（1 页）

完整的检查清单，确保所有修改都被执行：

```markdown
## 修改检查清单

### Critical (必改)
- [ ] Remove duplication between Related Work § 和 Methodology §
- [ ] Add negative results analysis to § 5
- [ ] Replace all "novel" with specific claims
- [ ] Verify all baseline methods have Algorithm/Equation

### Important (应改)
- [ ] Reduce Introduction to 350 words
- [ ] Add 2-3 motivating examples/figures
- [ ] Strengthen gap analysis with numbers
- [ ] Improve figure captions (current: too brief)

### Nice-to-have (可选)
- [ ] Improve writing flow in § 3
- [ ] Add more discussion on failure cases
- [ ] Consider adding a "method intuition" figure
```

---

## 制作流程

### Step 1: 获取论文和反馈

- 支持格式：PDF、DOCX、MD、HTML
- 自动提取结构、图表、表格、公式
- 可选：读取用户本地 notes/paper-notes/{paper-id}.md 中的已有反馈

### Step 2: 深度分析

**分析内容**：
1. 与已有 paper-table.md 对比，了解该论文的研究方向
2. 提取论文结构、关键数字、图表
3. 识别问题类型：逻辑、结构、证据、表达
4. 优先级排序：影响核心论证 > 学术严谨 > 文笔

### Step 3: 生成修改指南

为每个问题生成：
- 问题描述
- 修改建议（包括示例）
- 预期效果

### Step 4: 输出

#### 方式 A：Markdown 详细指南（默认）

输出到 `data/survey/paper-revision-{paper-id}.md`

#### 方式 B：Python 修改追踪脚本

输出 `scripts/revision_tracker.py`，用于：
- 跟踪多轮修改
- 对比修改前后
- 生成修改总结

---

## 与其他 Skill 的关系

```
paper-writing（初稿）
      ↓
paper-revision（迭代改进）← 可多轮使用
      ↓
rebuttal-writer（回复审稿意见）
```

- **上游**：paper-writing 生成的初稿
- **下游**：修改后的论文可用于 rebuttal-writer，或继续迭代
- **平行**：可与 citation-manager 配合，改进引用策略

---

## FAQ

**Q: 怎么区分"修改"和"重写"？**
A: 修改 ≤ 30% 词汇改动，核心结构保留。如果需要 > 50% 改动，用 paper-writing 的"section regeneration"。

**Q: 能同时处理多份反馈吗？**
A: 能。输入多个 reviewer comments，系统会合并、去重、优先级排序。

**Q: 修改后如何验证效果？**
A: 建议对比修改前后的 clarity score（用 NLP 工具），或递交给他人 blind review。

**Q: 支持非英文论文吗？**
A: 支持。内部转换为英文处理，输出可选英文或中文。

