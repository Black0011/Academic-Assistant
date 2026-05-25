---
name: writing-chapters
description: >-
  Write paper chapters one at a time under a strict Chapter Agent Contract:
  type-routing (Intro/Related Work → evidence-driven-writing; Methodology
  → input-to-output flow; Results/Discussion → experiment-results-planning),
  anti-enumeration 5-pattern prose, min_chars enforcement from
  `plan/chapter-architecture.md`, two-stage review (spec compliance +
  quality), and structured handoff status (DONE / DONE_WITH_CONCERNS /
  NEEDS_CONTEXT / BLOCKED). Use when the user says "写第 N 章 / 写
  introduction 章 / 写方法章 / 写结果章 / 一章一章地写 / chapter-by-chapter
  / write methodology / write results / 逐章节写作", or when paper-writing
  / paper-orchestration dispatches a single-chapter task.
domain: writing
triggers:
  - write chapter
  - 写第 N 章
  - write methodology
  - write results
  - 逐章节写作
  - chapter-by-chapter
version: "1.0.0"
compatibility:
  requires: ["python-3.9"]
# v2.2.5 Skill DAG metadata（WP6 of research-writing-skill adoption）
preconditions:
  - "data/papers/<paper-id>/plan/{project-overview,outline,progress}.md 存在"
  - "data/papers/<paper-id>/chapters/ 目录已创建（或允许本 SKILL 创建）"
  - "（推荐）plan/chapter-architecture.md 已锁 min_chars / agent owner / placeholders 策略（来自 paper-orchestration）"
consumes:
  - "data/papers/<paper-id>/plan/{project-overview,outline,progress,notes}.md"
  - "data/papers/<paper-id>/plan/chapter-architecture.md（如存在）"
  - "data/papers/<paper-id>/refs/evidence-map.md（Intro / Related Work 章必读）"
  - "data/papers/<paper-id>/plan/chapter-blueprints/<section>-blueprint.md"
  - "data/papers/<paper-id>/plan/experiment-protocol.md（Results / Discussion 章必读）"
  - "data/papers/<paper-id>/plan/review/method-experiment-traceability.md"
produces:
  - "data/papers/<paper-id>/chapters/<NN>_<Name>.md（独占 owner）"
  - "回填 plan/progress.md §五 章节完成度 + §二 capability-use audit"
  - "data/papers/<paper-id>/plan/review/<chapter-id>-spec-compliance.md（强制）"
  - "data/papers/<paper-id>/plan/review/<chapter-id>-quality.md（强制）"
  - "data/papers/<paper-id>/plan/chapter-agent-provenance.md（追加一行）"
effects:
  - "log_skill_usage 记一条 writing-chapters 调用"
  - "为下游 paper-revision / claim-verification / paper-quality-gate.py 提供 chapter prose"
failure_modes:
  - type: "missing_plan"
    repair: "INSERT_PREREQ（先跑 tools/init_paper_plan.py + brainstorming-research 完成 S0–S3）"
  - type: "type_routing_skipped"
    repair: "REBIND（Intro / Related Work 必先调 evidence-driven-writing；Results / Discussion 必先调 experiment-results-planning；Methodology 必须 input-to-output flow）"
  - type: "min_chars_unmet"
    repair: "REBIND（返回 NEEDS_CONTEXT，不允许把短稿标记为 DONE；继续扩写或回到上一阶段补证据）"
  - type: "list_pollution"
    repair: "REBIND（按 §四 反罗列 5 模式重写；正文项目符号占比 > 15% 直接 fail；详见 writing-core SKILL.md §2.3）"
  - type: "body_contamination"
    repair: "REBIND（章节正文出现『写自然一点』『此处填实验数据』『请用户替换』等过程词 → 必须迁回 plan/，详见 evidence-driven-writing §六 Firewall）"
  - type: "review_gate_failed"
    repair: "REBIND（spec compliance / quality 任一 fail：写新版本 <chapter-id>-v2.md，旧版本保留作为审计证据，不删）"
downstream_skills: ["writing-core", "paper-revision"]
---

# Writing-Chapters — 章节级写作（一次一章 + 契约式交接）

