#!/usr/bin/env python3
"""
OutlineBuilder: Generate structured paper outlines with section guidance.

Usage:
    from outline_builder import OutlineBuilder
    
    builder = OutlineBuilder(
        paper_profile={
            "one_liner": "Dynamic routing for multi-task RL",
            "target_venue": "ICLR",
            "paper_type": "method",
            "has_experiments": True,
            "estimated_pages": 8,
        }
    )
    
    outline = builder.build_outline()
    print(outline.to_markdown())
"""

from dataclasses import dataclass, asdict
from typing import Optional, Dict, List
from datetime import datetime


@dataclass
class Section:
    """Represents one section of the paper outline."""
    number: int
    title: str
    pages_min: int
    pages_max: int
    purpose: str
    structure: List[str]  # Subsections or key parts
    key_points: List[str]  # What must be covered
    citations_expected: int  # Approximate number of citations
    common_mistakes: List[str]
    evaluation_checklist: List[str]
    
    def to_markdown(self) -> str:
        """Convert section to markdown representation."""
        out = []
        out.append(f"### § {self.number}. {self.title}")
        out.append(f"\n**Pages**: {self.pages_min}-{self.pages_max} | **Citations**: ~{self.citations_expected}")
        out.append(f"\n**Purpose**: {self.purpose}\n")
        
        out.append("**Recommended Structure**:\n")
        for i, part in enumerate(self.structure, 1):
            out.append(f"- {part}")
        
        out.append("\n**Key Points to Cover**:\n")
        for point in self.key_points:
            out.append(f"- ✓ {point}")
        
        out.append("\n**Common Mistakes**:\n")
        for mistake in self.common_mistakes:
            out.append(f"- ❌ {mistake}")
        
        out.append("\n**Evaluation Checklist**:\n")
        for check in self.evaluation_checklist:
            out.append(f"- [ ] {check}")
        
        return "\n".join(out)


@dataclass
class PaperOutline:
    """Complete paper outline with all sections."""
    one_liner: str
    target_venue: str
    paper_type: str  # "method", "comparison", "survey", "application"
    estimated_pages: int
    estimated_duration: str  # e.g., "6-8 weeks"
    sections: List[Section]
    
    def to_markdown(self) -> str:
        """Convert entire outline to markdown."""
        out = []
        out.append(f"# Paper Outline: {self.one_liner}\n")
        out.append(f"**Target**: {self.target_venue}")
        out.append(f"**Type**: {self.paper_type.capitalize()}")
        out.append(f"**Estimated Length**: {self.estimated_pages}-{self.estimated_pages+2} pages")
        out.append(f"**Writing Duration**: {self.estimated_duration}\n")
        
        out.append("---\n")
        
        total_pages = sum(s.pages_max for s in self.sections)
        total_citations = sum(s.citations_expected for s in self.sections)
        
        out.append(f"## Overview\n")
        out.append(f"- **Total Sections**: {len(self.sections)}")
        out.append(f"- **Estimated Pages**: {total_pages} (adjust based on content)")
        out.append(f"- **Expected Citations**: ~{total_citations}\n")
        
        out.append("---\n")
        
        for section in self.sections:
            out.append(section.to_markdown())
            out.append("\n---\n")
        
        out.append("## Next Steps\n")
        out.append("1. Review this outline and confirm section structure\n")
        out.append("2. Select which sections to draft first\n")
        out.append("3. For each section, request a detailed draft with guidelines\n")
        out.append("4. Integrate drafts and check for flow and coherence\n")
        out.append("5. Iterate based on feedback\n")
        
        return "\n".join(out)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "one_liner": self.one_liner,
            "target_venue": self.target_venue,
            "paper_type": self.paper_type,
            "estimated_pages": self.estimated_pages,
            "estimated_duration": self.estimated_duration,
            "sections": [
                {
                    "number": s.number,
                    "title": s.title,
                    "pages": f"{s.pages_min}-{s.pages_max}",
                    "purpose": s.purpose,
                }
                for s in self.sections
            ]
        }


