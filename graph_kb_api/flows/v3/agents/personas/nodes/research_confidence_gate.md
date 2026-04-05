You are evaluating whether research findings are sufficient to proceed with specification planning.

## Specification
Name: {{ spec_name }}
Description: {{ user_explanation }}

## Research Findings Summary
{{ research_summary }}

## Outstanding Gaps ({{ gap_count }})
{{ gap_descriptions }}

## Identified Risks ({{ risk_count }})
{{ risk_descriptions }}

## Evaluation Criteria
Rate confidence from 0.0 to 1.0 based on:
- Coverage: Do the findings address the core requirements of the specification?
- Per-section coverage: When a Section Index is provided, does research cover
  each major section of the requirements document?
- Depth: Is there enough detail to proceed with planning?
- Gaps: Are outstanding gaps blockers or acceptable unknowns?
- Risks: Are risks identified and mitigable?

Respond in this exact format:
CONFIDENCE: <score between 0.0 and 1.0>
JUSTIFICATION: <2-3 sentence explanation>
