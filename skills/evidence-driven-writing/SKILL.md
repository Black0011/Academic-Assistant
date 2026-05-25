---
name: evidence-driven-writing
description: >-
  Force literature-driven sections (Introduction, Related Work, background,
  literature synthesis) to start from a structured evidence map and paragraph
  blueprint before any prose is written. Builds a citation→claim table from
  the user's literature pool (`data/survey/notes/*.yaml`), enforces "one
  citation = one concrete claim", anti-enumeration synthesis (≥ 2 of:
  problem condition / method family / shared limitation / bridge / boundary),
  body-contamination firewall (no template prompts in chapter text), and
  publishable Introduction / Related Work patterns. Use when the user says
  "写 introduction / 写 related work / 文献综述 / literature synthesis /
  导言 / 引言 / background / 我要把这堆论文织成正文", or when paper-writing
  / paper-orchestration routes a literature-heavy section here.
domain: writing
triggers:
  - write introduction
  - write related work
  - literature synthesis
  - 文献综述
  - 导言
  - 把这堆论文织成正文
version: "1.0.0"
compatibility:
  requires: ["python-3.9"]
# v2.2.5 Skill DAG metadata（WP2 of research-writing-skill adoption）
preconditions:
  - "data/survey/notes/<paper_id>.yaml ≥ 5 篇与本论文主题强相关的笔记存在"
  - "data/papers/<paper-id>/plan/project-overview.md 已通过 init_paper_plan.py 初始化"
consumes:
  - "data/survey/notes/*.yaml"
  - "data/survey/synthesis/*.md（可选，跨论文综合）"
  - "data/survey/paper-table.md（可选，用作交叉索引）"
  - "data/papers/<paper-id>/plan/outline.md（提供章节切分）"
produces:
  - "data/papers/<paper-id>/refs/evidence-map.md（强制产物）"
  - "data/papers/<paper-id>/plan/chapter-blueprints/<section>-blueprint.md（强制产物）"
  - "data/papers/<paper-id>/plan/review/evidence-coverage.md（每段→证据 IDs 覆盖矩阵）"
effects:
  - "log_skill_usage 记一条 evidence-driven-writing 调用"
  - "为 paper-writing / writing-chapters 的 Introduction / Related Work 章节解锁 hard gate"
failure_modes:
  - type: "evidence_map_missing"
    repair: "INSERT_PREREQ（先跑 tools/evidence_map_builder.py 从 notes/*.yaml 半自动生成模板）"
  - type: "blueprint_missing"
    repair: "INSERT_PREREQ（在 plan/chapter-blueprints/ 下补 <section>-blueprint.md，每段必须含 5 字段）"
  - type: "single_citation_single_claim_violation"
    repair: "REBIND（拆分『一段 1 个 citation 撑 5 句话』成多个段落，或补足证据；详见 §五 Anti-Enumeration）"
  - type: "body_contamination"
    repair: "REBIND（章节正文出现『写自然一点』『此处填实验数据』等 process notes — 必须迁回 plan/，详见 §六 Firewall）"
  - type: "indirect_evidence_unmarked"
    repair: "REBIND（间接 / 弱支持的 citation 必须在 evidence-map 里标 Risk: indirect，否则下游 claim-verification 拒绝放行）"
downstream_skills: ["paper-writing", "claim-verification"]
---

# Evidence-Driven Writing — 证据驱动的文献型章节

> 来源：吸收 `research-writing-skill-main/skills/evidence-driven-writing/SKILL.md` v3.1.0；
> 与 Academic-Agent 体系深度对接：把 `data/survey/notes/*.yaml` 升级为 evidence-map 的"上游真相源"，
> 与 `claim-verification` SKILL 形成"证据→主张"双向闭环。

---

## 一、Hard Gate（硬门，不可绕过）

写 **Introduction / Related Work / background / literature synthesis / 任何含 ≥ 3 处引用的章节** 前，必须存在以下三件产物，缺一不可：

```text
data/papers/<paper-id>/refs/evidence-map.md                      ← §三
data/papers/<paper-id>/plan/chapter-blueprints/<section>-blueprint.md  ← §四
data/papers/<paper-id>/plan/review/evidence-coverage.md          ← §四 末
```

如缺，立即停止 prose 写作，按 §三 / §四 补齐。

---

## 二、何时使用 / 何时不用

