# Paper Revision Guidelines — 论文修改指南

This document provides comprehensive guidance for analyzing and revising research papers across all sections. Use these guidelines to diagnose problems and generate actionable revision recommendations.

---

## Part A: General Revision Principles

### 1. Problem Diagnosis Framework

**Categorize each problem by type and severity**:

| Problem Type | Definition | Example | Severity |
|---|---|---|---|
| **Logical** | Argument flow breaks, claims unsupported | Gap analysis doesn't lead to core idea | P1 |
| **Structural** | Section organization unclear, duplication | Related Work overlaps with Methodology | P1 |
| **Evidential** | Missing data, insufficient support | "Method is efficient" without timing data | P1 |
| **Clarity** | Jargon overload, complex wording | Dense technical sentences; passive voice | P2 |
| **Style** | Tone, consistency, writing quality | Inconsistent notation; poor figure captions | P3 |

**Apply this framework consistently**:
- P1 (Critical): Affects core contribution assessment
- P2 (Important): Affects paper clarity and rigor
- P3 (Nice-to-have): Polish and style

### 2. The "Show, Don't Tell" Principle

**Common Problem**: Abstract statement
```
"Our method is more efficient than prior work."
```

**Diagnosis**: No quantification, no context
```
✗ Better way: "Our method is more efficient"
✓ Best way: "DR-MTRL achieves 45% speedup (2.1s vs 3.8s) over DR-Fixed 
            on average across 4 benchmark environments, while maintaining 
            competitive accuracy."
```

**Revision Strategy**:
1. Identify all quantitative claims
2. For each claim, ask: "Where is the number?"
3. If missing: add experiment result or cite source
4. If not applicable: rephrase as qualitative claim

### 3. The "Why → What → How" Arc

Every section should follow this narrative:

```
Why (Motivation): What problem are we solving?
What (Core Idea): What's our key insight?
How (Methodology): How do we implement it?
```

**Check each paragraph for this arc**:
- Does paragraph 1 establish a problem?
- Does paragraph 2 propose a solution?
- Does paragraph 3 explain the implementation?

**If missing**: The section feels unmotivated or technical.

---

## Part B: Section-Specific Revision Guide

### Introduction Revision Checklist

**Common Problems & Fixes**:

1. **Background too long**
   - Problem: First 2-3 paragraphs are all background
   - Fix: Cut background in half; start with specific problem
   - Before: "Reinforcement learning has been widely applied... [standard textbook material]"
   - After: "In multi-task RL, agents struggle with task interference, showing 40-60% accuracy drops on mixed benchmarks [CITE]. We address this through dynamic routing."
   - Expected gain: 30% reduction in intro length, 100% improvement in urgency

2. **Gap analysis vague**
   - Problem: Says "existing methods don't handle X well" but no specifics
   - Fix: Add one concrete example or dataset failure
   - Before: "Prior work struggles with multi-task adaptation."
   - After: "Prior work shows parameter sharing across tasks improves efficiency by 20%, but at 15-25% accuracy cost on diverse task combinations [CITE, CITE]. Task-conditional approaches isolate tasks but lose efficiency."
   - Validation: Reader can now explain the problem to others

3. **Core idea buried**
   - Problem: Key insight appears in paragraph 4 or 5
   - Fix: Move to paragraph 2-3; introduce with clarity aid
   - Before: "[Paragraph about background] [Paragraph about gap] [Paragraph about another gap] [Paragraph that finally says our idea]"
   - After: "[Quick background hook] [Core idea with intuition] [Why this idea addresses the gap] [What it enables]"
   - Expected gain: 40% faster reader comprehension

4. **Contributions list weak**
   - Problem: Contributions lack specificity or novelty markers
   - Before: "1. We propose a new method. 2. We conduct experiments."
   - After: 
     ```
     1. **[Method] Dynamic Routing for Multi-Task RL**: A novel architecture 
        that adaptively selects routing strategies per state and task, 
        improving both efficiency and accuracy.
     2. **[Analysis] Theoretical Foundation**: We analyze routing in multi-task 
        settings and prove convergence under X assumptions.
     3. **[Empirical] Comprehensive Benchmarks**: We evaluate DR-MTRL on 4 
        simulator environments and 2 real robot tasks, showing 45% speedup 
        with competitive accuracy.
     ```

