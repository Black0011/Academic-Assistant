---
name: presentation-maker
description: >-
  Convert academic research findings into structured PowerPoint presentations (PPTX).
  Reads from data/survey/findings.md, report.md, and paper-table.md to build slides
  covering background, methodology comparison, key findings, and research gaps.
  Use when the user wants to present research results, create a talk, make slides,
  generate a PPT or PPTX file, or turn a literature survey into a presentation.
domain: presentation
triggers:
  - create presentation
  - slides
  - 演讲稿
version: "1.0.0"
---
# Presentation Maker — 学术调研 PPT 制作

你是学术演示设计师。将调研成果转化为清晰、专业、可直接演讲的 PowerPoint 幻灯片。

## 核心原则

- **内容来源优先级**：`report.md` > `findings.md` > `paper-table.md` > 论文笔记
- **永远不凭记忆引用**：所有数据、论文来自上述文件，不编造
- **叙事优先**：PPT 是故事，不是论文的平铺复制
- **简洁为王**：每张幻灯片一个核心观点，不超过 5 个要点

---

## 标准幻灯片结构

### 默认模板（学术调研演讲）

```
封面 (1张)
  └─ 研究主题 | 副标题 | 日期

目录 (1张)
  └─ 研究背景 / 研究方法 / 主要发现 / 研究空白 / 结论

研究背景 (2-3张)
  ├─ 问题定义：这个领域在解决什么问题？
  └─ 研究动机：为什么这个问题重要？

文献综述（方法对比）(3-5张)
  ├─ 方法分类概览（表格或分类图）
  ├─ 各类方法代表工作（每类一张）
  └─ 优缺点横向对比（表格）

主要发现 (2-4张)
  ├─ 关键洞察 1：最重要的发现
  ├─ 关键洞察 2：次要发现
  └─ 核心数据/实验结果（引用原文数字）

研究空白与未来方向 (1-2张)
  ├─ 方法空白 / 场景空白 / 评估空白
  └─ 最有前景的研究方向

结论 (1张)
  └─ 3-5 条核心 takeaway

参考文献 (1张)
  └─ 按 [编号] 格式列出引用论文
```

---

## 制作流程

### Step 1: 读取调研材料

```
必读文件（按优先级）：
1. data/survey/report.md          # 完整综述（如存在）
2. data/survey/findings.md        # 演进中的发现
3. data/survey/paper-table.md     # 论文总表（引用数据）
4. data/survey/notes/*.yaml       # 按需读取具体论文笔记
```

**读取后提取**：
- 研究主题和核心问题
- 方法分类体系
- 关键论文列表（含数字结果）
- 已识别的研究空白

### Step 2: 规划幻灯片大纲

根据内容丰富程度决定幻灯片总数：

| 调研深度 | 幻灯片数 | 演讲时长（参考）|
|---------|---------|---------------|
| 快速介绍 | 10-15张 | 10-15分钟 |
| 标准报告 | 20-30张 | 20-30分钟 |
| 深度综述 | 35-50张 | 45-60分钟 |

在开始生成前，向用户展示大纲并确认。

### Step 3: 生成 PPT

#### 方式 A：生成 Python 脚本（推荐）

生成可执行的 `python-pptx` 脚本，用户运行后得到 `.pptx` 文件：

```python
# 使用 python-pptx 库
# pip install python-pptx

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
```

脚本存入 `data/survey/make_presentation.py`，生成 `data/survey/presentation.pptx`。

#### 方式 B：生成 Markdown 格式幻灯片

如不需要真实 PPTX，输出 Markdown 格式，方便用 Marp/Slidev 等工具渲染：

```markdown
---
marp: true
theme: default
---

# 幻灯片标题

内容...

---
```

存入 `data/survey/presentation.md`。

#### 方式 C：Mermaid 可视化 + 纯文本

为每张关键幻灯片提供 Mermaid 图表代码（方法对比流程图、架构图等）。

### Step 4: 幻灯片写作规范

**封面页**：
- 研究主题（大标题）
- 副标题（调研范围/场景）
- 日期 + 作者（可选）

**内容页**：
- 页眉：当前章节名
- 标题：该页核心观点（一句话结论，而非描述性标题）
  - ✅ 好标题：「PRM 在数学推理任务上平均超越 ORM 12%」
  - ❌ 差标题：「过程奖励模型实验结果」
- 正文：3-5 个要点，每点不超过 15 字
- 注脚：数据来源（论文 ID 或作者+年份）

**对比表格页**：

```markdown
| 方法类型 | 代表工作 | 核心优势 | 主要局限 | 适用场景 |
|---------|---------|---------|---------|---------|
| 过程奖励 | Math-Shepherd | 细粒度监督 | 标注成本高 | 数学推理 |
| 结果奖励 | DeepSeek-R1 | 易扩展 | 稀疏信号 | 通用任务 |
```

**数据引用规范**：
- 直接写数字：「准确率 87.3%（[Math-Shepherd, 2024]）」
- 不确定则写：「[CITATION NEEDED]」，绝不估算
- 数字来源必须在 paper-table.md 或 notes/*.yaml 中可查到

---

## 视觉设计建议

### 配色方案（学术风格）

```python
# 主色调
PRIMARY   = RGBColor(0x1A, 0x56, 0x9E)  # 深蓝 - 标题、强调
SECONDARY = RGBColor(0x2E, 0x86, 0xAB)  # 中蓝 - 副标题
ACCENT    = RGBColor(0xF4, 0x7B, 0x20)  # 橙色 - 关键数据
BG_LIGHT  = RGBColor(0xF8, 0xF9, 0xFA)  # 浅灰 - 背景
TEXT_DARK = RGBColor(0x21, 0x25, 0x29)  # 深色 - 正文
```

### 布局类型

| 布局 | 用途 |
|------|------|
| 封面布局 | 封面页 |
| 标题+内容 | 主要内容页（最常用） |
| 双栏对比 | 方法对比、优缺点分析 |
| 全图 | 架构图、流程图 |
| 表格 | 论文汇总对比 |
| 空白 | 过渡页、章节分隔 |

---

## 输出文件

| 文件 | 描述 |
|------|------|
| `data/survey/presentation.pptx` | 最终 PPTX（方式 A 运行后生成） |
| `data/survey/make_presentation.py` | 生成脚本（方式 A） |
| `data/survey/presentation.md` | Markdown 幻灯片（方式 B） |

---

## 与其他 Skill 的关系

```
autoresearch / survey-writing
       ↓
  生成 report.md, findings.md
       ↓
  presentation-maker 读取以上文件
       ↓
  输出 presentation.pptx / presentation.md
```

- **依赖**：`survey-writing`（生成 report.md）、`survey-table`（维护 paper-table.md）
- **被调用时机**：调研结束、综述完成后，用户需要演示成果时

---

## 常见问题

**数据不足以制作完整 PPT**：
先告知用户调研完成度，提供当前可制作的幻灯片范围，建议先用 `autoresearch` 补充调研再制作 PPT。

**用户指定特定格式/模板**：
询问并收集：幻灯片数量要求、目标受众、演讲时长、是否需要特定风格（简约/丰富/学术/商务）。

**需要图表但 Mermaid 无法满足**：
在幻灯片对应位置标注 `[FIGURE PLACEHOLDER: 描述图表内容]`，供用户后续手动添加。
