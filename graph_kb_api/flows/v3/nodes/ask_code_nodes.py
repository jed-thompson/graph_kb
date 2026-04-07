"""
Specialized nodes for AskCode agentic workflow.

This module provides all the specialized nodes needed for the AskCode workflow
including input validation, question analysis, clarification, retrieval,
context checking, and response formatting.
"""

import asyncio
import re
from dataclasses import asdict
from dataclasses import fields as dataclass_fields
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from graph_kb_api.context import AppContext
from graph_kb_api.database import SyncMetadataService
from graph_kb_api.flows.v3.models import ServiceRegistry
from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3
from graph_kb_api.flows.v3.utils.progress_queue import (
    ProgressQueue,
    create_retrieval_progress_event,
)
from graph_kb_api.flows.v3.utils.tool_display import ToolDisplayFormatter
from graph_kb_api.graph_kb.facade import GraphKBFacade
from graph_kb_api.graph_kb.models.retrieval import RetrievalStep
from graph_kb_api.utils.enhanced_logger import EnhancedLogger
from graph_kb_api.utils.timeout_config import TimeoutConfig

logger = EnhancedLogger(__name__)


class DetermineRepoNode(BaseWorkflowNodeV3):
    """Determines the repository ID from session or state."""

    # Regex patterns for extracting repo names from queries
    REPO_EXTRACTION_PATTERNS = [
        r"^([a-zA-Z0-9_\-]+)\s+",  # Repo name at start of query
        r"\bin\s+([a-zA-Z0-9_\-]+)",
        r"\bfrom\s+([a-zA-Z0-9_\-]+)",
        r"\bfor\s+([a-zA-Z0-9_\-]+)",
        r"\b([a-zA-Z0-9_\-]+)\s+repository",
        r"\b([a-zA-Z0-9_\-]+)\s+repo\b",
    ]

    def __init__(self):
        super().__init__("determine_repo")

    def _extract_repo_from_query(self, query: str, app_context: Optional[AppContext]) -> Optional[str]:
        """
        Extract repository name from query using regex patterns.

        Args:
            query: User's query text
            app_context: Application context with graph_kb_facade

        Returns:
            Repository ID if found and verified, None otherwise
        """
        if not app_context or not hasattr(app_context, "graph_kb_facade"):
            return None

        facade = app_context.graph_kb_facade
        if not facade or not hasattr(facade, "metadata_store"):
            return None
        metadata_store = facade.metadata_store
        if not metadata_store:
            return None

        for pattern in self.REPO_EXTRACTION_PATTERNS:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                potential_repo: str = match.group(1)

                # Verify this repo exists
                repo = metadata_store.get_repo(potential_repo)
                if repo:
                    logger.info(f"Extracted repo_id from query: {potential_repo}")
                    return potential_repo

        return None

    def _get_default_repo(
        self, app_context: Optional[AppContext]
    ) -> tuple[Optional[str], Optional[NodeExecutionResult]]:
        """
        Get default repository when none specified.

        If exactly one repo exists, use it. If multiple exist, return error.

        Args:
            app_context: Application context with graph_kb_facade

        Returns:
            Tuple of (repo_id, error_result). If repo_id is None, error_result contains the error.
        """
        if not app_context or not hasattr(app_context, "graph_kb_facade"):
            return None, None

        facade: GraphKBFacade | None = app_context.graph_kb_facade
        if not facade or not hasattr(facade, "metadata_store"):
            return None, None
        metadata_store: SyncMetadataService | None = facade.metadata_store
        if not metadata_store:
            return None, None
        repos: List[Any] = metadata_store.list_repos()

        if len(repos) == 1:
            repo_id: str = repos[0].repo_id
            logger.info(f"Using only available repository: {repo_id}")
            return repo_id, None

        elif len(repos) > 1:
            repo_list: str = ", ".join([r.repo_id for r in repos[:5]])
            error_result: NodeExecutionResult = NodeExecutionResult.error(
                f"Multiple repositories available. Please specify which one in your query.\n\n"
                f"Available: {repo_list}\n\n"
                f"Example: 'explain how adapters work in {repos[0].repo_id}'",
                metadata={"node_type": self.node_name, "error_type": "ambiguous_repo"},
            )
            return None, error_result

        return None, None

    async def _execute_async(self, state: Dict[str, Any], services: ServiceRegistry) -> NodeExecutionResult:
        """
        Determine the repository ID to use for the query.

        Priority:
        1. repo_id already in state
        2. Extract from args[0] (v3 command format)
        3. current_repo_id from session
        4. Extract from query (e.g., "in TARGET_INGESTED_REP")
        5. Use first available repo if only one exists
        6. Error if none found or multiple exist without specification
        """
        try:
            # Setup execution context
            self._setup_execution_context(state, services)

            # Check if repo_id already in state
            repo_id: Optional[str] = state.get("repo_id")

            # If not in state, try to extract from args[0]
            if not repo_id:
                args = state.get("args", [])
                repo_id = args[0] if args else None
                if repo_id:
                    logger.info(f"Extracted potential repo_id from args[0]: {repo_id}")

                    # Verify this repo exists
                    app_context: Optional[AppContext] = services.get("app_context")
                    if app_context and hasattr(app_context, "graph_kb_facade"):
                        metadata_store = app_context.graph_kb_facade.metadata_store
                        if not metadata_store:
                            repo_id = None
                        elif metadata_store.get_repo(repo_id):
                            logger.info(f"Verified repo_id from args: {repo_id}")
                        else:
                            # Not a valid repo_id, clear it and try other methods
                            logger.info(f"args[0] '{repo_id}' is not a valid repo_id, trying other methods")
                            repo_id = None

            if not repo_id:
                # Try to get from state (WebSocket-based flow doesn't use Chainlit sessions)
                repo_id = state.get("current_repo_id")

            # If still no repo_id, try extraction and default repo logic
            if not repo_id:
                app_context: Optional[AppContext] = services.get("app_context")

                # Try to extract from query
                query: str = state.get("original_question", "") or state.get("refined_question", "")
                if query:
                    repo_id = self._extract_repo_from_query(query, app_context)

                # If extraction failed, try to use default repo
                if not repo_id:
                    repo_id, error_result = self._get_default_repo(app_context)
                    if error_result:
                        return error_result

            if not repo_id:
                logger.warning("No repository ID found in state or session")
                return NodeExecutionResult.error(
                    "No repository selected. Please index a repository first.",
                    metadata={"node_type": self.node_name, "error_type": "no_repo"},
                )

            logger.info("Repository determined", data={"repo_id": repo_id})

            return NodeExecutionResult.success(output={"repo_id": repo_id})

        except Exception as e:
            logger.error(f"Failed to determine repository: {e}")
            return NodeExecutionResult.error(
                f"Failed to determine repository: {str(e)}", metadata={"node_type": self.node_name}
            )


