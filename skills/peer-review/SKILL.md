---
name: peer-review
description: >-
  Pre-submission self-audit and reviewer-style critique. Runs three stages
  (preliminary → section-by-section → methodology & statistical rigor),
  applies bias-detection table (confirmation / selection / publication /
  p-hacking) and logic-fallacy table (post-hoc / correlation-vs-cause /
  hasty generalization / cherry-picking), and emits a structured review
  report (Summary / Strengths / Major / Minor / Rating). Use when the
  user says "投稿前自审 / 自查 / pre-submission review / 审稿视角 /
  内审 / mock review / 给我做 reviewer / 严苛地审一下 / 顶会评审视角",
  or when paper-revision detects request scope = "before submission".
  Distinct from `paper-revision` which is for incoming reviewer feedback.
domain: revision
triggers:
  - 投稿前自审
  - pre-submission review
  - 审稿视角
  - 内审
  - mock review
  - 顶会评审视角
version: "1.0.0"
compatibility:
  requires: ["python-3.9"]
# v2.2.5 Skill DAG metadata（WP8 of research-writing-skill adoption）
preconditions:
  - "存在论文当前稿（chapters/*.md 或 drafts/paper.pdf 或 overleaf/*.tex）"
  - "（推荐）evidence-driven-writing 已生成 evidence-map.md（用于 §三 引用一致性核查）"
  - "（推荐）experiment-results-planning 已生成 traceability matrix（用于 §三 方法-实验对齐核查）"
consumes:
  - "data/papers/<paper-id>/chapters/*.md / overleaf/*.tex / drafts/*.pdf"
  - "data/papers/<paper-id>/refs/evidence-map.md（如存在）"
  - "data/papers/<paper-id>/plan/review/method-experiment-traceability.md（如存在）"
  - "data/papers/<paper-id>/plan/notes.md（用户偏好 / 投稿目标）"
produces:
  - "data/papers/<paper-id>/plan/review/peer-review-<YYYYMMDD>.md（强制产物，含三阶段输出）"
  - "data/papers/<paper-id>/plan/review/bias-fallacy-audit-<YYYYMMDD>.md（偏倚 + 谬误专项）"
  - "回填 plan/progress.md §五 阶段标记 S6 quality-review 为 reviewing 或 ready-for-revision"
effects:
  - "log_skill_usage 记一条 peer-review 调用"
  - "为下游 paper-revision 提供结构化反馈清单（major / minor / strategic advice）"
failure_modes:
  - type: "scope_misrouted"
    repair: "REBIND（用户其实是『拿到 reviewer 反馈后改』 → 走 paper-revision；本 SKILL 仅服务投稿前自审）"
  - type: "verdict_without_evidence"
    repair: "REBIND（『论文质量看起来不错』『大概能投』必须替换为带证据的 claim — 引用具体段落 / 数字 / 引用条目）"
  - type: "bias_check_skipped"
    repair: "REBIND（4 类偏倚至少各跑一次；缺一类视为未完成）"
  - type: "tone_unprofessional"
    repair: "REBIND（避免人身攻击 / 模糊批评；按 §五 审稿语气重写）"
  - type: "rating_inconsistent"
    repair: "REBIND（rating 必须与 major / minor 列表一致：≥ 1 致命 → 不能给 8+ 分）"
downstream_skills: ["paper-revision"]
---

# Peer-Review — 投稿前自审与 reviewer 视角

> 来源：吸收 `research-writing-skill-main/skills/peer-review/SKILL.md` v3.1.0；
> 与 Academic-Agent 体系深度对接：
> - **paper-revision** 服务"reviewer 反馈来后怎么改"——本 SKILL 服务"投稿前自己当 reviewer"
> - **claim-verification** 服务"论文里数字真不真"——本 SKILL 关心"论文整体是否值得发"
> - 两者错位互补，**不重复**

---

## 一、何时使用 / 何时不用

✅ 用：
- 投稿前 1 周左右
- 用户 mentions "自审 / pre-submission / mock review / 严苛地审一下 / 我要装作审稿人"
- 主稿基本定稿（chapter prose 已写完、experiments 已跑完）
- 想 dry-run 一遍 reviewer 视角

❌ 不用：
- 已收到 reviewer 反馈 → 走 paper-revision
- 还在写章节 → 走 writing-chapters
- 只想检查数字真假 → 走 claim-verification
- 论文还没成型 → 走 brainstorming-research

---

## 二、三阶段评审（严格按顺序）

### 阶段 1 — 初步评估（Preliminary）

回答 5 个关键问题（每条 1–2 句）：

1. 核心研究问题或假设是什么？
2. 主要发现和结论是什么？
3. 工作是否科学合理且有意义？
4. 是否适合目标期刊 / 会议？
5. 是否存在明显的重大缺陷？

**输出**：2–3 句话的 elevator-pitch 总结 → 落盘到 `peer-review-<YYYYMMDD>.md` §1 Preliminary。

### 阶段 2 — 逐节详细审查（Section-by-Section）

每节按下表打分（✓ / ⚠ / ❌），任一 ❌ 必须升级到 §三 偏倚 / 谬误专项。

