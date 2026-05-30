"""
Paper Revision Analyzer: Analyze draft papers and generate section-by-section revision guidance.

This module provides:
- RevisionProblem: Dataclass for individual revision problems
- RevisionGuidance: Dataclass for complete revision guidance
- RevisionAnalyzer: Main API for analyzing papers and generating guidance
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProblemSeverity(Enum):
    """Severity levels for revision problems."""
    P1_CRITICAL = "P1 - Critical"  # Affects core contribution
    P2_IMPORTANT = "P2 - Important"  # Affects clarity/rigor
    P3_NICE_TO_HAVE = "P3 - Nice-to-have"  # Polish/style


class ProblemType(Enum):
    """Types of problems identified in papers."""
    LOGICAL = "Logical"  # Argument flow issues
    STRUCTURAL = "Structural"  # Organization issues
    EVIDENTIAL = "Evidential"  # Missing evidence/support
    CLARITY = "Clarity"  # Jargon/wording issues
    STYLE = "Style"  # Tone/consistency issues


@dataclass
class RevisionProblem:
    """Individual revision problem with proposed fix."""
    section: str  # Section name (e.g., "Introduction", "Methodology")
    problem_id: str  # Unique identifier (e.g., "intro-1")
    problem_type: ProblemType
    severity: ProblemSeverity
    title: str  # Short problem title
    description: str  # Detailed problem description
    location: str  # Where in section (e.g., "Paragraph 2-3")
    before_text: str  # Original text (excerpt)
    after_text: str  # Suggested revision (excerpt)
    explanation: str  # Why this change helps
    expected_impact: str  # Predicted improvement
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "problem_id": self.problem_id,
            "problem_type": self.problem_type.value,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "location": self.location,
            "before_text": self.before_text,
            "after_text": self.after_text,
            "explanation": self.explanation,
            "expected_impact": self.expected_impact,
        }
    
    def to_markdown(self) -> str:
        """Convert to markdown problem report."""
        return f"""### [{self.problem_id}] {self.title}

**Section**: {self.section}  
**Type**: {self.problem_type.value}  
**Severity**: {self.severity.value}  
**Location**: {self.location}

**Problem Description**:
{self.description}

**Current Text**:
```
{self.before_text}
```

**Suggested Revision**:
```
{self.after_text}
```

**Why This Helps**:
{self.explanation}

**Expected Impact**:
{self.expected_impact}

---
"""


@dataclass
class SectionAnalysis:
    """Analysis result for a single section."""
    section_name: str
    current_state: str  # Brief description of current state
    problems: list[RevisionProblem] = field(default_factory=list)
    structural_recommendations: list[str] = field(default_factory=list)
    quality_score: float = 0.0  # 0-10 scale
    estimated_improvement_potential: float = 0.0  # 0-10 scale
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "section_name": self.section_name,
            "current_state": self.current_state,
            "problems": [p.to_dict() for p in self.problems],
            "structural_recommendations": self.structural_recommendations,
            "quality_score": self.quality_score,
            "estimated_improvement_potential": self.estimated_improvement_potential,
        }
    
    def to_markdown(self) -> str:
        """Convert to markdown section analysis."""
        problems_md = "\n".join(p.to_markdown() for p in self.problems)
        recs_md = "\n".join(f"- {r}" for r in self.structural_recommendations)
        
        return f"""## {self.section_name}

**Current State**: {self.current_state}

**Quality Score**: {self.quality_score}/10  
**Improvement Potential**: {self.estimated_improvement_potential}/10

### Problems Identified

{problems_md}

### Structural Recommendations

{recs_md}

---
"""


@dataclass
class OverallAssessment:
    """Overall paper assessment."""
    strengths: list[str]  # What's going well
    main_problems: list[tuple[str, str]]  # (problem, priority) tuples
    improvement_potential: str  # Estimated improvement level
    estimated_revision_time_hours: float  # Time to complete all changes
    priority_problems: list[RevisionProblem] = field(default_factory=list)  # P1 problems only
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "strengths": self.strengths,
            "main_problems": [{"problem": p[0], "priority": p[1]} for p in self.main_problems],
            "improvement_potential": self.improvement_potential,
            "estimated_revision_time_hours": self.estimated_revision_time_hours,
            "priority_problems": [p.to_dict() for p in self.priority_problems],
        }
    
    def to_markdown(self) -> str:
        """Convert to markdown overall assessment."""
        strengths_md = "\n".join(f"- {s}" for s in self.strengths)
        problems_md = "\n".join(
            f"- **{p[1]}**: {p[0]}" for p in self.main_problems
        )
        
        return f"""# Overall Assessment

## Strengths

{strengths_md}

## Main Problems (Priority Ordered)

{problems_md}

## Improvement Potential