class ValidateInputNode(BaseWorkflowNodeV3):
    """Validates and parses AskCode command arguments."""

    def __init__(self):
        super().__init__("validate_input")

    async def _execute_async(self, state: Dict[str, Any], services: ServiceRegistry) -> NodeExecutionResult:
        """
        Validate user query input.

        Extracts question from args using base class helper methods.
        """
        try:
            # Setup execution context
            self._setup_execution_context(state, services)

            # Extract args from state directly
            args = state.get("args", [])

            # Get refined_question or use it directly from state
            user_query = state.get("refined_question") or state.get("original_question", "")

            if not user_query:
                logger.error("No question provided in args")
                return NodeExecutionResult.error(
                    "No question provided. Usage: /ask_code <repo_id> <question>",
                    metadata={"node_type": self.node_name, "error_type": "validation"},
                )

            # Create initial progress message (step 0)
            progress_msg_id = ""

            logger.info(
                "Input validated successfully",
                data={"query_length": len(user_query), "args_count": len(args), "progress_msg_id": progress_msg_id},
            )

            # Clear messages from prior conversation turns to prevent token overflow.
            # The messages field uses add_messages (accumulates across turns via checkpoint).
            # Each turn adds a large HumanMessage with full code context, causing the
            # prompt to grow by ~hundreds of thousands of tokens per turn.
            prior_messages = state.get("messages", [])
            clear_messages = [RemoveMessage(id=msg.id) for msg in prior_messages]

            return NodeExecutionResult.success(
                output={
                    "original_question": user_query,
                    "refined_question": user_query,
                    "progress_message_id": progress_msg_id,
                    "messages": clear_messages,
                }
            )

        except Exception as e:
            logger.error(f"Input validation failed: {e}")
            return NodeExecutionResult.error(
                f"Input validation failed: {str(e)}", metadata={"node_type": self.node_name}
            )


class AnalyzeQuestionNode(BaseWorkflowNodeV3):
    """Analyzes question clarity to determine if clarification is needed."""

    def __init__(self):
        super().__init__("analyze_question")

    async def _execute_async(self, state: Dict[str, Any], services: ServiceRegistry) -> NodeExecutionResult:
        """
        Analyze question to determine clarity level.

        TODO: Implement LLM interaction to validate question fit

        Returns:
            question_clarity: "clear", "vague", or "ambiguous"
        """
        # Session ID set by _setup_execution_context

        try:
            question = state.get("refined_question") or state.get("original_question", "")

            # Validate question is not empty
            if not question or not question.strip():
                return NodeExecutionResult.error(
                    "No question provided to analyze",
                    metadata={"node_type": self.node_name, "error_type": "validation"},
                )

            # Simple heuristics for question clarity
            # In production, this could use an LLM for better analysis
            clarity: Literal["clear", "vague", "ambiguous"] = "vague"  # Default to vague for safety

            question_lower = question.lower()
            word_count = len(question.split())

            # Check for specific code-related indicators
            # Use word boundaries for short keywords to avoid false matches like
            # "functionality" matching "function", "classified" matching "class", etc.
            specific_keywords = ["function", "class", "method", "file", "module"]
            specific_extensions = [".py", ".js", ".java", ".ts", ".go", ".rb"]
            specific_python = ["def ", "import ", "from "]
            specific_verbs = ["authenticate", "calculate", "process", "validate"]
            # Note: "repository" is intentionally excluded — it always refers to the whole
            # codebase and is never a specific code reference.  Including it blocks
            # architectural detection for queries like "explain this repository".
            specific_nouns = ["service", "controller", "model", "handler", "manager"]

            # Check each category — use word boundaries for keywords to prevent
            # substring false positives ("functionality" ≠ "function", etc.)
            has_keyword = any(
                re.search(r"\b" + re.escape(keyword) + r"\b", question_lower)
                for keyword in specific_keywords
            )
            has_extension = any(ext in question_lower for ext in specific_extensions)
            has_python = any(py in question_lower for py in specific_python)
            has_verb = any(verb in question_lower for verb in specific_verbs)
            has_noun = any(noun in question_lower for noun in specific_nouns)

            has_specific = has_keyword or has_extension or has_python or has_verb or has_noun

            # Check for vague indicators
            vague_indicators = ["how", "what", "why", "explain", "tell me about", "show me"]

            # Check for generic terms that indicate vagueness
            generic_terms = ["this", "that", "it", "the code", "the system", "here", "there"]
            has_vague = any(indicator in question_lower for indicator in vague_indicators)
            has_generic = any(term in question_lower for term in generic_terms)

            # Check for CamelCase or specific code identifiers (e.g., DatabaseConnection, authenticate_user)
            # These indicate specific code references even if not in our keyword list
            has_camel_case = bool(re.search(r"[A-Z][a-z]+[A-Z]", question))  # CamelCase pattern
            has_snake_case = bool(re.search(r"[a-z]+_[a-z]+", question_lower))  # snake_case pattern
            has_code_identifier = has_camel_case or has_snake_case

            # Classification logic with priority:
            # 1. If has specific code references (function names, file paths, identifiers), it's clear
            #    even if it's short or has vague words
            if has_specific or has_code_identifier:
                clarity = "clear"
            # 2. Very short questions (< 5 words) without specific references are vague
            elif word_count < 5:
                clarity = "vague"
            # 3. Has vague words AND generic terms but no specific references
            elif has_vague and has_generic and not has_specific and not has_code_identifier:
                clarity = "vague"
            # 4. Has vague words but no specific references and no generic terms
            elif has_vague and not has_specific and not has_code_identifier:
                clarity = "vague"
            # 5. Longer questions (>= 5 words) without vague indicators or with context
            elif word_count >= 5 and not has_generic:
                clarity = "clear"
            # 6. Default to vague for safety
            else:
                clarity = "vague"

            # Detect architectural / broad questions to allocate more tool iterations.
            # Use multi-word phrases to avoid false positives on specific questions like
            # "how does authenticate_user work?" — those are caught by has_code_identifier.
            architectural_keywords = [
                "architecture", "overview", "core functionality", "data flow", "data flows",
                "end-to-end", "end to end", "how does the", "how do the",
                "how it works", "explain the", "describe the", "communicate", "integrate",
                "platform", "pipeline", "workflow", "infrastructure",
            ]
            is_architectural = (
                any(kw in question_lower for kw in architectural_keywords)
                and word_count >= 6
                and not has_code_identifier  # Not asking about a specific symbol
                and not has_specific  # Not asking about a named function/verb
            )

            if is_architectural:
                question_type: Literal["architectural", "specific", "general"] = "architectural"
                # Architectural questions are well-defined enough to not need clarification —
                # routing to "clarify" would interrupt for a question we already know how to handle.
                clarity = "clear"
            elif has_code_identifier or has_specific:
                question_type = "specific"
            else:
                question_type = "general"

            logger.info(
                "Question analyzed",
                data={
                    "clarity": clarity,
                    "question_type": question_type,
                    "question_length": len(question),
                    "word_count": word_count,
                    "has_specific": has_specific,
                    "has_vague": has_vague,
                    "has_generic": has_generic,
                    "has_code_identifier": has_code_identifier,
                    "is_architectural": is_architectural,
                },
            )

            output = {"question_clarity": clarity, "question_type": question_type}
            if question_type == "architectural":
                output["max_agent_iterations"] = 10
            return NodeExecutionResult.success(output=output)

        except Exception as e:
            logger.error(f"Question analysis failed: {e}")
            return NodeExecutionResult.error(
                f"Question analysis failed: {str(e)}", metadata={"node_type": self.node_name}
            )


