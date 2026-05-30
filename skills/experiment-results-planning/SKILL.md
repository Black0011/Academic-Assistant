---
name: experiment-results-planning
description: >-
  Engineer the entire result layer before any real metric exists: experiment
  protocol, method-experiment traceability matrix, table schema, figure data
  manifest, mock-data boundary, and result-chapter decontamination. Owns the
  D0–D5 experiment gates that gate-keep Results / Discussion writing. Use
  when the user says "设计实验 / 设计结果章 / 写 results / 实验设计 /
  实验协议 / experimental protocol / mock results / placeholder results /
  实验占位数据 / table schema / figure manifest", or when the paper is in
  D0–D2 stage of `plan/stage-gates.md`. Forbids presenting mock / synthetic
  data as real experimental evidence.
domain: writing
triggers:
  - design experiment
  - 设计实验
  - experimental protocol
  - 实验占位数据
  - table schema
  - figure manifest
  - 写 results
version: "1.0.0"
compatibility:
  requires: ["python-3.9"]
# v2.2.5 Skill DAG metadata（WP3 of research-writing-skill adoption）
preconditions:
  - "data/papers/<paper-id>/plan/project-overview.md / outline.md 已锁定"
  - "已有 ≥ 1 条贡献（contribution）声明（在 Introduction 或 plan/notes.md）"
  - "（推荐）evidence-driven-writing 已生成 evidence-map.md（用于 Related Work / Baseline 引用）"
consumes:
  - "data/papers/<paper-id>/plan/outline.md"
  - "data/papers/<paper-id>/plan/notes.md（用户偏好 + 贡献清单）"
  - "data/papers/<paper-id>/refs/evidence-map.md（baseline 引用来源）"
produces:
  - "data/papers/<paper-id>/plan/experiment-protocol.md（强制产物）"
  - "data/papers/<paper-id>/plan/review/method-experiment-traceability.md（强制产物）"
  - "data/papers/<paper-id>/tables/table-schema.md（强制产物）"
  - "data/papers/<paper-id>/figures/data-manifest.md（强制产物）"
  - "data/papers/<paper-id>/figures/data/{real,mock_*}.csv（数据物理文件）"
effects:
  - "log_skill_usage 记一条 experiment-results-planning 调用"
  - "为 paper-writing / writing-chapters 的 Results / Discussion 章节解锁 D0–D5 hard gate"
failure_modes:
  - type: "protocol_missing"
    repair: "INSERT_PREREQ（先按 §三 模板新建 plan/experiment-protocol.md）"
  - type: "traceability_gap"
    repair: "REBIND（每条 contribution 必须有主实验 / 消融 / limitation 三选一兜底；找不到的 contribution 必须从 Introduction 删除或降级到 future-work）"
  - type: "mock_mislabeled"
    repair: "REBIND（mock / synthetic 文件必须以 mock_ / synthetic_ 起首；mock 表必须含 'PLANNING DATA - replace before submission' 注释；prose 用 mock 值时必须含 [待真实实验替换] 标记）"
  - type: "results_chapter_contaminated"
    repair: "REBIND（Results 章节出现『实验目的』『表位』『回填模板』『讨论提示』即 D4 fail，把这些字串迁回 plan/，详见 §六）"
  - type: "data_manifest_missing_for_figure"
    repair: "INSERT_PREREQ（每张图必须先在 figures/data-manifest.md 登记 data 输入路径，再画图）"
downstream_skills: ["paper-writing", "paper-revision", "claim-verification"]
---

# Experiment-Results-Planning — 实验与结果工程化

> 来源：吸收 `research-writing-skill-main/skills/experiment-results-planning/SKILL.md` v3.1.0；
> 与 Academic-Agent 体系深度对接：把 D0–D5 gate 写进 `plan/stage-gates.md`；
> mock-data boundary 与 `claim-verification` SKILL 的 evidence-level 同语言。

---

## 一、Hard Gate（硬门，不可绕过）

写 **Results / Discussion** 章节前，以下 5 件产物缺一不可：

```text
data/papers/<paper-id>/plan/experiment-protocol.md
data/papers/<paper-id>/plan/review/method-experiment-traceability.md
data/papers/<paper-id>/tables/table-schema.md
data/papers/<paper-id>/figures/data-manifest.md
data/papers/<paper-id>/figures/data/{real_*.csv | mock_*.csv | synthetic_*.csv}
```

任一缺失 → 立即停止 Results prose 写作，按 §三–§六 补齐。

---

## 二、何时使用 / 何时不用

✅ 用：
- 设计实验章节、result tables、planning mock data、evaluation protocols
- D0–D2 stage（实验协议 → 数据契约 → 数据准备）
- 用户说「设计实验 / 写 results / mock 实验占位 / table schema / figure manifest」
- paper-writing 路由 Results 章节时（强制前置）

