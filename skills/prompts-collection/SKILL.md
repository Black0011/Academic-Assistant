---
name: prompts-collection
description: >-
  Reusable Role-Task-Constraints-Output prompt templates for academic
  translation, polishing, de-AI-ification, abstract refinement, expand /
  compress, figure / table caption generation, and final-pass logic check.
  Always plain-text Markdown templates (not auto-applied) — designed to be
  copy-pasted into a fresh chat with the LLM. Use when the user says
  "翻译 / polish / 润色 / 去 AI 化 prompt / 摘要打磨 / 扩写 / 缩写 /
  生成 caption / 终稿逻辑检查 / give me a prompt for ...", or when
  paper-revision § Part 6 needs a concrete prompt to dispatch.
domain: meta
triggers:
  - polish prompt
  - 翻译 prompt
  - 润色 prompt
  - 去 AI 化 prompt
  - 摘要打磨 prompt
  - give me a prompt
version: "1.0.0"
compatibility:
  requires: ["python-3.9"]
# v2.2.5 Skill DAG metadata（WP7 of research-writing-skill adoption）
preconditions:
  - "用户提交一段中 / 英文论文文本（待译 / 待润色 / 待去 AI 化）"
consumes:
  - "用户文本（chat 输入或文件路径）"
produces:
  - "可直接粘贴到新 chat 的完整 prompt（含 Role / Task / Constraints / Output 四段）"
effects:
  - "log_skill_usage 记一条 prompts-collection 调用"
failure_modes:
  - type: "wrong_template_picked"
    repair: "REBIND（按 §一 路由表重选模板；中→英 / 英→中 / 同语种润色 / 去 AI 化 是 4 个不同入口）"
  - type: "constraints_dropped"
    repair: "REBIND（必须保留 'Constraints' 段全部条款 — 否则模板效果不可控）"
  - type: "tex_or_md_mismatch"
    repair: "REBIND（输入是 LaTeX 时用 LaTeX 模板；输入是 Markdown 时用对应中英 prose 模板）"
downstream_skills: []
terminal: true
terminal_outputs:
  - "复用型 prompt 文本"
---

# Prompts-Collection — 学术写作复用 prompt 库

> 来源：吸收 `research-writing-skill-main/skills/prompts-collection/SKILL.md` v3.1.0；
> 与 Academic-Agent 体系对接：作为 `paper-revision §Part 6 文笔与清晰度改进` 的执行层。
> 本 SKILL **只输出 prompt 文本**，不自动改 chapter 文件——所有应用动作由用户/LLM 自行决定。

---

## 一、何时使用 / 何时不用

✅ 用：
- 用户要求"翻译 / polish / 润色 / 去 AI 化"
- paper-revision 诊断出某段需要重写但具体 prompt 用什么没定
- 写图标题 / 表标题
- 终稿逻辑检查
- writing-chapters 在 chapter prose 完成后做语言层迭代

❌ 不用：
- 写正文段落（走 paper-writing / writing-chapters）
- 数据级 audit（走 claim-verification）
- 实验设计（走 experiment-results-planning）

### 1.1 任务路由表

| 用户场景 | 入口模板（§编号）|
|---|---|
| 中文段落 → 英文 LaTeX | §二.1 中→英学术翻译 |
| 英文 LaTeX → 中文阅读理解 | §二.2 英→中快速理解 |
| 已有英文 LaTeX，要润色 | §三.1 英文论文润色 |
| 已有中文段落，要润色 | §三.2 中文论文润色 |
| 英文 LaTeX，AI 味重 | §四.1 去 AI 化（英文）|
| 中文段落，AI 味重 | §四.3 去 AI 化（中文）|
| 字数微缩 | §五.1 缩写 |
| 字数微扩 | §五.2 扩写 |
| 摘要打磨 | §六 |
| 终稿逻辑检查 | §七 |
| 生成 figure/table caption | §八 |

---

## 二、翻译类

### 2.1 中文 → 英文（学术翻译）

```markdown
# Role
你是一位兼具顶尖科研写作专家与资深会议审稿人双重身份的助手。

# Task
请将我提供的【中文草稿】翻译并润色为【英文学术论文片段】。

# Constraints
1. 不使用加粗、斜体或引号
2. 逻辑严谨，用词准确，使用常见单词
3. 不使用 \item 列表，使用连贯段落
4. 去除"AI 味"，行文自然
5. 保留原文 LaTeX 命令（\cite{} / \ref{} / \section{} 等）

# Output
- Part 1 [LaTeX]：翻译后的英文
- Part 2 [Translation]：对应中文直译（用于回译核对）

# Input
<paste 中文草稿 here>
```

