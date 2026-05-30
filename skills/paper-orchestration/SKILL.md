---
name: paper-orchestration
description: >-
  Control the workflow around all writing skills for medium-scope or full-paper
  tasks. Forces stage detection (S0–S5 + D0–D5), persistent task packets,
  multi-agent chapter dispatch, two-stage review gates, and a mandatory
  capability-use audit. Prevents "one prompt writes the paper" behaviour.
  Always called for any task that touches > 1 paragraph, > 1 figure/table set,
  any claim tied to references, or any medium / full-paper revision. Use when
  the user says "写整篇 / 整篇重写 / 多节联动 / 论文整体规划 / orchestrate /
  workflow / 多 agent 分章 / 写整本 / full draft / redraft / 再来一遍"
  or when paper-writing / paper-revision detects scope > single section.
domain: writing
triggers:
  - orchestrate paper
  - 整篇重写
  - 多 agent 分章
  - redraft
  - 多节联动
  - full draft
  - 论文整体规划
version: "1.0.0"
compatibility:
  requires: ["python-3.9"]
# v2.2.5 Skill DAG metadata（WP5 of research-writing-skill adoption）
preconditions:
  - "data/papers/<paper-id>/plan/{project-overview,outline,progress}.md 存在（由 init_paper_plan.py 初始化）"
  - "data/papers/<paper-id>/plan/stage-gates.md 存在"
  - "用户任务范围 ≥ 中等（多节 / 多 agent / full-paper）"
consumes:
  - "data/papers/<paper-id>/plan/{project-overview,outline,progress,notes,stage-gates}.md"
  - "data/papers/<paper-id>/refs/evidence-map.md（如已生成）"
  - "data/papers/<paper-id>/plan/experiment-protocol.md（如已生成）"
  - "data/papers/<paper-id>/plan/review/method-experiment-traceability.md（如已生成）"
produces:
  - "data/papers/<paper-id>/plan/task-packets/<task-id>.md（每个 medium 任务一个）"
  - "data/papers/<paper-id>/plan/chapter-architecture.md（full-paper 任务强制产物）"
  - "data/papers/<paper-id>/plan/chapter-agent-provenance.md（多 agent 分章溯源）"
  - "data/papers/<paper-id>/plan/review/<section>-spec-compliance.md（每节 spec review）"
  - "data/papers/<paper-id>/plan/review/<section>-quality.md（每节 quality review）"
  - "回填 plan/progress.md 的 capability-use audit 段（强制）"
effects:
  - "log_skill_usage 记一条 paper-orchestration 调用"
  - "为每个分发出去的 chapter task 触发 writing-chapters / evidence-driven-writing / experiment-results-planning"
failure_modes:
  - type: "scope_underestimated"
    repair: "REBIND（范围 ≥ 多节 / multi-agent / full-paper 但走了 paper-writing 单 prompt — 必须 rollback 到本 SKILL 编排）"
  - type: "no_task_packet"
    repair: "INSERT_PREREQ（dispatch 任何 medium 任务前必须落盘 task packet 到 plan/task-packets/）"
  - type: "single_agent_full_paper"
    repair: "REBIND（full-paper 必须按 §三 multi-agent gate 拆 chapter；如确无 subagent 能力，必须先问用户是否接受 degraded 单 agent 模式）"
  - type: "audit_skipped"
    repair: "REBIND（任务收尾必须在 plan/progress.md 写 capability-use audit；缺即视为未完成）"
  - type: "review_gate_skipped"
    repair: "REBIND（每个 medium 任务两次 review：spec compliance + quality；任一失败必须 fix 再前进）"
  - type: "old_chapter_split_inherited"
    repair: "REBIND（用户拒绝旧章节结构 → 必须重建 chapter-architecture.md，禁止沿用）"
downstream_skills: ["paper-writing", "evidence-driven-writing", "experiment-results-planning", "writing-core", "paper-revision", "claim-verification", "draft-to-latex"]
---

# Paper-Orchestration — 写作流程编排

