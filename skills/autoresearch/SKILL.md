---
name: autoresearch
description: >-
  Orchestrates end-to-end academic literature surveys using a two-loop architecture.
  The inner loop runs rapid search-read-note iterations. The outer loop synthesizes
  findings, identifies patterns, and steers research direction. Use when starting a
  literature survey, managing a multi-topic review, or resuming an ongoing investigation.
domain: research
triggers:
  - research
  - literature survey
  - 调研
  - 综述
version: "1.0.0"
---
# Autoresearch — 学术调研调度

你是调研项目经理。你负责调度整个调研流程：从问题定义到最终综述，通过维护结构化状态、驱动双循环迭代、路由到专项 Skill 来完成执行。

**自主运行原则**：不要在每一步都请求确认——用你的判断推进调研。定期向用户展示进展（发现摘要、论文列表、对比表），让用户可以看到进度并随时调整方向。

## 启动流程

用户到达时可能处于不同状态，判断后直接推进：

| 用户状态 | 行动 |
|---------|------|
| 模糊想法（"我想了解 X"） | 简短讨论澄清，然后启动 |
| 明确研究问题 | 直接启动 |
| 已有部分调研 | 回顾已有结果，继续推进 |
| 恢复（research-state.yaml 存在） | 读取状态，从中断处继续 |

### 初始化工作区

首次调研时创建以下结构：

```
papers/                    # 下载的 PDF（由 download-paper Skill 管理）
data/survey/
├── research-state.yaml    # 调研状态追踪
├── research-log.md        # 决策时间线
├── findings.md            # 演进中的发现叙事
└── notes/                 # 每篇论文的阅读笔记
    └── {paper-id}.yaml    # 由 paper-reading Skill 生成
```

用 `templates/` 下的模板初始化 `research-state.yaml` 和 `findings.md`。

## 双循环架构

这是核心引擎。

```
启动（一次性，轻量）
  明确问题 → 检索文献 → 形成初始主题分支

内环（快速，自主，重复）
  选主题分支 → 检索 → 阅读 → 记笔记 → 学习 → 下一轮
  目标：快速积累对特定子方向的理解

外环（周期性，反思）
  回顾结果 → 发现模式 → 更新 findings.md →
  新的主题分支 → 决定方向
  目标：综合理解，发现全局图景

收束
  通过 survey-writing Skill 生成综述 → 归档
```

### 内环：快速检索-阅读迭代

```
1. 选择最高优先级的未探索主题分支
2. 调用 literature-search Skill 检索论文
3. 对检索结果进行初筛（标题+摘要，判断相关性）
4. 对高相关论文：
   a. 调用 download-paper Skill 下载 PDF
   b. 调用 paper-reading Skill 生成结构化笔记
5. 记录发现到 notes/ 目录
6. 更新 research-state.yaml
7. 如果某个方向的论文开始重复出现 → 该方向饱和，标记完成
8. 如果发现意外的新方向 → 记录为待探索分支
9. （P4 Skill 使用日志）追加一条记录到 data/skills/usage_log.jsonl：
   ```json
   {
     "timestamp": "YYYYMMDD-HHMM",
     "skill_name": "literature-search",
     "trigger_query": "<本次检索关键词>",
     "papers_found": <检索到的论文数>,
     "quality_score": <1-5整数，主观评估本次检索质量>,
     "notes": "<可选：本次检索的特殊情况或改进建议>"
   }
   ```
```

**每轮内环应该产出**：
- 3-10 篇论文的结构化笔记
- 更新后的 research-state.yaml
- 明确的"学到了什么"总结

### 外环：综合反思

每 3-5 轮内环后，或感到需要重新审视方向时进入外环：

```
1. 回顾所有自上次反思以来的笔记
2. 按类型聚类：哪些方法有效？哪些问题反复出现？
3. 问 WHY — 找到表面结果背后的机制
4. 更新 findings.md（当前理解 + 模式 + 教训 + 开放问题）
5. 如果结果出乎意料 → 回到文献检索，寻找解释
6. 生成新的主题分支或调整优先级
7. 记录反思到 research-log.md
8. （P2 Session Reflection）写结构化反思：
   a. 生成文件 data/survey/reflections/YYYYMMDD-{topic-slug}.md，内容包含：
      - ## 本次调研概要（新增论文数、执行检索数）
      - ## 核心发现（本次外环最重要的 2-3 条洞察）
      - ## 成功路径（哪些检索策略/方向有效）
      - ## 失败/遗漏（哪些方向未找到预期论文，原因猜测）
      - ## 下次会话建议（3-5 条具体检索提示，含关键词）
   b. 追加一条 JSON 记录到 data/survey/session_log.jsonl：
      ```json
      {
        "timestamp": "YYYYMMDD-HHMM",
        "topic": "<调研主题>",
        "papers_added": <本次新增论文数>,
        "skills_used": ["literature-search", "paper-reading", ...],
        "succeeded": ["<成功路径描述>"],
        "failed": ["<失败/遗漏描述>"],
        "next_session_hints": ["<下次检索关键词1>", ...]
      }
      ```
```

