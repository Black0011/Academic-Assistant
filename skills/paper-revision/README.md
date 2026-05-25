# Paper Revision Skill — Implementation Complete

## Overview

The **paper-revision** skill provides comprehensive guidance for analyzing and revising research papers. It implements a 7-part revision framework that transforms draft papers into polished submissions.

## Components Implemented

### 1. **SKILL.md** (Complete)
- Comprehensive skill description with 7-part revision framework
- Entry points: YAML input formats, markdown/JSON output
- Integration with upstream (paper-writing) and downstream (rebuttal-writer) skills

### 2. **Core Data Classes** (`scripts/revision_analyzer.py`)
- `RevisionProblem`: Individual problems with before/after suggestions
- `SectionAnalysis`: Per-section analysis with problems and recommendations
- `OverallAssessment`: Paper-level assessment with strengths and gaps
- `RevisionGuidance`: Complete revision guidance combining all parts
- `RevisionAnalyzer`: Main API for generating example guidance

**Status**: ✅ Fully functional with dataclass serialization (to_dict, to_markdown)

### 3. **Paper Revision Engine** (`paper_revision_impl.py`)
- `PaperRevisionEngine`: Main engine for paper analysis
- `RevisionRequest`: Request dataclass for paper revisions
- Methods for:
  - Loading draft papers (PDF, DOCX, MD)
  - Analyzing draft structure
  - Generating revision guidance (7 parts)
  - Outputting as Markdown or JSON

**Status**: ✅ Core implementation complete

### 4. **LLM-Powered Analyzer** (`llm_revision_analyzer.py`)
- `LLMRevisionAnalyzer`: Uses Claude/GPT-4 to analyze papers
- Supports both Anthropic and OpenAI backends
- Methods for:
  - Overall assessment generation
  - Section-by-section analysis
  - Specific edit suggestions
  - Structural recommendations
  - Evidence gap identification
  - Writing improvement suggestions
  - Revision checklist generation

**Status**: ✅ Framework complete (LLM calls need API keys to run)

### 5. **Reference Guidelines** (`references/revision_guidelines.md`)
- Part A: General Revision Principles
- Part B: Section-Specific Revision Guide (Introduction, Related Work, Methodology, Experiments, Discussion)
- Part C: Cross-Cutting Issues (Evidence, Figures/Tables, Consistency)
- Part D: Writing Quality Improvements
- Part E: Revision Workflow

**Status**: ✅ Complete with 450+ lines of actionable guidance

### 6. **Evaluation Cases** (`evals/evals.json`)
Five comprehensive test cases covering:
1. Analyzing draft paper and identifying P1 problems
2. Generating section-by-section revision guidance with before/after examples
3. Analyzing evidence gaps and citation needs
4. Providing writing quality improvements
5. Generating prioritized revision checklist

**Status**: ✅ 5 evaluation cases well-defined

### 7. **Integration Tests** (`test_integration.py`)
Comprehensive test suite verifying:
- Dataclass functionality (creation, serialization, markdown generation)
- PaperRevisionEngine instantiation
- Example markdown generation
- Reference guidelines completeness
- Evaluation case schema validation

**Status**: ✅ All tests passing

### 8. **Configuration Loader** (`config/loader.py`)
- Loads configuration from YAML files
- Provides dot-notation key access
- Supports fallback defaults

**Status**: ✅ Complete

## File Structure

```
.cursor/skills/paper-revision/
├── SKILL.md                          # Main skill description
├── README.md                         # This file
├── paper_revision_impl.py            # Core engine implementation
├── llm_revision_analyzer.py          # LLM-powered analyzer
├── scripts/
│   └── revision_analyzer.py          # Dataclasses and core types
├── references/
│   └── revision_guidelines.md        # Comprehensive guidelines
├── evals/
│   └── evals.json                    # Evaluation test cases
├── test_integration.py               # Integration test suite
└── example_revision_guidance.md      # Example output
```

## Usage

### Basic Usage

```python
from paper_revision_impl import PaperRevisionEngine, RevisionRequest

# Initialize engine
engine = PaperRevisionEngine()

# Create request
request = RevisionRequest(
    draft_file="my_paper.pdf",
    user_feedback="Improve clarity and add more experiments"
)

# Generate guidance
guidance = engine.generate_revision_guidance(request)

# Output as markdown
md = engine.output_markdown(guidance, "revision_guidance.md")
```

### Using LLM-Powered Analysis

```python
from llm_revision_analyzer import LLMRevisionAnalyzer
import os

# Requires ANTHROPIC_API_KEY or OPENAI_API_KEY env var
analyzer = LLMRevisionAnalyzer(backend="claude")

paper_text = open("paper.txt").read()

result = analyzer.analyze_paper(
    paper_text,
    title="My Research Paper",
    user_feedback="Too long and unclear methodology"
)
```

