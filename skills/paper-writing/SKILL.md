---
name: paper-writing
description: >-
  Generate research paper outlines, draft sections, and improve paper organization
  from a title, abstract, or rough research idea. Output structured section drafts
  with detailed guidance, citations points, and revision suggestions. Use when you
  want to write a research paper from scratch, draft specific sections (intro, related
  work, methodology, results, conclusion), improve paper flow, or generate a literature
  review. Triggered by prompts like "write a paper on...", "draft intro section",
  "organize my findings", "generate paper structure", "create methodology section",
  or when shown a paper topic/abstract to develop.
compatibility:
  requires: ["python-3.9"]
domain: writing
triggers:
  - write paper
  - draft section
  - 论文写作
  - paper outline
version: "1.0.0"
---
# Paper Writing — 学术论文写作辅助

> 将研究想法转化为结构清晰、论证充分的学术论文。  
> 提供逐节指导、范例、修改建议、引文建议点、评估标准。

---

## 核心原则

- **Clarity First**: 每句话服务一个目标（解释、支撑、连接）
- **Top-Down Structure**: 全局想法 → 局部细节，避免平铺直叙
- **Argument-Driven**: 每节都在推进论文的中心论点
- **Evidence-Based**: 用引文或实验结果支撑观点，不凭空主张
- **Iterative**: 先结构再内容，先粗稿再打磨

---

## 何时使用

✅ **有研究想法和初步结果，需要写成论文**
✅ **某一节卡住了（如 Related Work），需要结构和范例**
✅ **整篇论文写完了，需要改进组织和流畅度**
✅ **需要学术写作的 checklist 和最佳实践**

❌ **不用于：只是找论文引用资料**（用 citation-manager）
❌ **不用于：修改已完成论文的语言/语法**（用 paper-revision）

---

## 标准论文结构

### 7 段式结构（推荐用于 ICLR/NeurIPS/ACL）

| 节次 | 标题 | 页数 | 核心任务 |
|------|------|------|---------|
| 1 | Abstract | 0.25-0.5 | 问题 + 方法 + 结果，150-250 字 |
| 2 | Introduction | 2-4 | 背景、motivation、贡献、论文组织 |
| 3 | Related Work | 2-3 | 现有方法分类、与本文位置关系 |
| 4 | Methodology | 3-5 | 问题定义、方法、主要技术细节 |
| 5 | Experiments | 3-4 | 实验设置、baseline、结果、消融 |
| 6 | Discussion | 1-2 | 发现的意义、局限、未来方向 |
| 7 | Conclusion | 0.5-1 | 总结贡献、impact、closing thought |

**补充部分**：References, Appendix（数学推导、额外实验、细节代码）

---

## 工作流程

### PHASE 1: 捕获意图

首先理解用户的需求和背景：

```
Q1: 你的核心研究问题/贡献是什么？
    → 一句话总结：[用户的 one-liner]

Q2: 你已经做过实验吗？完成度如何？
    → yes/partial/no
    → 如果有，列出主要结果

Q3: 你的目标会议/期刊是什么？
    → (ICLR, ACL, AAAI, TKDE, 等)
    → [决定论文结构和风格]

Q4: 你有现存的draft章节吗？
    → yes → 列举哪些章节，简要内容
    → no → 从零开始

Q5: 你的paper是单一方法、对比研究、还是调研综述？
    → 类型决定 Related Work 和实验设计
```

**生成的输出**：用户研究背景 Profile（一句话 one-liner、目标会议、现有草稿、paper 类型）

---

### PHASE 2: 生成论文大纲

基于用户 Profile，生成全纸的结构化大纲：

**输出格式**：
```
# Paper Outline: [用户的 One-liner]

## Target: [会议] | Estimated Length: 8-10 pages

### § 1. Abstract (150-250 words)
- 背景：[1 句]
- 问题：[1 句]
- 方法核心：[1-2 句]
- 主要结果：[1 句]
- 影响/意义：[1 句]

### § 2. Introduction (2-4 pages)
**Key Claims to Establish:**
- 背景 motivation：[2-3 bullet]
- 为什么现有方法不够：[2 bullet]
- 我们的核心想法：[1-2 bullet]
- 论文的贡献 (3-5 个)：[bullet list]
- 论文结构预告：[1-2 句]

**Recommended Structure:**
1. Hook: [具体场景/痛点]
2. Background: [领域状态]
3. Gap: [现有方法的问题]
4. Our Idea: [核心想法一句话]
5. Contributions: [3-5 个明确的贡献]
6. Paper Org: [各节简介]

... (类似的详细指导用于每一节) ...
```