| 节 | 检查项 | 通过条件 |
|---|---|---|
| **Abstract & Title** | 摘要是否准确反映研究内容和结论？标题是否具体、信息丰富？ | 没有"过度声称" / 没有"the first to" 缺证据 |
| **Introduction** | 背景是否充分且最新？研究问题是否有明确动机？相关工作是否引用充分？ | 引用 ≥ 5 篇 5 年内文献；研究空白论证 ≥ 2 段 |
| **Methods** | 其他研究者能否根据描述复现？方法是否适合解决研究问题？统计方法是否适当？ | 必须含 input-to-output flow（writing-chapters §四.1）|
| **Results** | 结果是否逻辑清晰？图表是否适当、清晰且正确标注？是否包含所有相关结果？ | 0 placeholders；mock 数据有标记；traceability 完整 |
| **Discussion** | 结论是否有数据支持？局限性是否承认？推测是否与数据明确区分？ | "we observe" / "this implies" 严格区分；limitations 段必存 |
| **Reproducibility** | 数据 / 代码是否公开？关键参数 / 随机种子是否报告？ | 至少有 data availability statement |

### 阶段 3 — 方法论 / 统计严谨性（Methodology & Stat Rigor）

**统计评估**：

- 统计假设是否满足？（normality / independence / homoscedasticity）
- 是否报告 effect size 和 p-value？
- 是否适当应用多重检验校正？（Bonferroni / FDR）
- 样本量是否有 power analysis 支持？

**实验设计评估**：

- 对照是否适当且充分？
- 重复是否足够？（≥ 3 seeds for ML；≥ 30 for human eval）
- 潜在混杂因素是否被控制？（leakage / order effect / data contamination）
- baseline 选择是否公平？（同一 model size / 同一 prompt / 同一硬件）

任一 ❌ → §三 偏倚专项。

---

## 三、批判性思维专项（Bias + Fallacy）

### 3.1 偏倚检测表（4 类必跑）

| 偏倚 | 检查要点 | 红旗例子 |
|---|---|---|
| **确认偏倚** Confirmation | 是否只强调支持性发现？ | "our method works on all benchmarks" 而忽略一个 fail case |
| **选择偏倚** Selection | 样本是否代表目标人群 / 任务分布？ | 只在 GSM8K 测但宣称 "general math reasoning" |
| **发表偏倚** Publication | 是否缺少阴性 / 中性结果？ | failed baseline 被静默删除 |
| **P-hacking** | 是否多次分析直到显著？ | 报告了 0.049 但没说试了 5 个超参组合 |

### 3.2 逻辑谬误识别表

| 谬误 | 表现 | 红旗例子 |
|---|---|---|
| **事后归因** post hoc | "B 跟在 A 后面，所以 A 导致 B" | 加了 module → loss 下降 → 归因 module（没消融）|
| **相关 = 因果** | 混淆关联与因果 | "用了 RAG 的模型也更准 → RAG 让它准"（没控制 base capability）|
| **草率泛化** | 从小样本得出广泛结论 | 5 个例子 → "all LLMs do X" |
| **挑选数据** cherry-picking | 只选支持性证据 | 论文只展示 Qwen-72B 的成功 case，不展示 7B 的失败 |
| **稻草人** straw man | 攻击虚构的对手立场 | "previous work assumes X" 而原文从未 assume X |

### 3.3 输出位置

阶段 2 / 阶段 3 中的 ❌ 全部聚到 `bias-fallacy-audit-<YYYYMMDD>.md`，每条含：

```text
- 类型：confirmation / selection / publication / p-hacking / post-hoc / ...
- 位置：chapter / 段落 ID / 行号
- 现象：原文摘录
- 影响：会让 reviewer 怎么质疑
- 修复建议：(a) 补对照 / (b) 改 claim 范围 / (c) 加 limitation 段
```

---

## 四、审稿报告结构（强制产物）

落盘到 `peer-review-<YYYYMMDD>.md`：

```markdown
# Peer-Review Report — <paper-id> — <YYYYMMDD>

## §1. Preliminary
- 5 个关键问题答案（§二.1）
- 2–3 句 elevator-pitch 总结

## §2. Overall Assessment

**研究概述**：1–2 句概括
**总体建议**：[Accept / Minor Revision / Major Revision / Reject]
**Rating**：1–10 分（≥ 1 致命缺陷不能给 8+；具体锚点见下）
**关键优点**（≤ 3 条）
**关键缺点**（≤ 5 条）

## §3. Major Comments（致命问题）

每条按以下结构：
- **位置**：section / paragraph
- **现象**：客观描述
- **影响**：reviewer 视角下的质疑路径
- **建议改动**：具体可操作（不要"建议加强论证"这种空话）

显著影响论文有效性的关键问题：
- 基本方法论缺陷
- 不适当的统计分析
- 不支持或过度陈述的结论
- 缺少关键对照或实验

## §4. Minor Comments（清晰度问题）

- 图表标签或图例不清晰
- 缺少方法细节
- 排版或语法错误
- 引用格式不统一

## §5. Bias & Fallacy Audit
（cross-reference bias-fallacy-audit-<YYYYMMDD>.md）

## §6. Strategic Advice（修订路线）
- 优先级 1：必须改否则不能投
- 优先级 2：能改就改，否则 reviewer 会扣分
- 优先级 3：细节，时间允许时改

## §7. Verdict
- 投稿决策：建议投（目标）/ 暂缓投 / 改投（更适合的 venue）
- 预估命中率：High / Medium / Low（要给理由）
```

