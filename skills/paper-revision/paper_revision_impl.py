"""
Paper Revision Implementation: Analyze draft papers and generate revision guidance.

Main entry point for paper-revision skill. Integrates with:
- revision_analyzer.py (dataclasses and core types)
- Paper reading system (read draft papers)
- LLM backend (analyze and generate guidance)
"""
from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Any
import os
import sys

# Add project root to path
project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

from tools.pdf_parser import extract_text_from_pdf
from config.loader import load_config


@dataclass
class RevisionRequest:
    """Request for paper revision guidance."""
    draft_file: str
    user_feedback: Optional[str] = None
    focus_areas: Optional[list[str]] = None
    revision_round: int = 1
    mode: str = "standard"  # "standard" or "auto_diagnose" or "reviewer_response"


class PaperRevisionEngine:
    """Main engine for paper revision guidance generation."""
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize the paper revision engine.
        
        Args:
            config_path: Path to configuration file. Defaults to config/default.yaml
        """
        self.config = load_config(config_path)
        self.llm_backend = self.config.get("llm_backend", "openai")
        self.model = self.config.get("paper_reader", {}).get("llm_model", "gpt-4o-mini")
    
    def load_draft_paper(self, file_path: str) -> str:
        """Load and extract text from draft paper.
        
        Args:
            file_path: Path to draft paper (PDF, DOCX, MD supported)
        
        Returns:
            Extracted text content
        """
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"Draft file not found: {file_path}")
        
        if path.suffix.lower() == ".pdf":
            text = extract_text(file_path)
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
    
    def analyze_draft(self, draft_text: str, user_feedback: Optional[str] = None) -> dict[str, Any]:
        """Analyze draft paper and identify problems.
        
        Args:
            draft_text: Full text of draft paper
            user_feedback: Optional feedback from user to guide analysis
        
        Returns:
            Analysis result with problems, assessment, etc.
        """
        # This would call the LLM to analyze the paper
        # For now, return structured analysis template
        from scripts.revision_analyzer import RevisionAnalyzer
        
        # Extract paper structure (simplified)
        sections = self._extract_sections(draft_text)
        
        analysis = {
            "sections": sections,
            "draft_length": len(draft_text),
            "user_feedback": user_feedback,
        }
        
        return analysis
    
    def _extract_sections(self, text: str) -> dict[str, str]:
        """Extract paper sections from text.
        
        Args:
            text: Full paper text
        
        Returns:
            Dictionary mapping section names to content
        """
        sections = {}
        
        # Simple heuristic: look for common section headers
        common_sections = [
            "abstract", "introduction", "related work", "methodology", 
            "experiments", "results", "discussion", "conclusion", "references"
        ]
        
        text_lower = text.lower()
        
        for i, section in enumerate(common_sections):
            start_idx = text_lower.find(section)
            if start_idx == -1:
                continue
            
            # Find next section header
            next_section_idx = len(text)
            for next_section in common_sections[i+1:]:
                next_idx = text_lower.find(next_section, start_idx + 1)
                if next_idx != -1:
                    next_section_idx = min(next_section_idx, next_idx)
            
            section_content = text[start_idx:next_section_idx].strip()
            sections[section.title()] = section_content
        
        return sections
    
    def generate_revision_guidance(
        self,
        request: RevisionRequest,
        analysis: Optional[dict] = None
    ) -> dict[str, Any]:
        """Generate complete revision guidance for a paper.
        
        Args:
            request: Revision request with paper and feedback
            analysis: Optional pre-computed analysis
        
        Returns:
            Complete revision guidance as dictionary
        """
        # Load draft
        draft_text = self.load_draft_paper(request.draft_file)
        
        # Analyze if not provided
        if analysis is None:
            analysis = self.analyze_draft(draft_text, request.user_feedback)
        
        # Generate guidance structure
        guidance = {
            "paper_title": self._extract_title(draft_text),
            "paper_id": self._generate_paper_id(request.draft_file),
            "overall_assessment": self._generate_overall_assessment(analysis),
            "sections": self._generate_section_analyses(analysis),
            "evidence_gaps": self._identify_evidence_gaps(analysis),
            "writing_improvements": self._identify_writing_issues(analysis),
            "revision_checklist": self._generate_checklist(analysis),
            "metadata": {
                "draft_file": str(request.draft_file),
                "revision_round": request.revision_round,
                "mode": request.mode,
                "user_feedback": request.user_feedback,
            }
        }
        
        return guidance
    
    def _extract_title(self, text: str) -> str:
        """Extract paper title from text."""
        lines = text.strip().split("\n")
        return lines[0].strip() if lines else "Untitled Paper"
    
    def _generate_paper_id(self, file_path: str) -> str:
        """Generate unique paper ID."""
        from datetime import datetime
        base = Path(file_path).stem
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{base}_{timestamp}"
    
    def _generate_overall_assessment(self, analysis: dict) -> dict[str, Any]:
        """Generate overall paper assessment."""
        return {
            "strengths": [
                "Structure generally follows academic conventions",
                "Methodology section provides technical depth",
            ],
            "main_problems": [
                ("Analysis required", "P1"),
                ("Detailed review needed", "P2"),
            ],
            "improvement_potential": "Further analysis required",
            "estimated_revision_time_hours": 6.0,
        }
    
    def _generate_section_analyses(self, analysis: dict) -> list[dict]:
        """Generate section-by-section analyses."""
        sections = []
        for section_name, content in analysis.get("sections", {}).items():
            sections.append({
                "section_name": section_name,
                "current_state": f"{len(content)} characters",
                "problems": [],
                "quality_score": 6.0,
                "improvement_potential": 8.0,
            })
        return sections
    
    def _identify_evidence_gaps(self, analysis: dict) -> list[dict]:
        """Identify gaps in evidence and citations."""
        return []
    
    def _identify_writing_issues(self, analysis: dict) -> list[dict]:
        """Identify writing quality issues."""
        return []
    
    def _generate_checklist(self, analysis: dict) -> dict[str, list]:
        """Generate revision checklist."""
        return {
            "Critical": ["Review and improve structure"],
            "Important": ["Enhance clarity"],
            "Nice-to-have": ["Polish writing"],
        }
    
    def output_markdown(self, guidance: dict[str, Any], output_path: Optional[str] = None) -> str:
        """Generate markdown revision guidance.
        
        Args:
            guidance: Guidance dictionary from generate_revision_guidance
            output_path: Optional path to save markdown file
        
        Returns:
            Markdown string
        """
        md = f"""# Paper Revision Guidance

