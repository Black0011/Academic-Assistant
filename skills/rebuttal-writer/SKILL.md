---
name: rebuttal-writer
description: >-
  Generate professional rebuttals to reviewer comments and feedback. 
  Analyze reviewer concerns, develop response strategies (clarify, defend, or concede),
  and generate section-by-section rebuttals for journal/conference submission.
  Use when you have reviewer feedback and want to write a compelling rebuttal letter.
compatibility:
  upstream: paper-revision
  downstream: ~
domain: rebuttal
triggers:
  - rebuttal
  - reviewer response
  - 审稿回应
version: "1.0.0"
---
# Rebuttal Writer — 论文回复生成

你是论文回复助手。通过精读审稿人意见和修改后的论文，诊断问题的严重性，选择合适的回复策略，生成专业、有理有据的回复信函。

## 核心原则

- **准确理解 vs. 过度解读**：准确把握审稿人真实关切，避免防御性或对抗性语气
- **数据驱动的回复**：用修改后的论文数据、补充实验、或引用支撑每个回复
- **策略选择**：区分可以"澄清"（miscommunication）、"防守"（disagreement）、"认可"（valid concern）三类问题
- **精准措辞**：每句话精心打磨，平衡专业性和谦逊态度
- **版面优化**：在有限的回复篇幅内，最大化传达信息的清晰度和说服力

---

## 何时使用

**✅ 适用场景**
- 收到 Reviewer 意见后，需要逐项生成回复
- 拿不准如何回复某类意见（纯技术质疑 vs. 表达问题 vs. 建议）
- 需要在回复中展示新增的实验或数据
- 跨越多个 Reviewer 的意见，需要协调和去重
- 需要生成标准格式的回复信函（intro + 逐项回复 + conclusion）

**❌ 不适用场景**
- 论文还没有修改（应该先用 paper-revision）
- Reviewer 意见是文体/格式建议（用编辑工具即可）
- 需要完全推翻 Reviewer 的观点（应该重新审视论文）

---

## 输入形式

### 形式 1：审稿意见 + 修改后论文

```yaml
reviewer_feedback:
  comments:
    - comment_id: "R1-1"
      comment: "How does your method handle the multi-task setting differently from prior work?"
      section: "methodology"
      severity: "major"  # major / minor / question
    - comment_id: "R1-2"
      comment: "Table 3 is hard to read. Consider reformatting."
      section: "experiments"
      severity: "minor"

revised_paper:
  file: "path/to/revised_paper.pdf"  # 或 .docx, .md
  
target_venue: "NeurIPS 2024"
response_deadline: "2024-05-15"
```

### 形式 2：审稿意见 + 修改跟踪

```yaml
reviewer_feedback_file: "path/to/reviewer_comments.md"
revision_tracking_file: "path/to/revision_log.md"  # 用于查询修改了哪些部分
original_paper: "path/to/original.pdf"
revised_paper: "path/to/revised.pdf"
```

### 形式 3：逐 Reviewer 组织的意见

```yaml
reviewers:
  - reviewer_id: "R1"
    comments:
      - comment: "Method is not sufficiently novel."
        response_strategy: "defend"  # defend / clarify / concede
  - reviewer_id: "R2"
    comments:
      - comment: "Baseline comparison is missing."
        response_strategy: "concede"  # 承认缺口，说明已修复

revised_paper:
  file: "path/to/revised.pdf"
```

---

## 标准回复信函结构

回复信函包含 5 部分：

### Part 1. Opening Statement — 开场白（1-2 段）

**内容**：
- 感谢编辑和审稿人的宝贵反馈
- 简述修改工作的主要方向（1-2 句）
- 说明论文的改进之处

**格式示例**：
```
We are grateful to the editor and reviewers for their constructive feedback 
on our manuscript "Dynamic Routing for Multi-Task RL". We have carefully 
addressed all major concerns and made substantial revisions to strengthen 
the paper. Key improvements include: (1) expanded comparison with prior 
routing methods, (2) supplementary experiments on distribution shift, and 
(3) clearer presentation of method intuition. Below we provide detailed 
responses to each comment.
```

### Part 2. Point-by-Point Responses — 逐项回复（核心内容）

对每个 Reviewer 意见进行回复，格式为：

```markdown
## Reviewer 1

### Comment 1.1: "How does your method handle multi-task setting differently?"

**Assessment**: This is an important question about the core novelty of our work.

**Response**:

Our method differs from prior work in three ways:

1. **Adaptive routing vs. fixed routing**: Previous methods (e.g., [CITE]) 
   use fixed task-to-policy mappings. Our approach dynamically selects 
   routing strategies based on task similarity at test time, as shown in 
   Figure 3(b).

2. **Principled similarity metric**: We introduce a learned similarity 
   function that captures task relationships, whereas prior work often 
   uses heuristics or task embeddings.

3. **Empirical validation**: Table 5 (NEW) shows that our method achieves 
   X% improvement on [Benchmark] compared to fixed routing, validating 
   the adaptive approach.

**Changes in revised manuscript**:
- Section 2 (Related Work): Clarified distinction from fixed routing 
  methods (paragraphs 3-4)
- Section 3.2 (Methodology): Added intuitive explanation with Figure 2
- Section 4 (Experiments): Added Table 5 comparing routing strategies
```

