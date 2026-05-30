---
name: literature-search
description: >-
  Multi-source academic paper search with query optimization, deduplication, and
  snowball expansion. Use when searching for papers on a topic, building a reading
  list, or expanding coverage from seed papers.
domain: research
triggers:
  - search papers
  - 文献检索
  - find related work
version: "1.0.0"
---
# Literature Search — 文献检索策略

## 检索流程

### 1. 构建检索式

从用户的研究问题出发，生成多组检索关键词：

```
原始问题: "多任务强化学习在机器人操作中的应用"

拆解为检索组合:
  - arXiv: ti:"multi-task reinforcement learning" AND abs:robot manipulation
  - Semantic Scholar: "multi-task RL" robot manipulation
  - 变体: "multi-objective RL" + "robotic grasping"
  - 中文变体: 多任务强化学习 机械臂
```

**关键词扩展策略**：
- 同义词替换：reinforcement learning ↔ RL, robot ↔ robotic
- 上位词/下位词：manipulation → grasping / pushing / assembly
- 缩写展开：MTRL → Multi-Task Reinforcement Learning
- 领域术语：如果搜"diffusion policy"，也搜"score-based policy"

### 2. 多源检索

按以下顺序检索，每个源的优势不同：

| 数据源 | 优势 | 用法 | 工具 |
|--------|------|------|------|
| **arXiv** | 最新预印本，开放获取 | 搜最近 1-2 年的工作 | `tools/arxiv.py` |
| **Semantic Scholar** | 引用计数，关联论文推荐 | 找高引经典 + 相关论文 | `tools/semantic_scholar.py` |
| **种子论文引用** | 高精度，顺藤摸瓜 | 从已知好论文出发扩展 | Semantic Scholar references API |

**每个源至少检索 10-20 篇**，除非主题极其狭窄。

### 3. 去重与合并

- 按 arXiv ID 去重（同一篇论文可能同时出现在 arXiv 和 Semantic Scholar）
- 按标题模糊匹配去重（处理标题略有差异的情况）
- 合并元数据：用 Semantic Scholar 的引用数补充 arXiv 的结果

### 4. 初筛排序

对合并后的结果排序，优先级权重：

```
score = 0.4 * relevance + 0.3 * recency + 0.3 * impact

relevance: 标题/摘要与查询的语义匹配度
recency:   发表时间（越新越好，线性衰减）
impact:    log(citation_count + 1) 归一化
```

### 5. 滚雪球扩展

从初筛后的 Top-5 论文出发：

- **后向滚雪球**：查看它们的参考文献（References），找到奠基性工作
- **前向滚雪球**：查看引用它们的论文（Cited By），找到最新进展
- 对滚雪球发现的论文重复步骤 3-4

**终止条件**：当新发现的论文与已有列表重叠率 > 70% 时，该方向的检索饱和。

## 输出格式

检索完成后输出结构化的论文列表：

```yaml
search_results:
  query: "原始查询"
  total_found: 45
  after_dedup: 32
  top_papers:
    - arxiv_id: "2501.12345"
      title: "..."
      authors: ["..."]
      year: 2025
      venue: "ICML"
      citations: 42
      relevance: "high"
      source: "arxiv+semantic_scholar"
      abstract_snippet: "前 200 字..."
```

## 常见问题

**搜不到论文**：尝试更宽泛的关键词；检查拼写；用不同的术语变体。

**结果太多（>100 篇）**：加时间限制（最近 3 年）；加限定词（特定方法/应用）；提高初筛阈值。

**非英文论文**：arXiv 主要是英文；如需中文论文，考虑 CNKI / Google Scholar 补充。

## 使用日志（P4）

每次检索完成后，追加一条记录到 `data/skills/usage_log.jsonl`：

```json
{
  "timestamp": "YYYYMMDD-HHMM",
  "skill_name": "literature-search",
  "trigger_query": "<本次主要检索关键词>",
  "papers_found": <去重后论文总数>,
  "quality_score": <1-5整数，1=很差/基本没相关，5=精准命中>,
  "notes": "<可选：本次检索遗漏的方向、下次改进的关键词建议>"
}
```

**quality_score 评分标准**：
- 5：Top-5 论文全部高度相关，覆盖核心方向
- 4：Top-5 中有 3-4 篇相关，方向基本正确
- 3：Top-5 中有 2-3 篇相关，部分偏离
- 2：Top-5 中仅 1-2 篇相关，关键词需调整
- 1：基本无相关结果，需换方向