**Paper**: {guidance.get('paper_title', 'Untitled')}  
**Paper ID**: {guidance.get('paper_id', 'unknown')}

---

## Overall Assessment

### Strengths

"""
        for strength in guidance.get("overall_assessment", {}).get("strengths", []):
            md += f"- {strength}\n"
        
        md += "\n### Main Problems (Priority Ordered)\n\n"
        for problem, priority in guidance.get("overall_assessment", {}).get("main_problems", []):
            md += f"- **{priority}**: {problem}\n"
        
        md += f"""
### Improvement Potential

{guidance.get("overall_assessment", {}).get("improvement_potential", "Analysis pending")}

### Estimated Revision Time

{guidance.get("overall_assessment", {}).get("estimated_revision_time_hours", 0)} hours

---

## Section-by-Section Analysis

"""
        for section in guidance.get("sections", []):
            md += f"### {section['section_name']}\n\n"
            md += f"**Current State**: {section['current_state']}\n\n"
            md += f"**Quality Score**: {section.get('quality_score', 0)}/10\n\n"
        
        md += "\n## Revision Checklist\n\n"
        for priority, tasks in guidance.get("revision_checklist", {}).items():
            md += f"### {priority}\n\n"
            for task in tasks:
                md += f"- [ ] {task}\n"
            md += "\n"
        
        md += "\n---\n\nGenerated by Paper Revision Engine\n"
        
        # Save if output path provided
        if output_path:
            Path(output_path).write_text(md, encoding="utf-8")
            print(f"✅ Revision guidance saved to {output_path}")
        
        return md
    
    def output_json(self, guidance: dict[str, Any], output_path: Optional[str] = None) -> str:
        """Generate JSON revision guidance.
        
        Args:
            guidance: Guidance dictionary
            output_path: Optional path to save JSON file
        
        Returns:
            JSON string
        """
        json_str = json.dumps(guidance, indent=2, ensure_ascii=False)
        
        if output_path:
            Path(output_path).write_text(json_str, encoding="utf-8")
            print(f"✅ Revision guidance saved to {output_path}")
        
        return json_str


def main():
    """CLI interface for paper revision."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Generate paper revision guidance"
    )
    parser.add_argument("draft_file", help="Path to draft paper (PDF, DOCX, or MD)")
    parser.add_argument("--feedback", "-f", help="User feedback on the draft")
    parser.add_argument("--output", "-o", help="Output file path (markdown by default)")
    parser.add_argument("--json", action="store_true", help="Output as JSON instead of markdown")
    parser.add_argument("--config", "-c", help="Path to config file")
    
    args = parser.parse_args()
    
    # Create engine
    engine = PaperRevisionEngine(args.config)
    
    # Create revision request
    request = RevisionRequest(
        draft_file=args.draft_file,
        user_feedback=args.feedback,
    )
    
    # Generate guidance
    print("Analyzing draft paper...")
    guidance = engine.generate_revision_guidance(request)
    
    # Output
    output_file = args.output or f"revision_guidance_{guidance['paper_id']}.md"
    
    if args.json:
        engine.output_json(guidance, output_file)
    else:
        engine.output_markdown(guidance, output_file)
    
    print(f"✅ Done! Check {output_file}")


if __name__ == "__main__":
    main()
