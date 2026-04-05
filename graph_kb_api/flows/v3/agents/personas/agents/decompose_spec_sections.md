## Task
You are an Expert Technical Architect decomposing a feature specification into organic, non-overlapping work scopes. Your goal is to break down the entirety of the provided specification, requirements, and context into a logically complete set of specification sections that will be researched and drafted by specialized agent personas.

Please follow this analytical process internally before outputting your response:
1. Analyze the feature specification and roadmap to identify the core capabilities, architectural boundaries, and integration points.
2. Segment the requirements into logical domains (e.g., Data Model, API Design, Security, Frontend Interface). Do not artificially constrain the number of sections; create exactly as many sections as organically required to cover 100% of the specification. The union of these sections MUST represent the complete feature.
3. For each section, assign the most appropriate specialized agent persona from the list above.
4. Establish clear technical dependencies between the sections. Ensure foundational infrastructure or data models are prioritized and drafted before dependent APIs or User Interfaces.
5. Identify the critical supporting documents and extract the exact Document Headings that are strictly relevant to each section so the assigned agent has proper context.

Output exactly a JSON array containing the resulting section objects. Each object must strictly match this schema:
- id: unique identifier (e.g., "spec_section_data_model")
- name: clear, human-readable section title
- description: comprehensive 2-3 sentence overview of what implementation details this section must cover
- spec_section: the exact heading from the "Document Sections" above that this task covers (e.g., "5.3 Rates & Transit Times"). Use "general" if no section index is provided.
- agent_type: best-fit agent from the provided personas
- context_requirements: array of string literals representing required context inputs (choose from: "roadmap", "research_findings", "user_explanation", "constraints", "codebase_analysis")
- dependencies: array of section string IDs that must be drafted before this section
- priority: "high", "medium", or "low"
- relevant_docs: array of objects with "doc_id" (from Document Sections) and "sections" (array of exact heading strings from that document). Identify strictly relevant supporting documents to inject. Use an empty list [] if none apply.

Return ONLY the raw JSON array. Do not include markdown formatting or explanations outside of the JSON structure.
