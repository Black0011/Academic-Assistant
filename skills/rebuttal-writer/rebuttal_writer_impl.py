"""
Rebuttal Writer Implementation: Generate responses to reviewer feedback.

Main entry point for rebuttal-writer skill. Integrates with:
- revision_analyzer.py (dataclasses for structured output)
- Paper reading system (read revised papers)
- LLM backend (analyze feedback and generate responses)
"""
from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Any, List
import os
import sys
from datetime import datetime

# Add project root to path
project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

from tools.pdf_parser import extract_text_from_pdf
from config.loader import load_config


@dataclass
class ReviewerComment:
    """A single reviewer comment."""
    comment_id: str
    comment: str
    section: Optional[str] = None
    severity: str = "minor"  # major / minor / question
    page_num: Optional[int] = None
    original_comment: Optional[str] = None


@dataclass
class ReviewerFeedback:
    """Feedback from a single reviewer."""
    reviewer_id: str
    comments: List[ReviewerComment] = field(default_factory=list)
    overall_recommendation: Optional[str] = None


@dataclass
class ResponseStrategy:
    """Strategy for responding to a comment."""
    strategy_type: str  # "clarify" / "defend" / "concede"
    assessment: str
    response_outline: str
    supporting_evidence: List[str] = field(default_factory=list)
    changes_in_paper: List[str] = field(default_factory=list)


@dataclass
class CommentResponse:
    """Complete response to a comment."""
    comment_id: str
    comment: str
    strategy: ResponseStrategy
    full_response: str
    evidence_strength: float = 0.5  # 0.0-1.0


@dataclass
class RebuttalLetter:
    """Complete rebuttal letter."""
    paper_id: str
    paper_title: str
    rebuttal_round: int
    opening: str
    reviewer_responses: List[dict] = field(default_factory=list)
    summary_of_changes: str = ""
    supplementary_materials: List[str] = field(default_factory=list)
    closing: str = ""
    metadata: dict = field(default_factory=dict)
    
    def to_markdown(self) -> str:
        """Convert to markdown."""
        md = f"""# Rebuttal Letter

**Paper Title**: {self.paper_title}  
**Paper ID**: {self.paper_id}  
**Rebuttal Round**: {self.rebuttal_round}

---

## Opening Statement

{self.opening}

---

## Responses to Reviewers

"""
        
        # Group responses by reviewer
        reviewers = {}
        for resp in self.reviewer_responses:
            rev_id = resp.get("reviewer_id", "Unknown")
            if rev_id not in reviewers:
                reviewers[rev_id] = []
            reviewers[rev_id].append(resp)
        
        for rev_id in sorted(reviewers.keys()):
            md += f"\n### {rev_id}\n\n"
            for resp in reviewers[rev_id]:
                md += f"#### Comment {resp.get('comment_id', '?')}\n\n"
                md += f"**Original**: {resp.get('comment', '')}\n\n"
                md += f"**Assessment**: {resp.get('assessment', '')}\n\n"
                md += f"**Response**: {resp.get('response', '')}\n\n"
                
                if resp.get('changes'):
                    md += "**Changes in manuscript**:\n"
                    for change in resp.get('changes', []):
                        md += f"- {change}\n"
                    md += "\n"
        
        if self.summary_of_changes:
            md += f"\n---\n\n## Summary of Changes\n\n{self.summary_of_changes}\n"
        
        if self.supplementary_materials:
            md += f"\n## Supplementary Materials\n\n"
            for material in self.supplementary_materials:
                md += f"- {material}\n"
            md += "\n"
        
        if self.closing:
            md += f"\n---\n\n{self.closing}\n"
        
        return md
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "paper_id": self.paper_id,
            "paper_title": self.paper_title,
            "rebuttal_round": self.rebuttal_round,
            "opening": self.opening,
            "reviewer_responses": self.reviewer_responses,
            "summary_of_changes": self.summary_of_changes,
            "supplementary_materials": self.supplementary_materials,
            "closing": self.closing,
            "metadata": self.metadata,
        }