### 4.1 Rating 锚点

| 分 | 含义 | 触发条件 |
|---|---|---|
| 9–10 | Top-tier accept | 0 致命 + ≥ 2 实质创新 + 实验非常充分 |
| 7–8 | Accept | 0 致命 + ≥ 1 实质创新 + 实验充分 |
| 5–6 | Borderline | 1–2 致命可修 + 实质创新有边界 |
| 3–4 | Reject (revisable) | ≥ 3 致命 / 实质创新薄弱 |
| 1–2 | Hard reject | 方法学根本性错误 / 数据造假风险 |

≥ 1 致命缺陷而给 ≥ 8 分 → 触发 `rating_inconsistent` failure mode。

---

## 五、审稿语气（强制约束）

### ✅ 最佳实践

- **建设性**：把批评 framed 为改进机会
- **具体**：给具体例子和可操作建议（"P3 段第 2 行的 effect size 缺 95% CI" 而不是"统计部分有问题"）
- **平衡**：承认优点和缺点
- **尊重**：作者投入了大量努力，但不影响诚实
- **客观**：关注科学，而非作者

### ❌ 避免

- 人身攻击 / 轻蔑语言
- 没有具体例子的模糊批评（"this paper is weak"）
- 要求超出 scope 的不必要实验（"也跑一下 GPT-5"）
- 在双盲场景里暴露身份信息
- "我喜欢" / "我不喜欢"（用证据表达）

---

## 六、Reviewer-视角 prompt 模板（直接复制使用）

### 6.1 完整 reviewer 角色

```markdown
# Role
你是一位严苛的资深学术审稿人（顶会 PC member 级别）。

# Task
请深入阅读并分析我的论文，撰写严厉但建设性的审稿报告。

# 审查维度
1. **原创性**：实质性突破还是边际增量？与最近 12 个月的 SOTA 关系？
2. **严谨性**：推导是否有跳跃？实验对比是否公平？统计是否标准？
3. **一致性**：声称的贡献是否得到验证？abstract / intro / experiments / discussion 是否相互支持？
4. **可复现性**：reviewer 自己有 GPU + 时间是否能复现？

# Output
- Part 1 [Review Report]：Summary / Strengths / Weaknesses (Critical) / Rating (1–10)
- Part 2 [Strategic Advice]：具体改进建议（按 priority 1/2/3）
- Part 3 [Bias-Fallacy-Audit]：4 类偏倚 + 5 类谬误专项检查（每条给位置 + 现象 + 影响）

# Input
- 投稿目标：[期刊 / 会议 + 年份]
- 论文当前稿：[paste 或 attach]
- 已知限制：[作者愿意承认的 limitation]
```

### 6.2 快速质量检查（5 分钟版）

```markdown
# Task
快速检查论文是否存在以下 5 类问题（不必详细，只列存在/不存在 + 例子）：

1. 逻辑一致性：introduction 的 claim 是否在 experiments 得到验证？
2. 术语一致性：核心概念是否保持同名（"agent harness" 不要一会叫 "agent system"）？
3. 数据支持：所有结论是否有数据支持？是否有"我们认为"无证据支撑？
4. 对照完整性：是否与足够的 baseline 比较？
5. 消融充分性：是否验证了每个关键模块？

# Output
- 无问题：[检测通过]
- 有问题：分点列出位置和具体问题
```

---

## 七、与其他 SKILL 的关系

```
writing-chapters / paper-orchestration（写完整 paper）
    ↓ 进入 S6 阶段（Quality / Review）
peer-review（本 SKILL：投稿前自审）
    ↓ 输出 review report
paper-revision（吸收反馈做修改）
    ↓ 同时
claim-verification（数字层面 audit）
    ↓
（可选）prompts-collection（针对单段重写时拿 prompt）
    ↓ 进入 S7 阶段（Submit）
draft-to-latex / 投稿
```

- **上游**：所有写完的章节
- **平行 / 错位**：paper-revision（接收反馈后改）/ claim-verification（数字真实性）
- **下游**：paper-revision

---

## 八、关键原则

1. **三阶段顺序不可乱**——preliminary → section → method/stat
2. **rating 必须有锚点**——锚点见 §4.1
3. **每条 critique 必须有位置**——chapter / paragraph / line
4. **偏倚 + 谬误专项必跑**——4+5 共 9 类，至少全部过一遍
5. **不允许 "应该没问题"**——参照 verification SKILL Red Flags
6. **不重复 paper-revision 工作**——本 SKILL 输出是 reviewer 视角的诊断；具体改动落到 paper-revision
