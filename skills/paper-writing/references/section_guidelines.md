# Section Writing Guidelines — 各节详细写作指南

This document provides detailed guidance for writing each section of a research paper. Use this when generating section drafts.

---

## § 1. Abstract (150-250 words, 3-5 sentences)

### Structure

```
Sentence 1 (Background): What is the general field/problem?
  → 1 sentence, 20-30 words
  → Sets context without being too broad
  → Example: "Multi-task reinforcement learning (MTRL) has shown promise 
     in improving sample efficiency and enabling transfer learning."

Sentence 2 (Motivation): Why is the current approach insufficient?
  → 1 sentence, 20-30 words
  → Identifies a specific gap or limitation
  → Example: "However, existing MTRL methods suffer from negative transfer, 
     where learning multiple tasks simultaneously hurts individual task performance."

Sentence 3-4 (Method): What is your core idea?
  → 1-2 sentences, 30-50 words
  → High-level overview (no technical details)
  → Example: "We propose RoutingRL, which enables agents to dynamically 
     select task-specific and shared modules during execution."

Sentence 5 (Results): What are the main empirical findings?
  → 1 sentence, 20-30 words
  → Specific numbers, not vague claims
  → Example: "Experiments on 5 continuous control tasks show 
     30-45% improvements over prior MTRL methods."

Optional Sentence 6 (Impact): What is the broader significance?
  → Optional, if space permits
  → Example: "These results suggest that dynamic routing is a promising 
     direction for scalable multi-task learning."
```

### Quality Checklist

- [ ] **No forward references**: Don't cite figures or sections
- [ ] **Self-contained**: Can a reader understand it without reading the full paper?
- [ ] **Specific numbers**: Results include quantitative improvements, not just "significant"
- [ ] **No undefined jargon**: First mention of specialized terms should be explained or avoided
- [ ] **Active voice**: "We propose" not "A method is proposed"
- [ ] **Fits target length**: 150-250 words typically

### Common Mistakes & Fixes

| ❌ Wrong | ✅ Right |
|---------|----------|
| "Machine learning has made great progress." | "Multi-task reinforcement learning enables agents to leverage knowledge across tasks, but naive approaches suffer from negative transfer." |
| "We achieve significant improvements." | "We achieve 30-45% improvement on 5 continuous control benchmarks, with particularly strong gains on hard exploration tasks." |
| "The paper is organized as follows..." | (Don't use this in abstract; that's for introduction) |
| "Using our new technique..." | "We propose RoutingRL, a framework that..." |

---

## § 2. Introduction (2-4 pages)

### Recommended Structure

#### 2.1 Hook & Background (0.5-1 page)

**Purpose**: Establish credibility and motivate the reader.

**Structure**:
1. **Opening hook** (1-2 sentences): A striking fact, successful application, or clear problem statement
   - Example: "Recent advances in RL have achieved superhuman performance in complex games and robotic control. Yet deploying RL agents in real-world settings remains challenging: most agents are trained on a single task and fail catastrophically when facing new environments."

2. **General background** (2-3 sentences): The field and its achievements
   - Example: "Over the past decade, deep reinforcement learning has demonstrated remarkable success in various domains [CITE-1, CITE-2], from game-playing to continuous control [CITE-3]. These advances are built on algorithmic innovations (policy gradients, actor-critic methods) and increases in compute."

3. **Why it matters** (1-2 sentences): Real-world context or importance
   - Example: "However, the brittleness of RL systems limits their deployment in safety-critical applications. A robot trained to pour coffee may fail when given a slightly different cup or placement."

**Key points to cover**:
- ✅ Establish that the problem is worth solving
- ✅ Show that the field has made progress
- ✅ Indicate why further progress is important

**Common mistake**: Overloading with background. Remember: detailed background goes in **Related Work**.

#### 2.2 Gap Analysis: What's Missing? (0.5-1 page)

**Purpose**: Identify the specific limitation that your work addresses.

**Structure**:
1. **Existing approaches** (2-3 sentences): Describe relevant prior work categories
   - Example: "Existing multi-task RL approaches fall into two categories: (1) Parameter sharing, where all tasks use overlapping network weights [CITE-4, CITE-5], and (2) Task conditioning, where a task embedding modulates the policy [CITE-6]."