> 来源：吸收 `research-writing-skill-main/skills/paper-orchestration/SKILL.md` v3.1.0；
> 与 Academic-Agent 体系深度对接：把"分发 - 评审 - 审计"做成机械门，避免"一 prompt 写完整篇"。
> 与 GraSP DAG-compilation（已存在的 `config/prompts/skill_compilation.md`）互补：
> 后者为单任务编译子图；本 SKILL 为多任务/多 agent 全流程编排。

---

## 一、Hard Gate（硬门，不可绕过）

任何 **medium task** 或 **full-paper task** 在动手写 prose 之前必须存在：

```text
data/papers/<paper-id>/plan/project-overview.md
data/papers/<paper-id>/plan/outline.md
data/papers/<paper-id>/plan/progress.md
data/papers/<paper-id>/plan/task-packets/<current-task-id>.md   ← 必产
data/papers/<paper-id>/plan/chapter-architecture.md             ← full-paper 必产
```

若任一缺失：立即停止 prose 写作，按 §四 / §五 / §六 补齐。

### 1.1 "Medium task" 的判定（非负即视为）

满足以下任一即视为 medium：
- 影响 > 1 段
- 影响 > 1 子节 / 1 章 / 1 组图表
- 任何含引用 / 实验数据的 claim
- 用户的请求需要协调 ≥ 2 个 SKILL（如 evidence-driven-writing + writing-chapters）

---

## 二、Stage Detection（先识别再动手）

每次任务**第一步**：分类当前工作所处 stage，并回填 `plan/progress.md §一 当前 stage`。

| Stage | 触发 | 下一 SKILL（必读）|
|---|---|---|
| S0 Scope | 主题 / 目标 / 结构未定 | `brainstorming-research`（待 WP8 落地）|
| S1 Evidence | 引用 / Introduction / Related Work | `evidence-driven-writing` + `survey-writing` |
| S2 Method | 模型 / 算法 / 系统 / 方法章 | `writing-chapters`（待 WP-? 落地，当前用 `paper-writing` + writing-core）|
| S3 Experiments | 实验设置 / Results / 表 / 图 | `experiment-results-planning` + `figures-python`（如启用）|
| S4 Drafting | 章节正文 | `paper-writing` + `writing-core`（去 AI 化）|
| S5 Review | 质量 / 一致性 / 投稿风险 | `peer-review`（待 WP7 落地）+ `claim-verification` |

实验型论文并行存在 `D0–D5`（详见 `plan/stage-gates.md` §二），由 `experiment-results-planning` SKILL 主管。

---

## 三、Multi-Agent Chapter Gate（full-paper 强制）

**full-paper draft / redraft 不允许由单一 controller 顺序写完所有章节。** 必须：

1. 锁 `plan/chapter-architecture.md`（§六 模板）
2. 每个主章节生成一个 `plan/task-packets/<chapter-id>.md`（§五 模板）
3. 派发独立 fresh agent / 子任务（每个 agent 仅看到对应章节的 task packet + evidence map + experiment protocol + 拒收清单）
4. **不同 agent 写不同 chapter 文件**（互不写入对方 chapter，禁止冲突 edit）
5. 在 `plan/chapter-agent-provenance.md` 记录：agent 名 / prompt 摘要 / inputs / output path / review status
6. controller 在 agent 产出后必须做 §七 两阶段 review，**才能**声称该章节完成

### 3.1 当 subagent 不可用时的退路

- **不允许**默默回退到单 agent 顺序生成
- 必须显式问用户："本环境没有 subagent 能力，是否接受 degraded 单 agent 模式（节奏会更慢，质量风险更高）？"
- 用户确认后才能继续；并在 `chapter-agent-provenance.md` 标 `mode: degraded-single-agent`

---

## 四、Full-Paper Redraft Gate（章节架构锁定）

整篇重写前必须先锁章节架构。**不允许**因为旧 outline 已存在就盲目沿用——若用户、目标 venue 或 paper-type 暗示需要不同结构，就必须重建 outline + chapter-architecture。

### 4.1 CS / 工程 SCI 默认章节结构