### 2.2 英文 → 中文（快速理解）

```markdown
# Role
你是计算机科学领域的资深学术翻译官。

# Task
请将【英文 LaTeX 代码片段】翻译为流畅、易读的【中文文本】。

# Constraints
1. 删除所有 \cite{}、\ref{}、\eqref{} 等 LaTeX 命令
2. 严格直译，不进行润色
3. 只输出纯中文文本段落

# Input
<paste 英文 LaTeX here>
```

---

## 三、润色类

### 3.1 英文论文润色

```markdown
# Role
你是计算机科学领域的资深学术编辑。

# Task
请对【英文 LaTeX 代码片段】进行深度润色与重写。

# Constraints
1. 调整句式结构，增强正式性与逻辑连贯性
2. 彻底修正所有语法错误
3. 使用标准学术书面语，禁用缩写形式（don't / can't / it's 等）
4. 保留原文 LaTeX 命令（\cite{} / \ref{} / \section{} 等）

# Output
- Part 1 [LaTeX]：润色后的英文
- Part 2 [Translation]：对应中文直译
- Part 3 [Modification Log]：修改说明（按编号列出每处改动）

# Input
<paste 英文 LaTeX here>
```

### 3.2 中文论文润色

```markdown
# Role
你是专注于计算机科学领域的资深中文学术编辑。

# Task
请对【中文论文段落】进行专业审视与润色。

# Constraints
1. 仅修正口语化表达、语法错误、逻辑断层
2. 原文已清晰则保留原样
3. 使用中文全角标点
4. 不改变原文的核心论点

# Output
- Part 1 [Refined Text]：重写后的中文段落
- Part 2 [Review Comments]：修改说明（按编号列出每处改动）

# Input
<paste 中文段落 here>
```

---

## 四、去 AI 化

### 4.1 去 AI 化（英文）

```markdown
# Role
你是计算机科学领域的资深学术编辑，专注于提升论文自然度。

# Task
请对【英文 LaTeX 代码片段】进行"去 AI 化"重写。

# Constraints
1. 避免使用被滥用的词汇：
   leverage / delve into / tapestry / underscore / pivotal / nuanced
   foster / elucidate / intricate / paramount
2. 将 \item 内容转化为连贯段落
3. 删除机械连接词：
   "First and foremost" / "Furthermore" / "Moreover" / "It is worth noting that"
4. 原文已自然则保留
5. 保留 LaTeX 命令

# Output
- Part 1 [LaTeX]：重写后的代码
- Part 2 [Translation]：对应中文直译
- Part 3 [Modification Log]：调整说明，或"[检测通过]"

# Input
<paste 英文 LaTeX here>
```

### 4.2 AI 味浓厚词汇表（避免使用 → 推荐替换）

| 避免 | 推荐 |
|---|---|
| leverage | use, employ |
| delve into | investigate, examine |
| tapestry | context, framework |
| underscore | highlight, show |
| pivotal | important, key |
| nuanced | detailed, subtle |
| foster | encourage, support |
| elucidate | explain, clarify |
| intricate | complex, detailed |
| paramount | important, critical |
| It is worth noting that | （删除）/ Notably, |
| Firstly, ... Secondly, | （重组为段落式承接）|
| In summary | （删除句首；让结句自身收束）|

### 4.3 去 AI 化（中文）

```markdown
# Role
你是一位中文科研写作编辑。

# Task
请改写【中文论文段落或草稿】，去除 AI 腔。

# Constraints
1. 使用连续段落，不使用项目符号
2. 不使用加粗、斜体
3. 避免"首先、其次、最后、此外、另外"等连接词
4. 避免"值得注意的是"等空壳句式
5. 保持克制语气，不写主观判断
6. 用"本文 / 本研究 / 实验结果表明"代替"我认为 / 我觉得"

# Output
- Part 1 [Refined Text]：改写后的中文正文
- Part 2 [Modification Log]：修改说明，或"[检测通过]"

# Input
<paste 中文段落 here>
```