{self.improvement_potential}

## Estimated Revision Time

{self.estimated_revision_time_hours} hours to complete all recommended changes.

---
"""


@dataclass
class RevisionGuidance:
    """Complete revision guidance for a paper."""
    paper_title: str
    paper_id: str  # e.g., "2024.04.10.v1"
    overall_assessment: OverallAssessment
    sections: list[SectionAnalysis] = field(default_factory=list)
    evidence_gaps: list[tuple[str, str, str]] = field(default_factory=list)  # (location, gap, fix)
    writing_improvements: list[tuple[str, str, str]] = field(default_factory=list)  # (issue, before, after)
    revision_checklist: dict[str, list[str]] = field(default_factory=dict)  # {priority: [tasks]}
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_title": self.paper_title,
            "paper_id": self.paper_id,
            "overall_assessment": self.overall_assessment.to_dict(),
            "sections": [s.to_dict() for s in self.sections],
            "evidence_gaps": [
                {"location": l, "gap": g, "fix": f} 
                for l, g, f in self.evidence_gaps
            ],
            "writing_improvements": [
                {"issue": i, "before": b, "after": a}
                for i, b, a in self.writing_improvements
            ],
            "revision_checklist": self.revision_checklist,
        }
    
    def to_markdown(self) -> str:
        """Convert entire guidance to markdown."""
        header = f"""# Paper Revision Guidance

**Paper**: {self.paper_title}  
**Paper ID**: {self.paper_id}

---

{self.overall_assessment.to_markdown()}

"""
        sections_md = "\n".join(s.to_markdown() for s in self.sections)
        
        evidence_md = "\n".join(
            f"- **{loc}**: {gap} → {fix}" 
            for loc, gap, fix in self.evidence_gaps
        )
        
        writing_md = "\n".join(
            f"""- **{issue}**
  - Before: "{b}"
  - After: "{a}\""""
            for issue, b, a in self.writing_improvements
        )
        
        checklist_md = "\n".join(
            f"""### {priority}
{"".join(f"- [ ] {task}" for task in tasks)}
"""
            for priority, tasks in self.revision_checklist.items()
        )
        
        return f"""{header}{sections_md}

## Evidence & Citation Gaps

{evidence_md}

---

## Writing & Clarity Improvements

{writing_md}

---

## Revision Checklist

{checklist_md}

---

Generated by Paper Revision Analyzer
"""