```text
1. Introduction（含 Related Work 整合到动机与 research-gap 论证）
2. Methodology
3. Dataset and Experimental Setting（短时可整合到 Methodology / Results）
4. Experimental Results and Analysis
5. Discussion
```

Abstract / Conclusion / References 可作 supporting files，但**不得**用来掩盖弱章节或夸大章节计数。**独立 Related Work 章** 仅在目标 outline 显式要求时允许。

### 4.2 chapter-architecture.md 模板

```markdown
# Chapter Architecture — <paper-id>

## §一、Required chapter files

- chapters/01_Introduction.md            | min_chars=4500 | agent=required | placeholders=no
- chapters/02_Methodology.md             | min_chars=4500 | agent=required | placeholders=no
- chapters/03_ExperimentalSetting.md     | min_chars=2500 | agent=optional | placeholders=allowed-until-D3
- chapters/04_ResultsAndAnalysis.md      | min_chars=4500 | agent=required | placeholders=allowed-until-D4
- chapters/05_Discussion.md              | min_chars=2500 | agent=required | placeholders=no
- chapters/00_Abstract.md                | min_chars=600  | agent=optional | placeholders=allowed
- chapters/06_Conclusion.md              | min_chars=900  | agent=optional | placeholders=no

## §二、Forbidden files
- chapters/RelatedWork.md  ← 已并入 Introduction，禁止单独章节

## §三、Quality gate
若实际 chapters/ 目录中出现额外章节或缺章节，paper-quality-gate（待 WP9）报 fail。
```

---

## 五、Task Packet（任务包，不允许只对话）

每个 medium 任务在 dispatch 前必须落盘 `plan/task-packets/<task-id>.md`。仅口头 / 仅 chat 历史的"任务"**不可审计**，视为未发生。

### 5.1 通用 task packet 模板

```markdown
# Task Packet — <task-id>

- Scope:
- Files to read:
- Files allowed to edit:
- Required skills:
- Evidence/data inputs:
- Required artifacts:
- Rejection checks:
- Validation commands:
```

### 5.2 Chapter-writing packet 必加字段

```markdown
- Target chapter file（独占 owner）：
- Required argument chain（按 paragraph roles，不是 bullet content）：
- Minimum prose length（与 chapter-architecture 一致）：
- Required sources（evidence-map / paper-table 行）：
- Required data artifacts（table-schema / data-manifest 引用）：
- Prohibited structure：
    · 项目符号堆叠观点
    · 用户需求 / 流程笔记进入正文（详见 evidence-driven-writing §六 firewall）
    · 旧 chapter scaffolding
- Handoff format：status / file path / unresolved evidence-data gaps / self-review
```

子 agent 必须**只**接到 task packet，不许接到整个项目（防止 "context rot"）。

### 5.3 任务粒度建议（subagent 可用时）

把独立工作切成：
- literature-mapping
- method-architecture
- experiment-planning
- figure-generation
- review

互不写入对方文件。

---

## 六、Review Gates（每个 medium 任务两道）

### Review Gate 1 — Spec Compliance

- 输出与 task packet 一致？
- 必产 artifacts 都存在（path + 行数 / 字段 / 锚点）？
- 没动 `Files allowed to edit` 之外的文件？

落盘到 `plan/review/<task-id>-spec-compliance.md`，失败必须 fix 再前进。

### Review Gate 2 — Quality

- claim 都有 evidence-map / experiment-results 支撑？
- 段落逻辑连贯（每段 5 字段对齐 evidence-driven-writing §四 blueprint）？
- 无 manuscript pollution（process notes / placeholder 残留）？
- style_check.py / paper-quality-gate（如启用）通过？

落盘到 `plan/review/<task-id>-quality.md`，失败必须 fix 再前进。

### 失败保留策略

如 Review Gate 失败，**不删除**失败的产物（保留作为审计证据），而是新建 `<task-id>-v2.md` 等修订版。

---

## 七、Capability-Use Audit（任务收尾，强制）

