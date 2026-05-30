---
name: verification
description: >-
  Universal "claim → evidence" gate. Forbids announcing completion without
  running a verification command and reading its full output. Maintains a
  Red-Flag list (apologetic / hedging / fatigue language) and an
  Excuses-vs-Facts table to mechanically intercept "should be done" /
  "looks fine" / "I'm pretty sure" style finalisations. Use when the
  agent is about to claim chapter complete / references verified / skill
  finished / search done / repo healthy / paper ready, or when the user
  says "确认 / 验证 / 真的写完了吗 / verify / are you sure". Distinct
  from `claim-verification` which audits paper-internal numerical claims;
  this skill audits skill-completion claims at every level.
domain: meta
triggers:
  - verify completion
  - 真的写完了吗
  - are you sure
  - verification report
  - 确认完成
version: "1.0.0"
compatibility:
  requires: ["python-3.9"]
# v2.2.5 Skill DAG metadata（WP11 of research-writing-skill adoption）
preconditions:
  - "已声称（或将要声称）某项工作完成（章节 done / 引用真实 / skill 改造完 / 仓库健康）"
consumes:
  - "当前任务的 stage / artifacts 路径"
  - "（按场景）chapters/*.md / refs/evidence-map.md / .cursor/skills/<name>/SKILL.md"
produces:
  - "verification 报告（stdout 或 plan/review/<task>-verification.md）"
  - "执行的具体命令 + 完整输出片段（粘到对话或文件）"
effects:
  - "log_skill_usage 记一条 verification 调用"
  - "为 paper-orchestration / writing-chapters / paper-revision / claim-verification / 任意 skill 完成判定提供机械门"
failure_modes:
  - type: "claim_without_evidence"
    repair: "REBIND（声称完成但未运行任何验证命令；按 §三 验证模式跑命令并粘输出）"
  - type: "partial_output_quoted"
    repair: "REBIND（只引用部分输出；必须读完整输出、给行数 / 关键摘要）"
  - type: "agent_relay_trusted"
    repair: "REBIND（『subagent 说做完了』不算证据；必须独立验证 — 至少跑一条独立命令）"
  - type: "fatigue_excuse"
    repair: "REBIND（『我累了 / 就这一次 / 应该没问题』 触发停下；必须运行验证或显式声明 partial_verified）"
downstream_skills: []
terminal: true
terminal_outputs:
  - "verification 报告（带命令 + 完整输出 + 结论）"
---

# Verification — 通用任务完成判定门（声称 → 证据）

> 来源：吸收 `research-writing-skill-main/skills/verification/SKILL.md` v3.1.0；
> 与 Academic-Agent 体系深度对接：
> - **claim-verification**：论文内 claim 的事实审计（数字、引用真假、方法-结果一致性）
> - **verification**（本 SKILL）：**任意 skill 的"完成"声称**的通用机械门
> - 两者**错位互补**，命名空间共享但职责分离

---

## 一、核心原则（不可妥协）

> **声称完成而没有验证，是不诚实的表现。**

```text
没有验证证据，就不能声称完成。
```

这条规则在 Academic-Agent 内不可协商：
- 不允许"应该完成了" / "看起来对" / "我很确信"
- 不允许只跑了一半验证就 claim done
- 不允许相信 subagent 的 status: DONE 而不独立核对

---

## 二、验证门控（5 步动作）

在声称任何状态或表达满意之前**必须**走完：

```text
1. 确认：什么命令 / 操作能证明这个声称？
2. 执行：运行完整的验证操作（不要部分，不要"应该够了"）
3. 读取：完整输出，检查结果
4. 验证：输出是否确认声称？
   - 是 → 声称 + 证据
   - 否 → 说明实际状态 + 已知偏差 + 后续动作
5. 然后才能：作出声称
```

跳过任一步 = **撒谎**，不是验证。

---

## 三、常见验证场景（速查表）