2. **Limitations of each approach** (2-3 sentences): Be specific about what doesn't work
   - Example: "Parameter sharing often leads to negative transfer [CITE-7]: shared representations hurt individual task performance. Task conditioning, while more flexible, requires learning task embeddings and assumes task descriptors are available at train time."

3. **The gap** (1 sentence): What's the unmet need?
   - Example: "What we lack is a method that can dynamically select which components to use *during execution*, enabling flexible task adaptation without negative transfer."

**Key points**:
- ✅ Be fair to prior work while being clear about limitations
- ✅ Avoid strawman criticisms ("Prior work is completely wrong")
- ✅ Frame the gap as an opportunity ("This suggests a new direction...")

#### 2.3 Our Core Idea (0.5 page)

**Purpose**: Present your key insight before diving into technical details.

**Structure**:
1. **One-liner** (1 sentence): The core idea in plain English
   - Example: "We propose RoutingRL: an approach where the agent learns to route information through task-specific and shared modules, dynamically assembling a task-appropriate computation graph."

2. **Intuition** (2-3 sentences): Why this idea is clever
   - Example: "The intuition is simple: rather than pre-committing to a fixed parameter-sharing scheme, let the agent decide *which* parts of its brain to use for each task at runtime. This is inspired by human learning—when you switch between writing in English and Chinese, you reuse some cognitive processes (e.g., planning) while activating different language-specific modules."

3. **Key advantage** (1-2 sentences): Why this is better
   - Example: "This approach avoids negative transfer by isolating task-specific learning while still enabling transfer through shared modules. The routing decisions are learned end-to-end, so no manual task engineering is needed."

**Key points**:
- ✅ Introduce the core idea before technical details
- ✅ Use analogy/intuition if it helps
- ✅ Emphasize why this solves the gap identified earlier

#### 2.4 Contributions (0.5 page)

**Purpose**: Clearly state what's novel and important about your work.

**Structure**: A bulleted list of 3-5 contributions, each with:
- A clear claim about what you've done
- Why it's novel (first to do X, first to prove Y, first to combine X and Y, etc.)
- Why it matters

**Format**:
```
1. **[Novelty type] [What]**: [Why it matters]
   - Novelty: first method/theory/empirical finding
   - Example: "Novel framework for multi-task RL via dynamic routing: 
     enables flexible task adaptation while preventing negative transfer."

2. **[Novelty type] [What]**: [Why it matters]
   - Example: "Theoretical analysis: we prove convergence guarantees 
     under mild assumptions and provide performance bounds."

3. **[Novelty type] [What]**: [Why it matters]
   - Example: "Comprehensive experiments: on 5 continuous control 
     benchmarks and 2 discrete action tasks, showing 30-45% improvements 
     over baselines and strong transfer performance."
```

**Key points**:
- ✅ Be specific. "We improve performance" is not a contribution. "We achieve 30-45% improvement on benchmark X, particularly on hard-exploration tasks" is.
- ✅ Claim novelty clearly. Use phrases like: "First method to...", "First to show...", "We prove...", "We introduce..."
- ✅ Balance types of contributions. Usually: 1 methodological, 1 theoretical, 1 empirical.

#### 2.5 Paper Organization (0.3 page)

**Purpose**: Help readers navigate and know what to expect.

**Structure**:
```
"The rest of the paper is organized as follows: 
§3 reviews related work on multi-task learning and task routing. 
§4 formally defines the problem and presents RoutingRL. 
§5 provides theoretical analysis of the routing mechanism. 
§6 describes experimental setup and main results. 
§7 discusses implications, limitations, and future directions. 
§8 concludes."
```

**Key points**:
- ✅ Keep it brief (3-5 sentences)
- ✅ One sentence per major section
- ✅ Help readers understand the logical flow

### Introduction Evaluation Checklist

- [ ] **Hook grabs attention**: Does the opening sentence make readers want to keep reading?
- [ ] **Background is accurate**: Are citations appropriate? Are claims fair?
- [ ] **Gap is clear**: Can readers articulate the specific limitation you're addressing?
- [ ] **Your idea is understandable**: Could a PhD student in the field understand your core idea from this section?
- [ ] **Contributions are specific and novel**: Each contribution has a novelty claim (first, new, combination, etc.)?
- [ ] **Length**: Roughly 15-20% of total paper length?
- [ ] **No technical jargon in intro**: Save detailed technical terminology for Method section
- [ ] **Transitions are smooth**: Does each paragraph flow naturally to the next?

