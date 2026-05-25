---
name: writing-core
description: >-
  Enforce de-AI-ification language rules and Markdown formatting standards
  for academic prose. Maintains banned-word lists (mechanical transitions,
  hollow emphasis phrases, hollow modifiers, subjective lead-ins), paragraph
  3-section rule (topic / supporting / closing), list-to-prose conversion,
  and three-pass quality checks (structure / language / typography). Use when
  finalising any paper section, after paper-writing produces prose, before
  paper-revision iterates, or when the user says "去AI化", "polish prose",
  "remove AI flavour", "去除AI味", "正文太机械", or asks for style audit.
  Always paired with `scripts/style_check.py` for mechanical verification.
domain: writing
triggers:
  - 去AI化
  - polish prose
  - remove AI flavour
  - 去除AI味
  - 正文太机械
  - style audit
version: "1.0.0"
compatibility:
  requires: ["python-3.9"]
# v2.2.5 Skill DAG metadata（WP1 of research-writing-skill adoption）
preconditions:
  - "Markdown 论文正文存在（用户指定路径，通常 chapters/*.md 或 drafts/paper.md）"
consumes:
  - "drafts/*.md（待检稿）"
  - "data/papers/<paper-id>/chapters/*.md（章节稿）"
produces:
  - "style_check 报告（stdout / 用户指定路径，含违规位置 + 修复模板）"
  - "去 AI 化版本的 Markdown（StrReplace 逐处替换，不 Write 覆盖）"
effects:
  - "log_skill_usage 记一条 writing-core 调用"
  - "为 paper-revision / paper-orchestration 提供语言层质量门"
failure_modes:
  - type: "banned_phrase_present"
    repair: "REBIND（按 §1 黑名单 → §3 推荐表达逐处替换；列表化场景按 §2 列表转段落 5 模式重写）"
  - type: "list_pollution"
    repair: "REBIND（正文项目符号占比 > 15% → 按 §2 列表转段落规则重写为连贯段落）"
  - type: "paragraph_unfocused"
    repair: "REBIND（段落无单一中心 → 按 §3 主题句+支撑句+收束句 3 段式重构）"
  - type: "subjective_lead_in"
    repair: "REBIND（论文正文出现『我认为』『我觉得』 → 改用『本文』『本研究』『实验结果表明』）"
downstream_skills: []
terminal: true
terminal_outputs:
  - "style_check 报告"
  - "去 AI 化版本的 Markdown"
---

# Writing-Core — 学术论文去 AI 化语言规范

> 来源：吸收 `research-writing-skill-main/skills/writing-core/SKILL.md` v3.1.0；
> 与 Academic-Agent 体系对接：作为 paper-writing 的语言层质量门，
> 与 paper-revision §Part 6 的「文笔与清晰度改进」错位互补。

## 核心原则

- **机械词必杀**：列表中的禁用词在论文正文场景**零容忍**（演讲稿、PPT、口语场景不受约束）
- **段落须有主**：每段一个中心论点；列表只在贡献点 / 操作步骤 / 参数清单时出现
- **客观语**优先：使用「本文 / 本研究 / 实验结果表明 / 数据显示」替代「我认为 / 我觉得」
- **机械验证**：写作收尾必须跑 `scripts/style_check.py`，违规位置 + 修复模板逐项呈现

---

## 何时使用

- ✅ paper-writing 产出 prose 之后（强制门）
- ✅ paper-revision 接收反馈、改完一节后（推荐）
- ✅ paper-orchestration 章节级两阶段 review 的「阶段 2 质量检查」
- ✅ 用户主动要求"去 AI 化 / 去 AI 味 / polish / 自查 prose"

- ❌ 不用于：演讲稿（paper-presentation）、Slides 文案（pptx / presentation-maker）——这些场景允许口语化转折
- ❌ 不用于：审稿意见回复（rebuttal-writer 有自己的语气规范）

---

## 一、禁用表达黑名单

### 1.1 四类零容忍

| 类型 | 禁用词 / 句 |
|------|-----------|
| **机械过渡词** | 首先、其次、然后、最后、此外、另外、接下来、综上所述、总之、值得一提的是、不仅如此、与此同时 |
| **空壳强调句** | 值得注意的是、需要指出的是、重要的是、必须强调的是、显而易见、毫无疑问、众所周知 |
| **空洞修饰词**（无数据支撑时禁）| 非常、极其、十分、相当、巨大的、显著的、大幅的 |
| **主观引导句**（论文正文禁）| 我认为、我觉得、我个人看法是、笔者认为、笔者以为 |

> 英文等价禁用：Firstly / Secondly / Furthermore / Moreover / In addition / It is worth noting that / Notably / It should be noted that / Obviously / Clearly / Significantly（无数据支撑时）

### 1.2 推荐替代

1. **用语义衔接替代模板衔接**：把「首先」改写为「初始阶段」「最早的尝试」「本文先从 X 切入」
2. **用数据 / 事实替代形容词**：把「显著提升」改写为「准确率 +12.3%」
3. **长短句交替**：等长句连续出现 ≥ 3 句时强制重构其中一句
4. **用客观主语**：「本文 / 本研究 / 实验结果表明 / 数据显示 / Table 3 显示」

### 1.3 句法与信息密度