❌ 不用：
- Introduction / Related Work（走 evidence-driven-writing）
- Methodology 主体（走 paper-writing 默认流程）
- 已经跑完真实实验、只想画一两张图（直接走 figures / draft-to-latex）

---

## 三、Experiment Protocol（实验协议模板）

`plan/experiment-protocol.md` 必须含以下 8 段：

```markdown
# Experiment Protocol — <paper-id>

## §1 数据集与切分
- 数据集：
- 切分策略（train/dev/test 比例 / k-fold / hold-out / Non-IID 构造规则）：
- 随机种子（≥ 3 个）：
- 数据预处理流程：

## §2 Baselines（公平性论证）
| Baseline | 来源 | 调过的超参 | 与本方法的可比口径 |
|---|---|---|---|
| | | | |

## §3 评价指标与不平衡处理
- 主指标：
- 辅助指标：
- 类别不平衡处理（如 macro-F1 vs micro-F1 / weighted）：
- 显著性检验方法：

## §4 主实验
- 实验编号：M-01
- 验证的 contribution：
- 期望结论：

## §5 效率评估
- 时延 / 吞吐 / 显存 / FLOPs（按 venue 要求）：
- 测量协议（warmup / 重复次数 / 误差区间）：

## §6 消融研究（每条 claimed contribution 必有）
| Ablation | 移除的模块 | 期望性能下降 | 表/图 |
|---|---|---|---|
| | | | |

## §7 泛化 / 鲁棒性
- 跨域 / 跨任务 / 噪声扰动 / 对抗 / 长尾：
- 评测脚本：

## §8 复现性与日志 schema
- 硬件 / 软件 / 依赖版本：
- 日志路径与字段：`logs/<exp-id>/{config.yaml, metrics.jsonl, run.log}`
- 复现步骤（5 行 bash）：
```

每条 Introduction 中的 contribution **必须**映射到 §4 / §6 / §7 中的某个实验，或显式声明 limitation。

---

## 四、Method-Experiment Traceability（方法-实验追踪矩阵）

`plan/review/method-experiment-traceability.md`：

```markdown
| Contribution | Method module | Experiment | Table/Figure | Allowed claim | Evidence status |
|---|---|---|---|---|---|
| C1 - 提出 X | §3.2 模块 A | M-01 主实验 + A-01 消融 | Table 2 / Fig. 3 | "在 D 数据集上 +N%" | real / mock / partial |
| C2 - ... | | | | | |
```

强制规则：
- 任一 contribution 在 Introduction 出现，必须在本表对应；找不到对应 → 该 contribution 从 Introduction 删除或降级到 future-work
- `Allowed claim` 列写"基于现有实验，能下的最强结论是什么"——这条会被下游 `claim-verification` SKILL 用来卡 prose
- `Evidence status`：`real`（真实数据已回填）/ `mock`（仍是 placeholder）/ `partial`（部分回填）

---

## 五、Mock Data Boundary（占位数据红线）

mock / synthetic 数据**仅允许**用于 planning figures / table layout 的可视化预演。

### 5.1 文件命名

- CSV / JSON 文件必须以 `mock_` 或 `synthetic_` 开头：`figures/data/mock_main_results.csv`
- 真实数据文件以 `real_` 或方法名开头：`figures/data/real_main_results.csv`

### 5.2 表格注释

每张含 mock 数据的表 **必须**在 `tables/table-schema.md` 与 chapter 中同时含：

```markdown
> ⚠️ PLANNING DATA - replace before submission
```

### 5.3 Prose 占位规则

manuscript prose 中引用 mock 值时**必须**保留：

- 中文：`[待真实实验替换]`
- 英文：`[REPLACE WITH REAL DATA]`

**禁止**用以下 phrase 描述 mock 值：「实验结果表明」「results show」「verified」「we observe」「achieves」「outperforms」。这些动词是 D4 decontamination 的扫描关键词，违者必须改为 hedged 语言。

### 5.4 提交前清单

D4 阶段必须扫描 chapter prose：

```bash
grep -rE "PLANNING DATA|\[待真实实验替换\]|\[REPLACE WITH REAL DATA\]" \
    data/papers/<paper-id>/chapters/ \
    && echo "❌ STILL HAS PLACEHOLDERS — fix or block submission"
```

---

## 六、Table Schema 与 Figure Handoff

### 6.1 Table Schema

`tables/table-schema.md`：

```markdown
| Table | Purpose | Rows | Metrics | Data source | Replacement owner | Aggregation |
|---|---|---|---|---|---|---|
| T-01 主比较 | C1 验证 | Methods × Datasets | F1 / Acc / EM | real_main.csv | <author> | mean ± std (3 seeds) |
```

