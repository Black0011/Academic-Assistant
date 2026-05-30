"""Integration tests for paper-revision skill."""
import sys
import json
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))


def test_revision_analyzer_dataclasses():
    """Test that dataclasses module loads and works."""
    from scripts.revision_analyzer import (
        RevisionProblem, ProblemSeverity, ProblemType,
        SectionAnalysis, OverallAssessment, RevisionGuidance,
        RevisionAnalyzer
    )
    
    # Create example problem
    problem = RevisionProblem(
        section="Introduction",
        problem_id="intro-1",
        problem_type=ProblemType.STRUCTURAL,
        severity=ProblemSeverity.P1_CRITICAL,
        title="Background too long",
        description="First two paragraphs are standard material",
        location="Paragraph 1-2",
        before_text="RL has been widely applied...",
        after_text="In multi-task RL, agents struggle with...",
        explanation="Moves directly to problem",
        expected_impact="30% reduction in length"
    )
    
    # Test to_dict
    d = problem.to_dict()
    assert d["problem_id"] == "intro-1"
    assert d["severity"] == "P1 - Critical"
    print("✅ RevisionProblem dataclass works")
    
    # Test to_markdown
    md = problem.to_markdown()
    assert "Background too long" in md
    assert "Paragraph 1-2" in md
    print("✅ RevisionProblem.to_markdown() works")
    
    # Test RevisionAnalyzer with example
    analyzer = RevisionAnalyzer(
        paper_title="Test Paper",
        paper_id="test-001"
    )
    guidance = analyzer.example_guidance()
    assert guidance.paper_title == "Dynamic Routing for Multi-Task RL"
    print("✅ RevisionAnalyzer.example_guidance() works")
    
    # Test markdown output
    md_output = guidance.to_markdown()
    assert "Overall Assessment" in md_output
    assert "Introduction" in md_output
    print("✅ RevisionGuidance.to_markdown() works")
    
    # Test dict output
    dict_output = guidance.to_dict()
    assert dict_output["paper_title"] == "Dynamic Routing for Multi-Task RL"
    print("✅ RevisionGuidance.to_dict() works")


def test_paper_revision_engine():
    """Test basic PaperRevisionEngine functionality."""
    from paper_revision_impl import PaperRevisionEngine, RevisionRequest
    
    engine = PaperRevisionEngine()
    print("✅ PaperRevisionEngine instantiates")
    
    # Test request creation
    request = RevisionRequest(
        draft_file="test.pdf",
        user_feedback="Improve clarity",
        revision_round=1
    )
    assert request.draft_file == "test.pdf"
    print("✅ RevisionRequest works")


def test_example_markdown_generation():
    """Test generating example markdown output."""
    from scripts.revision_analyzer import RevisionAnalyzer
    from pathlib import Path
    
    analyzer = RevisionAnalyzer("Test Paper", "test-001")
    guidance = analyzer.example_guidance()
    
    md = guidance.to_markdown()
    
    # Verify key sections
    assert "# Paper Revision Guidance" in md
    assert "# Overall Assessment" in md
    assert "## Evidence & Citation Gaps" in md
    assert "## Writing & Clarity Improvements" in md
    assert "## Revision Checklist" in md
    
    print("✅ Example markdown output complete and well-formed")
    
    # Write to file for manual inspection
    output_file = Path(__file__).parent / "example_revision_guidance.md"
    output_file.write_text(md, encoding="utf-8")
    print(f"✅ Example output saved to {output_file}")


def test_reference_guidelines():
    """Verify reference guidelines file is complete."""
    from pathlib import Path
    
    guidelines_file = Path(__file__).parent / "references" / "revision_guidelines.md"
    assert guidelines_file.exists(), f"Guidelines not found: {guidelines_file}"
    
    content = guidelines_file.read_text(encoding="utf-8")
    
    # Verify key sections
    sections = [
        "Part A: General Revision Principles",
        "Part B: Section-Specific Revision Guide",
        "Introduction Revision Checklist",
        "Related Work Revision Checklist",
        "Methodology Revision Checklist",
        "Experiments Revision Checklist",
        "Part C: Cross-Cutting Revision Issues",
        "Part D: Writing Quality Improvements",
    ]
    
    for section in sections:
        assert section in content, f"Missing section: {section}"
    
    print("✅ Reference guidelines complete")


def test_evals_schema():
    """Verify evaluation cases are well-formed."""
    import json
    from pathlib import Path
    
    evals_file = Path(__file__).parent / "evals" / "evals.json"
    assert evals_file.exists(), f"Evals not found: {evals_file}"
    
    with open(evals_file, "r", encoding="utf-8") as f:
        evals_data = json.load(f)
    
    assert "skill_name" in evals_data
    assert evals_data["skill_name"] == "paper-revision"
    assert "evals" in evals_data
    assert len(evals_data["evals"]) == 5
    
    # Check each eval
    for i, eval_case in enumerate(evals_data["evals"], 1):
        assert "id" in eval_case
        assert "name" in eval_case
        assert "prompt" in eval_case
        assert "expected_output" in eval_case
        assert "expectations" in eval_case
        assert isinstance(eval_case["expectations"], list)
    
    print(f"✅ Evaluation cases well-formed ({len(evals_data['evals'])} cases)")


if __name__ == "__main__":
    print("Running paper-revision integration tests...\n")
    
    try:
        test_revision_analyzer_dataclasses()
        print()
        
        test_paper_revision_engine()
        print()
        
        test_example_markdown_generation()
        print()
        
        test_reference_guidelines()
        print()
        
        test_evals_schema()
        print()
        
        print("=" * 50)
        print("✅ All integration tests passed!")
        print("=" * 50)
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