---

## § 3. Related Work (2-3 pages)

### Recommended Structure

**DO NOT**: List papers chronologically.  
**DO**: Organize by research direction or technical approach.

#### 3.1 Group 1: [Related Direction]

**Example heading**: "Task Routing and Dynamic Networks"

```
Paragraph 1: Introduce the direction
  → "A complementary line of work studies dynamic networks, 
     where the computation graph changes based on input. 
     Examples include..."

Paragraph 2: Representative works and their approaches
  → "Routing networks [CITE-A] learn to route inputs to different 
     modules based on gating mechanisms. Recent work on mixture 
     of experts [CITE-B] enables scaling by selectively activating 
     experts. However, these approaches..."

Paragraph 3: How your work differs
  → "Our work differs in that we specifically study routing in 
     multi-task settings, where we need to balance task specialization 
     with transfer. We show that dynamic routing..."
```

#### 3.2 Group 2: [Related Direction]

**Example heading**: "Multi-Task Learning"

(Similar structure to 3.1)

#### 3.3 Group 3: [Related Direction]

(If applicable, e.g., "Reward Shaping" or "Transfer Learning")

### Related Work Best Practices

**DO**:
- ✅ Group papers by approach/theme, not chronologically
- ✅ For each group, include 3-5 representative papers with 1-2 sentence summaries
- ✅ Explicitly state how your work differs
- ✅ Be generous with citations (20-30 papers typical for related work)

**DON'T**:
- ❌ Summarize every paper in detail (save that for when you cite them in method)
- ❌ Criticize prior work unnecessarily; be fair and constructive
- ❌ Cite papers you haven't actually read
- ❌ Organize purely chronologically ("In 2019, paper A... In 2020, paper B...")

### Related Work Evaluation Checklist

- [ ] **Organized by theme**: Papers grouped by approach/direction, not time
- [ ] **Each group has 3-5 papers**: Provides coverage without overwhelming
- [ ] **Differences are clear**: For each group, explicitly state how your work differs
- [ ] **No strawman**: Don't misrepresent prior work to make yours look better
- [ ] **Balanced coverage**: Both classical papers and recent work included
- [ ] **Length**: 10-15% of total paper

---

## § 4. Methodology / Method (3-5 pages)

### Recommended Structure

#### 4.1 Problem Definition / Setup (0.5-1 page)

**Purpose**: Formally define what you're solving.

**Structure**:

1. **Symbol definitions** (usually a table or list):
```
- s ∈ S: state space
- a ∈ A: action space  
- τ = {s₁, a₁, r₁, ...}: trajectory
- T = {T₁, ..., Tₙ}: set of tasks
```

2. **Objective** (1-2 equations):
```
Maximize: E_τ [Σ γ^t r_t(s_t, a_t, τᵢ)]
Subject to: [constraints, if any]
```

3. **Problem statement** (1-2 sentences):
```
"We consider the multi-task RL problem: given a set of tasks T, 
learn a single policy π that can efficiently solve all tasks while 
enabling positive transfer and avoiding negative transfer."
```

#### 4.2 Framework Overview (0.5-1 page)

**Purpose**: Provide intuition before diving into technical details.

**Format**:
- **Description** (2-3 sentences): How does the system work at a high level?
- **Figure reference**: "See Figure 1 for an overview"
- **Key components** (bulleted list): What are the main parts?

**Example**:
```
"RoutingRL consists of three components: (1) a set of task-specific 
modules, (2) a shared backbone network, and (3) a learned routing 
network that decides which modules to activate for each task.

Key components:
- Task-specific modules T_i: each learns task i's unique dynamics
- Shared backbone B: captures common structure across tasks
- Routing network R: outputs gating weights g_i(s) ∈ [0,1] for each task
```

#### 4.3 Detailed Technical Presentation (1.5-2 pages)

**Purpose**: Provide sufficient detail for reproduction.

**Structure**: One or more subsections, each covering a key component.