✅ 用：
- 写 / 改 Introduction、Related Work、Background、Literature Synthesis
- 任何章节引用文献 ≥ 3 处时（包括 Methodology 的"前人工作对比段"）
- paper-writing / paper-orchestration 路由到文献密集型章节
- 用户说「帮我写引言 / 写 related work / 把文献织进正文 / literature synthesis」

❌ 不用：
- Methodology 主体（不是文献章节，走 paper-writing 默认流程）
- Experiments 数据章（走 experiment-results-planning）
- Conclusion / Future Work（走 writing-chapters）
- 单论文精读卡片（走 paper-reading）

---

## 三、Evidence Map（证据图谱）

### 3.1 半自动生成

```bash
# 从 notes/*.yaml 抽 5–30 篇，生成 evidence-map.md 模板（含已填字段 + TODO 槽）
python tools/evidence_map_builder.py \
    --paper-id <paper-id> \
    --paper-ids arxiv-2509.01238,he-deusyu-concepts,...

# 或按 tag 抽全集
python tools/evidence_map_builder.py \
    --paper-id <paper-id> \
    --tags harness-engineering,mechanical-enforcement
```

输出位置：`data/papers/<paper-id>/refs/evidence-map.md`，已存在则默认拒绝覆盖（Tier 1 护栏）。

### 3.2 表格 schema

每条来源（即 `data/survey/notes/<paper_id>.yaml`）一行：

| 字段 | 来源 / 填写规则 |
|---|---|
| Source ID | YAML 的 `paper_id`（短形式，如 `he-deusyu-concepts`）|
| Citation | "Author Year, Venue"（来自 YAML 的 `authors[0]` + `year` + `venue`）|
| Source type | `survey` / `method` / `system` / `framework` / `benchmark` / `theory` / `position` / `dataset`（人工标）|
| Abstract-level finding | 来自 YAML 的 `problem` 或 `key_results` 一句压缩 |
| Usable fact | 你打算引用进段落的"具体可用事实"（必须是单条，不是泛论）|
| Supported claim | 这条事实在你段落里支撑哪一句（一一对应）|
| Citation slot | `Introduction-P1` / `RelatedWork-Theme1-P2` 等（与 §四 blueprint 对齐）|
| Risk | `direct` / `indirect`（弱支持 / 类比 / 仅前置条件）|

### 3.3 强制规则

- **优先用户 literature pool**：先扫 `data/survey/notes/`，再扫 `data/survey/synthesis/`，再扫 `data/survey/paper-table.md`；都没有时**禁止编造**（与 `claim-verification` SKILL 共享）
- **只用元数据可见信息**：title / abstract / DOI metadata / 用户笔记字段；除非已有全文，否则不得"猜测"原文未提的细节
- **一引用 = 一具体事实**：「X 等人提出了 Y」属于泛论，禁止；要写成「X 等人在 Y 数据集上达到 Z%（Table 3, Page 5）」
- **弱支持必须显式标记**：`Risk: indirect`，下游 `claim-verification` SKILL 据此降级该 claim 的证据等级

---

## 四、Paragraph Blueprint（段落蓝图）

### 4.1 每段 5 字段

`plan/chapter-blueprints/<section>-blueprint.md` 中，每段定义为：

```markdown
### Paragraph N
- Role: context / method-landscape / limitation / gap / contribution / bridge
- Main claim: <一句话，本段主题句的种子>
- Evidence IDs: [<Source ID 1>, <Source ID 2>, ...]
- Contrast or transition: <与上一段的关系：递进 / 转折 / 类比 / 对照>
- Forbidden content: <本段不能出现的概念，例如 "implementation details", "user requirement notes">
```

### 4.2 Blueprint → Prose 解锁

仅当 blueprint 含 ≥ 5 段且每段 5 字段全填 → 解锁 prose 写作。

### 4.3 Evidence Coverage（覆盖矩阵）

`plan/review/evidence-coverage.md` 横纵交叉：

```markdown
| Paragraph | Evidence IDs | Used in prose | Notes |
|---|---|---|---|
| Introduction-P1 | he-deusyu-concepts, arxiv-2509.01238 | ✅ | |
| Introduction-P2 | <TODO> | ⏳ | 缺 method-family 维度的证据 |
```

每完成一段 prose，回填该段实际用到的 Evidence IDs；空槽视为"借证据但没用上 / 用了但没标"——必须二选一。

---

## 五、Introduction Pattern（5 段链）

可发表的 CS / 工程 SCI Introduction 通常按以下 5 段链：