- 列表转段落时补足主语、谓语、连接成分
- 一句话只承担一个核心动作（避免「先 A 然后 B 接着 C 同时 D」式套娃）
- 保留方法、条件、对象、数据；杜绝「很多」「较大提升」「明显改进」类模糊表述

---

## 二、Markdown 排版规范

### 2.1 正文规范

1. **正文默认不使用加粗 / 斜体**（术语首次定义可用一次加粗）
2. **段落之间必须空一行**
3. **正文优先连贯叙述**，不用项目符号堆叠观点
4. 同一段保持单一中心
5. 不把一个完整观点拆成多个短段

### 2.2 允许使用列表的场景

只在以下场景允许：
- 计划文档（`plan/*.md`）
- 检查清单
- 参数 / 配置
- 操作步骤
- 贡献点（≤ 3 条且必须由前后段落解释）

正文项目符号占比 > 15% 视为列表污染，必须重构。

### 2.3 列表转段落规则

**错误写法**：

```markdown
本研究贡献如下：
- 提出新方法
- 完成自动化流程
- 验证有效性
```

**推荐写法**：

```markdown
本研究提出了一种新方法，并将其整合为可执行的自动化流程。
实验结果显示，该方法在目标任务上具有稳定增益，验证了其可行性与应用价值。
```

---

## 三、段落构建 3 段式

一个标准段落包含：

1. **主题句** — 本段核心结论（领头一句话即可读懂全段）
2. **支撑句** — 依据 / 证据 / 解释 / 数据 / 引用
3. **收束句** — 过渡或小结，承接下段

**长度建议**：
- 中文正文：150–300 字
- 英文正文：100–200 词

**反罗列写作 5 模式**（与 evidence-driven-writing / writing-chapters 共享）：

| 段落角色 | 结构 |
|---|---|
| 背景段 | 场景约束 → 研究矛盾 → 本章承接 |
| 文献段 | 同类研究共同问题 → 代表性证据 → 尚未覆盖边界 |
| 方法段 | 输入对象 → 处理过程 → 输出形式 → 设计理由 |
| 实验段 | 评价目标 → 对照关系 → 指标含义 → 可接受结论边界 |
| 讨论段 | 结果含义 → 工程 / 学术解释 → 局限和后续验证 |

每个正文段落必须含因果、转折、承接或限定关系；除参考文献外，正文默认不出现项目符号。

---

## 四、引用与事实

<HARD-GATE>
1. 不编造文献或数据 — 本规则与 `claim-verification` SKILL 共享
2. 引用格式与全文统一
3. 含结论性表述时必须给出处或数据
</HARD-GATE>

写作中遇到「这里需要一个引用但找不到 notes/*.yaml」时，必须保留 `[CITATION NEEDED]` 标记，**不得编造**——这条规则会被下游 `claim-verification` 强制审计。

---

## 五、三轮质量检查

### 第一轮：结构检查

- [ ] 正文是否被项目符号堆叠（占比 > 15% 即违规）
- [ ] 每段是否围绕单一中心
- [ ] 章节逻辑是否连续

### 第二轮：语言检查

- [ ] 是否出现 §1.1 四类禁用词
- [ ] 是否含主观化表述（论文正文）
- [ ] 是否堆积无信息量形容词

### 第三轮：排版检查

- [ ] 是否有无意义加粗 / 斜体
- [ ] 段间是否统一空一行
- [ ] 中英文之间是否含半角空格（混排）

---

## 六、机械验证（必跑）

写作完成后必须跑：

```bash
python scripts/style_check.py <文件.md>
```

输出会列出每条违规的：
- `文件:行号`
- 违规类型（banned_phrase / list_pollution / paragraph_unfocused / subjective_lead_in）
- 修复模板（按 §1.2 / §2.3 / §3）

`--strict` 模式下任一违规非零退出，可挂到 `.githooks/pre-commit`（来自 Harness P2.2 计划）。

---

## 七、与其他 Skill 的关系

```
paper-writing (产出 prose)
    ↓ 强制调用
writing-core (语言层自检 + style_check.py)
    ↓ 通过后
paper-revision / paper-orchestration (下一步迭代或编排)
    ↓ 失败时
进入 §1 黑名单的 REBIND 修复
```

- **上游**：paper-writing / writing-chapters / paper-revision 产出的任何 prose
- **下游**：paper-revision §Part 6 文笔改进 / paper-orchestration 阶段 2 质量检查
- **平行**：claim-verification（事实层）/ scripts/style_check.py（机械层）

---

## 八、FAQ

**禁用词列表里有「首先」，但我有时确实需要列举顺序怎么办？**
→ 改写为「初始 / 早期 / 第一阶段 / 第一步」，把「顺序」转成「阶段化命名」。或在贡献点列表（≤ 3 条且段前段后有解释）里使用项目符号 `1./2./3.` 而非用「首先 / 其次」散文化。

**这套规则对英文论文同样生效吗？**
→ 是。§1.1 末尾给出英文等价词；style_check.py 同时支持中英扫描。

**我在写演讲稿，可以放过我吗？**
→ 可以。本 SKILL 仅约束论文正文场景。paper-presentation / pptx / presentation-maker 不强制本规则。

**禁用词在历史段落里发现一堆，怎么办？**
→ 跑 `python scripts/style_check.py <chapter.md> --json` 拿到位置列表，再让 LLM 按 §1.2 推荐表达批量改写；改完再跑一次 style_check.py 验证。
