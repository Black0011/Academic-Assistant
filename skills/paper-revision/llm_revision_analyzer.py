"""
LLM-powered Paper Revision Analyzer.

Uses Claude/GPT-4 to deeply analyze papers and generate structured revision guidance
following the 7-part framework (Overall Assessment, Section Analysis, Specific Edits,
Structural Recommendations, Evidence Gaps, Writing Improvements, Checklist).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Any
import os
import sys

# Add project root to path
project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

from config.loader import load_config

try:
    import anthropic
    CLAUDE_AVAILABLE = True
except ImportError:
    CLAUDE_AVAILABLE = False

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class LLMRevisionAnalyzer:
    """Uses LLM to analyze papers and generate revision guidance."""
    
    def __init__(self, backend: str = "claude", config_path: Optional[str] = None):
        """Initialize LLM analyzer.
        
        Args:
            backend: "claude" or "openai"
            config_path: Path to config file
        """
        self.config = load_config(config_path)
        self.backend = backend.lower()
        self._init_client()
    
    def _init_client(self):
        """Initialize LLM client."""
        if self.backend == "claude":
            if not CLAUDE_AVAILABLE:
                raise ImportError("anthropic package required. Install: pip install anthropic")
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY environment variable not set")
            self.client = anthropic.Anthropic(api_key=api_key)
            self.model = "claude-3-5-sonnet-20241022"
        elif self.backend == "openai":
            if not OPENAI_AVAILABLE:
                raise ImportError("openai package required. Install: pip install openai")
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY environment variable not set")
            self.client = OpenAI(api_key=api_key)
            self.model = self.config.get("llm_model", "gpt-4o-mini")
        else:
            raise ValueError(f"Unknown backend: {self.backend}")
    
    def analyze_paper(
        self,
        paper_text: str,
        title: str = "",
        user_feedback: Optional[str] = None,
        focus_areas: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Analyze paper and generate revision guidance.
        
        Args:
            paper_text: Full text of paper
            title: Paper title
            user_feedback: Optional user feedback to incorporate
            focus_areas: Optional list of sections to focus on
        
        Returns:
            Structured revision guidance
        """
        # Step 1: Generate overall assessment
        overall_assessment = self._analyze_overall(paper_text, title, user_feedback)
        
        # Step 2: Analyze each section
        sections = self._extract_sections(paper_text)
        section_analyses = {}
        for section_name, section_text in sections.items():
            if focus_areas and section_name.lower() not in [f.lower() for f in focus_areas]:
                continue
            section_analyses[section_name] = self._analyze_section(
                section_text, section_name, title
            )
        
        # Step 3: Identify specific problems and edits
        specific_edits = self._generate_specific_edits(paper_text, section_analyses)
        
        # Step 4: Structural recommendations
        structural_recs = self._generate_structural_recs(paper_text, sections)
        
        # Step 5: Evidence gaps
        evidence_gaps = self._identify_evidence_gaps(paper_text)
        
        # Step 6: Writing improvements
        writing_improvements = self._identify_writing_improvements(paper_text)
        
        # Step 7: Revision checklist
        revision_checklist = self._generate_revision_checklist(
            overall_assessment, section_analyses, evidence_gaps
        )
        
        return {
            "overall_assessment": overall_assessment,
            "sections": section_analyses,
            "specific_edits": specific_edits,
            "structural_recommendations": structural_recs,
            "evidence_gaps": evidence_gaps,
            "writing_improvements": writing_improvements,
            "revision_checklist": revision_checklist,
        }
    
    def _analyze_overall(
        self, 
        paper_text: str, 
        title: str = "",
        user_feedback: Optional[str] = None
    ) -> dict[str, Any]:
        """Generate overall assessment using LLM."""
        
        prompt = f"""Analyze this research paper and provide an overall assessment.

Paper Title: {title or "Unknown"}

{"User Feedback: " + user_feedback if user_feedback else ""}

---
PAPER CONTENT (first 3000 chars for context):
{paper_text[:3000]}...

---

Provide assessment in JSON format with:
1. "strengths": list of 3-5 major strengths
2. "main_problems": list of (problem, priority) tuples where priority is P1/P2/P3
3. "improvement_potential": description of achievable improvement level
4. "estimated_revision_time_hours": hours to implement all recommendations

Be specific and actionable. Focus on problems that affect core contribution (P1 > P2 > P3).
"""
        
        response = self._call_llm(prompt)
        
        try:
            result = json.loads(response)
        except json.JSONDecodeError:
            # Fallback if LLM doesn't return valid JSON
            result = {
                "strengths": ["Structure present", "Methods described"],
                "main_problems": [("Analysis pending", "P1")],
                "improvement_potential": "Detailed analysis needed",
                "estimated_revision_time_hours": 6.0,
            }
        
        return result
    
    def _analyze_section(self, section_text: str, section_name: str, paper_title: str) -> dict[str, Any]:
        """Analyze individual section using LLM."""
        
        prompt = f"""Analyze the {section_name} section of a research paper and identify revision problems.

Paper: {paper_title}
Section: {section_name}

---
SECTION TEXT:
{section_text[:2000]}...

---

Provide analysis in JSON format with:
1. "current_state": brief description of what's there now
2. "problems": list of objects with:
   - "problem_id": e.g., "section-1"
   - "title": short title
   - "description": detailed description
   - "location": where in section (paragraph, line range)
   - "before_text": current text excerpt
   - "after_text": suggested revision
   - "explanation": why change helps
   - "severity": P1/P2/P3
3. "structural_recommendations": list of structural improvements
4. "quality_score": 1-10 (where 10 is excellent)
5. "improvement_potential": 1-10 (where 10 is vast room for improvement)

Be specific with location. Provide 2-4 problems per section maximum.
"""
        
        response = self._call_llm(prompt)
        
        try:
            result = json.loads(response)
        except json.JSONDecodeError:
            result = {
                "current_state": f"{len(section_text)} characters",
                "problems": [],
                "structural_recommendations": [],
                "quality_score": 6.0,
                "improvement_potential": 7.0,
            }
        
        return result
    
    def _generate_specific_edits(
        self,
        paper_text: str,
        section_analyses: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Generate specific edit suggestions."""
        # Collect top problems from section analyses
        problems = []
        for section_name, analysis in section_analyses.items():
            for problem in analysis.get("problems", []):
                problems.append({
                    "section": section_name,
                    **problem
                })
        
        return problems[:10]  # Return top 10 problems
    
    def _generate_structural_recs(
        self,
        paper_text: str,
        sections: dict[str, str]
    ) -> list[str]:
        """Generate structural recommendations."""
        
        prompt = f"""Review the structure of this research paper and provide 3-5 structural recommendations.

Sections present: {', '.join(sections.keys())}

Paper text preview (first 2000 chars):
{paper_text[:2000]}...

---

Provide recommendations as a JSON list of strings, e.g.:
["Merge Related Work insights into Introduction for clearer positioning", ...]

Focus on:
- Missing sections
- Section ordering issues
- Duplication across sections
- Organization improvements

Provide realistic recommendations only (not global rewrites).
"""
        
        response = self._call_llm(prompt)
        
        try:
            result = json.loads(response)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass
        
        return ["Further structural review needed"]
    
    def _identify_evidence_gaps(self, paper_text: str) -> list[dict[str, str]]:
        """Identify gaps in evidence and citations."""
        
        prompt = f"""Review this paper for evidence and citation gaps.

Paper text (first 3000 chars):
{paper_text[:3000]}...

---

Provide analysis as JSON list of objects with:
- "location": where in paper (e.g., "Abstract, paragraph 2")
- "claim": the claim made
- "gap": what evidence is missing
- "fix": how to fix it

Example:
[{{"location": "Intro, para 3", "claim": "Method is 50% faster", "gap": "No timing data provided", "fix": "Add benchmark results showing X ms vs Y ms"}}]

Identify 3-5 key evidence gaps maximum.
"""
        
        response = self._call_llm(prompt)
        
        try:
            result = json.loads(response)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass
        
        return []
    
    def _identify_writing_improvements(self, paper_text: str) -> list[dict[str, str]]:
        """Identify writing quality issues."""
        
        prompt = f"""Review this paper for writing quality issues: passive voice, jargon, vague quantifiers, clarity.

Paper text (first 2000 chars):
{paper_text[:2000]}...

---

Provide as JSON list of objects with:
- "issue": type of issue (passive voice, jargon, vague, clarity, etc.)
- "before": original text example
- "after": improved version
- "explanation": why better

Identify 3-5 key issues maximum.
"""
        
        response = self._call_llm(prompt)
        
        try:
            result = json.loads(response)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass
        
        return []
    
    def _generate_revision_checklist(
        self,
        overall_assessment: dict,
        section_analyses: dict,
        evidence_gaps: list
    ) -> dict[str, list]:
        """Generate prioritized revision checklist."""
        
        checklist = {
            "Critical": [],
            "Important": [],
            "Nice-to-have": [],
        }
        
        # Extract critical problems from overall assessment
        for problem, priority in overall_assessment.get("main_problems", []):
            if priority == "P1":
                checklist["Critical"].append(problem)
            elif priority == "P2":
                checklist["Important"].append(problem)
            else:
                checklist["Nice-to-have"].append(problem)
        
        # Add section-specific tasks
        for section_name, analysis in section_analyses.items():
            for rec in analysis.get("structural_recommendations", [])[:2]:
                checklist["Important"].append(f"{section_name}: {rec}")
        
        # Add evidence gap tasks
        for gap in evidence_gaps[:3]:
            checklist["Important"].append(f"Evidence: {gap.get('location', 'Unknown')} - {gap.get('fix', 'Add support')}")
        
        return checklist
    
    def _extract_sections(self, text: str) -> dict[str, str]:
        """Extract paper sections."""
        sections = {}
        common_headers = [
            "abstract", "introduction", "related work", "background",
            "methodology", "method", "experiments", "results", 
            "discussion", "conclusion", "limitations"
        ]
        
        text_lower = text.lower()
        
        for i, header in enumerate(common_headers):
            start = text_lower.find(header)
            if start == -1:
                continue
            
            # Find end (next section)
            end = len(text)
            for next_header in common_headers[i+1:]:
                next_start = text_lower.find(next_header, start + 1)
                if next_start != -1:
                    end = min(end, next_start)
            
            section_content = text[start:end].strip()
            sections[header.title()] = section_content
        
        return sections
    
    def _call_llm(self, prompt: str) -> str:
        """Call LLM with prompt."""
        
        if self.backend == "claude":
            message = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            return message.content[0].text
        
        elif self.backend == "openai":
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=2000,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
            )
            return response.choices[0].message.content
        
        else:
            raise ValueError(f"Unknown backend: {self.backend}")


def main():
    """CLI for LLM-powered revision analysis."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Analyze paper with LLM")
    parser.add_argument("paper_file", help="Path to paper (TXT or extracted)")
    parser.add_argument("--backend", choices=["claude", "openai"], default="claude")
    parser.add_argument("--output", "-o", help="Output JSON file")
    parser.add_argument("--title", "-t", help="Paper title")
    parser.add_argument("--feedback", "-f", help="User feedback")
    
    args = parser.parse_args()
    
    # Read paper
    paper_text = Path(args.paper_file).read_text(encoding="utf-8")
    
    # Analyze
    analyzer = LLMRevisionAnalyzer(backend=args.backend)
    print(f"Analyzing paper with {args.backend}...")
    result = analyzer.analyze_paper(
        paper_text,
        title=args.title or Path(args.paper_file).stem,
        user_feedback=args.feedback,
    )
    
    # Output
    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"✅ Saved to {args.output}")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