class RebuttalWriterEngine:
    """Main engine for rebuttal generation."""
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize the rebuttal writer engine.
        
        Args:
            config_path: Path to configuration file. Defaults to config/default.yaml
        """
        self.config = load_config(config_path)
        self.llm_backend = self.config.get("llm_backend", "openai")
        self.model = self.config.get("paper_reader", {}).get("llm_model", "gpt-4o-mini")
    
    def load_revised_paper(self, file_path: str) -> str:
        """Load and extract text from revised paper.
        
        Args:
            file_path: Path to revised paper (PDF, DOCX, MD supported)
        
        Returns:
            Extracted text content
        """
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"Paper file not found: {file_path}")
        
        if path.suffix.lower() == ".pdf":
            text = extract_text_from_pdf(file_path)
        elif path.suffix.lower() == ".md":
            text = path.read_text(encoding="utf-8")
        elif path.suffix.lower() in [".docx", ".doc"]:
            try:
                from docx import Document
                doc = Document(file_path)
                text = "\n".join([p.text for p in doc.paragraphs])
            except ImportError:
                raise ImportError("python-docx required for .docx support. Install: pip install python-docx")
        else:
            raise ValueError(f"Unsupported file format: {path.suffix}")
        
        return text
    
    def parse_reviewer_feedback(self, feedback_data: dict) -> List[ReviewerFeedback]:
        """Parse reviewer feedback from structured data.
        
        Args:
            feedback_data: Dictionary containing reviewer comments
        
        Returns:
            List of ReviewerFeedback objects
        """
        reviewers = []
        
        # Handle different input formats
        if "reviewers" in feedback_data:
            for reviewer_entry in feedback_data["reviewers"]:
                reviewer_id = reviewer_entry.get("reviewer_id", "Unknown")
                comments = []
                
                for comment_data in reviewer_entry.get("comments", []):
                    comment = ReviewerComment(
                        comment_id=comment_data.get("comment_id", ""),
                        comment=comment_data.get("comment", ""),
                        section=comment_data.get("section"),
                        severity=comment_data.get("severity", "minor"),
                    )
                    comments.append(comment)
                
                reviewers.append(ReviewerFeedback(
                    reviewer_id=reviewer_id,
                    comments=comments,
                ))
        
        elif "reviewer_feedback" in feedback_data:
            comments_data = feedback_data["reviewer_feedback"].get("comments", [])
            comments = []
            
            for i, comment_data in enumerate(comments_data):
                comment = ReviewerComment(
                    comment_id=comment_data.get("comment_id", f"C{i+1}"),
                    comment=comment_data.get("comment", ""),
                    section=comment_data.get("section"),
                    severity=comment_data.get("severity", "minor"),
                )
                comments.append(comment)
            
            # Group by reviewer if available
            reviewers.append(ReviewerFeedback(
                reviewer_id="Reviewers",
                comments=comments,
            ))
        
        return reviewers
    
    def diagnose_comment(self, comment: ReviewerComment, paper_text: str) -> ResponseStrategy:
        """Diagnose a comment and suggest response strategy.
        
        Args:
            comment: The reviewer comment
            paper_text: Text of the revised paper
        
        Returns:
            Response strategy
        """
        # Simple heuristic for now
        comment_lower = comment.comment.lower()
        
        if any(word in comment_lower for word in ["clarif", "explain", "unclear", "confus", "ambig"]):
            strategy_type = "clarify"
        elif any(word in comment_lower for word in ["disagree", "don't agree", "problem with", "issue"]):
            strategy_type = "defend"
        elif any(word in comment_lower for word in ["agree", "valid", "good point", "limitation"]):
            strategy_type = "concede"
        else:
            strategy_type = "defend"
        
        assessment = self._generate_assessment(comment, strategy_type)
        response_outline = self._generate_response_outline(comment, strategy_type)
        evidence = self._identify_supporting_evidence(comment, paper_text)
        
        return ResponseStrategy(
            strategy_type=strategy_type,
            assessment=assessment,
            response_outline=response_outline,
            supporting_evidence=evidence,
        )
    
    def _generate_assessment(self, comment: ReviewerComment, strategy_type: str) -> str:
        """Generate assessment for a comment."""
        assessments = {
            "clarify": "This concern arises from an ambiguity in our presentation.",
            "defend": "We understand the concern, but respectfully believe our approach is justified.",
            "concede": "The reviewer makes a valid point. We acknowledge this limitation.",
        }
        return assessments.get(strategy_type, "Thank you for this feedback.")
    
    def _generate_response_outline(self, comment: ReviewerComment, strategy_type: str) -> str:
        """Generate response outline for a comment."""
        if strategy_type == "clarify":
            return f"We appreciate the question. Our work does not assume [clarify assumption]. Rather, [explanation]."
        elif strategy_type == "defend":
            return f"While we understand the concern about [topic], our approach is justified because: [evidence]. We have added [improvement] to address this."
        else:  # concede
            return f"We agree that [issue] was insufficient. We have addressed this by: [improvements]."
    
    def _identify_supporting_evidence(self, comment: ReviewerComment, paper_text: str) -> List[str]:
        """Identify supporting evidence for a response."""
        evidence = []
        
        if comment.section:
            if comment.section.lower() in paper_text.lower():
                evidence.append(f"Paper discusses {comment.section} in detail")
        
        # Look for specific markers
        if any(marker in paper_text for marker in ["Figure", "Table", "Experiment", "Algorithm"]):
            evidence.append("Supporting data available in paper")
        
        return evidence
    
    def generate_rebuttal(
        self,
        paper_id: str,
        paper_title: str,
        reviewer_feedback: List[ReviewerFeedback],
        revised_paper_text: str,
        rebuttal_round: int = 1,
    ) -> RebuttalLetter:
        """Generate complete rebuttal letter.
        
        Args:
            paper_id: Unique paper identifier
            paper_title: Title of the paper
            reviewer_feedback: List of reviewer feedback objects
            revised_paper_text: Text of the revised paper
            rebuttal_round: Which rebuttal round this is
        
        Returns:
            Complete RebuttalLetter
        """
        # Generate opening
        opening = self._generate_opening(paper_title)
        
        # Generate responses
        reviewer_responses = []
        for reviewer in reviewer_feedback:
            for comment in reviewer.comments:
                strategy = self.diagnose_comment(comment, revised_paper_text)
                
                response_dict = {
                    "reviewer_id": reviewer.reviewer_id,
                    "comment_id": comment.comment_id,
                    "comment": comment.comment,
                    "section": comment.section,
                    "severity": comment.severity,
                    "strategy": strategy.strategy_type,
                    "assessment": strategy.assessment,
                    "response": strategy.response_outline,
                    "changes": strategy.changes_in_paper,
                    "evidence": strategy.supporting_evidence,
                }
                reviewer_responses.append(response_dict)
        
        # Generate summary
        summary = self._generate_summary_of_changes(reviewer_responses)
        
        # Generate closing
        closing = self._generate_closing()
        
        return RebuttalLetter(
            paper_id=paper_id,
            paper_title=paper_title,
            rebuttal_round=rebuttal_round,
            opening=opening,
            reviewer_responses=reviewer_responses,
            summary_of_changes=summary,
            closing=closing,
            metadata={
                "generation_date": datetime.now().isoformat(),
                "num_reviewers": len(reviewer_feedback),
                "num_comments": sum(len(r.comments) for r in reviewer_feedback),
            },
        )
    
    def _generate_opening(self, paper_title: str) -> str:
        """Generate opening statement."""
        return f"""We are grateful to the editor and reviewers for their constructive feedback on our manuscript "{paper_title}". 