用户审核大纲后，询问："这个结构对吗？要修改吗？"

---

### PHASE 3: 分章节草稿生成

用户可以选择生成某一节的详细草稿，或让系统按顺序全部生成。

**单节草稿包含**：
1. **推荐结构**：该节通常的 3-5 个小节/段落
2. **样板文本**：每个小节 1-2 个示范句子，展示风格和论证方式
3. **关键要点检查**：该节必须涵盖的 5-10 个要点
4. **引文建议点**：应该在哪里引用相关论文，用 [CITE-1], [CITE-2] 标记
5. **字数目标**：该节的推荐页数/字数
6. **常见错误**：该节常犯的 3-5 个错误及改进方式
7. **修改建议**：根据用户的想法如何改进

**示例（Introduction 部分）**：

```markdown
# § 2. Introduction

## Recommended Structure

### 2.1 Hook & Background (0.5-1 page)
**样板**：
"在过去十年，强化学习在游戏、机器人控制等领域取得突破性进展 [CITE-1, CITE-2]。
然而，大多数 RL agent 是在单一任务上训练的。面对新任务时，从零学习的效率很低。"

**关键要点**：
- RL 的成功案例（要具体）
- RL 的局限：单任务、sample inefficient
- 多任务学习的意义：transfer、generalization

### 2.2 Gap Analysis (0.5-1 page)
**样板**：
"现有多任务 RL 方法主要分为两类：① 参数共享（parameter sharing）、② 任务条件化（task conditioning）。
前者通常导致 negative transfer [CITE-3]；后者则需要复杂的任务表示学习 [CITE-4]。"

**关键要点**：
- 列举 2-3 个相关方向
- 指出每个方向的局限
- 标记 Gap：这些都没解决的问题

### 2.3 Our Core Idea (0.5 page)
**样板**：
"我们提出 RoutingRL，一个基于动态路由的多任务强化学习框架。核心想法是：
与其预先决定参数共享的方式，我们让 agent 在执行过程中动态选择该用哪些模块。"

**关键要点**：
- 一句话核心想法
- 为什么这个想法能解决 Gap？
- 直觉解释（不涉及技术细节）

### 2.4 Contributions (0.5 page)
**关键要点**：
- 列举 3-5 个明确的贡献
- 每个贡献用一句话说清楚
- 标注 novelty（方法 vs 经验 vs 理论）

**样板**：
"本文的主要贡献包括：
1. **新框架**：提出 RoutingRL，一个端到端可学的多任务路由机制
2. **理论分析**：证明了路由机制下的收敛性，并给出性能上界 [THEORY]
3. **实验验证**：在 5 个多任务 Benchmark 上超越 SOTA，特别是在 transfer 场景下改进 30-45%"

### 2.5 Paper Organization (0.5 page)
**样板**：
"本文结构如下：§3 回顾多任务 RL 的相关工作。§4 正式定义问题并提出 RoutingRL 框架。
§5 分析路由机制的理论性质。§6 在三个 benchmark 上进行广泛实验。§7 讨论发现和局限。"

**关键要点**：
- 每个主要节的一句话总结
- 节的顺序合理吗？

## Common Mistakes in Introduction

❌ **错误 1**：Introduction 变成 Related Work  
→ **改进**：Focus on motivation and gap，Related Work 用独立一节详细讨论

❌ **错误 2**：Contributions 不清楚  
→ **改进**：每个贡献用一句话，标注是否 novel in method/experiments/theory

❌ **错误 3**：Hook 太generic  
→ **改进**：用具体的数字、场景、成功案例吸引读者

❌ **错误 4**：没有 paper organization 段  
→ **改进**：最后一段必须预告各章内容，帮助读者导航

❌ **错误 5**：Motivation 和 idea 混淆  
→ **改进**：先说为什么需要改进（motivation），再说我们的想法（core idea）

## Evaluation Checklist: Introduction

✅ Hook 中有具体数字/场景？
✅ Background 段落清楚传达了现状？
✅ Gap 明确指出了现有方法的 2-3 个具体局限？
✅ Our Idea 用一句话说清楚核心想法？
✅ Contributions 列出 3-5 个，每个一句话？
✅ Paper Org 段帮助读者预期各章内容？
✅ 整个 Introduction 占全文 15-20%？
✅ 没有过多技术细节（那是 Methodology 的事）？
```

---

### PHASE 4: 修改建议 & 流畅度检查

完成初稿后，系统可以进行：

**内容检查**：
- 各节是否独立又连贯？
- 论证链条清楚吗？
- 每节的 claim 都有支撑吗？