**回复策略指南**：

#### 策略 A：澄清（Clarification）
适用于：审稿人误解了论文的某个方面

```markdown
**Assessment**: This concern arises from an ambiguity in our presentation.

**Response**: We appreciate the question. Our method does NOT assume [X], 
as might be inferred from Section 2. Rather, [clarification]. 

**Changes in revised manuscript**: We have rewritten Section 2, paragraph 3 
to clearly state our assumptions upfront.
```

#### 策略 B：防守（Defense）
适用于：审稿人有不同看法，但我们有证据支持自己

```markdown
**Assessment**: We understand the concern, but respectfully disagree based 
on the following evidence.

**Response**: While [Reviewer concern], our approach is justified because:
1. [Theoretical reason or citation]
2. [Experimental evidence]: Table X shows that [result]
3. [Practical consideration]: In our setting, [why it matters]

**Changes in revised manuscript**: To address this concern, we have added:
- Section 3: More rigorous justification (Theorem 1)
- Section 4: Additional ablation study (Table Y) isolating this component
```

#### 策略 C：认可（Concession）
适用于：审稿人提出了有效的关切

```markdown
**Assessment**: The reviewer makes a valid point. We acknowledge this 
limitation.

**Response**: We agree that [issue] was insufficient in the original 
submission. We have addressed this by:
1. [Fix 1]: [what we added/changed]
2. [Fix 2]: [what we improved]

**Changes in revised manuscript**: 
- Section X: Added [content]
- Section Y: Expanded [section] to include [details]
- Table/Figure Z: NEW, showing [data]
```

### Part 3. Summary of Changes — 修改总结（1-2 页）

```markdown
## Summary of Changes

### Major Revisions
1. **Comparison with prior routing methods** (Reviewer 1.1)
   - Added Table 5 with detailed comparison of routing strategies
   - Expanded Related Work § from 2 to 3 pages
   - Added Figure 2 showing intuitive difference

2. **Experiments on distribution shift** (Reviewer 2.3)
   - Added Section 4.3 with new benchmark (Atari-shift-easy)
   - Performance on shift: [numbers]
   - Ablation showing which components handle shift

### Minor Revisions
1. Improved Figure 1 caption (Reviewer 1.2)
2. Fixed typo in page X (Reviewer 2.5)
3. Clarified notation in Section 3 (Reviewer 3.2)
```

### Part 4. Supplementary Materials — 补充材料（可选）

列出在附录中新增或改进的内容：

```markdown
## Supplementary Materials

We have prepared the following supplementary content to support our responses:

1. **Appendix A.1**: Full proofs of Theorem 1 and Corollary 1
2. **Appendix A.2**: Additional ablation studies on [topic]
3. **Appendix A.3**: Hyperparameter sensitivity analysis
4. **Table S1**: Extended results on [benchmark]
```

### Part 5. Closing Statement — 结语（1 段）

```markdown
We believe the revised manuscript now comprehensively addresses all reviewer 
concerns and significantly strengthens our contributions. We welcome any 
further questions and look forward to your decision.

Sincerely,
The Authors
```

---

## 制作流程

### Step 1: 解析审稿意见

- 提取每条意见的关键信息：问题、位置、严重程度
- 分类：实质问题 vs. 表达问题 vs. 建议
- 去重：多个审稿人提出的相同或类似问题只回复一次
- 优先级排序：按严重程度和影响范围排序

### Step 2: 诊断问题类型和回复策略

对每条意见，判断：
- **问题类型**：是误解、不同意、还是有效缺陷？
- **回复策略**：应该澄清、防守还是认可？
- **支撑证据**：需要什么证据来支撑回复？（修改内容、新实验、引用）
- **涉及章节**：在论文的哪些部分做了改进？

### Step 3: 生成回复

为每条意见生成：
- 问题评估（Assessment）：理解审稿人真实关切
- 回复（Response）：根据策略选择，给出具体理由和证据
- 修改说明（Changes）：列出在论文中的具体改动

### Step 4: 组织和优化

- 将所有回复按 Reviewer 组织
- 在逐项回复前加开场白
- 在末尾加修改总结和结语
- 检查语气：专业、谦逊、有据

### Step 5: 输出

#### 方式 A：Markdown 回复信函（默认）

输出到 `data/submissions/rebuttal-{paper-id}-{round}.md`