**Introduction Quality Checklist**:
- [ ] Paragraph 1: Hook (1 compelling problem or stat)
- [ ] Paragraph 2: Why it matters (industry relevance or research gap)
- [ ] Paragraph 3: Existing approaches and their limitations
- [ ] Paragraph 4: Our core idea + intuition
- [ ] Paragraph 5: Contributions (numbered, specific, novel markers)
- [ ] Paragraph 6: Paper organization
- [ ] Total length: 400-600 words

---

### Related Work Revision Checklist

**Common Problems & Fixes**:

1. **Over-lengthy, under-focused**
   - Problem: 6-8 pages, lists many papers but weak positioning
   - Fix: Cut to 2-3 pages, organize by research direction, add "where we fit" for each
   - Organization example:
     ```
     ## Related Work
     
     ### Multi-Task Learning
     [2-3 representative papers]
     - Paper A: Approach X, limitation Y
     - Paper B: Approach X', solves Y but not Z
     - **Our positioning**: We also use task-conditional features (like B) 
       but propose dynamic routing (novel element).
     
     ### Policy Optimization
     [2-3 representative papers]
     - Paper C: Uses method M, achieves result R
     - Paper D: Extends M to multi-task, shows trade-off T
     - **Our positioning**: Unlike C/D which fix routing strategy, we 
       adapt routing per state, achieving better scaling.
     ```

2. **Duplication with Methodology**
   - Problem: Related work discusses "how to design routing," but so does Methodology
   - Fix: Clear boundary — Related Work explains prior approaches, Methodology explains yours
   - Before: [Related Work § discusses 5 different routing designs]
   - After: [Related Work § names them, Methodology § compares yours vs. them detail]

3. **Positioning unclear**
   - Problem: Reads as list of papers, not as narrative
   - Fix: Explicit positioning after each subsection
   - Add: "Unlike [A] and [B] which [limitation], we [solution]."

**Related Work Quality Checklist**:
- [ ] Length: 2-3 pages (not 6-8)
- [ ] Organized by research direction (not chronological)
- [ ] 3-5 papers per direction, not 20+
- [ ] Each direction has "where we fit" summary
- [ ] No duplication with Methodology section
- [ ] Clear boundary: Related Work (prior art), Methodology (our contribution)

---

### Methodology Revision Checklist

**Common Problems & Fixes**:

1. **Problem definition fuzzy**
   - Problem: Unclear what exactly is being solved
   - Fix: Formal problem statement with clear notation
   - Before: "We want to find a good routing policy."
   - After: 
     ```
     Problem: Given a multi-task environment with task set T = {t₁, ..., tₙ}, 
     state space S, and action space A, find a routing policy π_r: S × T → [0,1]^K 
     (where K is # routing options) that maximizes expected cumulative reward 
     R = Σ γ^t r(s_t, a_t, t) while minimizing computational cost C.
     ```

2. **Method explanation too dense**
   - Problem: 10 paragraphs of continuous technical text, no structure
   - Fix: Break into subsections with clear transitions
   - Structure: [Problem Definition] → [Intuition/Motivation] → [Formal Framework] 
     → [Algorithm] → [Theoretical Properties]

3. **Missing algorithm/pseudocode**
   - Problem: Only prose description, no formal algorithm
   - Fix: Add Algorithm box with clear pseudocode
   ```
   Algorithm 1: Dynamic Routing for Multi-Task RL
   
   Input: state s, task t, routing network π_r
   Output: selected routing option r
   
   1. Encode state: s_enc ← encoder(s)
   2. Get routing logits: z ← π_r(s_enc, t)
   3. Sample or argmax: r ← softmax(z)
   4. Execute: a ← π_r(s, t, r)
   5. Return: (r, a)
   ```

4. **Notation inconsistency**
   - Problem: Same variable called "a", "action", "a_t" in different paragraphs
   - Fix: Create notation table at section start
   ```
   ## Notation
   
   | Symbol | Meaning | Dimension |
   |--------|---------|-----------|
   | s | state | d_s |
   | t | task index | scalar ∈ [1,K] |
   | a | action | d_a |
   | π_r | routing policy | K → [0,1] |
   | θ | learned parameters | varies |
   ```