class _QuestionClassification(BaseModel):
    """Structured output schema for LLM-based question classification."""

    question_type: Literal["architectural", "specific", "general"] = Field(
        description=(
            "architectural: broad questions about the whole system — how the repo works end-to-end, "
            "data flows, system architecture, repository overview, pipelines, infrastructure, "
            "component communication. "
            "specific: targets a named code element — a function, class, method, file, or a "
            "CamelCase/snake_case code identifier. "
            "general: everything else."
        )
    )
    question_clarity: Literal["clear", "vague", "ambiguous"] = Field(
        description=(
            "clear: answerable as-is; architectural questions are almost always clear. "
            "vague: too short or contentless to answer (e.g. 'how does it work?' with no subject). "
            "ambiguous: could reasonably mean multiple conflicting things."
        )
    )
    reasoning: str = Field(description="One-sentence explanation of the classification decision.")


class ClassifyQuestionNode(BaseWorkflowNodeV3):
    """
    LLM-powered question classifier that replaces brittle keyword heuristics.

    Uses structured output to determine:
    - question_type: architectural | specific | general
    - question_clarity: clear | vague | ambiguous

    Falls back to simplified keyword heuristics if the LLM call fails.
    """

    _SYSTEM_PROMPT = (
        "You are a code question classifier for a codebase assistant. "
        "Classify the user's question by type and clarity.\n\n"
        "QUESTION TYPE:\n"
        "  architectural — broad questions about the whole system: how the repo works end-to-end, "
        "data flows, system architecture, repository overview, pipelines, infrastructure, "
        "component communication. Examples: 'Explain the core functionality', 'How does data "
        "flow through this system?', 'Give me an overview of this repository'.\n"
        "  specific — targets a named code element: a specific function, class, method, file, "
        "module, or an identifiable code identifier (CamelCase or snake_case name). "
        "Examples: 'How does authenticate_user work?', 'What does GraphKBFacade do?'.\n"
        "  general — everything else.\n\n"
        "QUESTION CLARITY:\n"
        "  clear — answerable as-is. Architectural and specific questions are almost always clear.\n"
        "  vague — too short or contentless to answer meaningfully without guessing "
        "(e.g. 'how does it work?' with no subject and no loaded repository).\n"
        "  ambiguous — could reasonably mean multiple conflicting things.\n\n"
        "RULE: If the question is architectural, set clarity to 'clear' unless it is genuinely "
        "impossible to answer without additional information from the user.\n\n"
        'Respond with ONLY a JSON object, no markdown, no explanation:\n'
        '{"question_type": "architectural|specific|general",'
        ' "question_clarity": "clear|vague|ambiguous", "reasoning": "one sentence"}'
    )

    def __init__(self, llm):
        super().__init__("classify_question")
        self._llm = llm

    async def _execute_async(self, state: Dict[str, Any], services: ServiceRegistry) -> NodeExecutionResult:
        self._setup_execution_context(state, services)

        question = state.get("refined_question") or state.get("original_question", "")
        if not question or not question.strip():
            return NodeExecutionResult.error(
                "No question provided to classify",
                metadata={"node_type": self.node_name, "error_type": "validation"},
            )

        try:
            import json as _json

            response = await self._llm.ainvoke(
                [
                    SystemMessage(content=self._SYSTEM_PROMPT),
                    HumanMessage(content=f"Classify this question:\n\n{question}"),
                ]
            )
            content = response.content if hasattr(response, "content") else str(response)

            # Extract JSON — strip markdown fences if present
            json_match = re.search(r"\{[^{}]+\}", content, re.DOTALL)
            raw = json_match.group() if json_match else content.strip()
            data = _json.loads(raw)
            result = _QuestionClassification.model_validate(data)

            logger.info(
                "Question classified by LLM",
                data={
                    "question_type": result.question_type,
                    "question_clarity": result.question_clarity,
                    "reasoning": result.reasoning,
                },
            )

            output: Dict[str, Any] = {
                "question_clarity": result.question_clarity,
                "question_type": result.question_type,
            }
            if result.question_type == "architectural":
                output["max_agent_iterations"] = 10

            return NodeExecutionResult.success(output=output)

        except Exception as e:
            logger.warning(f"LLM classification failed, falling back to keyword heuristics: {e}")
            return self._heuristic_classify(question)

    def _heuristic_classify(self, question: str) -> NodeExecutionResult:
        """Keyword-based fallback when LLM classification fails."""
        question_lower = question.lower()
        word_count = len(question.split())

        has_camel = bool(re.search(r"[A-Z][a-z]+[A-Z]", question))
        has_snake = bool(re.search(r"[a-z]+_[a-z]+", question_lower))
        has_code_id = has_camel or has_snake

        architectural_keywords = [
            "architecture", "overview", "core functionality", "data flow", "data flows",
            "end-to-end", "end to end", "how does the", "how do the", "how it works",
            "explain the", "describe the", "communicate", "integrate",
            "platform", "pipeline", "workflow", "infrastructure",
        ]
        is_architectural = (
            any(kw in question_lower for kw in architectural_keywords)
            and word_count >= 6
            and not has_code_id
        )

        if is_architectural:
            q_type: Literal["architectural", "specific", "general"] = "architectural"
            clarity: Literal["clear", "vague", "ambiguous"] = "clear"
        elif has_code_id:
            q_type = "specific"
            clarity = "clear"
        else:
            q_type = "general"
            clarity = "clear" if word_count >= 5 else "vague"

        output: Dict[str, Any] = {"question_clarity": clarity, "question_type": q_type}
        if q_type == "architectural":
            output["max_agent_iterations"] = 10

        return NodeExecutionResult.success(output=output)