| 声称 | 必跑命令 | ❌ 不充分（Red Flag）|
|---|---|---|
| 章节完成 | `wc -m chapters/<file>.md` + 跑 §五 spec / quality review | "应该写完了" |
| 引用真实 | `python scripts/paper_quality_gate.py --paper-id <id> --checks citation_coverage` 或 CrossRef API | "看起来像真的" |
| 论点有支撑 | 在 evidence-map.md 中确认每条 claim 有 ≥ 1 支撑 source | "这段写得像论文" |
| 格式正确 | `python scripts/style_check.py <file>` + `paper_quality_gate.py` | 目检 |
| 无 AI 痕迹 | `python scripts/style_check.py <file> --strict` | "读起来还行" |
| 文献搜索完成 | 检查 search 输出 JSON / paper-table 行数 / DOI 列表非空 | "搜过了" |
| Skill 改造完成 | `python skills/dag_build.py && python skills/dag_validate.py` | "文件都写了" |
| 初稿达到稿件门 | `python scripts/paper_quality_gate.py --paper-id <id>`（必要时 `--submission`）| 只跑 style_check |
| 仓库护栏健康 | `python scripts/check_writes.py` + `python scripts/quality_check.py` | "应该没破" |
| 测试零回归 | `pytest -q` 完整跑 + 看到 `passed` 数字 | "我跑了" 不给数字 |

---

## 四、Red Flags — 出现立即停止

下列任一信号出现，**必须**先验证再继续：

- 使用"应该" / "可能" / "看起来" / "should be" / "probably"
- 在验证前表达满意：「好了！」「完成！」「搞定！」「Done!」
- 准备 commit / push / merge 而未验证
- 相信 subagent 的成功报告（只看 status: DONE 不看 changed file）
- 依赖部分验证（"我跑了 1 个测试" / "看了开头"）
- 想着「就这一次」「下次再补」「先这样吧」
- 疲劳想结束工作（"我累了" / "时间不多了"）
- **任何暗示成功但没有运行验证的措辞**

---

## 五、借口 vs 事实（机械替换表）

| 借口 | 事实 |
|---|---|
| "应该行了" | 运行验证命令 |
| "我很确信" | 确信 ≠ 证据 |
| "就这一次" | 没有例外 |
| "格式检查过了" | 格式检查 ≠ 内容正确 |
| "subagent 说成功了" | 独立验证（再跑一遍 / 看 changed file）|
| "我累了" | 疲劳不是借口；显式 partial_verified 或暂停 |
| "部分检查够了" | 部分证明不了什么 |
| "看起来正确" | 对照 reference / spec / 目标输出 |
| "和上次一样" | 上次也未必对；重新跑 |
| "用户没反对就是同意" | 用户没反对 ≠ 通过 |

---

## 六、关键验证模式（含具体命令 + 输出形态）

### 6.1 章节完成验证

```text
✅ wc -m chapters/01_Introduction.md           → 看到："4823 chapters/01_Introduction.md"
✅ ls -la chapters/                            → 看到：文件存在 + 字节数与上面一致
✅ python scripts/style_check.py chapters/01_Introduction.md
                                                → 看到："PASS" 或具体违规位置
✅ 在 plan/chapter-architecture.md 找 min_chars=4500 → 4823 > 4500 × 0.9 = 4050  ✓
❌ "Introduction 已完成" — 无证据
```

### 6.2 引用验证

```text
✅ python scripts/paper_quality_gate.py --paper-id <id> --checks citation_coverage
                                                → 看到：no citation_coverage issues
✅ 抽 5 处 \cite{Yao2023ReAct}，反查 refs/evidence-map.md 行号 → 全部命中
✅ 调 CrossRef API 或 Google Scholar，DOI 存在 + 题目 / 作者 / 年份匹配
❌ "引用看起来正确" / "应该是真的"
```

### 6.3 论点支撑验证

```text
✅ grep -n "我们提出" chapters/01_Introduction.md
   对每条 claim → 在 refs/evidence-map.md 中找到 ≥ 1 supporting source ID
✅ 在 plan/review/method-experiment-traceability.md 中找到本贡献 → 对应实验存在
❌ "相关工作看起来完整" / "这段有学术感"
```

### 6.4 Skill 完整性验证

```bash
python skills/dag_build.py
python skills/dag_validate.py
# 期望输出："Cycles found: 0" 或 "PASS"
```

用于确认新增技能、路由、验证脚本和关键门控仍然存在。

