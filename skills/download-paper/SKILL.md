---
name: download-paper
description: >-
  Download academic papers (PDF) into the papers/ folder with standardised naming.
  Use when the user asks to download, save, or collect papers, or when finalising
  a reading list from a literature survey. Handles arXiv PDFs and arbitrary URLs.
domain: research
triggers:
  - download paper
  - download pdf
  - 下载论文
version: "1.0.0"
---
# Download Paper Skill

## Overview

Download academic paper PDFs into `papers/` at the project root, named by a strict convention so papers are easy to browse, sort, and reference.

## Naming Convention

```
YY-机构-会议/期刊-主题[-应用领域].pdf
```

| Field | Description | Examples |
|-------|-------------|----------|
| YY | 2-digit publication year | `25`, `24`, `23` |
| 机构 | First author affiliation or well-known lab | `清华`, `DeepMind`, `MIT`, `UC Berkeley` |
| 会议/期刊 | Venue short name; use `arXiv` for preprints | `NIPS`, `ICML`, `ICLR`, `AAAI`, `ICRA`, `CoRL`, `RSS`, `RA-L`, `arXiv` |
| 主题 | Core topic; may include parenthetical qualifier | `多任务强化学习（路由选择）`, `Diffusion Policy` |
| 应用领域 | (Optional) downstream task / domain | `机械臂操作`, `导航`, `双足行走` |

**Full example:**

```
25-清华-NIPS-多任务强化学习（路由选择）-机械臂操作.pdf
24-DeepMind-ICML-World Models-机器人灵巧操作.pdf
23-UC Berkeley-CoRL-Diffusion Policy-桌面操作.pdf
```

## How to Download

Use `tools/paper_downloader.py`. Two main approaches:

### 1. Single paper (interactive)

```python
from tools.paper_downloader import download_paper, build_meta

meta = build_meta(
    year="25",
    institution="清华",
    venue="NIPS",
    topic="多任务强化学习（路由选择）",
    application="机械臂操作",
    arxiv_id="2501.12345",   # arXiv ID → auto-resolves PDF URL
)
download_paper(meta)
```

### 2. Batch download (reading list)

```python
from tools.paper_downloader import download_papers, build_meta

papers = [
    build_meta("25", "清华", "NIPS", "多任务强化学习（路由选择）", "机械臂操作",
               arxiv_id="2501.12345"),
    build_meta("24", "DeepMind", "ICML", "World Models", "灵巧操作",
               url="https://example.com/paper.pdf"),
]
download_papers(papers)
```

### 3. Direct URL download

If the paper is not on arXiv, pass a direct `url=` to `build_meta`:

```python
meta = build_meta(
    year="24", institution="Stanford", venue="ICRA",
    topic="Visual Pre-training", application="移动操作",
    url="https://some-site.com/paper.pdf",
)
download_paper(meta)
```

## Workflow: From Survey to Download

1. **Search** — use `tools/arxiv.py` or `tools/semantic_scholar.py` to find candidate papers.
2. **User confirms** — present candidates and let the user select which papers to read.
3. **Fill metadata** — for each confirmed paper, construct a `PaperMeta` with:
   - `year`: extract from paper's `published` date
   - `institution`: look up first author affiliation (or guess from well-known labs)
   - `venue`: publication venue; use `arXiv` for preprints
   - `topic` / `application`: summarise from the title/abstract
   - `arxiv_id` or `url`: the download source
4. **Download** — call `download_papers(paper_list)` to batch-save them.
5. **Report** — print a table showing filename, size, and status for each paper.

## Where Files Go

```
Academic-Agent/
└── papers/
    ├── 25-清华-NIPS-多任务强化学习（路由选择）-机械臂操作.pdf
    ├── 24-DeepMind-ICML-World Models-灵巧操作.pdf
    └── ...
```

## Tips

- Keep filenames concise but descriptive — ideally < 80 characters.
- Use Chinese for Chinese-authored topics when the user communicates in Chinese.
- When unsure about venue, default to `arXiv`.
- For non-arXiv papers (ACM, IEEE, etc.), you may need the user to provide a direct PDF URL since those often require authentication.
- arXiv requests are rate-limited to 3 seconds apart automatically.
