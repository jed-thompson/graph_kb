# Code Context

Below is relevant code from the repository that may help answer the question.

{% if directory_summaries %}
## Directory/Module Overview

{% for dir in directory_summaries %}
### {{ dir.path }}

**Files:** {{ dir.file_count }} | **Symbols:** {{ dir.symbol_count }}

{% if dir.files %}
**Key Files:**
{% for file in dir.files[:10] %}
- `{{ file }}`
{% endfor %}
{% if dir.files|length > 10 %}
- ... and {{ dir.files|length - 10 }} more files
{% endif %}
{% endif %}

{% if dir.main_symbols %}
**Main Symbols:**
{% for symbol in dir.main_symbols[:15] %}
- `{{ symbol }}`
{% endfor %}
{% if dir.main_symbols|length > 15 %}
- ... and {{ dir.main_symbols|length - 15 }} more symbols
{% endif %}
{% endif %}

{% if dir.incoming_deps %}
**Used by:** {{ dir.incoming_deps|join(', ') }}
{% endif %}

{% if dir.outgoing_deps %}
**Depends on:** {{ dir.outgoing_deps|join(', ') }}
{% endif %}

---
{% endfor %}
{% endif %}

## Code Chunks

{% for item in chunks %}
### {{ item.file_path }} (Lines {{ item.start_line }}-{{ item.end_line }})
{% if item.symbol %}
**Symbol:** `{{ item.symbol }}`
{% endif %}
**Relevance Score:** {{ "%.2f"|format(item.score) }}

```{{ item.language|default('') }}
{{ item.content }}
```

---
{% endfor %}

{% if graph_paths %}
## Code Relationships

The following paths show how different parts of the code are connected:

{% for path in graph_paths %}
### {{ path.description }}

**Path:** {{ path.nodes|join(' → ') }}

{% endfor %}
{% endif %}

## User Question

{{ question }}