强制：
- 不存在 supports any claim 的表 → 不创建（禁绝"漂亮但无用"的表）
- 多 seed 实验必须 `mean ± std` 或 95% CI

### 6.2 Figure Data Manifest

`figures/data-manifest.md`：

```markdown
| Figure | Section | Data file | Script | Status |
|---|---|---|---|---|
| F-01 主结果柱状图 | §4.1 | figures/data/real_main.csv | figures/results/fig01.py | real |
| F-02 消融热图 | §4.3 | figures/data/mock_ablation.csv | figures/results/fig02.py | mock — replace at D3 |
```

每张图必须先在 manifest 登记 → 再写 plot 脚本 → 输出 PNG + SVG → 写 caption（描述图衡量了什么，**不是**作者希望它证明什么）。

模型架构 / 流程图走 `figures-diagram`（mermaid / draw.io），**不**经过本流程的数据 manifest。

---

## 七、Results Prose Pattern

### 7.1 真实数据段（推荐写法）

```markdown
The method achieves <X%> under <condition Y>, compared with baseline <Z (citation)>.
The improvement is mainly associated with <module M>, while <failure mode F>
remains visible in <metric K (-N%)>.
```

要求：claim → number → condition → comparison baseline → mechanism → counter-evidence，五段一体。

### 7.2 mock / placeholder 段（强制写法）

```markdown
[待真实实验替换] This paragraph will compare Table N once real experiment logs
arrive at gate D3. Expected direction: method outperforms baseline B by X% on
metric F1 under condition C, but a parity range remains plausible if the
ablation removes module M.
```

D4 后该段必须替换为 §7.1 真实数据段；保留 `[待真实实验替换]` 即视为 D4 fail。

---

## 八、与 Stage Gates 的对接

`plan/stage-gates.md` 已含 D0–D5；本 SKILL 的产物对应：

| Gate | 本 SKILL 产物 |
|---|---|
| D0 实验协议锁定 | `plan/experiment-protocol.md` 全 8 段填完 |
| D1 表格 / 图骨架 | `tables/table-schema.md` + `figures/data-manifest.md` |
| D2 数据准备 | `figures/data/` 下文件命名合规（real / mock_ / synthetic_ 前缀）|
| D3 主实验跑通 | manifest `Status: real`；表格 placeholder 替换 |
| D4 Results 去污染 | chapter 不含 `PLANNING DATA` / `[待真实实验替换]` 残留 |
| D5 内审通过 | `plan/review/<section>-peer-review.md` |

---

## 九、与其他 Skill 的关系

```
paper-orchestration（编排者，决定何时触发本 SKILL）
    ↓
brainstorming-research / evidence-driven-writing（提供 contribution 清单与 baseline 来源）
    ↓
experiment-results-planning (本 SKILL：D0–D2)
    ↓ (产出 protocol / traceability / table-schema / data-manifest)
执行实验（人工 / scripts/eval_*.py）
    ↓ (D3 真实数据回填)
paper-writing / writing-chapters (D4 Results prose；强制读本 SKILL §五 / §七)
    ↓ (D4 完成)
claim-verification（扫 prose 中的 number / claim → 反查 traceability + table-schema）
    ↓ (D5 通过)
paper-revision (下一轮迭代)
```

- **上游**：evidence-driven-writing / brainstorming-research / paper-orchestration
- **平行**：figures-python / figures-diagram（数据图 / 架构图）/ statistical-analysis（如启用）
- **下游**：paper-writing（Results / Discussion 章）/ claim-verification（数据级审计）/ paper-revision

---

## 十、FAQ

**我已经有真实实验数据，可以跳过 D0–D2 直接写吗？**
→ 不能跳过 traceability matrix（C × M × Table × Claim）。即使数据齐，也必须显式列出每条 contribution 的 allowed claim 边界，否则下游 claim-verification 会卡 prose 中的过强主张。

**论文是 survey / position paper，不需要实验怎么办？**
→ 在 `plan/stage-gates.md §三` 明确声明跳过 D0–D5，并在 paper-orchestration 任务包里标 `experiment_required: false`。本 SKILL 只在 method/framework/system/benchmark 类论文强制。

**mock 数据后期忘了替换怎么办？**
→ §5.4 的 grep 命令在 D4 / S5 阶段强制跑；paper-orchestration 阶段 2 review 会调用本检查，未通过即阻塞投稿。

**main / ablation / efficiency 实验顺序如何安排？**
→ 推荐：先 ablation（验证模块设计是否合理）→ 再 main（横向比较）→ 最后 efficiency（提交前 1 周即可）。这与"先验证内部一致性再外部对比"的方法论一致。
