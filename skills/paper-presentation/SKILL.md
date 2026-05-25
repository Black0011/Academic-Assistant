---
name: paper-presentation
description: Generate a structured academic paper presentation (12-section format)
  from a paper URL, arXiv ID, paper title, or local PDF. Outputs a detailed slide
  outline with speaker notes, or a runnable python-pptx script for PPTX generation.
  Use when the user wants to present a single paper, prepare a paper talk, make a
  conference-style presentation, create slides for a paper reading group, or turn
  a paper into a seminar talk. Also triggers when the user asks to "讲解论文", "做论文汇报",
  "prepare a paper talk", or "generate slides for this paper".
domain: presentation
triggers:
- present paper
- paper talk
- 论文汇报
- make slides
version: 1.0.0
---

# Paper Presentation — 单篇论文汇报制作

你是学术汇报设计师。将一篇论文转化为结构清晰、逻辑连贯、适合口头汇报的演示内容。

## 核心原则

- **讲故事，不是抄论文**：每张幻灯片传递一个观点，用汇报者的语言重构
- **连接听众**：开头建立"为什么关心这篇论文"，结尾回到"对我们有什么用"
- **数据支撑**：关键数字直接引用原文，标注出处（Table/Figure 编号）
- **批判性视角**：不仅展示论文说了什么，还要评论做得好不好

---

## 12 节标准结构

这是论文汇报的完整框架。每一节的目的、内容要求和幻灯片数量如下：

### § 1. Why This Paper — 选题动机（1-2 张）

**目的**：让听众理解你为什么选了这篇论文，建立与你自身工作方向的关联。

**内容要素**：
- 这篇论文解决的核心问题是什么（一句话）
- 与汇报者当前研究方向的关联（数据 Agent、评估模块、RL 等）
- 与汇报者已有工作（如多任务 RL）的技术衔接点
- "读完这篇论文，我们能获得什么"

**生成方法**：
1. 读取用户的研究背景（从对话上下文、paper-table.md、research-state.yaml 推断）
2. 提取论文核心贡献
3. 找到二者的交叉点，用 2-3 个 bullet 说明关联

### § 2. Table of Contents — 目录（1 张）

**内容**：列出汇报的章节结构和页码范围，让听众有预期。

### § 3. Research Background — 研究背景（3-5 张）

**目的**：为不熟悉该领域的听众提供必要上下文。

**内容要素**：
- **学术界趋势**：该方向近 2-3 年的发展脉络（配时间线或里程碑图）
- **工业界应用**：实际产品/系统中的落地场景
- **研究动机（重点）**：现有方法的核心痛点是什么？为什么需要新方案？
  - 用"旧方法存在问题 X → 本文提出方案 Y"的叙事逻辑

**生成方法**：
1. 从论文 Introduction 和 Related Work 提取背景信息
2. 结合 WebSearch 补充最新行业动态
3. 用"问题驱动"的叙事组织（不是历史流水账）

### § 4. Related Work — 相关工作（2-3 张）

**目的**：定位本文在技术谱系中的位置。

**内容要素**：
- 将相关工作按方法类型/技术路线分组（表格或分类树）
- 每组代表性工作的核心思想（1 句话）
- 本文与每组的区别/改进点

**呈现方式**：推荐用分类表格，最后一列标注"本文改进"。

### § 5. Insight — 核心洞察（1-2 张）

**目的**：用最精炼的语言传达论文的"Aha moment"。

**内容要素**：
- **目标问题**：一句话定义要解决的问题
- **主要思想**：一句话说明核心 idea（不是方法细节，是思想层面的突破）
- **解决路径**：从 idea 到方法的推导逻辑

**质量标准**：听众看完这 1-2 张应该能说出"哦，原来可以这样想"。

### § 6. Problem Definition — 问题定义（1-2 张）

**目的**：用数学/形式化语言精确描述问题。

**内容要素**：
- 符号定义表（输入、输出、关键变量）
- 形式化问题陈述（目标函数/优化目标）
- 关键假设和约束条件

**呈现方式**：左侧符号表，右侧公式。公式不超过 3 个核心等式。

### § 7. Proposed Framework — 研究框架（1-2 张）

**目的**：给出方法的全局视图。

**内容要素**：
- 框架整体架构图（流程图/系统图）
- 主要模块及其功能（用颜色区分）
- 数据流方向标注

**呈现方式**：一张大图 + 简要文字标注。细节留到下一节。

### § 8. Framework Details — 框架细节（3-5 张）

**目的**：深入每个模块的具体设计。

**内容要素**：
- 每个核心模块单独一张（或两张）：
  - 模块内部构造
  - 输入/输出规格
  - 关键算法步骤或伪代码
- 数据处理流程（端到端流水线）
- 训练流程 vs 推理流程的区别（如适用）

### § 9. Experimental Setup — 实验设置（1-2 张）

**内容要素**：
- 数据集：名称、规模、特点
- 基线方法列表
- 评估指标
- 实现细节（模型规模、训练超参数等关键信息）

### § 10. Results & Analysis — 实验结果（3-5 张）

**内容要素**：
- **主实验结果**：核心对比表格，高亮本文方法的最优数字
- **消融实验**：各组件贡献分析
- **分析与可视化**：case study、attention 图、误差分析等
- 每张结果页的标题用"结论句"而非描述句
  - ✅ "GenRM-CoT 在 GSM8K 上超越判别式 RM 16-64%"
  - ❌ "GSM8K 实验结果"