> 来源：吸收 `research-writing-skill-main/skills/writing-chapters/SKILL.md` v3.1.0；
> 与 Academic-Agent 体系深度对接：
> - **paper-writing** 负责骨架 / outline / abstract 速生成；本 SKILL 负责**单章细写**与**契约式交付**
> - **paper-orchestration** 负责 task packets 分发；本 SKILL 负责**章节内**强制门
> - **writing-core** 负责语言层质量门；本 SKILL 在 prose 收尾**强制**调它

---

## 一、Hard Gate（硬门，不可绕过）

调用本 SKILL 前必须满足：

```text
data/papers/<paper-id>/plan/project-overview.md  存在且含论文类型 + 章节结构
data/papers/<paper-id>/plan/outline.md           存在且已与用户确认
data/papers/<paper-id>/plan/progress.md          存在
data/papers/<paper-id>/chapters/                 目录存在（或本 SKILL 创建）
```

任一缺失 → 立即停止，按 §六 错误处理 路由到 `init_paper_plan.py` / `brainstorming-research` / `paper-orchestration`。

### 1.1 章节类型路由（强制）

```text
Introduction / Related Work / Background / Literature Synthesis
    ↓ 必先调
.cursor/skills/evidence-driven-writing/SKILL.md
    （读 refs/evidence-map.md + plan/chapter-blueprints/<section>-blueprint.md）

Methodology / Methods / 研究方法
    ↓ 必按
"输入到输出 flow"（§四.方法段 5 模式）— 不允许只罗列模块

Results / Discussion / Experimental Results / 实验结果与讨论
    ↓ 必先调
.cursor/skills/experiment-results-planning/SKILL.md
    （读 plan/experiment-protocol.md + tables/table-schema.md
     + figures/data-manifest.md + plan/review/method-experiment-traceability.md）
```

任何用户的「写得自然」「不要泛泛而谈」「注意衔接」**只能**转化为段落 / 结构 / 证据使用，**不得**直接进入正文（详见 evidence-driven-writing §六 Body Contamination Firewall）。

---

## 二、Chapter Agent Contract（章节代理契约）

`paper-orchestration` 派发的 chapter task packet 必须含：

- 独占 owner 章节文件路径（`chapters/<NN>_<Name>.md`）
- 本章在全文中的角色（与 Introduction / Related Work / Methodology 等对齐）
- 必读 source files + Evidence IDs（来自 evidence-map.md 行号）
- **段落级**论证链（按 paragraph roles 而非 section labels）
- min_chars 下限（来自 `plan/chapter-architecture.md`）
- 禁用措辞 + 禁用结构（与 writing-core §1.1 / evidence-driven-writing §六 一致）
- 上报未解 gap 而非编造证据 / 结果

### 2.1 Handoff Status（强制返回）

每个 chapter task 完成时必须返回 4 种状态之一：

| Status | 含义 | 必须随附 |
|---|---|---|
| **DONE** | 章节完成，spec + quality 双通过 | changed file path / 论证链摘要 / verification 命令 / 全部 review 段 |
| **DONE_WITH_CONCERNS** | 完成但有 ≥ 1 条已知 limitation 未消除 | + 未解 concern 列表（具体到段落 ID）|
| **NEEDS_CONTEXT** | 缺前置（min_chars 不达 / evidence 不足 / data 缺失）| + 缺什么 / 上游应跑哪 SKILL / 期望 input 形态 |
| **BLOCKED** | 被冲突 / 不一致 / 用户决策卡住 | + 冲突点 / 候选解决方案 ≥ 2 条 |

**禁止**直接说「写完了」「应该完成了」「看起来没问题」（参照 verification SKILL.md Red Flags）。

### 2.2 Provenance 记录

每次 chapter task 完成必须在 `plan/chapter-agent-provenance.md` 追加一行：

```markdown
| ts | chapter | agent | status | inputs | output | review-1 | review-2 | concerns |
|---|---|---|---|---|---|---|---|---|
| 2026-05-08T21:30 | 02_Methodology | sub-agent-1 | DONE | outline,blueprint,protocol | chapters/02_Methodology.md | ✅ | ✅ | - |
```