class ClarificationNode(BaseWorkflowNodeV3):
    """Requests clarification from user for vague questions."""

    def __init__(self):
        super().__init__("clarification")

    async def _execute_async(self, state: Dict[str, Any], services: ServiceRegistry) -> NodeExecutionResult:
        """
        Request clarification from user using interrupt().

        This node pauses execution and waits for user input.
        """
        # Session ID set by _setup_execution_context

        try:
            original_question = state.get("original_question", "")

            # Use interrupt() to pause and request user input
            user_response = interrupt(
                {
                    "message": "Your question seems vague. Can you be more specific?",
                    "original_question": original_question,
                    "suggestions": [
                        "Which specific function or class?",
                        "Which file or module?",
                        "What specific behavior are you asking about?",
                    ],
                }
            )

            # When resumed, user_response contains the clarification
            refined_question = user_response.get("refined_question", original_question)

            logger.info(
                "Clarification received",
                data={"original_length": len(original_question), "refined_length": len(refined_question)},
            )

            return NodeExecutionResult.success(
                output={
                    "refined_question": refined_question,
                    "clarification_attempts": state.get("clarification_attempts", 0) + 1,
                    "question_clarity": "clear",
                }
            )

        except Exception as e:
            logger.error(f"Clarification failed: {e}")
            return NodeExecutionResult.error(f"Clarification failed: {str(e)}", metadata={"node_type": self.node_name})


