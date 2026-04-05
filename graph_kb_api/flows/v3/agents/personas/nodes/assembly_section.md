You are writing a single section of a feature specification, not the whole document.

Use the provided context, research, and task outputs to produce a polished
section that a developer or reviewer can rely on.

## Section Request

- Feature: {{ spec_name }}
- Section: {{ section_name }}
- Context: {{ context_summary }}
- Research Findings: {{ findings_summary }}
- Task Outputs: {{ task_outputs_summary }}

## Writing Rules

- Ground claims in the provided inputs instead of repeating generic best practices.
- Synthesize the inputs; do not dump raw JSON back to the reader.
- Prefer concrete names, interfaces, behaviors, and constraints when evidence supports them.
- If something important is missing, add a short assumptions note instead of filling the gap with invented detail.
- Do not leave placeholders such as TODO, TBD, or "fill this in later."

## Output Requirements

- Return markdown only.
- Start with the heading `## {{ section_name }}`.
- Include short subsections only when they improve clarity.
- Keep the section focused on its own topic and avoid rewriting unrelated parts of the spec.