**结构检查**：
- Section 顺序合理吗？
- 有冗余或遗漏的地方吗？
- Transition 句够清楚吗？

**引文检查**：
- [CITE-X] 标记的位置够准确吗？
- 引文数量合理吗？（通常 introduction 10-15 篇，related work 20-30 篇）

**术语一致性**：
- 术语定义第一次使用时清楚吗？
- 同一个概念是否用同一个术语？

---

## 制作流程详述

### Step 1: 解析用户输入

用户可能提供：
- 论文标题 + 摘要草稿
- 论文想法的一段描述
- 已有的 draft 章节
- 指向 paper-reading 笔记的引用

**任务**：
1. 提取核心研究问题（用 one-liner 表达）
2. 识别目标会议/期刊（从用户输入推断或直接问）
3. 判断 paper 类型（方法、对比研究、综述、应用）
4. 列举已有草稿的质量和覆盖范围

### Step 2: 读取上下文文件

如果用户工作目录中存在以下文件，自动读取以增强个性化：

| 文件 | 用途 |
|------|------|
| `data/survey/paper-table.md` | 了解用户已读的相关论文 → 可用于引文建议 |
| `data/survey/research-state.yaml` | 了解用户当前研究方向 → 可用于背景补充 |
| `data/survey/notes/*.yaml` | 已读论文的详细笔记 → 可直接引用 |
| `paper-outline.md` 或 `research-plan.md` | 用户自己的研究计划 |

### Step 3: 生成 Paper Profile

```yaml
paper_profile:
  one_liner: "一句话研究问题"
  target_venue: "ICLR/ACL/..."
  paper_type: "method/comparison/survey/application"
  estimated_pages: 8-10
  has_experiments: yes/partial/no
  existing_sections: ["intro draft", "methodology sketch"]
  related_papers: [list of arxiv IDs from paper-table]
```

### Step 4: 生成大纲

调用 `scripts/outline_builder.py` 生成各节的结构化大纲。大纲包含：
- 各节推荐结构（几个小节，每个小节几段）
- 各节的核心要点检查表
- 各节的推荐字数/页数
- 过渡句建议

### Step 5: 交互式分章节生成

用户选择需要生成的章节（或全部自动生成）。每章包含：
- 推荐结构说明
- 样板文本（展示风格和论证方式）
- 关键要点检查列表
- [CITE-X] 引文标记点
- 常见错误清单
- 修改建议

### Step 6: 集成和打磨

生成完整的 paper draft，然后进行：
- 内容连贯性检查
- 论证链条验证
- 术语一致性扫描
- 引文位置优化建议
- 字数/页数调整建议

### Step 7: 导出格式

输出选项：
- **Markdown Draft**（default）：完整的 draft 可直接复制到 Overleaf
- **LaTeX Template**：带 section 模板的 .tex 文件
- **Critical Review**：打分卡，每节评估 clarity/evidence/structure
- **Revision Plan**：优先级清单，建议改进顺序

---

## 各节写作指南

本节提供各节的详细写作指南。详见 `references/section_guidelines.md`。

简要概览：

### 1. Abstract

**目标** (3-5 句，150-250 字)：
- 背景 (1 句)
- 问题 (1 句)
- 方法核心 (1-2 句)
- 主要结果 (1 句)
- 意义 (1 句)

**常见错误**：太generic、没有具体数字、method 过多细节

### 2. Introduction

**目标** (2-4 页)：Motivate → Identify Gap → Propose Idea → List Contributions

**结构**：Hook + Background + Gap + Our Idea + Contributions + Paper Org

### 3. Related Work

**目标** (2-3 页)：分类现有方法、定位本文

**方式**：不是按时间顺序列举，而是按技术维度分组

### 4. Methodology / Problem Definition

**目标** (3-5 页)：形式化问题、提出方法、说明技术创新

**结构**：Problem Setup → Our Framework → Technical Details → Algorithm/Pseudo-code

### 5. Experiments

**目标** (3-4 页)：Setup → Baselines → Results → Analysis

**结构**：Data & Implementation → Baselines → Main Results → Ablation → Case Studies

### 6. Discussion

**目标** (1-2 页)：发现的含义、局限、未来方向

**结构**：Key Findings → Why It Works → Limitations → Future Work

### 7. Conclusion

**目标** (0.5-1 页)：简洁总结、impact 陈述

**结构**：Summary of Contributions → Broader Impact → Closing Thought

---

## 输出格式

### 默认输出：Markdown Draft

生成完整的论文 draft，存储到 `data/writing/paper-draft-{timestamp}.md`：

