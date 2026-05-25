"""
LLM-Powered Rebuttal Analysis: Use Claude or OpenAI to generate high-quality rebuttals.

Handles:
- Strategy selection (clarify vs. defend vs. concede)
- Response generation with evidence integration
- Tone and professionalism optimization
- Multi-reviewer coordination and deduplication
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Any, List, Dict
import os
import sys
from datetime import datetime

# Add project root to path
project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

from config.loader import load_config


class LLMRebuttalAnalyzer:
    """LLM-powered rebuttal analysis."""
    
    def __init__(self, backend: str = "claude", config_path: Optional[str] = None):
        """Initialize the LLM-powered rebuttal analyzer.
        
        Args:
            backend: "claude" or "openai"
            config_path: Path to config file
        """
        self.backend = backend.lower()
        self.config = load_config(config_path)
        self._init_client()
    
    def _init_client(self):
        """Initialize the LLM client."""
        if self.backend == "claude":
            try:
                import anthropic
                self.client = anthropic.Anthropic(
                    api_key=os.getenv("ANTHROPIC_API_KEY")
                )
                self.model = self.config.get("claude_model", "claude-3-5-sonnet-20241022")
            except ImportError:
                raise ImportError("Anthropic SDK required. Install: pip install anthropic")
        
        elif self.backend == "openai":
            try:
                import openai
                self.client = openai.OpenAI(
                    api_key=os.getenv("OPENAI_API_KEY")
                )
                self.model = self.config.get("openai_model", "gpt-4o-mini")
            except ImportError:
                raise ImportError("OpenAI SDK required. Install: pip install openai")
        
        else:
            raise ValueError(f"Unknown backend: {self.backend}")
    
    def analyze_comment(
        self,
        comment: str,
        paper_section: Optional[str] = None,
        paper_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Analyze a reviewer comment and determine response strategy.
        
        Args:
            comment: The reviewer comment
            paper_section: Which section of the paper it refers to
            paper_context: Relevant context from the paper
        
        Returns:
            Analysis result with strategy and explanation
        """
        prompt = f"""You are an expert in generating professional rebuttals to reviewer comments. 
Analyze the following reviewer comment and determine the best response strategy.

## Reviewer Comment
{comment}

{f"## Paper Section: {paper_section}" if paper_section else ""}

{f"## Paper Context\n{paper_context}" if paper_context else ""}

## Task
Determine which response strategy is most appropriate:
1. **Clarify**: The reviewer misunderstood or the presentation was unclear
2. **Defend**: We have evidence supporting our approach despite the concern
3. **Concede**: The reviewer raises a valid point we should acknowledge

Provide your analysis in JSON format with these fields:
- strategy: "clarify" | "defend" | "concede"
- rationale: Explanation of why you chose this strategy
- key_points: List of 2-3 key points for the response
- tone_guidance: How to phrase the response (e.g., "neutral and factual", "appreciative but confident")
"""
        
        response = self._call_llm(prompt)
        return self._parse_json_response(response)
    
    def generate_response(
        self,
        comment: str,
        strategy: str,
        paper_text: str,
        paper_section: Optional[str] = None,
        changes_made: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Generate a professional response to a reviewer comment.
        
        Args:
            comment: The reviewer comment
            strategy: Response strategy ("clarify", "defend", or "concede")
            paper_text: Full text of the revised paper
            paper_section: Which section the comment refers to
            changes_made: List of changes made in response to the comment
        
        Returns:
            Generated response with supporting evidence
        """
        prompt = f"""Generate a professional response to the following reviewer comment.

## Reviewer Comment
{comment}

## Response Strategy
Use a "{strategy}" strategy:
- "clarify": Address misunderstandings and clarify the paper's position
- "defend": Provide evidence supporting our approach while respectfully disagreeing
- "concede": Acknowledge the valid concern and explain how we addressed it

## Paper Context
Section: {paper_section or "General"}

{f"Changes made: {changes_made}" if changes_made else ""}

## Revised Paper (excerpt)
{paper_text[:2000]}...

## Task
Generate a response that:
1. Respectfully acknowledges the reviewer's concern
2. Provides clear reasoning and evidence
3. References specific sections/figures/tables in the paper
4. Maintains professional and collaborative tone
5. Is concise (2-4 paragraphs)

Provide in JSON format:
- assessment: Brief statement of the issue
- response: Full response text
- supporting_evidence: List of relevant paper sections/figures/tables
- evidence_strength: 0.0-1.0 confidence in the response
"""
        
        response = self._call_llm(prompt)
        return self._parse_json_response(response)
    
    def generate_opening_statement(self, paper_title: str, num_changes: int) -> str:
        """Generate opening statement for rebuttal letter.
        
        Args:
            paper_title: Title of the paper
            num_changes: Number of major changes made
        
        Returns:
            Opening statement text
        """
        prompt = f"""Generate a professional opening statement for a rebuttal letter.

## Paper
Title: {paper_title}
Major changes made: {num_changes}

## Task
Generate a 2-3 paragraph opening statement that:
1. Expresses gratitude to reviewers
2. Summarizes the key improvements made
3. Sets a collaborative, professional tone
4. Is concise and confident

Return ONLY the opening statement text, no JSON.
"""
        
        return self._call_llm(prompt)
    
    def generate_closing_statement(self, paper_title: str) -> str:
        """Generate closing statement for rebuttal letter.
        
        Args:
            paper_title: Title of the paper
        
        Returns:
            Closing statement text
        """
        prompt = f"""Generate a professional closing statement for a rebuttal letter to "{paper_title}".

The closing should:
1. Reiterate that all concerns have been addressed
2. Express confidence in the revised work
3. Thank reviewers again
4. Be 1-2 paragraphs

Return ONLY the closing statement text, no JSON.
"""
        
        return self._call_llm(prompt)
    
    def dedup_and_prioritize_comments(
        self,
        comments: List[Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        """Deduplicate and prioritize reviewer comments.
        
        Args:
            comments: List of reviewer comments
        
        Returns:
            Deduplicated and prioritized comments
        """
        if not comments:
            return []
        
        # Format comments for LLM
        formatted = "\n".join([
            f"{i+1}. [{c.get('reviewer_id', 'R?')}] {c.get('comment', '')}"
            for i, c in enumerate(comments)
        ])
        
        prompt = f"""Analyze these reviewer comments and:
1. Identify duplicates or very similar concerns
2. Group related comments
3. Prioritize by importance

## Comments
{formatted}

## Task
Return JSON with:
- groups: List of comment groups, each with:
  - group_id: Unique identifier
  - original_ids: List of original comment indices
  - key_issue: Summary of the issue
  - priority: "critical" | "important" | "minor"
  - recommended_strategy: Response strategy
"""
        
        response = self._call_llm(prompt)
        return self._parse_json_response(response, default=[])
    
    def _call_llm(self, prompt: str) -> str:
        """Call the LLM backend.
        
        Args:
            prompt: Prompt to send to LLM
        
        Returns:
            Response text
        """
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
                ]
            )
            return response.choices[0].message.content
    
    def _parse_json_response(self, text: str, default: Any = None) -> dict:
        """Parse JSON from LLM response.
        
        Args:
            text: Response text that should contain JSON
            default: Default value if parsing fails
        
        Returns:
            Parsed JSON as dict
        """
        try:
            # Try to extract JSON from response
            start_idx = text.find('{')
            end_idx = text.rfind('}') + 1
            
            if start_idx >= 0 and end_idx > start_idx:
                json_str = text[start_idx:end_idx]
                return json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            pass
        
        # Return default if parsing fails
        if default is None:
            return {"raw_response": text, "parse_error": True}
        return default


def main():
    """CLI interface for LLM rebuttal analysis."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="LLM-powered rebuttal analysis"
    )
    parser.add_argument("comment", help="Reviewer comment to analyze")
    parser.add_argument("--backend", "-b", default="claude", help="LLM backend (claude or openai)")
    parser.add_argument("--strategy", "-s", help="Response strategy (clarify, defend, concede)")
    parser.add_argument("--section", help="Paper section the comment refers to")
    parser.add_argument("--config", "-c", help="Path to config file")
    
    args = parser.parse_args()
    
    # Create analyzer
    analyzer = LLMRebuttalAnalyzer(args.backend, args.config)
    
    # Analyze comment
    print(f"Analyzing comment with {args.backend}...")
    result = analyzer.analyze_comment(args.comment, paper_section=args.section)
    
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