class RevisionAnalyzer:
    """Main API for analyzing papers and generating revision guidance."""
    
    def __init__(self, paper_title: str, paper_id: str):
        """Initialize analyzer for a specific paper."""
        self.paper_title = paper_title
        self.paper_id = paper_id
        self.sections: list[SectionAnalysis] = []
        self.overall_assessment: OverallAssessment | None = None
    
    def add_section_analysis(self, analysis: SectionAnalysis) -> None:
        """Add analysis for a section."""
        self.sections.append(analysis)
    
    def set_overall_assessment(self, assessment: OverallAssessment) -> None:
        """Set overall paper assessment."""
        self.overall_assessment = assessment
    
    def generate_guidance(
        self,
        evidence_gaps: list[tuple[str, str, str]] | None = None,
        writing_improvements: list[tuple[str, str, str]] | None = None,
        revision_checklist: dict[str, list[str]] | None = None,
    ) -> RevisionGuidance:
        """Generate complete revision guidance."""
        if self.overall_assessment is None:
            raise ValueError("Overall assessment not set. Call set_overall_assessment first.")
        
        return RevisionGuidance(
            paper_title=self.paper_title,
            paper_id=self.paper_id,
            overall_assessment=self.overall_assessment,
            sections=self.sections,
            evidence_gaps=evidence_gaps or [],
            writing_improvements=writing_improvements or [],
            revision_checklist=revision_checklist or {},
        )
    
    def example_guidance(self) -> RevisionGuidance:
        """Generate example revision guidance for testing."""
        # Create example problems
        intro_problems = [
            RevisionProblem(
                section="Introduction",
                problem_id="intro-1",
                problem_type=ProblemType.STRUCTURAL,
                severity=ProblemSeverity.P1_CRITICAL,
                title="Background too long",
                description="First two paragraphs are standard background material that readers likely know. The core problem doesn't appear until paragraph 3.",
                location="Paragraph 1-2",
                before_text="Reinforcement learning has been widely applied to many domains... Multi-task learning combines benefits...",
                after_text="In multi-task RL, agents must handle diverse tasks efficiently. However, existing approaches sacrifice either efficiency or accuracy.",
                explanation="Moves directly to specific problem without generic background.",
                expected_impact="Reduce intro by 30%, improve engagement.",
            ),
            RevisionProblem(
                section="Introduction",
                problem_id="intro-2",
                problem_type=ProblemType.EVIDENTIAL,
                severity=ProblemSeverity.P2_IMPORTANT,
                title="Gap analysis lacks data",
                description="Claim about task interference has no supporting data or citations.",
                location="Paragraph 3",
                before_text="Task interference is a known challenge in multi-task RL.",
                after_text="Studies show task interference causes 40-60% accuracy drops in diverse multi-task settings [CITE]. For example, shared parameters in multi-task networks...",
                explanation="Adds quantitative evidence and citation support.",
                expected_impact="Increases credibility and specificity.",
            ),
        ]
        
        intro_analysis = SectionAnalysis(
            section_name="Introduction",
            current_state="500 words, 3 main points, but background too long and gap analysis vague.",
            problems=intro_problems,
            structural_recommendations=[
                "Reduce background to 1 paragraph",
                "Add motivating example with specific failure case",
                "Move core idea to paragraph 2-3",
            ],
            quality_score=6.0,
            estimated_improvement_potential=8.5,
        )
        
        methodology_problems = [
            RevisionProblem(
                section="Methodology",
                problem_id="method-1",
                problem_type=ProblemType.CLARITY,
                severity=ProblemSeverity.P2_IMPORTANT,
                title="Problem definition implicit",
                description="No formal problem statement. Uses prose only, making it hard to follow the technical content.",
                location="Opening paragraph",
                before_text="We design a method to select routing policies for multi-task environments...",
                after_text="We define the routing problem: given task t ∈ T and state s ∈ S, find policy π_r: S × T → [0,1]^K maximizing cumulative reward while minimizing computational cost.",
                explanation="Formal definition provides precise target and enables rigorous discussion.",
                expected_impact="Improves clarity; enables theoretical analysis.",
            ),
        ]
        
        method_analysis = SectionAnalysis(
            section_name="Methodology",
            current_state="4 pages, dense technical prose, no formal problem definition or algorithm pseudocode.",
            problems=methodology_problems,
            structural_recommendations=[
                "Add formal problem statement section",
                "Provide Algorithm 1 pseudocode",
                "Create notation table",
            ],
            quality_score=5.5,
            estimated_improvement_potential=8.0,
        )
        
        # Overall assessment
        assessment = OverallAssessment(
            strengths=[
                "Core idea is novel and well-motivated",
                "Experiments cover 4 environments with ablations",
                "Writing is generally clear and well-structured",
            ],
            main_problems=[
                ("Related Work and Methodology have too much overlap", "P1"),
                ("Experiments section lacks failure case analysis", "P1"),
                ("Abstract is too generic, needs specific numbers", "P2"),
            ],
            improvement_potential="From acceptable (6/10) to strong (8-8.5/10) with focused revisions.",
            estimated_revision_time_hours=8.0,
        )
        
        evidence_gaps = [
            ("Abstract", "Claims efficiency but no number", "Add: '45% speedup compared to fixed routing'"),
            ("Intro, Paragraph 3", "Task interference mentioned without data", "Add citation + result: [CITE] shows X% accuracy drop"),
        ]
        
        writing_improvements = [
            ("Passive voice overuse", "The method was evaluated on...", "We evaluated our method on..."),
            ("Vague quantifiers", "Many approaches use parameter sharing", "Five prior approaches [CITE] use parameter sharing"),
        ]
        
        checklist = {
            "Critical": [
                "Merge Related Work insights into Methodology § 2",
                "Add failure analysis subsection to Experiments",
                "Add formal problem definition to Methodology § 1",
            ],
            "Important": [
                "Strengthen Abstract with specific numbers",
                "Reduce Introduction from 500 to 350 words",
                "Add notation table to Methodology",
            ],
            "Nice-to-have": [
                "Improve figure captions (currently too brief)",
                "Add more discussion on computational overhead trade-offs",
            ],
        }
        
        guidance = RevisionGuidance(
            paper_title="Dynamic Routing for Multi-Task RL",
            paper_id="2024.04.10.v1",
            overall_assessment=assessment,
            sections=[intro_analysis, method_analysis],
            evidence_gaps=evidence_gaps,
            writing_improvements=writing_improvements,
            revision_checklist=checklist,
        )
        
        return guidance


# Example usage
if __name__ == "__main__":
    analyzer = RevisionAnalyzer(
        paper_title="Dynamic Routing for Multi-Task RL",
        paper_id="2024.04.10.v1"
    )
    
    # Generate example guidance
    guidance = analyzer.example_guidance()
    
    # Output as markdown
    markdown_output = guidance.to_markdown()
    print(markdown_output)
    
    # Output as dictionary
    dict_output = guidance.to_dict()
    print("\n\n=== JSON Output (first 500 chars) ===")
    import json
    print(json.dumps(dict_output, indent=2)[:500] + "...")