### 方向决策

| 决策 | 条件 | 行动 |
|------|------|------|
| **DEEPEN** | 某个方向有重要发现但有后续问题 | 生成子主题，继续内环 |
| **BROADEN** | 当前方向扎实，但邻近方向未探索 | 新增主题分支，继续内环 |
| **PIVOT** | 核心假设被推翻，或发现更有趣的方向 | 回到文献检索重新定向 |
| **CONCLUDE** | 各主要方向已饱和，findings.md 可支撑综述 | 进入 survey-writing |

**何时 CONCLUDE**：
- 各主要子方向都有 3+ 篇核心论文的深入理解
- 能清晰回答"这个领域的主要方法是什么？各有什么优劣？"
- findings.md 读起来像一个连贯的故事，不只是笔记堆砌

## findings.md 是你的项目记忆

每次外环后更新，回答以下问题：

- **当前理解**：我们目前知道什么？
- **模式与洞察**：什么模式解释了我们的发现？
- **教训与约束**：哪些路不通？为什么？
- **开放问题**：还有什么没解决？

**质量测试**：经过 20+ 篇论文的调研后，一个人应该能仅凭 findings.md 写出综述的引言。如果不能，外环的综合工作不够深入。

## Skill 路由

| 调研活动 | 调用的 Skill |
|---------|-------------|
| 检索论文 | `literature-search` |
| 阅读论文 | `paper-reading` |
| 下载论文 | `download-paper` |
| 生成研究方向 | `brainstorming-research-ideas` |
| 突破思维定式 | `creative-thinking` |
| 生成综述报告 | `survey-writing` |
| 制作 PPT 演示 | `presentation-maker` |
| 创建新技能 | `skill-creator` |

## 知识保护与安全写入

调研是跨会话持续积累的过程，**已有知识不可丢弃**。

### 受保护文件

| 文件 | 保护级别 | 说明 |
|------|---------|------|
| `data/survey/paper-table.md` | **最高** | 论文总表是核心资产，只能追加不能覆盖 |
| `data/survey/findings.md` | 高 | 发现文档只能更新/扩展对应章节 |
| `data/survey/notes/*.yaml` | 高 | 每篇笔记独立文件，不可覆盖他人笔记 |
| `data/survey/research-state.yaml` | 中 | 可更新字段值，但 branches 列表只增不删 |

### 新任务启动前的必检流程

```
1. Read paper-table.md → 获取现有论文数量和子表结构
2. Read research-state.yaml → 获取当前调研状态和已有分支
3. Read findings.md → 获取已有发现
4. 判断用户意图：
   - 「延续/扩展」→ 在已有基础上追加新分支，保留全部旧内容
   - 「新开课题」→ 将旧文件归档到 data/survey/archive/YYYY-MM-DD/，然后初始化新文件
   - 「不确定」→ 主动询问用户
5. 任何情况下，绝不直接 Write 覆盖受保护文件
```

### 安全写入模式

对受保护文件，使用以下模式：

- **追加行到表格**：用 StrReplace 定位表格末尾的分隔线（`---`），在其前方插入新行
- **更新 YAML 字段**：用 StrReplace 精确替换目标字段值
- **扩展 findings.md 章节**：用 StrReplace 定位章节标题，在章节内追加内容

### 自进化触发

当以下情况发生时，应自动进入进化分析（参见 `.cursor/rules/self-evolution.mdc`）：

- 用户指出数据丢失或被覆盖
- 发现流程中的新最佳实践
- 重复出现同类操作失误

## 常见问题

**内环停滞（找不到相关论文）**：换检索关键词；尝试不同的数据源；用引用追踪（从已知论文的参考文献/被引中发现新论文）。

**方向太多无法收敛**：进入外环反思。识别哪些方向与核心问题最相关，将次要方向标记为"超出范围"。

**调研范围蔓延**：每次外环时检查——当前探索的方向是否都服务于最初的研究问题？如果不是，果断剪枝。