### CLI Usage

```bash
# Generate revision guidance
python3 paper_revision_impl.py my_draft.pdf --feedback "Improve clarity"

# With LLM analysis
python3 llm_revision_analyzer.py extracted_paper.txt --backend claude --title "My Paper"
```

## 7-Part Revision Framework

The skill generates comprehensive revision guidance across 7 parts:

### 1. **Overall Assessment** (1-2 pages)
- **Strengths**: 3+ positive aspects
- **Main Problems**: Priority-ordered issues
- **Improvement Potential**: Achievable target quality
- **Time Estimate**: Hours to complete revisions

### 2. **Section-by-Section Analysis** (3-5 pages)
For each major section:
- Current state assessment
- 2-4 specific problems identified
- Structural recommendations
- Quality score (1-10)
- Improvement potential (1-10)

### 3. **Specific Edits** (2-4 pages)
For each problem:
- Original text excerpt
- Suggested revision
- Explanation of why it helps
- Expected impact

### 4. **Structural Recommendations** (1-2 pages)
- Section reordering suggestions
- Merging/splitting guidance
- Organization improvements
- Missing sections

### 5. **Evidence & Citation Gaps** (1-2 pages)
For each gap:
- Location in paper
- Claim requiring support
- Missing evidence type
- How to fix

### 6. **Writing & Clarity Improvements** (1-2 pages)
- Passive voice issues → active alternatives
- Jargon overload → clearer phrasing
- Vague quantifiers → specific numbers
- Missing transitions → added connectors

### 7. **Revision Checklist** (1 page)
Prioritized by criticality:
- **Critical (P1)**: Must change
- **Important (P2)**: Should change
- **Nice-to-have (P3)**: Could improve

## Integration with Academic Agent

### Upstream (Input)
- **paper-writing**: Draft papers from paper-writing skill
- User feedback: Reviewer comments, advisor notes
- Config: LLM model, revision depth settings

### Downstream (Output)
- **rebuttal-writer**: Guidance can feed into rebuttal generation
- **survey-writing**: Revision patterns inform literature review
- **paper-presentation**: Revision insights affect presentation structure

## Test Results

✅ All integration tests passing:
- RevisionProblem dataclasses work correctly
- Markdown and JSON serialization complete
- Example guidance generation functional
- Reference guidelines comprehensive
- Evaluation cases well-structured

**Run tests**: `python3 test_integration.py`

## Example Output

Sample revision guidance demonstrating:
- Problem identification with before/after examples
- Clear severity levels (P1/P2/P3)
- Actionable recommendations
- Estimated improvement potential

See: `example_revision_guidance.md`

## Future Extensions

### LLM Enhancement
- Integrate with paper-reading skill for deeper understanding
- Use vector embeddings for similar paper comparison
- Automatic baseline extraction from related work

### Workflow Integration
- Multi-round revision tracking
- Automatic progress measurement
- Integration with git for version control

### Advanced Features
- Reviewer-specific feedback generation
- Conference-specific formatting guidance
- Citation network analysis for evidence gaps

## Configuration

Place LLM API keys in environment:

```bash
# For Claude
export ANTHROPIC_API_KEY="sk-ant-..."

# For GPT-4
export OPENAI_API_KEY="sk-..."
```

Configuration loaded from `config/default.yaml`:
```yaml
paper_reader:
  llm_model: "gpt-4o-mini"
  llm_backend: "openai"
```

## Dependencies

Core:
- pyyaml
- pdfplumber (for PDF extraction)

Optional (for LLM features):
- anthropic (for Claude)
- openai (for GPT-4)
- python-docx (for DOCX support)

## Quality Checklist

- ✅ SKILL.md complete with 7-part framework
- ✅ Core dataclasses implemented and tested
- ✅ PaperRevisionEngine functional
- ✅ LLM analyzer framework complete
- ✅ Reference guidelines comprehensive
- ✅ Evaluation cases defined
- ✅ Integration tests passing
- ✅ Example output generated
- ✅ Documentation complete

## Known Limitations

1. **LLM-powered analysis** requires API credentials
2. **PDF extraction** depends on pdfplumber availability
3. **DOCX support** optional (requires python-docx)
4. **Automatic section detection** uses simple heuristics
5. **Evidence gap identification** works best with well-structured papers

## Next Steps

1. **Integration with skill evolver**: Track which revision patterns lead to accepted papers
2. **Reviewer feedback integration**: Map reviewer comments to revision framework
3. **Citation network analysis**: Identify undercited areas automatically
4. **Multi-language support**: Extend beyond English papers
5. **Template-based guidance**: Venue-specific revision recommendations

---

**Status**: Implementation Complete ✅
**Last Updated**: 2026-04-13
**Tests**: All passing
