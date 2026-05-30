---
name: brainstorming-research
description: >-
  Pre-writing research dialogue gate. Forces a 7-round one-question-at-a-time
  conversation (paper type → discipline → title → background → method →
  LaTeX template → chapter structure) before any chapter is written. Maps
  paper type to a default chapter structure (CS-SCI / SCI journal / 中文
  核心 / Course / Thesis / Survey / Workshop), creates `plan/` directory
  via `init_paper_plan.py`, and locks the result in
  `plan/project-overview.md`. Hard gate: cannot dispatch writing-chapters
  / paper-writing until user explicitly confirms summary. Use when the
  user says "新论文 / 我要开始写 / start a new paper / 帮我写一篇关于...
  / 选题确定了 / 论文初始化", or when paper-orchestration detects
  S0 (Scope) is incomplete. Distinct from existing `brainstorming` skill
  which is for creative-divergent ideation only.
domain: ideation
triggers:
  - 新论文
  - 我要开始写
  - start a new paper
  - 论文初始化
  - 选题确定了
version: "1.0.0"
compatibility:
  requires: ["python-3.9"]
# v2.2.5 Skill DAG metadata（WP10 of research-writing-skill adoption）
preconditions:
  - "用户表达启动新论文 / 论文规划 / 重启已有论文（无 plan/）的意图"
consumes:
  - "用户对话回答（7 轮以上，逐轮收集）"
  - "（可选）用户已上传的题目 / 摘要 / 导师要求"
  - "data/papers/<paper-id>/latex-templates/*.tex（如存在）"
produces:
  - "data/papers/<paper-id>/plan/{project-overview,outline,progress,notes,stage-gates}.md（强制产物，通过 init_paper_plan.py 生成）"
  - "data/papers/<paper-id>/chapters/（空目录占位）"
  - "data/papers/<paper-id>/refs/（空目录占位，等 evidence-driven-writing 填）"
effects:
  - "log_skill_usage 记一条 brainstorming-research 调用"
  - "为下游 evidence-driven-writing / experiment-results-planning / paper-orchestration / writing-chapters 解锁 hard gate"
failure_modes:
  - type: "skipped_questions"
    repair: "REBIND（7 轮 1+1+1+1+1+1+1 不可一次性问完；必须等用户回答再问下一轮 — 详见 §二 交互方式）"
  - type: "no_summary_confirmation"
    repair: "REBIND（汇总段必须等用户明确说『可以 / 确认 / 没问题』才能调 init_paper_plan.py）"
  - type: "scope_creep"
    repair: "REBIND（用户说『就一个简单的课程作业』也必须走 7 轮，简化措辞但不省略确认 — 见 §一 反模式）"
  - type: "wrong_skill"
    repair: "REBIND（用户其实想发散选题 / 看新方向 → 走 brainstorming（创意发散）；本 SKILL 只服务『论文已确定要写』之后的结构锁定）"
downstream_skills: ["evidence-driven-writing", "experiment-results-planning", "paper-orchestration", "writing-chapters"]
---

# Brainstorming-Research — 论文写作前置门（7 轮结构化对话）

> 来源：吸收 `research-writing-skill-main/skills/brainstorming-research/SKILL.md` v3.1.0；
> 与 Academic-Agent 体系对接：
> - **brainstorming**（已有）：创意发散型，10 个框架，研究方向探索
> - **brainstorming-research**（本 SKILL）：写作前置门，7 轮对话锁定论文结构
> - 两者**角色互补**，不重叠

---

## 一、何时使用 / 何时不用

✅ 用：
- 用户要"新论文 / 我要开始写 / start a new paper"
- 用户已选定要写但还没拆 outline
- 已有论文目录但 `plan/` 缺失或 outline 没确认
- paper-orchestration 检测到 S0 阶段未完成

❌ 不用：
- 用户只想发散思考课题方向 → 走 `brainstorming`（创意框架）
- 论文已写完，要审 → 走 `peer-review`
- plan/ 已存在且 outline 已确认 → 直接走 writing-chapters

### 1.1 反模式："这太简单了不需要讨论"

每个论文项目都要经过这个流程。一篇课程论文、一个简单修改、一段摘要——都需要。

"简单"的项目往往因为未经检验的假设导致最多的返工：
- 不知道引用格式 → 后期返工
- 不知道默认章节结构 → 中途改大纲
- 不知道 LaTeX 模板 → 最后转格式

讨论可以很简短，但**必须呈现信息并获得确认**。如果用户说"跳过"，可以缩短措辞，但**汇总段 + 用户确认**两步不可省。