class SemanticRetrievalNode(BaseWorkflowNodeV3):
    """Performs initial semantic search to retrieve relevant context."""

    def __init__(self):
        super().__init__("semantic_retrieval")

    async def _execute_async(self, state: Dict[str, Any], services: ServiceRegistry) -> NodeExecutionResult:
        """
        Perform semantic search to find relevant code.

        Note: Always runs fresh retrieval, ignoring any cached context_items from checkpoints.
        This ensures we use the latest retrieval configuration and limits.
        """

        # Session ID set by _setup_execution_context

        try:
            # Setup execution context
            self._setup_execution_context(state, services)

            repo_id = state.get("repo_id")
            question = state.get("refined_question") or state.get("original_question", "")

            if not repo_id or not question:
                return NodeExecutionResult.error("Missing repo_id or question", metadata={"node_type": self.node_name})

            logger.info("Performing semantic retrieval", data={"repo_id": repo_id, "query": question[:100]})

            # Warn if we're loading from a checkpoint with stale context
            if "context_items" in state and len(state.get("context_items", [])) > 100:
                logger.warning(
                    "Checkpoint contains large context from previous conversation - running fresh retrieval",
                    data={"old_context_count": len(state.get("context_items", []))},
                )

            # Get retrieval service - returns error if not available
            retrieval_service, error = self._require_retrieval_service(services)
            if error:
                return error

            try:
                # Get app_context for retrieval settings
                app_context = self._get_app_context(services)
                if not app_context:
                    return NodeExecutionResult.error(
                        "Application context not available",
                        metadata={"node_type": self.node_name, "error_type": "service_unavailable"},
                    )

                # Get user's retrieval settings
                app_context.get_retrieval_settings()

                # Get progress queue for SSE streaming (optional)
                progress_queue: Optional[ProgressQueue] = services.get("progress_queue")

                # Track last update time for keepalive
                last_update = asyncio.get_event_loop().time()
                keepalive_interval = TimeoutConfig.get_websocket_keepalive_interval()

                # Progress callback to update UI and reset keepalive timer
                # Maps retrieval sub-steps to main progress steps (2-5)
                async def on_retrieval_progress(step_name: str, current: int, total: int):
                    nonlocal last_update

                    # Emit to SSE progress queue if available
                    if progress_queue:
                        step_messages = {
                            RetrievalStep.VECTOR_SEARCH: "Searching vector database",
                            RetrievalStep.ANCHOR_EXPANSION: "Expanding anchors",
                            RetrievalStep.GRAPH_EXPANSION: "Expanding graph relationships",
                            RetrievalStep.LOCATION_SCORING: "Scoring locations",
                            RetrievalStep.RANKING_RESULTS: "Ranking results",
                            RetrievalStep.BUILDING_CONTEXT: "Building context",
                        }
                        event = create_retrieval_progress_event(
                            step=step_name,
                            message=step_messages.get(step_name, step_name),
                            details={"current": current, "total": total},
                        )
                        await progress_queue.emit(event)

                    last_update = asyncio.get_event_loop().time()

                # Retrieval task with timing
                async def retrieval_task():
                    with logger.timer("vector_search", level="info") as timer:
                        result = await retrieval_service.retrieve_with_progress(
                            repo_id=repo_id,
                            query=question,
                            anchors=None,
                            config=None,  # Use service's default config
                            progress_callback=on_retrieval_progress,
                        )
                        logger.info(
                            "Retrieval service returned",
                            data={
                                "has_context_items": hasattr(result, "context_items"),
                                "context_items_type": type(result.context_items)
                                if hasattr(result, "context_items")
                                else None,
                                "context_items_len": len(result.context_items)
                                if hasattr(result, "context_items")
                                else 0,
                                "result_type": type(result).__name__,
                                "duration_seconds": timer.elapsed_seconds,
                            },
                        )
                        return result, timer.elapsed_seconds

                # Keepalive task to prevent WebSocket timeout
                async def keepalive_task():
                    nonlocal last_update
                    while True:
                        await asyncio.sleep(5)  # Check every 5 seconds
                        current_time = asyncio.get_event_loop().time()
                        if current_time - last_update > keepalive_interval:
                            last_update = current_time

                # Run both tasks concurrently
                retrieval_task_obj = asyncio.create_task(retrieval_task())
                keepalive_task_obj = asyncio.create_task(keepalive_task())

                try:
                    # Wait for retrieval with timeout
                    timeout_seconds = TimeoutConfig.get_retrieval_timeout()
                    retrieval_response, vector_search_duration = await asyncio.wait_for(
                        retrieval_task_obj, timeout=timeout_seconds
                    )
                    keepalive_task_obj.cancel()
                except asyncio.TimeoutError:
                    keepalive_task_obj.cancel()
                    logger.error(f"Retrieval timed out after {timeout_seconds}s")
                    return NodeExecutionResult.error(
                        f"Retrieval timed out after {timeout_seconds}s",
                        metadata={"node_type": self.node_name, "error_type": "timeout"},
                    )
                except Exception as e:
                    keepalive_task_obj.cancel()
                    raise e

                # Convert RetrievalResponse to context items
                context_items = retrieval_response.context_items if hasattr(retrieval_response, "context_items") else []

                logger.info(
                    f"Semantic retrieval completed: found {len(context_items)} context items",
                    data={
                        "context_items_count": len(context_items),
                        "repo_id": repo_id,
                        "query": question[:100],
                        "vector_search_duration": vector_search_duration,
                    },
                )

            except AttributeError as e:
                logger.error(f"AttributeError during retrieval: {e}", exc_info=True)
                return NodeExecutionResult.error(
                    f"Retrieval structure error: {str(e)}",
                    metadata={"node_type": self.node_name, "error_type": "attribute_error"},
                )
            except Exception as retrieval_error:
                logger.error(f"Unexpected error during retrieval: {retrieval_error}", exc_info=True)
                return NodeExecutionResult.error(
                    f"Retrieval failed: {str(retrieval_error)}",
                    metadata={"node_type": self.node_name, "error_type": "retrieval_error"},
                )

            # Determine context sufficiency
            sufficiency: Literal["sufficient", "sparse", "none"] = "none"
            if len(context_items) >= 5:
                sufficiency = "sufficient"
            elif len(context_items) > 0:
                sufficiency = "sparse"

            logger.info(
                "Semantic retrieval completed",
                data={
                    "result_count": len(context_items),
                    "sufficiency": sufficiency,
                    "vector_search_duration": vector_search_duration,
                },
            )

            # Create initial message for the agent with the user's question and context
            question = state.get("refined_question") or state.get("original_question", "")

            # Use prompt_manager to render context (same as v2)
            app_context = services.get("app_context")
            graph_store = getattr(app_context, "graph_kb_facade", None) if app_context else None

            limited_context_items = context_items

            if graph_store and graph_store.prompt_manager:
                # Use prompt_manager to render the context properly (same as v2)
                prompts = graph_store.prompt_manager.render_full_prompt(
                    question=question,
                    context_items=limited_context_items,
                    include_tools=False,  # Agent handles tools natively
                )

                # The user prompt contains the formatted context
                context_with_question = prompts.get("user", f"User Question: {question}")

                logger.info(
                    "Context rendered using prompt_manager",
                    data={
                        "user_prompt_length": len(context_with_question),
                        "context_items_total": len(context_items),
                        "context_items_in_prompt": len(limited_context_items),
                    },
                )
            else:
                # Fallback: simple formatting if prompt_manager not available
                logger.warning("prompt_manager not available, using simple context formatting")
                context_summary = "\n\n".join(
                    [f"File: {item.file_path}\n{item.content}" for item in context_items[:10]]
                )
                context_with_question = f"""User Question: {question}

Retrieved Context:
{context_summary}

Please analyze the retrieved context and answer the user's question."""

            # Prepend prior conversation summary so the LLM retains multi-turn context.
            # Messages from prior turns are cleared in ValidateInputNode to prevent token
            # overflow, so conversation_history is the lightweight replacement.
            conversation_history: List[dict] = state.get("conversation_history", [])
            if conversation_history:
                prior_qa = "\n".join(
                    f"Q: {entry.get('question', '')}\nA: {entry.get('answer', '')}"
                    for entry in conversation_history[-3:]  # last 3 turns max
                )
                context_with_question = (
                    f"Prior conversation (for context):\n{prior_qa}\n\n---\n\n{context_with_question}"
                )

            # For architectural/broad questions, prepend a mandatory exploration directive.
            # Without this, the LLM answers from the pre-loaded context dump and makes
            # zero tool calls — even though the system prompt says to explore with tools.
            question_type = state.get("question_type", "general")
            if question_type == "architectural":
                repo_id_hint = f'"{state.get("repo_id", "this-repo")}"'
                exploration_directive = (
                    "**MANDATORY EXPLORATION REQUIRED**\n\n"
                    "This is a broad architectural question. The context below is a *starting point only*. "
                    "You MUST use the available tools to research the codebase before answering. "
                    "Do NOT answer based solely on the context provided.\n\n"
                    "Required steps before writing your answer:\n"
                    f"1. Call `search_code` to find the main entry points and startup logic (repo_id={repo_id_hint})\n"
                    f"2. Call `trace_call_chain` on the primary entry point "
                    f"(direction=\"outgoing\", max_depth=4) to trace the main request flow\n"
                    f"3. Call `get_file_content` on key orchestrator/facade files you discover\n"
                    f"4. Repeat for each major capability or distinct code path (do not stop after one)\n"
                    f"5. Call `search_code` for error handling patterns\n\n"
                    "Only write your final answer after completing these tool calls.\n\n"
                    "---\n\n"
                )
                context_with_question = exploration_directive + context_with_question

            # Create HumanMessage with the rendered context
            initial_message = HumanMessage(content=context_with_question)

            logger.info("Initial message created for agent", data={"message_length": len(initial_message.content)})

            # Convert ContextItem dataclasses to dicts before storing in state.
            # The state schema declares List[dict] but retrieval returns ContextItem
            # dataclasses, causing LangGraph msgpack deserialization warnings.
            def _to_dict(item: Any) -> dict:
                try:
                    dataclass_fields(item)
                    raw = asdict(item)
                    # asdict() preserves enum instances; convert to primitives so
                    # LangGraph msgpack checkpointing doesn't warn about unregistered types.
                    return {k: v.value if isinstance(v, Enum) else v for k, v in raw.items()}
                except TypeError:
                    return item if isinstance(item, dict) else vars(item)

            return NodeExecutionResult.success(
                output={
                    "context_items": [_to_dict(item) for item in context_items],
                    "context_sufficiency": sufficiency,
                    "vector_search_duration": vector_search_duration,
                    "messages": [initial_message],
                }
            )

        except Exception as e:
            logger.error(f"Semantic retrieval failed: {e}")
            return NodeExecutionResult.error(
                f"Semantic retrieval failed: {str(e)}", metadata={"node_type": self.node_name}
            )


