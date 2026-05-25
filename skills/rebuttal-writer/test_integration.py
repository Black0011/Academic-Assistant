"""Integration tests for rebuttal-writer skill."""
import sys
import json
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))


def test_dataclasses():
    """Test that dataclasses module loads and works."""
    from rebuttal_writer_impl import (
        ReviewerComment, ReviewerFeedback, ResponseStrategy,
        CommentResponse, RebuttalLetter
    )
    
    # Create example comment
    comment = ReviewerComment(
        comment_id="R1-1",
        comment="How does your method handle multi-task settings differently?",
        section="methodology",
        severity="major"
    )
    assert comment.comment_id == "R1-1"
    print("✅ ReviewerComment dataclass works")
    
    # Create example feedback
    feedback = ReviewerFeedback(
        reviewer_id="R1",
        comments=[comment]
    )
    assert feedback.reviewer_id == "R1"
    assert len(feedback.comments) == 1
    print("✅ ReviewerFeedback dataclass works")
    
    # Create example strategy
    strategy = ResponseStrategy(
        strategy_type="defend",
        assessment="Valid concern about novelty",
        response_outline="Our approach differs in X ways..."
    )
    assert strategy.strategy_type == "defend"
    print("✅ ResponseStrategy dataclass works")


def test_rebuttal_engine():
    """Test basic RebuttalWriterEngine functionality."""
    from rebuttal_writer_impl import RebuttalWriterEngine, ReviewerComment, ReviewerFeedback
    
    engine = RebuttalWriterEngine()
    print("✅ RebuttalWriterEngine instantiates")
    
    # Test comment parsing
    comment = ReviewerComment(
        comment_id="C1",
        comment="Please clarify the methodology",
        section="methodology",
        severity="minor"
    )
    assert comment.comment_id == "C1"
    print("✅ Comment parsing works")
    
    # Test strategy diagnosis
    strategy = engine.diagnose_comment(comment, "Sample paper text")
    assert strategy.strategy_type in ["clarify", "defend", "concede"]
    print("✅ Strategy diagnosis works")


def test_rebuttal_letter_generation():
    """Test generating a rebuttal letter."""
    from rebuttal_writer_impl import (
        RebuttalWriterEngine, ReviewerComment, ReviewerFeedback
    )
    
    engine = RebuttalWriterEngine()
    
    # Create sample comments
    comments = [
        ReviewerComment(
            comment_id="R1-1",
            comment="Method is not sufficiently novel compared to prior work",
            section="introduction",
            severity="major"
        ),
        ReviewerComment(
            comment_id="R1-2",
            comment="Table 3 is hard to read",
            section="experiments",
            severity="minor"
        )
    ]
    
    feedback = ReviewerFeedback(
        reviewer_id="Reviewer 1",
        comments=comments
    )
    
    # Generate rebuttal
    rebuttal = engine.generate_rebuttal(
        paper_id="test-001",
        paper_title="Test Paper",
        reviewer_feedback=[feedback],
        revised_paper_text="Sample revised paper content",
    )
    
    assert rebuttal.paper_id == "test-001"
    assert rebuttal.paper_title == "Test Paper"
    assert len(rebuttal.reviewer_responses) == 2
    print("✅ Rebuttal letter generation works")
    
    # Test markdown output
    md = rebuttal.to_markdown()
    assert "Test Paper" in md
    assert "Rebuttal Letter" in md
    print("✅ Rebuttal markdown output works")
    
    # Test dict output
    d = rebuttal.to_dict()
    assert d["paper_title"] == "Test Paper"
    print("✅ Rebuttal dict output works")


def test_markdown_output():
    """Test generating example markdown output."""
    from rebuttal_writer_impl import (
        RebuttalWriterEngine, ReviewerComment, ReviewerFeedback
    )
    
    engine = RebuttalWriterEngine()
    
    # Create comprehensive example
    comments_r1 = [
        ReviewerComment(
            comment_id="R1-1",
            comment="The related work section conflates your method with prior work. Please clarify the key differences.",
            section="related_work",
            severity="major"
        ),
        ReviewerComment(
            comment_id="R1-2",
            comment="Missing comparison with baseline X on dataset Y",
            section="experiments",
            severity="major"
        ),
    ]
    
    comments_r2 = [
        ReviewerComment(
            comment_id="R2-1",
            comment="Notation in Equation 3 is inconsistent with Section 2",
            section="methodology",
            severity="minor"
        ),
    ]
    
    feedback1 = ReviewerFeedback(
        reviewer_id="Reviewer 1",
        comments=comments_r1
    )
    
    feedback2 = ReviewerFeedback(
        reviewer_id="Reviewer 2",
        comments=comments_r2
    )
    
    rebuttal = engine.generate_rebuttal(
        paper_id="example-001",
        paper_title="Dynamic Routing for Multi-Task RL",
        reviewer_feedback=[feedback1, feedback2],
        revised_paper_text="This is sample content from the revised paper.",
    )
    
    md = rebuttal.to_markdown()
    
    # Verify key sections
    assert "# Rebuttal Letter" in md
    assert "Reviewer 1" in md
    assert "Reviewer 2" in md
    assert "Opening Statement" in md
    assert "Summary of Changes" in md
    
    print("✅ Example markdown output complete")
    
    # Save to file
    output_file = Path(__file__).parent / "example_rebuttal.md"
    output_file.write_text(md, encoding="utf-8")
    print(f"✅ Example output saved to {output_file}")


def test_feedback_parsing():
    """Test parsing various feedback formats."""
    from rebuttal_writer_impl import RebuttalWriterEngine
    
    engine = RebuttalWriterEngine()
    
    # Format 1: reviewer_feedback structure
    feedback_data_1 = {
        "reviewer_feedback": {
            "comments": [
                {
                    "comment_id": "C1",
                    "comment": "Question about methodology",
                    "section": "methodology",
                    "severity": "major"
                }
            ]
        }
    }
    
    feedback1 = engine.parse_reviewer_feedback(feedback_data_1)
    assert len(feedback1) == 1
    assert len(feedback1[0].comments) == 1
    print("✅ Feedback format 1 parsing works")
    
    # Format 2: reviewers structure
    feedback_data_2 = {
        "reviewers": [
            {
                "reviewer_id": "R1",
                "comments": [
                    {
                        "comment_id": "R1-1",
                        "comment": "First comment",
                        "severity": "minor"
                    }
                ]
            }
        ]
    }
    
    feedback2 = engine.parse_reviewer_feedback(feedback_data_2)
    assert len(feedback2) == 1
    assert feedback2[0].reviewer_id == "R1"
    print("✅ Feedback format 2 parsing works")


if __name__ == "__main__":
    print("Running rebuttal-writer integration tests...\n")
    
    try:
        test_dataclasses()
        print()
        
        test_rebuttal_engine()
        print()
        
        test_rebuttal_letter_generation()
        print()
        
        test_markdown_output()
        print()
        
        test_feedback_parsing()
        print()
        
        print("=" * 50)
        print("✅ All integration tests passed!")
        print("=" * 50)
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