每个 medium 任务结束**必须**在 `plan/progress.md §二 capability-use audit` 写：

```markdown
### Capability-use audit — <task-id>
- Required skills:
- Skills actually used:
- Inputs consumed:
- Inputs not used and why:
- Artifacts produced:
- Verification commands run:
    · python scripts/style_check.py <chapter.md>
    · python scripts/check_writes.py
    · ...
- Remaining risk:
```

未写 audit = 未完成；下游任务 dispatch 时必须先核对前任务的 audit 段。

---

## 八、与 Academic-Agent 既有体系的对接

### 8.1 与 GraSP DAG-compilation 的关系

- `config/prompts/skill_compilation.md`：**单任务**子图编译（GraSP Prompt 1 改编）
- 本 SKILL：**多任务 / 多 agent 全流程**编排（包含 stage / packet / review / audit）

两者**互补**：
- 单 medium 任务（如"写 Introduction P1–P3"）：先用本 SKILL 落盘 task packet，再用 GraSP 编译该任务的 sub-DAG
- 多 medium 任务（如"整篇重写"）：本 SKILL 主导，每个 sub-task 内部再调 GraSP 编译

### 8.2 与已有 SKILL 的关系

```
paper-orchestration（本 SKILL：编排 / 分发 / 审计）
    ↓ stage S0
brainstorming-research（待 WP8）
    ↓ stage S1
evidence-driven-writing → claim-verification（证据闭环）
    ↓ stage S2 / S4
paper-writing + writing-core（去 AI 化语言层）
    ↓ stage S3 + D0–D2
experiment-results-planning + figures-* + statistical-analysis（实验闭环）
    ↓ stage S4
writing-chapters（待 WP-?）/ paper-writing
    ↓ stage S5
peer-review（待 WP7）+ claim-verification + style_check.py
    ↓
draft-to-latex（投稿打包）
```

### 8.3 与 knowledge-protection.mdc 的关系

- `plan/task-packets/*.md` / `plan/review/*.md` / `plan/chapter-agent-provenance.md`：Tier 1（仅追加 / 新建；改旧任务包 = Tier 3）
- `plan/chapter-architecture.md`：Tier 2（行内修订；删 chapter / 改 schema = Tier 3）
- `plan/progress.md`：Tier 1（capability-use audit 仅追加）

---

## 九、常见失败（必须警惕）

- 把"用户指令"当成 manuscript content 写进章节正文（必须转成结构 / edits，**绝不**贴进正文）
- 章节"完成"了但只是标题 + placeholder
- 跑了 style_check 但跳过 evidence / data / claim 检查
- 用表格代替散文以掩盖弱论证
- 用户拒绝旧章节结构后，仍沿用旧 outline——必须先重建 chapter-architecture
- controller 顺序写完整 manuscript（违反 §三 multi-agent gate）
- 接受短小、列表化的 prose 因为它过了关键词检查——长度 / 段落流 / 证据使用 / agent provenance 都必须 review

---

## 十、FAQ

**我只是改一段话，也要走这套流程吗？**
→ 不必。单段 / 单 paragraph 任务不属于 medium。直接走 paper-revision / writing-core 即可；但若那一段含 ≥ 1 处新引用 / 新数据 claim，也要触发本 SKILL（属 medium 的"含引用 claim"判据）。

**subagent 能力不可用时应该怎么办？**
→ 显式问用户是否接受 degraded 单 agent 模式（§3.1）；用户同意后才继续，并在 chapter-agent-provenance.md 标记。**不允许**默默退化。

**用户已经在用 paper-writing 写了一半，被本 SKILL 截胡了怎么办？**
→ 不打断当前段；当下任务收尾时（每完成一段 / 一节）回填 task packet 与 audit。下次 medium 任务前必须先走完本 SKILL 的 §一 hard gate。

**和 GraSP `config/prompts/skill_compilation.md` 重复吗？**
→ 不重复。GraSP 是"单任务 / 多 SKILL 子图"编译；本 SKILL 是"多任务 / 多 agent / 全流程"编排。详见 §8.1。
