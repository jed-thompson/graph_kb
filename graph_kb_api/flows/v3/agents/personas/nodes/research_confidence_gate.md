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
- **Gaps**: Evaluate each gap by its type and importance (provided in [TYPE / importance=LEVEL] format):
  - `REQUIREMENTS` or `CONSTRAINT` gaps with high importance: deduct 0.10 from confidence per gap
  - `REQUIREMENTS` or `CONSTRAINT` gaps with medium importance: deduct 0.05 per gap
  - `SCOPE` or `CONTEXT` gaps: deduct 0.02 per gap
  - A confidence score above 0.80 with 3 or more REQUIREMENTS or CONSTRAINT gaps is rarely justified
    unless findings directly and explicitly address those gap questions.
  - Example: 6 requirements/constraint gaps of medium importance → deduct ~0.30, cap justified score at ~0.65-0.70
- Risks: Are risks identified and mitigable?

Respond in this exact format:
CONFIDENCE: <score between 0.0 and 1.0>
JUSTIFICATION: <2-3 sentence explanation>