未记录 provenance 的章节**不被** paper-orchestration / paper-quality-gate 接受。

---

## 三、两阶段 Review（强制门）

每章写作收尾必须做两阶段检查（与 paper-orchestration §六 同语义）。

### 阶段 1 — 规范合规（Spec Compliance）

落盘到 `plan/review/<chapter-id>-spec-compliance.md`：

| 检查项 | 验证方法 | 通过条件 |
|---|---|---|
| 字数 | `wc -m chapters/<file>.md` | ≥ chapter-architecture.md 的 min_chars × 0.9 |
| 结构 | 目检小节层级 | 与 outline.md 一致；标题层级最多 3 级 |
| 引用格式 | grep `\[CITE`/`\\cite{` | 风格统一（GB/T / APA / IEEE）|
| 标题层级 | 目检 | 一级章用 `# `；不用粗体替代 |
| File ownership | git status | 仅本章 owner 修改 chapter file |

任一 ❌ → 返回 NEEDS_CONTEXT 或 BLOCKED；不写新版直接覆盖。

### 阶段 2 — 质量（Quality）

落盘到 `plan/review/<chapter-id>-quality.md`：

| 检查项 | 验证方法 | 通过条件 |
|---|---|---|
| 去 AI 化 | `python scripts/style_check.py chapters/<file>.md --strict` | 0 ERROR |
| 段落 3 段式 | 目检 | 每段含主题句 / 支撑句 / 收束句 |
| 列表污染 | style_check 同时报 | 项目符号占比 ≤ 15% |
| 学术表达 | grep `我认为`/`我觉得` | 0 命中（论文正文）|
| 引用真实 | 抽查 ≥ 5 处 cite 反查 evidence-map.md | 全部命中 |
| 反罗列 | 段落表达检查 | 满足 §四 5 模式至少 2 项要素 |
| Min_chars 达成 | 字数对比 | ≥ chapter-architecture.md 下限 |

任一 ❌ → 返回 NEEDS_CONTEXT；不接受「应该没事」式自评（详见 verification SKILL.md）。

---

## 四、反罗列写作 5 模式（每段必须满足之一）

正文段落必须按以下结构之一组织（与 writing-core / evidence-driven-writing §五 共享）：

| 段落角色 | 结构 |
|---|---|
| **背景段** | 场景约束 → 研究矛盾 → 本章承接 |
| **文献段** | 同类研究共同问题 → 代表性证据 → 尚未覆盖边界 |
| **方法段** | 输入对象 → 处理过程 → 输出形式 → 设计理由 |
| **实验段** | 评价目标 → 对照关系 → 指标含义 → 可接受结论边界 |
| **讨论段** | 结果含义 → 工程 / 学术解释 → 局限和后续验证 |

每段必须含因果 / 转折 / 承接 / 限定关系；**禁止**把 5 模式写成项目符号列表。

### 4.1 Methodology 章特别规则

**禁止**「由三层组成 / 包括若干模块」式罗列，**必须**采用 input-to-output flow：

1. 输入对象（数据形态、样本、特征、约束）
2. 预处理或表示（清洗、编码、划分、标准化）
3. 核心模型 / 算法（每模块说明输入 / 处理 / 输出 / 设计理由）
4. 训练或推理流程（公式、算法、参数更新或决策路径）
5. 输出（预测、解释、告警、指标或下游接口）
6. 与实验的对应（每个关键模块映射到消融 / 对照 / 局限）

缺任一环节 → 返回 NEEDS_CONTEXT。

### 4.2 Results 章特别规则

**禁止**保留「实验目的 / 表位 / 回填模板 / 讨论提示 / 请用户替换」等过程词。
真实结果用数据支撑；mock 数据**只**作为 planning data，并保留 `[待真实实验替换]` 标记，**不得**写成已验证结论（详见 experiment-results-planning §五 Mock Data Boundary）。

---

## 五、Min_Chars 与短稿处理

### 5.1 来源

`plan/chapter-architecture.md` 的 `Required chapter files` 段（来自 paper-orchestration §四.2）：