---

## 二、交互方式约束（强制门）

**核心原则：一次只问一个问题，等待用户回答再问下一个。**

**附加原则：让用户少做选择，多做确认。提供推荐方案，让用户确认或微调。**

### ✅ 正确做法

- 每次只问一个问题
- 用自然语言提问，像同事间的讨论
- 等用户回答后，先确认理解（"好的，[xx]"），再问下一个
- **提供推荐方案**，让用户确认；不是让用户从空白开始
- 给出建议和理由

### ❌ 错误做法

- 一次列出所有问题
- 用编号像表单一样
- 不等回答就继续
- 干巴巴列选项不给建议
- 让用户从空白开始填

### 2.1 示例对比

❌ 错误："请选择：1. 本科 2. 硕士 3. 博士 4. 期刊 5. 会议 6. 课程"

✅ 正确："你这次要写的是什么类型的论文？是毕业论文、期刊投稿，还是课程作业？如果是毕业论文，是本科、硕士还是博士阶段的？"

---

## 三、Hard Gate（不可绕过）

在 7 轮问答完成 + 用户对汇总段明确确认之前，**禁止**：

- 写任何正文内容（chapters/*.md）
- 调用 `writing-chapters` SKILL
- 输出任何论文章节的实际 prose
- 跳过或延后 `init_paper_plan.py` 的执行

无论用户的任务看起来多么"简单"，都必须经过本流程。

---

## 四、语言默认规则（不主动询问）

| 论文类型 | 默认语言 | 说明 |
|---|---|---|
| 本科 / 硕士 / 博士毕业论文 | 中文 | 除非用户明确要求英文 |
| 中文核心期刊 | 中文 | |
| SCI / SSCI 期刊 | 英文 | 根据期刊要求 |
| 国际会议（NeurIPS / ICML / ACL / NDSS 等）| 英文 | |
| 课程论文 | 中文 | 除非课程要求英文 |
| Survey / Workshop | 英文优先 | |

**不需要主动询问语言**，根据论文类型自动确定。只有用户有特殊语言需求时才调整。

---

## 五、7 轮对话流程

按顺序逐轮进行；每轮**等用户回答**后再进入下一轮。

### 已有信息提示（在第一轮前问一次）

> "在开始之前，如果你已经有论文的相关材料（比如题目、摘要、导师要求的结构、目标 venue），可以现在发给我，我会优先采纳这些信息。
>
> 如果没有也没关系，我们从头开始讨论。"

**等待用户回复**。如果提供了材料，快速浏览并提取关键信息，后续对应问题可改为"我看到你已经写了 [xx]，确认一下是这样吗？"

---

### 第 1 轮：论文类型

> "你这次要写的是什么类型的论文？
>
> 比如：
> - 毕业论文（本科 / 硕士 / 博士）
> - 期刊投稿（中文核心 / SCI / SSCI）
> - 国际会议论文（NeurIPS / ICML / ACL / NDSS / SIGMOD ...）
> - 课程论文 / 调研报告
> - Survey / Workshop
>
> 不同类型在篇幅、结构和语言风格上差异很大，我先了解这个来规划。"

**等待回答**。收到后确认：
> "好的，[论文类型]。这类通常使用 [引用格式]，写作风格偏向 [风格特点]。"

---

### 第 2 轮：学科领域

> "你的研究属于哪个学科 / 子领域？
>
> 比如：CS（NLP / CV / RL / Systems / Security / DB ...）/ 工科（电气、机械、土木 ...）/ 理科 / 社科 / 医学 / 法学。
>
> 这会影响章节安排和写作建议。比如 CS 论文一般 Intro 含 Related Work；社科论文有独立的理论框架章；医学论文有 IMRaD/CONSORT 等专项规范。"

**等待回答**。

---

### 第 3 轮：论文题目

> "论文题目定了吗？可以是暂定的，我们后面还可以调整。
>
> 如果还在犹豫，可以告诉我你想研究的大方向，我帮你一起想想怎么聚焦。"

**等待回答**。

---

### 第 4 轮：研究背景与目的

根据用户的学科和题目，用更具体的方式提问：

> "关于你的研究，我想了解一下：
>
> 你为什么选择这个题目？是发现了什么问题想解决，还是想验证某个想法？
>
> 简单说说背景就好，不用太正式。"

**等待回答**。如果回答不够清晰，可以追问：
> "明白了。那你希望通过这个研究达成什么目标？解决什么具体问题？"

---

### 第 5 轮：研究方法

根据学科领域，问题侧重点不同：

**工科 / CS**：
> "你打算用什么技术方案或方法？有没有要做的实验或系统？性能怎么评估？"

**社科**：
> "你的研究方法是什么？问卷、访谈、案例分析，还是其他？数据怎么收集和分析？"

**医学**：
> "这是临床研究还是基础研究？样本量大概多少？伦理审批这块有没有考虑？"

**文科**：
> "你打算从什么理论视角切入？研究的文本或材料来源是什么？"

**法学**：
> "你要分析的法律问题是什么？会用到案例分析还是比较法研究？"

**等待回答**。

---

### 第 6 轮：LaTeX 模板检测

检查 `data/papers/<paper-id>/latex-templates/` 或 `overleaf/` 目录：

**如果存在模板文件**：
> "我注意到你放了 LaTeX 模板（[文件名]）。你想用这个模板来输出论文吗？
>
> 用模板的话，draft-to-latex 会直接生成 .tex 文件，可以编译成 PDF。
> 不用的话，先输出 Markdown 章节，后续再决定。
>
> 你想怎么处理？"

**如果不存在模板**：默认 Markdown，**不询问**（少做选择多做确认原则）。

---

### 第 7 轮：章节结构

根据用户确认的论文类型，**自动推荐**对应结构：

> "根据你的 [论文类型 + 学科]，我建议这样的章节结构：
>
> [展示对应类型的结构（见 §六.默认结构表）]
>
> 这是 [论文类型] 的标准结构。你可以：
> 1. **直接确认** — 使用这个结构
> 2. **微调** — 告诉我增删或调整的章节
>
> 你想怎么处理？"

**重要**：优先让用户确认，不是让用户设计。如果用户没有特殊要求，使用默认结构即可。

---

### 汇总确认（强制 hard gate）

收集完所有信息后，呈现汇总：

> "好，我整理一下我们讨论的内容：
>
> - **论文类型**：[类型]
> - **学科领域**：[领域]
> - **论文题目**：[题目]
> - **研究背景**：[简述]
> - **研究目的**：[简述]
> - **研究方法**：[简述]
> - **输出格式**：[Markdown / LaTeX]
> - **章节结构**：
>   - [章节列表]
>
> 这些信息都对吗？确认后我会通过 `python tools/init_paper_plan.py --paper-id <id> --apply` 创建项目结构（含 plan/ 5 个 .md + chapters/ + refs/），然后我们就可以开始写了。"

**必须等用户明确确认**（如"对"、"可以"、"确认"、"没问题"），**不得假设**用户同意。

---

## 六、默认章节结构（论文类型 → 推荐 outline）

### 6.1 CS 顶会论文（NeurIPS / ICML / ACL / etc.，通常 8–10 页）

```
1. Introduction (含 motivation + 贡献 + Related Work 简要融合)
2. Related Work / Background（如 venue 要求拆出）
3. Method（含 Problem Formulation / Approach / Implementation）
4. Experiments（含 Setup / Main Results / Ablation / Analysis）
5. Discussion / Limitations
6. Conclusion
References / Appendix
```

### 6.2 SCI / SSCI 期刊（IEEE / Elsevier，通常 12–20 页）

```
1. Introduction
2. Related Work
3. Methodology
4. Experimental Setting
5. Results
6. Discussion
7. Conclusion
References / Appendix
```

### 6.3 中文核心期刊（中文，1.5–2 万字）

```
1. 引言（含研究背景、研究问题、本文贡献、章节安排）
2. 相关工作 / 文献综述
3. 研究方法
4. 实验与结果
5. 讨论与分析
6. 结论与展望
参考文献
```

### 6.4 本科 / 硕士 / 博士毕业论文（中文，3–10 万字）

```
摘要 / Abstract（中英）
1. 绪论（研究背景、研究意义、国内外研究现状、本文工作、论文结构）
2. 相关理论与技术（含基础理论、相关算法、关键技术）
3. <研究主体章 1>（方法 / 系统 / 模型）
4. <研究主体章 2>（实验 / 验证 / 案例）
5. <研究主体章 3>（应用 / 优化）— 博士论文必有，硕士可选
6. 总结与展望
参考文献 / 致谢 / 附录
```

### 6.5 课程论文 / 调研报告（中文，5–15 千字）

```
摘要
1. 研究背景与问题
2. 相关工作综述
3. <方法 / 分析 / 复现>
4. 结果与讨论
5. 结论
参考文献
```

### 6.6 Survey 论文（英文，14–30 页）

```
1. Introduction
2. Background & Definitions
3. Taxonomy（核心：分类树 / 表格）
4. <分类章 1>
5. <分类章 2>
...
N-1. Open Challenges & Future Directions
N. Conclusion
References
```

### 6.7 Workshop 论文（英文，4–6 页）

```
1. Introduction
2. Approach（合并 Method + Implementation）
3. Experiments
4. Discussion
References
```

---

## 七、确认后的项目初始化

用户确认汇总后，**必须**通过 `tools/init_paper_plan.py` 创建结构（不要手动 Write 5 个文件）：

```bash
python tools/init_paper_plan.py --paper-id <id> --apply
# 想覆盖已有 plan/（自动备份到 plan/.backup_<ts>/）：加 --force
# 想 dry-run 不写盘：去掉 --apply
```

执行后：
1. `data/papers/<paper-id>/plan/` 5 个 .md 文件（template 复制 + paper-id / 创建日期 填充）
2. `data/papers/<paper-id>/chapters/` 空目录
3. `data/papers/<paper-id>/refs/` 空目录

接下来手动**回填**（同样落到 plan/）——把 §五 7 轮收集的论文题目 / 学科 / 研究背景 / 目的 / 方法 / 章节结构填到对应文件：
- `plan/project-overview.md`：把 §五 7 轮收集的信息（论文类型 / 学科 / 题目 / 背景 / 目的 / 方法 / 章节结构）填入对应段
- `plan/outline.md`：根据 §六 推荐结构 + 用户调整结果，填具体章节大纲
- `plan/notes.md §一 用户偏好`：投稿目标 / 引用格式 / 写作风格偏好 / 不可改的术语

---

## 八、转到下一阶段

`init_paper_plan.py` 跑完后：

> "项目结构已创建：
> - plan/{project-overview, outline, progress, notes, stage-gates}.md
> - chapters/（空，等你开始写）
> - refs/（空，等 evidence-driven-writing 填）
>
> 接下来推荐路径：
>
> 1. **如果是 Intro / Related Work 章**：先调 `evidence-driven-writing` SKILL 建 `refs/evidence-map.md`
> 2. **如果是 Method / Results 章**：先调 `experiment-results-planning` SKILL 建 `plan/experiment-protocol.md`
> 3. **如果你想先看到大纲再写**：跑 `paper-orchestration` 锁 `plan/chapter-architecture.md`
>
> 你想从哪个开始？"

**等用户回答**，然后路由到对应 SKILL（不要假设）。

---

## 九、错误处理

### 9.1 用户跳过某些回答

允许，但**汇总确认**那一步不能省。在汇总时把跳过的项标 `[未确认]`：
> "你跳过了 Q4 (研究方法)，我先按 [推断] 填入 plan/project-overview.md，开始写 Method 章前会再次确认。"

### 9.2 用户答非所问

追问一次：
> "我想先确认 [Q-X]，你刚才说的 [xx] 我没把握理解对——你的意思是 [推断]，还是 [另一种]？"

仍不清晰则记录到 plan/notes.md `§五 待澄清问题`。

### 9.3 用户已经发了 design.md / 摘要 / 标题

按 §五 已有信息提示流程处理：先抽取 → 用确认问题代替开放问题 → 缩短问答轮数。

---

## 十、与 brainstorming（创意发散）的角色区分

| | brainstorming | brainstorming-research（本 SKILL）|
|---|---|---|
| **场景** | 选题 / 课题方向 / 探索性研究 | 论文已选定要写，需要锁定结构 |
| **核心** | 10 个创意发散框架 | 7 轮结构化对话 |
| **产出** | 候选研究方向清单 | plan/ 5 个 .md + chapters/ 空目录 |
| **下游** | autoresearch / paper-design | writing-chapters / paper-orchestration |
| **门控** | 软门（用户随时跳出）| 硬门（汇总不确认不能写正文）|

简单判断：**还在选题** → brainstorming；**已确定写哪篇** → brainstorming-research。

---

## 十一、关键原则（不可违反）

1. **一次只问一个问题**——不用多个问题压倒用户
2. **等待回答再继续**——不假设用户的选择
3. **对话式而非表单式**——像同事讨论
4. **给出建议和理由**——帮助用户做选择
5. **灵活调整但不省汇总**——简化措辞 OK，跳过最终确认 NO
6. **记录一切到 plan/**——所有决策都进 project-overview.md / notes.md
7. **必须用 init_paper_plan.py 创建结构**——不要手 Write 5 个 .md