class OutlineBuilder:
    """Build paper outlines based on user profile."""
    
    # Templates for different section types
    SECTIONS_METHOD_PAPER = [
        Section(
            number=1,
            title="Abstract",
            pages_min=0,
            pages_max=1,
            purpose="Summarize problem, method, and results in 150-250 words",
            structure=[
                "Background (1 sentence)",
                "Problem/Motivation (1 sentence)",
                "Method/Approach (1-2 sentences)",
                "Main Results (1 sentence)",
                "Significance (optional)",
            ],
            key_points=[
                "Hook the reader with specific numbers",
                "Clearly state the problem",
                "Summarize the method without details",
                "Include quantitative results",
                "Self-contained (no forward references)",
            ],
            citations_expected=0,
            common_mistakes=[
                "Too generic or vague",
                "Too much technical detail",
                "No specific numbers in results",
                "Cites figures or sections",
            ],
            evaluation_checklist=[
                "Abstract is 150-250 words?",
                "Includes specific quantitative results?",
                "Method is understandable without details?",
                "No citations to paper sections?",
                "Self-contained and compelling?",
            ],
        ),
        Section(
            number=2,
            title="Introduction",
            pages_min=2,
            pages_max=4,
            purpose="Motivate problem, identify gap, present idea, state contributions",
            structure=[
                "Hook & Background (0.5-1 page)",
                "Identify Gap (0.5-1 page)",
                "Our Core Idea (0.5 page)",
                "Contributions (0.5 page)",
                "Paper Organization (0.3 page)",
            ],
            key_points=[
                "Establish credibility with background",
                "Clearly identify the limitation/gap",
                "Present core insight before technical details",
                "List 3-5 clear contributions",
                "Help readers navigate paper structure",
            ],
            citations_expected=10,
            common_mistakes=[
                "Introduction reads like Related Work",
                "Contributions are vague",
                "Too much technical detail upfront",
                "Gap is not clearly identified",
            ],
            evaluation_checklist=[
                "Hook is compelling?",
                "Background is established?",
                "Gap is specific and clear?",
                "Core idea is understandable?",
                "Contributions are specific and novel?",
                "Paper organization is clear?",
                "No unexplained jargon?",
            ],
        ),
        Section(
            number=3,
            title="Related Work",
            pages_min=2,
            pages_max=3,
            purpose="Organize and position prior work by research direction",
            structure=[
                "[Direction 1]: (e.g., Parameter Sharing Methods)",
                "[Direction 2]: (e.g., Dynamic Networks)",
                "[Direction 3]: (if applicable)",
                "Summary of Positioning",
            ],
            key_points=[
                "Organize by research direction, not chronologically",
                "3-5 papers per group with brief summaries",
                "Explicitly state differences from your work",
                "Fair treatment of prior work",
                "Both classical and recent papers included",
            ],
            citations_expected=20,
            common_mistakes=[
                "Organized chronologically instead of by theme",
                "Too much detail on each paper",
                "Unfair criticism of prior work",
                "Missing recent work",
            ],
            evaluation_checklist=[
                "Organized by research direction?",
                "3-5 papers per group?",
                "Differences clearly stated?",
                "Fair to prior work?",
                "Recent papers included?",
                "10-15% of total paper length?",
            ],
        ),
        Section(
            number=4,
            title="Methodology",
            pages_min=3,
            pages_max=5,
            purpose="Formally define problem and present technical approach",
            structure=[
                "Problem Definition / Setup",
                "Framework Overview",
                "Detailed Technical Presentation",
                "Training Procedure / Algorithm",
            ],
            key_points=[
                "Symbols and notation clearly defined",
                "Problem formally stated with objective",
                "Framework explained intuitively first",
                "Key equations numbered and explained",
                "Algorithm/pseudocode included",
                "Sufficient detail for reproduction",
            ],
            citations_expected=5,
            common_mistakes=[
                "Notation not defined",
                "Equations without explanation",
                "Insufficient algorithmic detail",
                "Missing hyperparameters",
                "Too much detail without overview",
            ],
            evaluation_checklist=[
                "All symbols defined?",
                "Problem formally stated?",
                "Framework explained before details?",
                "Key equations numbered?",
                "Algorithm is clear and complete?",
                "Reproducible from description?",
                "Consistent notation throughout?",
            ],
        ),
        Section(
            number=5,
            title="Experiments",
            pages_min=3,
            pages_max=4,
            purpose="Evaluate method on benchmarks with comprehensive analysis",
            structure=[
                "Experimental Setup",
                "Main Results & Comparison",
                "Ablation Studies",
                "Analysis & Qualitative Results",
            ],
            key_points=[
                "Benchmarks justified and standard",
                "Baselines include SOTA methods",
                "Setup is reproducible",
                "Results include error bars",
                "Ablation shows component importance",
                "Analysis provides insight",
            ],
            citations_expected=10,
            common_mistakes=[
                "Missing error bars or std dev",
                "Weak baselines (not SOTA)",
                "Incomplete ablation",
                "Only quantitative results (no analysis)",
                "Not enough runs for statistical significance",
            ],
            evaluation_checklist=[
                "Benchmarks well-justified?",
                "Baselines are SOTA?",
                "Setup is reproducible?",
                "Results have error bars?",
                "Ablation is comprehensive?",
                "Analysis provides insight?",
                "3+ runs with different seeds?",
            ],
        ),
        Section(
            number=6,
            title="Discussion",
            pages_min=1,
            pages_max=2,
            purpose="Interpret findings, discuss implications, acknowledge limitations",
            structure=[
                "Key Findings & Implications",
                "Limitations & Failure Cases",
                "Future Directions",
            ],
            key_points=[
                "Interpret results in context of contributions",
                "Discuss broader implications",
                "Honestly acknowledge limitations",
                "Suggest concrete future directions",
                "Connect back to original motivation",
            ],
            citations_expected=3,
            common_mistakes=[
                "No discussion of limitations",
                "Over-claiming implications",
                "Repeating results without interpretation",
                "Vague future work",
            ],
            evaluation_checklist=[
                "Key findings clearly stated?",
                "Implications discussed?",
                "Limitations honestly addressed?",
                "Not over-claiming?",
                "Future work is concrete?",
            ],
        ),
        Section(
            number=7,
            title="Conclusion",
            pages_min=1,
            pages_max=1,
            purpose="Summarize contributions and impact",
            structure=[
                "Summary of Main Contributions",
                "Broader Impact & Significance",
                "Closing Thought",
            ],
            key_points=[
                "Concise summary of what was done",
                "Broader significance or impact",
                "Memorable closing thought",
            ],
            citations_expected=0,
            common_mistakes=[
                "Repeating introduction verbatim",
                "No forward-looking perspective",
                "Too long or detailed",
            ],
            evaluation_checklist=[
                "Concise and clear?",
                "Summarizes key contributions?",
                "Discusses broader impact?",
                "Memorable closing?",
            ],
        ),
    ]
    
    SECTIONS_SURVEY_PAPER = [
        # Similar structure but with expanded Related Work sections
        # and different methodology treatment
    ]
    
    def __init__(self, paper_profile: Dict):
        """Initialize builder with paper profile."""
        self.profile = paper_profile
        self.one_liner = paper_profile.get("one_liner", "")
        self.target_venue = paper_profile.get("target_venue", "ICLR")
        self.paper_type = paper_profile.get("paper_type", "method")
        self.has_experiments = paper_profile.get("has_experiments", True)
        self.estimated_pages = paper_profile.get("estimated_pages", 8)
    
    def build_outline(self) -> PaperOutline:
        """Build the complete outline."""
        
        # Choose template based on paper type
        if self.paper_type == "method":
            sections = self.SECTIONS_METHOD_PAPER
        elif self.paper_type == "survey":
            sections = self.SECTIONS_SURVEY_PAPER
        else:
            sections = self.SECTIONS_METHOD_PAPER  # Default
        
        # Adjust for experiments availability
        if not self.has_experiments:
            # Reduce experiment section or modify
            pass
        
        duration = self._estimate_duration()
        
        return PaperOutline(
            one_liner=self.one_liner,
            target_venue=self.target_venue,
            paper_type=self.paper_type,
            estimated_pages=self.estimated_pages,
            estimated_duration=duration,
            sections=sections,
        )
    
    def _estimate_duration(self) -> str:
        """Estimate writing duration based on paper complexity."""
        if self.has_experiments:
            if self.estimated_pages >= 10:
                return "8-12 weeks"
            else:
                return "4-8 weeks"
        else:
            return "2-4 weeks"


def main():
    """Example usage."""
    profile = {
        "one_liner": "Dynamic Routing for Multi-Task Reinforcement Learning",
        "target_venue": "ICLR",
        "paper_type": "method",
        "has_experiments": True,
        "estimated_pages": 8,
    }
    
    builder = OutlineBuilder(profile)
    outline = builder.build_outline()
    
    print(outline.to_markdown())


if __name__ == "__main__":
    main()