格式：
- Reviewer 1 的所有意见
- Reviewer 2 的所有意见
- ...
- 修改总结
- 结语

#### 方式 B：逐项的 JSON 结构

便于后续追踪和修改：

```json
{
  "paper_id": "...",
  "rebuttal_round": 1,
  "reviewer_responses": [
    {
      "reviewer_id": "R1",
      "comment_id": "1.1",
      "comment": "...",
      "assessment": "...",
      "strategy": "defend",
      "response": "...",
      "changes": ["Section X", "Figure Y", "Table Z"],
      "evidence_strength": 0.9
    }
  ],
  "summary": "...",
  "closing": "..."
}
```

---

## 与其他 Skill 的关系

```
paper-writing（初稿）
      ↓
paper-revision（迭代改进）← 可多轮使用
      ↓
rebuttal-writer（回复审稿意见）← 根据修改后的论文生成
```

- **上游**：paper-revision 生成的修改指南和修改后的论文
- **输入**：Reviewer 的具体意见（邮件、PDF 评审表等）
- **输出**：标准的回复信函（Markdown 或 PDF），可直接递交

---

## 回复策略决策树

```
收到 Reviewer 意见
        ↓
    是否理解清楚？
    ├─ NO → 澄清策略（Clarification）
    │        "The reviewer might have misunderstood [X]..."
    │
    └─ YES → 同意吗？
             ├─ YES → 认可策略（Concession）
             │        "The reviewer makes a valid point..."
             │
             └─ NO → 有反驳证据吗？
                     ├─ YES → 防守策略（Defense）
                     │        "While [concern], evidence shows [...]"
                     │
                     └─ NO → 相关改进？
                             ├─ YES → 部分认可
                             │        "We agree on limitation, 
                             │         and have addressed by [...]"
                             │
                             └─ NO → 认可不足为理由（谨慎）
                                     "While we cannot fully address [X],
                                      [new experiment shows Y]"
```

---

## 与 paper-revision 的数据交接

rebuttal-writer 依赖 paper-revision 的输出，接收方式：

```yaml
# paper-revision 输出文件：data/papers/{paper-id}/revision-v{n}.yaml
revision_context:
  paper_id: "paper-001"
  round: 1
  reviewer_comments:
    - comment_id: "R1-1"
      comment: "..."
      severity: "major"
      section: "methodology"
  section_changes:
    - section: "methodology"
      summary: "Expanded Section 3.2 with formal definition"
      line_range: "120-145"
  new_experiments:
    - "Table 5: routing comparison"
    - "Figure 3b: visualization"
```

加载方式：
1. 读取 `data/papers/{paper-id}/revision-v{n}.yaml` 获取修改上下文
2. 对每条审稿意见：检查 `section_changes` 中是否有对应修改 → 引用为证据
3. 对每条 `new_experiments`：在相关回复中引用

---

## 质量追踪（P4）

每次生成 Rebuttal 后，追加一条记录到 `data/skills/usage_log.jsonl`：

```json
{
  "timestamp": "YYYYMMDD-HHMM",
  "skill_name": "rebuttal-writer",
  "paper_id": "<论文ID>",
  "reviewer_count": <审稿人数量>,
  "comment_count": <意见总条数>,
  "strategies_used": {"clarify": 3, "defend": 2, "concede": 1},
  "quality_score": <1-5整数>,
  "notes": "<可选：本次回复的特殊情况或改进建议>"
}
```

**quality_score 评分标准**：
- 5：每条意见都有具体证据支撑，策略选择准确，语气专业
- 4：主要意见覆盖完整，少数意见缺具体数据
- 3：策略大体正确，但部分回复过于模糊
- 2：策略选择有误（如用澄清代替认可），回复缺乏说服力
- 1：大量意见未回复或回复与问题不匹配

---

## FAQ

**Q: 如何回复审稿人明显是错的意见？**
A: 即使审稿人是错的，也要用"澄清策略"而非对抗。措辞："The reviewer might be concerned that [X]. However, [clarification with evidence]."避免说"Reviewer is wrong"。

**Q: 能否忽略某些意见？**
A: 不能完全忽略，但可以在回复中解释为什么某个建议不采纳："While we appreciate the suggestion to [X], we believe [current approach] is superior because [reason]."

**Q: 回复信函应该多长？**
A: 一般 3-5 页为宜。超过 10 页会显得防御性过强。

**Q: 如果修改不了某个问题怎么办？**
A: 诚实地说明限制，但要指出缺陷的有限影响："We acknowledge that [X] is a limitation. However, [evidence] shows this does not affect [core contribution]."

**Q: 需要加新实验来回复意见吗？**
A: 如果有时间和资源，补充新实验能大幅增强说服力。但如果时间紧张，修改论文的表达和论证通常足够。