### 6.5 稿件质量门验证

```bash
python scripts/paper_quality_gate.py --paper-id <paper-id>
# 投稿前严格模式
python scripts/paper_quality_gate.py --paper-id <paper-id> --submission
```

用于检查 plan/ 模板齐备、引用覆盖、正文污染、列表化、占位策略、figure data manifest 和 evidence map。

### 6.6 仓库护栏 / 测试零回归

```bash
python scripts/check_writes.py     # 知识保护 Tier 框架检查
python scripts/quality_check.py    # 仓库级数据健康
pytest -q                          # 完整测试套件
```

每条命令必须**读完输出**并把关键数字（passed / failed / 0 errors）粘到对话里。

### 6.7 文献搜索验证

```text
✅ ls -la data/survey/raw/<query>/                → 看到：N 个 JSON / PDF
✅ wc -l data/survey/paper-table.md               → 看到：与之前对比 +M 行
✅ jq '.[].doi' data/survey/raw/.../results.json  → 看到：每条有 DOI
❌ "搜过了" / "应该有结果"
```

---

## 七、验证检查清单（每项工作完成前必跑）

- [ ] 运行了验证命令（具体命令名）
- [ ] 读取了完整输出（不只是开头）
- [ ] 确认结果支持声称（不是"似乎支持"）
- [ ] 没有依赖"应该"或"可能"
- [ ] 证据在当前消息中呈现（命令 + 输出片段 + 结论 三件套）
- [ ] 无 Red Flags 措辞
- [ ] 如果是 subagent 报告 → 独立再核对一次

---

## 八、验证报告标准格式

如需落盘（推荐用于 medium / full-paper 任务收尾），写到 `plan/review/<task>-verification.md`：

```markdown
# Verification Report — <task-id> — <YYYYMMDD-HHMM>

## Claim
<本次声称的内容；一行>

## Commands Run
| # | command | duration | exit code |
|---|---|---|---|
| 1 | python scripts/style_check.py chapters/01_Introduction.md | 0.4s | 0 |
| 2 | python scripts/paper_quality_gate.py --paper-id paper-X | 1.2s | 0 |
| 3 | wc -m chapters/01_Introduction.md | 0.1s | 0 |

## Output Excerpts
<关键行 + 数字；不全文粘贴；可链到 logs>

## Verdict
- PASS：所有命令通过 + 关键数字 ≥ 阈值
- PASS_WITH_CONCERNS：通过但 ≥ 1 项 WARN（具体说哪条）
- FAIL：≥ 1 项 ERROR（必须列出）

## Remaining Risk
- <未覆盖的潜在问题，如 reviewer 维度 / 学术伦理 / 复现性>
```

---

## 九、与其他 SKILL 的关系

```
任意 skill 自称"完成"
    ↓
verification（本 SKILL：通用门控）
    ↓ 命令 + 输出 + 结论 三件套
真正完成 / 重新跑

paper-internal claim 真假
    ↓
claim-verification（论文 claim 专项）

style / 语言层"完成"
    ↓
writing-core + scripts/style_check.py

稿件层"完成"
    ↓
paper-quality-gate.py
```

- **平行**：claim-verification（专攻论文 claim）/ writing-core（语言层）
- **互补**：所有 SKILL 在自己的 §X.收尾验证 中**应该**调本 SKILL 的 §三 速查表
- **被引用**：paper-orchestration / writing-chapters 在 review gates 中显式 cross-reference 本 SKILL

---

## 十、为什么这很重要

从实际失败案例：
- 引用伪造导致论文撤稿
- 章节字数不达标导致返工
- 格式错误导致投稿失败
- AI 痕迹明显导致 reviewer 质疑
- "应该没问题"导致 commit 后 CI 红
- subagent 报告 DONE 实际只改了 1/5 文件

每一条都对应过去**没跑验证**而留的洞。

---

## 十一、底线

**验证没有捷径。**

运行命令 → 读取输出 → 然后才能声称结果。

这是不可协商的（与 `verification SKILL.md` 同标准、与 `data/proposals/20260428-harness-engineering-adoption.md` 的 P2 机械护栏同语义、与 `knowledge-protection.mdc v2` 同强度）。