**Methodology Quality Checklist**:
- [ ] Problem formally defined with clear symbols
- [ ] Intuition explained before technical details
- [ ] Method broken into logical subsections (not one dense paragraph)
- [ ] Algorithm or pseudocode provided
- [ ] Notation consistent and defined upfront
- [ ] Comparison to baseline methods clear (why our choice better)
- [ ] Implementation details sufficient for reproduction

---

### Experiments Revision Checklist

**Common Problems & Fixes**:

1. **Experimental setup under-described**
   - Problem: Reader can't reproduce results
   - Fix: Detailed subsection for each element
   ```
   ### Experimental Setup
   
   **Environments**: 
   - Atari (10 games): Breakout, Pong, Space Invaders, ...
   - DeepMind Control Suite (8 tasks): Walker, Cheetah, ...
   - Real Robot (2 tasks): Reaching, Pushing
   
   **Baselines**:
   - DR-Random: Routing uniformly at random (lower bound)
   - DR-Fixed: Fixed routing per task (common practice)
   - MTL-Shared: Shared task-agnostic policy (standard)
   - TCN: Task-conditional network (SOTA) [CITE]
   
   **Hyperparameters**:
   - Learning rate: 0.001
   - Batch size: 32
   - Routing network hidden: 256
   - Number of runs: 5 (± std dev reported)
   ```

2. **Results table hard to read**
   - Problem: Table has 12 columns, unclear which is main metric, no emphasis
   - Fix: Redesign for clarity
   ```
   Before:
   | Method | Atari-1 | Atari-2 | ... | Avg | Time |
   | A | 0.45 | 0.67 | ... | 0.55 | 2.1s |
   
   After:
   | Method | Main Accuracy ↑ | Speedup ↑ | Env Coverage |
   | DR-Random | 0.42 | 1.0x | 4/10 |
   | DR-Fixed | 0.45 | 0.8x | 6/10 |
   | TCN (SOTA) | 0.52 | 0.5x | 8/10 |
   | **DR-MTRL (Ours)** | **0.58** | **0.9x** | **10/10** |
   ```

3. **No ablation study**
   - Problem: Unclear which components contribute to performance
   - Fix: Add ablation table
   ```
   ## Ablation Study
   
   | Configuration | Accuracy | Speedup | Notes |
   |---|---|---|---|
   | w/o dynamic routing | 0.45 | 1.0x | (baseline) |
   | + routing learning | 0.51 | 0.9x | improves routing |
   | + state encoder | 0.55 | 0.85x | better state rep |
   | + task embedding | 0.58 | 0.9x | full model |
   ```

4. **Analysis missing**
   - Problem: Just presents numbers, no insight into why method works
   - Fix: Add analysis section with case studies
   ```
   ## Analysis
   
   ### When does DR-MTRL win?
   - High-diversity task sets (> 5 distinct tasks)
   - Tasks with shared state representation
   - Environments where routing overhead < 10% of inference time
   
   ### When does it lose?
   - Single-task settings (unnecessary overhead)
   - Very diverse tasks (routing overhead exceeds routing quality benefit)
   
   ### Case Study: Atari Games
   [Detailed analysis of 2-3 games showing how routing adapts]
   ```

**Experiments Quality Checklist**:
- [ ] Environments: Described with number/names
- [ ] Baselines: 3+ including SOTA
- [ ] Hyperparameters: Complete, reproducible
- [ ] Statistical significance: Error bars or p-values
- [ ] Main results: Clear winner, quantified
- [ ] Ablation: All major components tested
- [ ] Analysis: Why does method work? When does it fail?
- [ ] Reproducibility: Sufficient detail to reimplement

---

### Discussion Revision Checklist

**Common Problems & Fixes**:

1. **Discussion too brief or missing**
   - Problem: 1 paragraph or just restate results
   - Fix: Add 2-3 subsections: [Implications] [Limitations] [Future Work]
   ```
   ## Discussion
   
   ### Implications for Multi-Task RL
   Our results suggest that adaptive routing is more effective than... 
   [2-3 sentences synthesizing key findings]
   
   ### Limitations
   - **Computation**: Routing overhead (X%) may not justify gains in faster inference settings
   - **Generalization**: Tested on discrete action spaces; continuous control domain unknown
   - **Scalability**: K > 10 routing options untested; memory/time complexity unclear
   
   ### Future Work
   - Extend to continuous action spaces (quadruped, manipulation)
   - Theoretical analysis of routing in RL convergence
   - Hybrid architectures combining routing with attention mechanisms
   ```