We have carefully considered all comments and made substantial revisions to strengthen the paper. 
Below we provide detailed responses to each comment, organized by reviewer."""
    
    def _generate_summary_of_changes(self, responses: List[dict]) -> str:
        """Generate summary of changes."""
        summary = "### Major Revisions\n\n"
        
        major_changes = [r for r in responses if r.get("severity") in ["major"]]
        for i, change in enumerate(major_changes[:5], 1):
            summary += f"{i}. **{change['section'] or 'General'}** (Comment {change['comment_id']})\n"
            summary += f"   - Strategy: {change['strategy']}\n\n"
        
        summary += "\n### Minor Revisions\n\n"
        minor_changes = [r for r in responses if r.get("severity") in ["minor", "question"]]
        for i, change in enumerate(minor_changes[:5], 1):
            summary += f"{i}. {change['section'] or 'General'} (Comment {change['comment_id']})\n"
        
        return summary
    
    def _generate_closing(self) -> str:
        """Generate closing statement."""
        return """We believe the revised manuscript now comprehensively addresses all reviewer concerns 
and significantly strengthens our contributions. We welcome any further questions and look forward to your decision.

Sincerely,
The Authors"""
    
    def output_markdown(self, rebuttal: RebuttalLetter, output_path: Optional[str] = None) -> str:
        """Generate markdown rebuttal letter.
        
        Args:
            rebuttal: RebuttalLetter object
            output_path: Optional path to save markdown file
        
        Returns:
            Markdown string
        """
        md = rebuttal.to_markdown()
        
        # Save if output path provided
        if output_path:
            Path(output_path).write_text(md, encoding="utf-8")
            print(f"✅ Rebuttal letter saved to {output_path}")
        
        return md
    
    def output_json(self, rebuttal: RebuttalLetter, output_path: Optional[str] = None) -> str:
        """Generate JSON rebuttal letter.
        
        Args:
            rebuttal: RebuttalLetter object
            output_path: Optional path to save JSON file
        
        Returns:
            JSON string
        """
        json_str = json.dumps(rebuttal.to_dict(), indent=2, ensure_ascii=False)
        
        if output_path:
            Path(output_path).write_text(json_str, encoding="utf-8")
            print(f"✅ Rebuttal letter saved to {output_path}")
        
        return json_str


def main():
    """CLI interface for rebuttal writing."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Generate rebuttal to reviewer feedback"
    )
    parser.add_argument("feedback_file", help="Path to reviewer feedback (JSON or YAML)")
    parser.add_argument("--paper", "-p", help="Path to revised paper (PDF, DOCX, or MD)")
    parser.add_argument("--output", "-o", help="Output file path (markdown by default)")
    parser.add_argument("--json", action="store_true", help="Output as JSON instead of markdown")
    parser.add_argument("--config", "-c", help="Path to config file")
    parser.add_argument("--title", "-t", help="Paper title")
    parser.add_argument("--paper-id", help="Paper ID")
    
    args = parser.parse_args()
    
    # Create engine
    engine = RebuttalWriterEngine(args.config)
    
    # Load feedback
    feedback_path = Path(args.feedback_file)
    if feedback_path.suffix.lower() == ".json":
        with open(feedback_path) as f:
            feedback_data = json.load(f)
    else:
        import yaml
        with open(feedback_path) as f:
            feedback_data = yaml.safe_load(f)
    
    # Parse feedback
    reviewer_feedback = engine.parse_reviewer_feedback(feedback_data)
    
    # Load paper if provided
    paper_text = ""
    if args.paper:
        paper_text = engine.load_revised_paper(args.paper)
    
    # Generate rebuttal
    print("Generating rebuttal letter...")
    rebuttal = engine.generate_rebuttal(
        paper_id=args.paper_id or "unknown",
        paper_title=args.title or "Untitled Paper",
        reviewer_feedback=reviewer_feedback,
        revised_paper_text=paper_text,
    )
    
    # Output
    output_file = args.output or f"rebuttal_{rebuttal.paper_id}.md"
    
    if args.json:
        engine.output_json(rebuttal, output_file)
    else:
        engine.output_markdown(rebuttal, output_file)
    
    print(f"✅ Done! Check {output_file}")


if __name__ == "__main__":
    main()