**For each component**:
1. **What problem does this solve?** (context)
2. **How does it work?** (description)
3. **Formal definition** (equations)
4. **Algorithm or pseudocode** (if applicable)

**Example subsection**:
```
### Routing Mechanism

**Problem**: We need to dynamically select which modules are active 
for each state-task pair.

**Approach**: We learn a routing network R_θ that outputs a gating 
weight for each task module:

  g_i = softmax_i(R_θ(s))    where g_i ∈ [0, 1], Σ_i g_i = 1

This gating weight modulates the output of task i's module.

**Policy parameterization**:
  π(a|s) = Σ_i g_i(s) · π_i(a|s)

where π_i is the policy for task i's module.
```

#### 4.4 Training Procedure (0.5-1 page)

**Purpose**: Make the work reproducible.

**Include**:
- Loss function(s)
- Optimization algorithm (SGD, Adam, etc.)
- Training procedure in pseudocode or numbered steps
- Key hyperparameters

**Format**:

```
Algorithm 1: RoutingRL Training

Input: Tasks T = {T₁, ..., Tₙ}, hyperparameters (α, β, γ)
Initialize: modules M_i, routing network R, replay buffers D_i

for episode e in 1 to E do
  for each task T_i in T do
    Collect trajectory τ using policy π (with routing)
    Append to replay buffer D_i
    
    Sample batch from D_i
    Compute policy loss: L_π = -E[log π(a|s) · A(s,a)]
    Compute routing loss: L_route = -E[entropy(g(s))]  [optional regularization]
    
    Update M_i, R with α∇(L_π + β·L_route)
```

### Method Evaluation Checklist

- [ ] **Problem is formally defined**: Symbols, state/action spaces, objective clear?
- [ ] **Framework is explained intuitively**: Before formalization, high-level idea is clear?
- [ ] **Key equations are numbered**: Enables easy reference
- [ ] **Algorithm is in pseudocode**: Sufficient detail for implementation?
- [ ] **Training procedure is clear**: Can someone implement this from the description?
- [ ] **All hyperparameters mentioned**: Or referenced to appendix?
- [ ] **Notation is consistent**: Same symbol used throughout?
- [ ] **No undefined notation**: All symbols introduced before use?

---

## § 5. Experiments (3-4 pages)

### Recommended Structure

#### 5.1 Experimental Setup (0.5-1 page)

**Subsections**:

1. **Environments/Datasets**:
   - Which benchmark(s) do you use?
   - Why these benchmarks? (justify choice)
   - Basic statistics (number of tasks, state/action dimensions, etc.)

2. **Baselines**:
   - What prior methods do you compare against?
   - Why these baselines? (are they SOTA?)
   - Any variants or ablations of your method?

3. **Metrics**:
   - How do you measure success?
   - Why these metrics? (standard in the field?)

4. **Implementation Details**:
   - Network architecture (layer sizes, activation functions)
   - Optimization (optimizer, learning rate, batch size)
   - Training duration (number of steps/episodes)
   - Randomness (random seed, number of runs)

**Example**:
```
### Experimental Setup

Environments: We evaluate on three continuous control benchmarks:
  1. MTRL-10: 10 continuous control tasks with shared state/action spaces
  2. MT-Vision: 5 visual navigation tasks in simulated environments  
  3. Robot-Suite: 3 real robotic manipulation tasks

Baselines:
  - MTRL (Rusu et al., 2019): parameter sharing baseline
  - PCGrad (Yu et al., 2020): gradient-based multi-task learning
  - RoutingNet (proposed by this work)

Metrics:
  - Average return across all tasks (primary metric)
  - Success rate: % of tasks with > 90% of single-task performance
  - Transfer efficiency: average performance after N steps for new task

Implementation:
  - All agents use 3-layer MLPs (256 units per layer)
  - Optimizer: Adam with learning rate 3e-4
  - Training: 1M environment steps total, 10 random seeds
```

#### 5.2 Main Results (1-1.5 pages)

**Format**: Typically a table + brief narrative.