2. **Limitations defensively stated or missing**
   - Problem: No mention of when method doesn't work
   - Fix: Proactively list limitations with mitigation strategies
   - Before: [Nothing said]
   - After: 
     ```
     We acknowledge three main limitations:
     1. Routing overhead (X%) limits applicability to very fast inference settings. 
        Future work could optimize the routing network architecture.
     2. Our experiments use discrete action spaces. Continuous control is future work.
     3. Scalability to > 10 tasks untested; memory usage grows quadratically.
     ```

**Discussion Quality Checklist**:
- [ ] 2-3 subsections (Implications / Limitations / Future)
- [ ] Limitations proactively stated (not defensive)
- [ ] Mitigation strategies for each limitation mentioned
- [ ] Future work concrete and grounded in current work
- [ ] Connects results back to motivating problem from Intro

---

## Part C: Cross-Cutting Revision Issues

### Evidence & Citation Quality

**Checklist for every quantitative claim**:

```
Claim: "Multi-task RL agents suffer from task interference."

Evidence checklist:
- [ ] Is this cited? If not: add citation [CITE-Park2020]
- [ ] Is a number provided? If not: add "Studies show 40-60% accuracy drops..."
- [ ] Is the source reliable? If not: find peer-reviewed paper
- [ ] Is the context clear? If not: explain "on diverse Atari games, parameter sharing..."
```

**Citation best practices**:
- Use academic citations (ICLR, CVPR, NeurIPS papers)
- Avoid relying solely on arXiv papers
- Cite recent work (within 3 years) + foundational work
- Balance your own citations (1-2) with others (8-12 per section)

### Figure & Table Quality

**Before submitting, audit all figures**:

1. Captions too brief
   - Before: "Routing performance"
   - After: "DR-MTRL routing accuracy across 10 Atari games, showing 58% mean accuracy compared to 45% for fixed routing (dashed line). Error bars show ±1 std dev over 5 runs."

2. Figure readability
   - Check: Can you read labels on screen at 5cm distance?
   - If not: increase font size to 12pt minimum
   - Add legend, grid, units on axes

3. Table organization
   - Bold row/column headers
   - Right-align numbers for easier comparison
   - Add units (%, ms, points)
   - Highlight best result with **bold**

---

## Part D: Writing Quality Improvements

### Clarity Issues & Fixes

| Issue | Before | After | Why |
|-------|--------|-------|-----|
| Passive voice | "The method was evaluated on..." | "We evaluated our method on..." | Active voice = clarity + directness |
| Vague quantifiers | "Many approaches exist" | "Five prior approaches [CITE]..." | Specificity aids precision |
| Jargon overload | "We employ a gating mechanism for policy parameterization" | "We use a gating network to select which policy to execute" | Simpler phrasing without losing meaning |
| Missing transition | "...baseline achieves 0.45. [New sentence with no connection] The overhead is 2.1s" | "...baseline achieves 0.45. Despite this baseline performance, the overhead is 2.1s, which..." | Explicit connectors maintain flow |
| Weak verb | "This work has implications" | "This work enables faster multi-task RL" | Specific action verb > passive "has" |

### Consistency Checklist

- [ ] Notation: Same symbol for same concept throughout
- [ ] Terminology: "method" vs "approach" vs "algorithm" used consistently
- [ ] Tense: Past tense for experiments, present for descriptions
- [ ] Style: Consistent abbreviation use (RL not RL and Reinforcement Learning mixed)
- [ ] Citations: Same style throughout (Author 2020 or [#] format)

---

## Part E: Revision Workflow

### The "Edit → Review → Repeat" Cycle

1. **Make all P1 edits** (1-2 hours)
   - Delete duplication
   - Add missing algorithms
   - Strengthen evidence

2. **Review for clarity** (30 min)
   - Read introduction aloud
   - Check paragraph transitions
   - Verify all jargon explained

3. **Final proofing** (30 min)
   - Run spell check
   - Verify formatting
   - Check citation format

4. **Get external review** (ideal: 24 hours)
   - Have someone read Introduction + Methodology
   - Ask: "Could you explain the core idea in 2 sentences?"
   - If they can't: revise for clarity

---