1. **应用上下文** — 问题为什么重要（fundamental / survey 引用）
2. **现有技术路线** — 按 method-family 分组，**不要**按论文 list 罗列
3. **瓶颈级联** — 每条路线解决了什么 + 留下什么；这是"为什么需要本文"的因果根
4. **具体研究空白** — 本文方法可以现实地解决的、明确边界的 gap
5. **贡献概述** — prose 段或 ≤ 3 条短列表（仅当目标 venue 风格允许）

**对 CS 工程 SCI 论文**：除非 outline 显式要求独立的 Related Work 章，否则把最相关的相关工作综合到 Introduction 里。整段必须读起来像论证：场域压力 → 现有路线 → 未解瓶颈 → 本文定位 → 贡献边界。

**禁止**：在 Introduction 末尾写超长机械式 chapter map（"Section 2 reviews ..., Section 3 introduces ..."），一段简洁的 manuscript-organization 段落足够。

---

## 六、Related Work Pattern（按主题，非按时间）

每个主题段：

- **Theme opening**：定义方法族 / 研究流
- **Evidence synthesis**：在同一段内对比 2–4 条来源（不是"逐篇介绍"）
- **Critical boundary**：明示该主题"未解决的"
- **Bridge**：解释下一主题或本文方法为何被需要

---

## 七、Body Contamination Firewall（正文污染防火墙）

### 7.1 禁止入正文的模板词

用户需求 / 流程笔记 / 模板提示词不得进入章节正文。以下短语只允许出现在 `plan/`，不允许出现在 `chapters/`：

- 「写自然一点」/ "write naturally"
- 「避免泛泛而谈」/ "avoid generic wording"
- 「此处填实验数据」/ "fill later" / "TBD"（除非用 `<TBD: ...>` 显式占位标记）
- 「用户应替换」/ "user should replace"
- 「这是一个模板」/ "this section is a template"

### 7.2 压缩 ≠ 删除

缩短段落时必须保留：claim / evidence / method condition / limitation 四要素。删任一要素属于 Tier 3 结构性修改，必须走 `paper-writing` 的提案流程。

---

## 八、Anti-Enumeration Gate（反罗列门）

文献章节如读起来像"逐条 source notes"——直接 review fail。每段必须综合 §下列 5 项中至少 2 项：

1. 问题条件
2. 方法族
3. 多研究共享的限制
4. 直接桥接到本文方法
5. 引用支撑的边界

**判定法**：如果一段可以无损地转成表格的一行（每条 source 一格），它就还不是 manuscript prose。

---

## 九、与其他 Skill 的关系

```
literature-search / paper-reading / autoresearch
    ↓ (产出 notes/*.yaml + synthesis/*.md)
evidence-driven-writing (本 SKILL：notes → evidence-map → blueprint)
    ↓ (产出 evidence-map + blueprint)
paper-writing / writing-chapters (写 prose；强制读本 SKILL §五 / §六)
    ↓ (产出 chapter prose)
claim-verification (扫 prose 中的 claim → 反查 evidence-map → 标弱证据)
    ↓ (审计通过)
paper-revision / paper-orchestration（下一轮）
```

- **上游**：`autoresearch` / `literature-search` / `paper-reading` / `survey-writing`
- **平行**：`paper-writing`（本 SKILL 负责文献章节，paper-writing 负责非文献章节）
- **下游**：`claim-verification`（必经；它会校验 chapter 中每条引用都能反查到 evidence-map 行）

---

## 十、FAQ

**我没有那么多 notes 怎么办？**
→ 先跑 `autoresearch` / `literature-search` 补足 ≥ 5 篇笔记；本 SKILL 不允许在「无证据池」状态下凭空开写。

**我能不能跳过 blueprint 直接写？**
→ 不能。blueprint 缺失的章节会被 paper-orchestration 阶段 1 拒绝放行；写完后 paper-quality-gate（如启用）会扫描 chapter 中是否所有引用都能反查到 blueprint。

**Evidence-map 已经存在但我想加新论文怎么办？**
→ 在表格末追加新行（StrReplace 锚点 `<!-- INSERT_NEW_EVIDENCE_HERE -->`，由 builder 自动写入），不要 Write 整文件覆盖（Tier 1 护栏）。

**`Risk: indirect` 的 citation 还能不能用？**
→ 能用，但 `claim-verification` 会把这条 claim 的证据等级降为 weak，需在正文里加 hedge 表达（例如「prior survey reports …, though direct empirical comparison is missing」）。