**Table structure**:
```
| Method | Task 1 | Task 2 | ... | Average | Std Dev |
|--------|--------|--------|-----|---------|---------|
| Baseline 1 | 0.72 | 0.68 | ... | 0.70 | ±0.05 |
| Baseline 2 | 0.75 | 0.71 | ... | 0.73 | ±0.04 |
| Our method | 0.82 | 0.79 | ... | 0.81 | ±0.03 |
| Improvement | +11.4% | +11.3% | ... | +11.0% | — |
```

**Narrative** (2-3 sentences summarizing):
```
"RoutingRL achieves 81% average return, outperforming the parameter-sharing 
baseline (70%) and PCGrad (73%) by 11% and 8% respectively. Notably, 
RoutingRL achieves particularly strong improvements on task clusters with 
high task diversity (e.g., visual vs. proprioceptive tasks)."
```

#### 5.3 Ablation Study (0.5-1 page)

**Purpose**: Show which components matter.

**Structure**: 
```
Table 2: Ablation Study

| Variant | Role | Average Return |
|---------|------|-----------------|
| RoutingRL (full) | — | 0.81 |
| w/o task-specific modules | no specialization | 0.76 (-5.8%) |
| w/o shared backbone | no transfer | 0.78 (-3.7%) |
| w/o routing network | fixed weighting | 0.79 (-2.5%) |

Interpretation:
- Task-specific modules are critical (5.8% drop)
- Routing flexibility provides modest but consistent benefit
- Shared backbone enables transfer
```

#### 5.4 Analysis / Qualitative Results (0.5-1 page)

**Options**:
- **Learned routing patterns**: Visualize which modules are used for which tasks
- **Case study**: Show detailed behavior on a representative task
- **Failure modes**: Where does the method struggle?
- **Attention/saliency maps** or **learned module specialization**: What does each module learn?

**Example**:
```
### Analysis: Learned Module Specialization

To understand what each module learns, we analyze the module 
activations across tasks. Figure 2 shows the learned routing weights:
  - Module 1 is consistently active for vision-based tasks
  - Module 2 activates for manipulation tasks
  - Shared backbone is always partially active

This specialization emerges without explicit task labeling, suggesting 
the routing mechanism discovers natural task structure.
```

### Experiments Evaluation Checklist

- [ ] **Benchmarks are justified**: Why these datasets/environments?
- [ ] **Baselines are SOTA**: Are you comparing against the best prior methods?
- [ ] **Metrics are standard**: Can results be compared fairly to other work?
- [ ] **Implementation details are complete**: Could someone reproduce this?
- [ ] **Results table has error bars**: Standard deviation or confidence interval shown?
- [ ] **Number of runs specified**: 3+ runs with different random seeds?
- [ ] **Improvements are quantified**: 11% improvement, not "significant"?
- [ ] **Ablation is comprehensive**: Each component's contribution clear?

---

## General Writing Guidelines

### Clarity

**DO**:
- ✅ Use active voice ("We show" not "It is shown")
- ✅ One idea per sentence
- ✅ Define terms before using them
- ✅ Use standard terminology

**DON'T**:
- ❌ Use jargon without explanation
- ❌ Write overly long sentences
- ❌ Use weak hedging ("seems to", "might")

### Evidence

**DO**:
- ✅ Back up claims with citations or experiments
- ✅ Quote specific results ("30% improvement" not "significant improvement")
- ✅ Acknowledge limitations

**DON'T**:
- ❌ Make unsupported claims
- ❌ Overstate results
- ❌ Ignore contradictory evidence

### Structure

**DO**:
- ✅ Start each section with a statement of purpose
- ✅ Use topic sentences to guide readers
- ✅ Transition between ideas explicitly

**DON'T**:
- ❌ Have paragraphs without a main point
- ❌ Jump between topics abruptly
- ❌ Bury key findings in details

---

## Citation Best Practices

**When to cite**:
- ✅ Existing methods or algorithms
- ✅ Benchmark datasets
- ✅ Related empirical findings
- ✅ Theoretical results

**How often**:
- **Introduction**: 10-15 papers (establish context)
- **Related Work**: 20-30 papers (thorough coverage)
- **Method**: 2-5 papers (cite specific techniques)
- **Experiments**: 5-10 papers (cite baselines, datasets)

**Citation format** (adapt to your venue):
```
[1] Last, First M., et al. "Paper Title." Conference or Journal Name, 2024.
```