```markdown
# [论文标题]

**作者**：[用户名]
**目标**：[会议]
**状态**：Draft v1
**生成于**：[时间]

---

## Abstract

[完整的 abstract 草稿]

## 1. Introduction

[完整的 introduction 草稿，包括 [CITE-X] 标记]

... (其他章节)

## References

[按引用出现顺序排列的参考文献列表]

---

## Revision Notes

[系统生成的修改建议，按优先级排序]
```

### 可选输出 1：Critical Review

为每一节生成评分卡：

```yaml
sections:
  abstract:
    clarity: 7/10
    evidence: 6/10
    structure: 8/10
    issues:
      - "背景句太generic"
      - "结果部分缺少具体数字"
    suggestions:
      - "用具体的性能数字替换 'significant improvement'"
  introduction:
    clarity: 8/10
    ...
```

### 可选输出 2：Revision Priority

```markdown
# Revision Plan (Priority Order)

## 🔴 Critical (must fix before submission)
- [ ] Abstract: 添加具体的性能指标数字
- [ ] Introduction: 清晰定义"negative transfer"的含义
- [ ] Related Work: 添加 3 篇关于 task routing 的最新论文

## 🟡 Important (should fix)
- [ ] Methodology: Algorithm 1 的伪代码需要更清楚
- [ ] Experiments: 补充 std dev 错误条
- [ ] Discussion: 对比与 DER 的具体差异

## 🟢 Nice to have (polish)
- [ ] 统一术语：用 "module routing" 替代 "dynamic routing"
- [ ] Introduction: 添加 1-2 个引用以支持 motivation
```

---

## 上下文感知

Skill 会读取以下文件优化建议：

| 文件 | 用途 |
|------|------|
| `data/survey/paper-table.md` | 提取用户已读论文，用于引文建议和背景补充 |
| `data/survey/research-state.yaml` | 理解当前研究主题，提供方向性指导 |
| `data/survey/notes/` | 已读论文的详细笔记，可引用其分析 |

如果这些文件不存在或为空，直接询问用户的研究背景。

---

## Speaker Notes / Writing Tips

### Introduction 的常见陷阱

❌ 用太多背景（这不是 Related Work）  
✅ 聚焦 motivation 和 gap，快速切入核心想法

❌ Contributions 不清楚或过于谦虚  
✅ 每个贡献清晰独立，用"我们是第一个 / 首次展示 / 首次证明"

❌ "Our work" 出现太多次  
✅ 在第一段明确后，多用"该方法"、"框架"等代词

### Related Work 的黄金法则

❌ 按时间顺序列举论文  
✅ 按技术维度分组，每组指出与本文的关系

❌ 对每篇论文逐句总结  
✅ 每组 1-2 句 takeaway，解释与本文的区别

### Methodology 的清晰性检查

- 问题定义能用符号表达吗？（如果不能，说明还不够清楚）
- Algorithm 能用伪代码 (pseudocode) 表达吗？
- 核心 technical contribution 能用一张图表达吗？

### Experiments 的可信度

- Baseline 是 SOTA 吗？（如果不是，为什么选它们？）
- 数据集是 standard benchmark 吗？
- 实验是否可复现？（超参数、随机种子、重复次数都清楚吗？）

---

## 与其他 Skill 的关系

```
brainstorming (产生想法)
    ↓
paper-writing (组织成论文结构)
    ↓
paper-revision (接收反馈，改进)
    ↓
rebuttal-writer (应对 review)
```

- **上游**：可先用 `brainstorming` 理清想法，再用本 Skill 组织成论文
- **下游**：完成初稿后用 `paper-revision` 接收 feedback，或用 `paper-presentation` 制作 talk

---

## FAQ

**我还没想好想写什么**  
→ 用 `brainstorming` Skill 先产生和筛选想法，然后回到 paper-writing

**我有完整的 draft，只想改进某几节**  
→ 输入现有 draft，指定需要改进的节，系统只生成那些部分的修改建议

**我想写 survey/综述类论文**  
→ Related Work 会自动扩展成 3-5 页，Methodology 改为"Survey 框架"和"分类法"

**怎样选择合适的目标会议？**  
→ 根据研究方向推荐：强化学习→ICLR/IJCAI；NLP→ACL/EMNLP；系统→OSDI/SOSP；等

**我应该先写 Introduction 还是 Methodology？**  
→ 通常顺序：Methodology(清思路) → Abstract(最后) → Introduction(定位) → Related Work(对标) → Experiments(验证) → Discussion(反思) → Conclusion(总结)

