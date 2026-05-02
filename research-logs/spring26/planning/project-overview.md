# Project Overview

The project is split into six major parts

1. Stakeholder Interface
   - User selects smart-city domain and debated policy scenario
   - User reviews predefined alternatives and evaluation criteria
   - User inputs preference importance using linguistic ratings
   - Optional: multiple stakeholders submit separate preferences

2. Data Acquisition and Policy Modeling
   - Retrieve scenario data from predefined datasets or simulated sources
   - Map alternatives to measurable criteria values
   - Build the decision matrix
   - Mark each criterion as benefit or cost type
   - Normalize and validate inputs before ranking

3. Weight Derivation
   - Convert stakeholder preferences into pairwise comparisons or fuzzy preference values
   - Derive criteria weights using AHP or Fuzzy AHP
   - Check consistency of stakeholder inputs
   - Output final weight vector for ranking

4. TOPSIS Ranking Engine
   - Apply TOPSIS or Fuzzy TOPSIS to the weighted decision matrix
   - Compute closeness scores and final ranking of alternatives
   - Support reruns under modified weight scenarios for sensitivity analysis

5. AI Interpretation and Policy Advisor
   - Generate explanation for why each alternative ranked where it did
   - Highlight major trade-offs between criteria
   - Suggest alternative scenarios or weight adjustments
   - Provide policy-oriented recommendations grounded in the ranking outputs

6. Verification and Evaluation
   - Verify AI explanations against mathematical ranking contributions
   - Flag misleading or hallucinated explanations
   - Measure ranking stability under changing weights
   - Evaluate advisory usefulness, stakeholder trust, interpretability, and runtime
   - Allow user to revise preferences and rerun the process