```text
chapters/01_Introduction.md   | min_chars=4500 | agent=required | placeholders=no
chapters/02_Methodology.md    | min_chars=4500 | agent=required | placeholders=no
chapters/04_ResultsAndAnalysis.md | min_chars=4500 | agent=required | placeholders=allowed-until-D4
```

### 5.2 短稿处理

实际字数 < min_chars × 0.9：
- **不允许**标记 DONE
- **必须**返回 NEEDS_CONTEXT，并在 handoff 中说明：缺什么 / 是 evidence 不足还是 outline 太薄 / 上游应跑哪 SKILL

### 5.3 长稿处理

实际字数 > min_chars × 1.5：
- 不强制压缩
- 在 quality review 中标 `length: above expected; 是否拆分子节？`，由用户决定

---

## 六、错误处理

### 6.1 plan/ 不存在

```text
检测到论文项目结构未创建。修复路径：
  ① python tools/init_paper_plan.py --paper-id <id> --apply
  ② 调 brainstorming-research SKILL 完成 S0 / S1
  ③ 完成 plan/outline.md 后再回到本 SKILL
```

### 6.2 前置章节未完成

```text
建议先完成「<前置章节>」再写「<当前章节>」，因为：
  · <原因 1>（如：实验章必须先有 protocol）
  · <原因 2>（如：方法章引用了未定义的术语）

是否要先写前置章节？还是接受降级（先写本章，但 review 阶段会标 partial）？
```

记录用户选择到 `plan/notes.md §二 关键决策`。

### 6.3 用户要求跳过确认

```text
理解你想加快进度。我会简化每章的"开始前确认 / 结束后展示"对话，
但 §三 两阶段 review **强制门**不能简化。
```

跳过确认的事实记录到 `plan/progress.md`。

---

## 七、与其他 SKILL 的关系

```
brainstorming-research（S0–S1）→ tools/init_paper_plan.py（创建 plan/）
    ↓
evidence-driven-writing（S2，Intro / Related Work）/ experiment-results-planning（D0–D2，Results）
    ↓
paper-orchestration（task packet 派发 + chapter-architecture 锁定 min_chars）
    ↓
writing-chapters（本 SKILL：单章细写 + Chapter Agent Contract）
    ↓ 收尾强制
writing-core（去 AI 化 + style_check.py）
    ↓ 通过后
paper-revision / claim-verification（下一轮）
```

- **上游**：paper-orchestration / brainstorming-research / evidence-driven-writing / experiment-results-planning
- **平行**：paper-writing（粗骨架 / abstract / outline）
- **下游**：writing-core（语言层）/ paper-revision / claim-verification

---

## 八、关键原则（不可违反）

1. **一次只写一章**——完成并通过两阶段 review 后才写下一章
2. **min_chars 不达不能 DONE**——返回 NEEDS_CONTEXT，回上游补 evidence / data
3. **章节类型路由不可绕过**——Intro 必走 evidence-driven-writing；Results 必走 experiment-results-planning
4. **provenance 必须记录**——chapter-agent-provenance.md 缺失即视为未完成
5. **failed review 不删旧版**——写 v2，保留 v1 作为审计证据
6. **绝不编造**——引用必须可追溯到 `data/survey/notes/*.yaml` 或 `refs/evidence-map.md`

---

## 九、FAQ

**我能不能直接用 paper-writing 写完整章？**
→ 可以但只在以下场景：(a) 单 paragraph 修改、(b) abstract / conclusion 等短章、(c) 你已确认章节类型不需要 §1.1 路由（极少）。其它场景必须走本 SKILL。

**chapter-architecture.md 还没建怎么办？**
→ 先跑 paper-orchestration 锁定 chapter-architecture（§四.2），再调本 SKILL。本 SKILL 不会自己创建 chapter-architecture（因为它是 multi-agent gate 的产物，需要 controller 决策）。

**两阶段 review 的脚本不存在怎么办？**
→ §三的 spec compliance 大多是目检；§三的 quality 自动化部分依赖 `scripts/style_check.py`（已落地）+ `scripts/paper_quality_gate.py`（已落地，见 WP9）。手动检查项需要 LLM 或人工核对，但**必须**落盘到对应 review .md，不允许只在脑子里过。