### § 11. Commentary — 评论与讨论（1-2 张）

**目的**：展示汇报者的批判性思考。

**内容要素**：
- **优点总结**：论文做得好的地方（方法/实验/写作）
- **局限与不足**：
  - 方法层面：假设是否成立？泛化性如何？
  - 实验层面：基线是否充分？场景是否覆盖？
  - 工程层面：计算开销、可落地性
- **对我们的启发**：哪些想法可以直接借鉴到自己的工作中
- **未来方向**：基于这篇论文可以做什么后续工作

### § 12. Appendix & References — 附录与参考文献（1-2 张）

- 引用的关键论文列表
- 补充材料（额外实验、数学推导等）
- Q&A 页（可选）

---

## 制作流程

### Step 1: 获取论文内容

根据用户提供的输入类型获取论文：

| 输入类型 | 获取方式 |
|---------|---------|
| arXiv URL / ID | WebFetch `https://arxiv.org/html/{id}` 获取 HTML 全文 |
| 论文标题 | WebSearch 定位，然后获取全文 |
| 本地 PDF 路径 | 直接 Read 读取 |
| Semantic Scholar URL | WebFetch 获取元数据，再找全文 |

**优先获取 HTML 版本**（arXiv HTML），内容提取最完整。PDF 次之。

### Step 2: 三遍提取

**第一遍（结构扫描）**：
- 提取所有章节标题
- 提取所有图表的 caption
- 提取摘要和结论

**第二遍（内容提取）**：
- 逐节提取核心内容，映射到 12 节结构
- 提取所有关键数字（实验结果、对比数据）
- 提取所有公式和符号定义

**第三遍（连接构建）**：
- 识别论文的核心 insight（区别于方法描述）
- 构建与用户研究方向的关联
- 形成批判性评价

### Step 3: 构建汇报大纲

输出结构化大纲供用户确认：

```yaml
presentation:
  title: "论文标题"
  subtitle: "汇报副标题"
  total_slides: 25-35
  duration_estimate: "30-40 分钟"
  sections:
    - name: "§1 Why This Paper"
      slides: 2
      key_points: ["关联点1", "关联点2"]
    - name: "§2 Table of Contents"
      slides: 1
    # ... 以此类推
```

### Step 4: 生成内容

为每张幻灯片生成：
- **标题**：结论句（不是描述句）
- **要点**：3-5 个 bullet，每个不超过 20 字
- **Speaker Notes**：口头讲解的完整文本（100-200 字/页）
- **视觉建议**：图表、表格、流程图的描述

### Step 5: 输出

#### 方式 A：Markdown 详细大纲（默认）

输出到 `data/survey/paper-talk-{paper-id}.md`，包含完整的幻灯片内容和 speaker notes。

#### 方式 B：Python-pptx 脚本

生成可执行脚本到 `data/survey/make-paper-talk.py`，运行后生成 `.pptx` 文件。
使用与 `presentation-maker` Skill 相同的视觉设计规范。

#### 方式 C：Marp Markdown

输出 Marp 格式的 Markdown，可直接渲染为幻灯片。

---

## 上下文感知

Skill 会自动读取以下文件获取用户研究背景（用于 §1 和 §11）：

| 文件 | 用途 |
|------|------|
| `data/survey/paper-table.md` | 了解用户已调研的论文和方向 |
| `data/survey/research-state.yaml` | 了解当前调研主题和分支 |
| `data/survey/findings.md` | 了解已有发现和开放问题 |

如果这些文件不存在或为空，直接询问用户的研究背景。

---

## Speaker Notes 写作规范

Speaker notes 是汇报者的口头讲稿，质量直接决定汇报效果：

- **开场**（§1）：用一个具体场景引入，不要上来就念公式
- **过渡**：每节之间有显式过渡句（"了解了背景，我们看看作者具体怎么做的"）
- **节奏**：每张幻灯片的讲解时间 1-2 分钟，notes 控制在 100-200 字
- **互动**：在关键 insight 处加入修辞问句（"你觉得这里应该怎么做？"）
- **总结**：每个大节结束时有一句话回顾

---

## 与其他 Skill 的关系

```
paper-reading（精读论文，生成 YAML 笔记）
       ↓
paper-presentation（将精读结果转化为汇报）
       ↓
presentation-maker（如需更精美的 PPTX）
```

- **上游**：可先用 `paper-reading` 生成结构化笔记，再用本 Skill 转化为汇报
- **下游**：如需高质量 PPTX 排版，可将大纲传递给 `presentation-maker`

---

## 常见问题

**论文太长/太技术化**：聚焦 §5-§8 的核心方法，§3 背景和 §10 实验适度精简。

**找不到与自身工作的关联**：扩大关联维度——方法论借鉴、问题定义相似、评估思路可迁移、同一技术栈等。

**听众不熟悉该领域**：加厚 §3 背景（3→5 张），精简 §8 细节（5→3 张），增加直觉解释。

**时间限制**：

| 时长 | 建议幻灯片数 | 精简策略 |
|------|------------|---------|
| 15 分钟 | 15-18 张 | 合并 §3+§4，精简 §8，跳过 §12 |
| 30 分钟 | 25-35 张 | 标准 12 节 |
| 45 分钟 | 35-45 张 | 扩展 §8 和 §10，增加 demo/case study |
