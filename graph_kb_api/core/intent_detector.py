"""
Intent detection service for natural language command matching.

Uses LLM to classify user input into one of 22 known intents
with confidence scoring and parameter extraction.
"""

import json
from typing import TYPE_CHECKING, Dict

from graph_kb_api.schemas.intent import IntentConfig, IntentResult

if TYPE_CHECKING:
    from graph_kb_api.core.llm import LLMService


class IntentDetector:
    """Detect user intent from natural language and match to commands."""

    INTENTS = [
        "ingest_repo",
        "resume_ingest",  # Resume interrupted ingestion
        "check_diff",
        "list_repos",
        "check_status",
        "upload_docs",
        "list_docs",
        "view_doc",
        "delete_doc",
        "generate_spec",
        "generate_doc",
        "add_template",
        "add_steering",
        "list_steering",
        "remove_steering",
        "show_menu",
        "get_help",
        "ask_code",  # Simple code question (quick answer)
        "deep_analysis",  # Complex analysis requiring iterative reasoning
        "ask_agent",  # Agent-specific query
        "list_agents",  # List available agents
    ]

    CONFIDENCE_THRESHOLD = 0.7

    INTENT_CONFIGS: Dict[str, IntentConfig] = {
        "ingest_repo": IntentConfig(
            handler="/ingest",
            required_params=["url"],
            optional_params=["branch"],
        ),
        "resume_ingest": IntentConfig(
            handler="/ingest",
            required_params=["repo_id"],
            optional_params=[],
        ),
        "check_diff": IntentConfig(
            handler="/diff",
            required_params=[],
            optional_params=["url"],
        ),
        "list_repos": IntentConfig(
            handler="/list_repos",
            required_params=[],
            optional_params=[],
        ),
        "check_status": IntentConfig(
            handler="/status",
            required_params=[],
            optional_params=["repo_id"],
        ),
        "upload_docs": IntentConfig(
            handler="/upload",
            required_params=[],
            optional_params=["parent", "category"],
        ),
        "list_docs": IntentConfig(
            handler="/list_docs",
            required_params=[],
            optional_params=["parent", "category"],
        ),
        "view_doc": IntentConfig(
            handler="/view_doc",
            required_params=["filename"],
            optional_params=[],
        ),
        "delete_doc": IntentConfig(
            handler="/delete_doc",
            required_params=["filename"],
            optional_params=[],
        ),
        "generate_spec": IntentConfig(
            handler="/prompts",
            required_params=[],
            optional_params=["spec_type", "carrier"],
        ),
        "generate_doc": IntentConfig(
            handler="/generate",
            required_params=[],
            optional_params=["doc_type", "topic"],
        ),
        "add_template": IntentConfig(
            handler="/add_template",
            required_params=[],
            optional_params=[],
        ),
        "add_steering": IntentConfig(
            handler="/add_steering",
            required_params=[],
            optional_params=[],
        ),
        "list_steering": IntentConfig(
            handler="/list_steering",
            required_params=[],
            optional_params=[],
        ),
        "remove_steering": IntentConfig(
            handler="/remove_steering",
            required_params=["filename"],
            optional_params=[],
        ),
        "show_menu": IntentConfig(
            handler="/menu",
            required_params=[],
            optional_params=[],
        ),
        "get_help": IntentConfig(
            handler="/help",
            required_params=[],
            optional_params=[],
        ),
        "ask_code": IntentConfig(
            handler="/ask_code",
            required_params=["repo_id", "question"],
            optional_params=[],
        ),
        "deep_analysis": IntentConfig(
            handler="/deep",
            required_params=["query", "repo_id"],
            optional_params=[],
        ),
        "ask_agent": IntentConfig(
            handler="/ask_agent",
            required_params=["question"],
            optional_params=["agent_type"],
        ),
        "list_agents": IntentConfig(
            handler="/agents",
            required_params=[],
            optional_params=[],
        ),
    }

    SYSTEM_PROMPT = (
        "You are a command intent classifier. "
        "Analyze the user's input and classify it into exactly one of these intents:\n\n"
        "1. ingest_repo - Add/ingest/index a GitHub repository\n"
        "2. resume_ingest - Resume an interrupted or paused ingestion\n"
        "3. check_diff - Check for updates/changes in a repository\n"
        "4. list_repos - List all ingested repositories\n"
        "5. check_status - Check ingestion or indexing status\n"
        "6. upload_docs - Upload documents or files\n"
        "7. list_docs - List or browse documents\n"
        "8. view_doc - View a specific document\n"
        "9. delete_doc - Delete a document\n"
        "10. generate_spec - Generate a technical specification\n"
        "11. generate_doc - Generate documentation\n"
        "12. add_template - Add a custom template\n"
        "13. add_steering - Add a steering/guideline document\n"
        "14. list_steering - List steering documents\n"
        "15. remove_steering - Remove a steering document\n"
        "16. show_menu - Show the command menu\n"
        "17. get_help - Get help or list commands\n"
        "18. ask_code - SIMPLE code questions requiring quick lookup or brief explanation.\n"
        "    Use for: 'What does X do?', 'Where is Y defined?', 'Show me Z', "
        "'How do I use W?', 'List the functions in X', 'What parameters does Y take?'\n"
        "19. deep_analysis - COMPLEX questions requiring multi-step reasoning, tool calls, "
        "or investigation.\n"
        "    Use for: 'Trace the auth flow', 'How does X connect to Y?', "
        "'Analyze the architecture', 'Why is Z slow?', 'Debug the issue with X', "
        "'Map the dependencies', 'Explain the data flow', 'Create a diagram of X', "
        "'Compare X and Y', 'Find all places where X is used', 'What would happen if I change X?'\n"
        "    KEYWORDS indicating deep_analysis: trace, analyze, investigate, debug, explore, "
        "map, diagram, flow, architecture, relationship, dependency, connect, compare, "
        "how does X work with Y, what happens when, walk through, step by step\n"
        "20. ask_agent - Query a specific agent (@analyst, @architect, etc.)\n"
        "21. list_agents - List available agents and their capabilities\n\n"
        "Classification rules:\n"
        "- Single entity lookup → ask_code (e.g., 'What does function X do?')\n"
        "- Multi-entity or relationship question → deep_analysis (e.g., 'How does X call Y?')\n"
        "- Simple 'what/where/show' → ask_code\n"
        "- Complex 'how/why/trace/analyze' → deep_analysis\n"
        "- Requests for diagrams or visualizations → deep_analysis\n\n"
        "Respond ONLY with a JSON object:\n"
        '{"intent": "<intent_name>", "confidence": <0.0-1.0>, '
        '"params": {<extracted parameters>}}\n\n'
        "Extract any relevant parameters from the query such as url, branch, "
        "repo_id, filename, question, parent, category, spec_type, doc_type, topic, agent_type.\n"
        "Only include parameters that are clearly present in the input.\n"
        "Return ONLY the JSON object, no other text."
    )

    def __init__(self, llm: "LLMService") -> None:
        self.llm = llm

    async def detect(self, query: str) -> IntentResult:
        """Classify a natural language query into one of 22 known intents.

        Args:
            query: The user's natural language input.

        Returns:
            IntentResult with intent name, confidence score (0.0-1.0),
            and extracted parameters.
        """
        try:
            response = await self.llm.a_generate_response(
                system_prompt=self.SYSTEM_PROMPT,
                user_prompt=f"User input: {query}",
            )

            parsed = self._parse_response(response)

            # Validate intent is one of the known intents
            intent = parsed.get("intent", "ask_code")
            if intent not in self.INTENTS:
                intent = "ask_code"

            # Clamp confidence to [0.0, 1.0]
            confidence = float(parsed.get("confidence", 0.0))
            confidence = max(0.0, min(1.0, confidence))

            params = parsed.get("params", {})
            if not isinstance(params, dict):
                params = {}

            return IntentResult(
                intent=intent,
                confidence=confidence,
                params=params,
            )

        except Exception:
            # On any failure, return low-confidence ask_code so the caller
            # routes to QA_Handler via the < 0.7 threshold path.
            return IntentResult(
                intent="ask_code",
                confidence=0.0,
                params={},
            )

    def get_config(self, intent: str) -> IntentConfig:
        """Return the IntentConfig for a given intent name."""
        return self.INTENT_CONFIGS.get(
            intent,
            IntentConfig(handler="/ask_code", required_params=[], optional_params=[]),
        )

    @staticmethod
    def _parse_response(raw: str) -> dict:
        """Parse the LLM JSON response, stripping markdown fences if present."""
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()
        return json.loads(text)