---

## 五、扩写与缩写

### 5.1 缩写（压缩字数）

```markdown
# Task
请将【英文 LaTeX 代码片段】进行微幅缩减（减少约 5–15 个单词）。

# Constraints
1. 保留所有核心信息（claim / evidence / method condition / limitation）
2. 句法压缩：从句转短语、被动转主动
3. 剔除冗余填充词（actually / basically / quite / very）

# Output
- Part 1 [LaTeX]：缩减后的代码
- Part 2 [Translation]：对应中文直译
- Part 3 [Modification Log]：调整说明

# Input
<paste 英文 LaTeX here>
```

### 5.2 扩写（增加内容）

```markdown
# Task
请将【英文 LaTeX 代码片段】进行微幅扩写（增加约 5–15 个单词）。

# Constraints
1. 不添加无意义形容词
2. 挖掘隐含的结论、前提或因果关系
3. 增加必要的连接词，明确句间关系

# Output
- Part 1 [LaTeX]：扩写后的代码
- Part 2 [Translation]：对应中文直译
- Part 3 [Modification Log]：调整说明

# Input
<paste 英文 LaTeX here>
```

---

## 六、摘要打磨

```markdown
# Role
你是顶刊摘要编辑（CS / NLP / RL 同一标准）。

# Task
请把【已写好的论文摘要】打磨到顶会 / 顶刊提交标准。

# Constraints
1. 结构：背景（1–2 句）→ 方法（2–3 句）→ 主结果（1–2 句，含具体数字）→ 一句结论
2. 中文 300–500 字 / 英文 200–300 词
3. 不含引用、不含图表、不含 \cite{}
4. 数字表达："+12.3%" 而不是"显著提升"
5. 删除空壳词：notably / it is worth noting that / significantly（无数据时）

# Output
- Part 1 [Polished Abstract]：打磨后的摘要
- Part 2 [Diagnostic]：列出原稿被改的 3–5 处主要问题

# Input
<paste 摘要 here>
```

---

## 七、终稿逻辑检查

```markdown
# Task
请对【英文 LaTeX 代码片段】进行最后的一致性与逻辑核对。

# Constraints
1. 预设草稿质量较高，不做润色，只做逻辑审计
2. 仅报告致命逻辑、术语不一致、严重语病
3. 忽略"可改可不改"的问题
4. 必须给出位置定位（行号 / 节号）

# Output
- 无问题：[检测通过，无实质性问题]
- 有问题：中文分点简要指出（位置 + 现象 + 影响）

# Input
<paste 英文 LaTeX here>
```

---

## 八、Figure / Table Caption 生成

### 8.1 Figure Caption

```markdown
# Task
请将【中文描述】转化为【英文图标题】。

# Constraints
1. 名词性短语用 Title Case；完整句子用 Sentence case
2. 去除"The figure shows / We present"等冗余开头
3. 只输出标题文本，不含"Figure 1:"前缀
4. 描述图衡量了什么，**不是**作者希望它证明什么

# Input
<paste 中文描述 here>
```

### 8.2 Table Caption

```markdown
# Task
请将【中文描述】转化为【英文表标题】。

# Constraints
1. 推荐起手词：Comparison with / Ablation study on / Results on
2. 避免：showcase / depict（改用 show / compare / present）
3. 不含"Table 1:"前缀

# Input
<paste 中文描述 here>
```

---

## 九、与其他 SKILL 的关系

```
paper-revision（诊断"哪里要改"）
    ↓ 调
prompts-collection（本 SKILL：给一个具体 prompt）
    ↓ 用户复制粘贴到新 chat
LLM 执行重写
    ↓ 输出
回到 paper-revision 应用 diff / 写入章节文件
```

- **平行**：writing-core（机械语言规则）/ paper-revision（章节级修改诊断）
- **下游**：用户 / LLM 手动执行；本 SKILL 不直接改文件

---

## 十、使用建议

1. **复制即用**：模板可直接复制使用，但不要省略 Constraints 段
2. **按需选择**：先按 §1.1 路由表选模板，避免误用
3. **保持完整**：4 段（Role / Task / Constraints / Output）不能裁
4. **替换 `<paste ... here>`**：把示例占位替换为实际内容
5. **核对回译**：英文翻译类模板默认输出"对应中文直译"，用于人工核对