class GraphExpansionNode(BaseWorkflowNodeV3):
    """Expands semantic search results using multi-hop graph traversal."""

    def __init__(self):
        super().__init__("graph_expansion")

    async def _execute_async(self, state: Dict[str, Any], services: ServiceRegistry) -> NodeExecutionResult:
        """
        Execute graph expansion to discover code relationships.

        Input from state:
            - repo_id: Repository identifier
            - refined_question: User's question (refined)
            - context_items: Initial vector search results
            - progress_message_id: UI progress message ID

        Output to state:
            - graph_context: GraphRAGResult with context packets
            - total_nodes_explored: Count of graph nodes traversed
            - symbols_found: Starting symbols from vector search
            - visualization: Mermaid diagram (if generated)
            - graph_expansion_duration: Time taken for expansion

        Returns:
            NodeExecutionResult with success/error status
        """
        try:
            # Setup execution context
            self._setup_execution_context(state, services)

            # 1. Extract inputs from state
            repo_id = state.get("repo_id")
            question = state.get("refined_question") or state.get("original_question", "")

            if not repo_id or not question:
                return NodeExecutionResult.error("Missing repo_id or question", metadata={"node_type": self.node_name})

            # 2. Get configuration (with defaults)
            config = self._get_expansion_config(state)

            # 3. Check if graph expansion is enabled
            if not config.get("enable_graph_expansion", True):
                logger.info("Graph expansion disabled by configuration")
                return NodeExecutionResult.success(output={"graph_expansion_skipped": True, "reason": "disabled"})

            # 4. Get analysis service
            analysis_service, error = self._get_analysis_service(services)
            if error:
                # Service unavailable - graceful fallback
                logger.warning("Analysis service unavailable, skipping graph expansion")
                return NodeExecutionResult.success(
                    output={"graph_expansion_skipped": True, "reason": "service_unavailable"}
                )

            # 6. Perform graph expansion with timeout and timing
            duration = 0.0  # Initialize duration before try block
            try:
                with logger.timer("graph_expansion", level="info") as timer:
                    graph_context = await asyncio.wait_for(
                        asyncio.to_thread(
                            analysis_service.retrieve_context,
                            repo_id=repo_id,
                            query=question,
                            max_depth=config.get("max_depth", 5),
                            max_expansion_nodes=config.get("max_expansion_nodes", 500),
                            top_k=config.get("top_k", 30),
                            include_visualization=config.get("include_visualization", True),
                        ),
                        timeout=config.get("expansion_timeout", 30),
                    )
                    duration = timer.elapsed_seconds

                # 7. Log success
                logger.info(
                    "Graph expansion completed",
                    data={
                        "nodes_explored": graph_context.total_nodes_explored
                        if hasattr(graph_context, "total_nodes_explored")
                        else 0,
                        "symbols_found": len(graph_context.symbols_found)
                        if hasattr(graph_context, "symbols_found")
                        else 0,
                        "duration": duration,
                    },
                )

                # 8. Build graph expansion summary message for the agent.
                # Use SystemMessage so it doesn't break the HumanMessage → AIMessage
                # alternating pattern required by some model providers.
                nodes_explored = (
                    graph_context.total_nodes_explored if hasattr(graph_context, "total_nodes_explored") else 0
                )
                symbols_found = graph_context.symbols_found if hasattr(graph_context, "symbols_found") else []
                # Extract .code (str) from MermaidDiagram dataclass; state declares visualization: str
                _viz = graph_context.visualization if hasattr(graph_context, "visualization") else None
                visualization_code: Optional[str] = _viz.code if _viz is not None else None

                graph_messages = []
                if symbols_found:
                    symbols_preview = ", ".join(f"`{s}`" for s in symbols_found[:25])
                    if len(symbols_found) > 25:
                        symbols_preview += f" ... and {len(symbols_found) - 25} more"
                    graph_summary = (
                        f"[Graph Expansion Results]\n"
                        f"Traversed {nodes_explored} nodes in the code graph and found "
                        f"{len(symbols_found)} related symbols.\n\n"
                        f"Key symbols discovered: {symbols_preview}"
                    )
                    if visualization_code:
                        graph_summary += f"\n\nRelationship diagram:\n```mermaid\n{visualization_code}\n```"
                    graph_messages = [SystemMessage(content=graph_summary)]

                # 9. Return results
                return NodeExecutionResult.success(
                    output={
                        "graph_context": graph_context,
                        "total_nodes_explored": nodes_explored,
                        "symbols_found": symbols_found,
                        "visualization": visualization_code,
                        "graph_expansion_duration": duration,
                        "messages": graph_messages,
                    }
                )

            except asyncio.TimeoutError:
                logger.warning(f"Graph expansion timed out after {config.get('expansion_timeout', 30)}s")
                return NodeExecutionResult.success(
                    output={
                        "graph_expansion_skipped": True,
                        "reason": "timeout",
                        "graph_expansion_duration": config.get("expansion_timeout", 30),
                    }
                )
            except AttributeError as e:
                # AttributeError typically means service is None (unavailable)
                if "'NoneType' object has no attribute" in str(e):
                    logger.warning(f"Graph expansion failed due to service unavailability: {e}")
                    result = NodeExecutionResult.success(
                        output={
                            "graph_expansion_skipped": True,
                            "reason": "service_unavailable",
                            "error_message": str(e),
                            "graph_expansion_duration": duration,
                        }
                    )
                    logger.info(f"Returning result with output: {result.output}")
                    return result
                # Other AttributeErrors are genuine errors
                logger.error(f"Graph expansion failed: {e}", data={"error": str(e)})
                return NodeExecutionResult.success(
                    output={
                        "graph_expansion_skipped": True,
                        "reason": "error",
                        "error_message": str(e),
                        "graph_expansion_duration": duration,
                    }
                )
            except Exception as e:
                logger.error(f"Graph expansion failed: {e}", data={"error": str(e)})
                return NodeExecutionResult.success(
                    output={
                        "graph_expansion_skipped": True,
                        "reason": "error",
                        "error_message": str(e),
                        "graph_expansion_duration": duration,
                    }
                )

        except Exception as e:
            logger.error(f"Graph expansion node failed: {e}")
            return NodeExecutionResult.error(
                f"Graph expansion node failed: {str(e)}", metadata={"node_type": self.node_name}
            )

    def _get_expansion_config(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract graph expansion configuration from state or use defaults.

        Args:
            state: Current workflow state

        Returns:
            Configuration dictionary with defaults
        """
        return {
            "enable_graph_expansion": state.get("enable_graph_expansion", True),
            "max_depth": state.get("max_depth", 5),
            "max_expansion_nodes": state.get("max_expansion_nodes", 500),
            "top_k": state.get("top_k", 30),
            "expansion_timeout": state.get("expansion_timeout", 30),
            "include_visualization": state.get("include_visualization", True),
        }

    def _get_analysis_service(self, services: ServiceRegistry):
        """
        Get analysis service from app context.

        Args:
            services: Injected services

        Returns:
            Tuple of (analysis_service, error_result). Check if service is None.
        """
        app_context = self._get_app_context(services)
        if not app_context:
            return None, NodeExecutionResult.error(
                "Application context not available",
                metadata={"node_type": self.node_name, "error_type": "service_unavailable"},
            )

        # Get GraphKB facade
        if not hasattr(app_context, "graph_kb_facade") or not app_context.graph_kb_facade:
            logger.warning("GraphKB facade not available")
            return None, None  # Return None for graceful fallback

        facade = app_context.graph_kb_facade

        # Get analysis service
        if not hasattr(facade, "analysis_service") or not facade.analysis_service:
            logger.warning("Analysis service not available in facade")
            return None, None  # Return None for graceful fallback

        return facade.analysis_service, None


class ContextSufficiencyCheckNode(BaseWorkflowNodeV3):
    """Checks if retrieved context is sufficient to answer the question."""

    def __init__(self):
        super().__init__("context_sufficiency_check")

    async def _execute_async(self, state: Dict[str, Any], services: ServiceRegistry) -> NodeExecutionResult:
        """
        Check if context is sufficient.

        This is a simple check - in production could use LLM.
        """
        # Session ID set by _setup_execution_context

        try:
            context_items = state.get("context_items", [])

            # Simple heuristic: need at least 3 items
            is_sufficient = len(context_items) >= 3

            logger.info(
                "Context sufficiency check", data={"context_count": len(context_items), "is_sufficient": is_sufficient}
            )

            return NodeExecutionResult.success(output={"context_sufficient": is_sufficient})

        except Exception as e:
            logger.error(f"Context sufficiency check failed: {e}")
            return NodeExecutionResult.error(
                f"Context sufficiency check failed: {str(e)}", metadata={"node_type": self.node_name}
            )


class GraphRAGExpansionNode(BaseWorkflowNodeV3):
    """Expands context using graph relationships."""

    def __init__(self):
        super().__init__("graph_rag_expansion")

    async def _execute_async(self, state: Dict[str, Any], services: ServiceRegistry) -> NodeExecutionResult:
        """
        Expand context using graph relationships.
        """
        # Session ID set by _setup_execution_context

        try:
            app_context = services.get("app_context")
            if not app_context:
                return NodeExecutionResult.error(
                    "Application context not available", metadata={"node_type": self.node_name}
                )

            repo_id: str | None = state.get("repo_id")
            context_items = state.get("context_items", [])

            if not repo_id or not context_items:
                logger.info("No repo_id or context items for graph expansion")
                return NodeExecutionResult.success(output={})

            logger.info("Expanding context via graph", data={"repo_id": repo_id, "initial_items": len(context_items)})

            # Extract file paths from context items
            file_paths = list(set(item.get("file_path") for item in context_items if item.get("file_path")))

            # Get related files through imports
            facade = app_context.graph_kb_facade
            if not facade:
                logger.warning("GraphKB facade not available for graph expansion")
                return NodeExecutionResult.success(output={})

            query_service = facade.query_service
            if not query_service:
                logger.warning("Query service not available for graph expansion")
                return NodeExecutionResult.success(output={})

            expanded_context = []

            for file_path in file_paths[:5]:  # Limit to first 5 files
                try:
                    # Find symbols in this file via pattern matching
                    file_symbols = query_service.get_symbols_by_pattern(
                        repo_id=repo_id,
                        file_pattern=file_path,
                        limit=5,
                    )
                    for symbol in file_symbols[:3]:
                        # Get outgoing neighbors (calls, imports)
                        neighbors = query_service.get_neighbors(
                            node_id=symbol.id,
                            direction="outgoing",
                            limit=3,
                        )
                        for neighbor in neighbors:
                            neighbor_file = neighbor.attrs.get("file_path")
                            if neighbor_file and neighbor_file != file_path:
                                expanded_context.append(
                                    {
                                        "source": "graph",
                                        "file_path": neighbor_file,
                                        "relationship": "dependency",
                                        "metadata": {},
                                    }
                                )
                except Exception as e:
                    logger.warning(f"Failed to expand context for {file_path}: {e}")

            logger.info("Graph expansion completed", data={"expanded_items": len(expanded_context)})

            return NodeExecutionResult.success(output={"flow_context": expanded_context})

        except Exception as e:
            logger.error(f"Graph RAG expansion failed: {e}")
            return NodeExecutionResult.error(
                f"Graph RAG expansion failed: {str(e)}", metadata={"node_type": self.node_name}
            )


class FormatResponseNode(BaseWorkflowNodeV3):
    """Formats the final response for presentation."""

    def __init__(self):
        super().__init__("format_response")

    async def _execute_async(self, state: Dict[str, Any], services: ServiceRegistry) -> NodeExecutionResult:
        """
        Format the LLM response for user presentation with statistics.
        """
        # Session ID set by _setup_execution_context

        try:
            # Setup execution context
            self._setup_execution_context(state, services)

            messages = state.get("messages", [])
            context_items = state.get("context_items", [])
            tool_calls_history = state.get("tool_calls_history", [])

            # Check if we have messages to format
            if not messages or len(messages) == 0:
                logger.warning("No messages to format - LLM may have failed")
                # Create a helpful error message
                error_response = (
                    "I encountered an issue analyzing the code. This might be because:\n\n"
                    f"- Too much context was retrieved ({len(context_items)} code chunks)\n"
                    "- The context exceeded the model's token limit\n\n"
                    "Try:\n"
                    "- Asking a more specific question\n"
                    "- Focusing on a particular file or function\n"
                    "- Breaking your question into smaller parts"
                )
                return NodeExecutionResult.success(
                    output={"llm_response": error_response, "final_output": error_response}
                )

            # Get last message (should be AIMessage from LLM)
            last_message = messages[-1]

            # Check if the last message is actually an AI response (not the user's question with context)
            if not isinstance(last_message, AIMessage):
                logger.warning(
                    "Last message is not an AIMessage - LLM likely failed",
                    data={"message_type": type(last_message).__name__, "messages_count": len(messages)},
                )
                error_response = (
                    "I encountered an issue analyzing the code. This might be because:\n\n"
                    f"- Too much context was retrieved ({len(context_items)} code chunks)\n"
                    "- The context exceeded the model's token limit\n"
                    "- The LLM call failed or timed out\n\n"
                    "Try:\n"
                    "- Starting a new conversation\n"
                    "- Asking a more specific question\n"
                    "- Focusing on a particular file or function"
                )
                return NodeExecutionResult.success(
                    output={"llm_response": error_response, "final_output": error_response}
                )

            # Extract content from the AI message
            if hasattr(last_message, "content"):
                response_content = last_message.content
            else:
                response_content = str(last_message)

            # If response is empty or too short, provide helpful message
            if not response_content or len(response_content.strip()) < 10:
                logger.warning(
                    "LLM response is empty or too short",
                    data={"response_length": len(response_content) if response_content else 0},
                )
                response_content = (
                    "I encountered an issue analyzing the code. This might be because:\n\n"
                    f"- Too much context was retrieved ({len(context_items)} code chunks)\n"
                    "- The context exceeded the model's token limit\n\n"
                    "Try:\n"
                    "- Asking a more specific question\n"
                    "- Focusing on a particular file or function\n"
                    "- Breaking your question into smaller parts"
                )

            # Add statistics footer to the response
            # Use explicit newlines to ensure proper formatting in Chainlit
            stats_footer = (
                "\n\n"  # Two newlines for spacing
                "---\n\n"  # Horizontal rule with spacing
                "**📊 Analysis Statistics:**\n\n"  # Header with spacing
                f"- **Code chunks analyzed:** {len(context_items)}\n"  # First stat
            )

            # Count tool calls by type
            completed_tools = ToolDisplayFormatter.count_completed_calls(tool_calls_history)
            if completed_tools > 0:
                stats_footer += f"- **Additional searches:** {completed_tools} tool calls\n"

            final_output = response_content + stats_footer

            # Debug: Log the final output to verify formatting
            logger.info(
                "Final output prepared",
                data={
                    "response_length": len(response_content),
                    "stats_footer_length": len(stats_footer),
                    "final_output_length": len(final_output),
                    "has_newlines": "\n" in final_output,
                    "newline_count": final_output.count("\n"),
                    "stats_footer_preview": repr(stats_footer[:100]),  # Show first 100 chars with escape sequences
                },
            )

            logger.info(
                "Response formatted with statistics",
                data={
                    "response_length": len(response_content),
                    "context_items": len(context_items),
                    "tool_calls": completed_tools,
                },
            )

            return NodeExecutionResult.success(output={"llm_response": response_content, "final_output": final_output})

        except Exception as e:
            logger.error(f"Response formatting failed: {e}")
            return NodeExecutionResult.error(
                f"Response formatting failed: {str(e)}", metadata={"node_type": self.node_name}
            )


class PresentToUserNode(BaseWorkflowNodeV3):
    """Presents the final response to the user."""

    def __init__(self):
        super().__init__("present_to_user")

    async def _execute_async(self, state: Dict[str, Any], services: ServiceRegistry) -> NodeExecutionResult:
        """
        Present the response to the user via messaging system.
        """
        # Session ID set by _setup_execution_context

        try:
            # Setup execution context
            self._setup_execution_context(state, services)

            final_output = state.get("final_output", "")
            error = state.get("error", "")
            progress_msg_id = state.get("progress_message_id")
            tool_calls_history = state.get("tool_calls_history", [])

            logger.info(
                "PresentToUserNode state check",
                data={
                    "has_final_output": bool(final_output),
                    "final_output_length": len(final_output) if final_output else 0,
                    "has_error": bool(error),
                    "has_progress_msg_id": bool(progress_msg_id),
                    "tool_calls_count": len(tool_calls_history),
                },
            )

            # Handle error case - present error to user
            if error and not final_output:
                logger.info("Presenting error to user")
                return NodeExecutionResult.success(output={"success": False, "error_presented": True})

            if not final_output:
                logger.error("No final_output or error in state!")
                return NodeExecutionResult.error("No output to present", metadata={"node_type": self.node_name})

            # Count completed tool calls for logging using utility
            completed_calls_count = ToolDisplayFormatter.count_completed_calls(tool_calls_history)

            logger.info(
                "Response presented to user",
                data={"output_length": len(final_output), "tools_used": completed_calls_count},
            )

            # Persist this turn's Q&A to conversation_history so future turns
            # can reference prior context without re-sending the full code context.
            question = state.get("refined_question") or state.get("original_question", "")
            llm_response = state.get("llm_response", "")
            history_entry = {
                "question": question,
                "answer": llm_response,
            }

            return NodeExecutionResult.success(
                output={"success": True, "conversation_history": [history_entry]}
            )

        except Exception as e:
            logger.error(f"Presentation failed: {e}")
            return NodeExecutionResult.error(f"Presentation failed: {str(e)}", metadata={"node_type": self.node_name})
