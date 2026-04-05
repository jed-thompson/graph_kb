"""
Tests for WebSocket protocol models and message handling.

Covers protocol validation, message routing, and handler dispatch
for start, input, cancel, reconnect, and action message types.
"""

from typing import Literal, cast

import pytest
from pydantic import ValidationError

from graph_kb_api.schemas.websocket import WorkflowType
from graph_kb_api.websocket.protocol import (
    VALID_ACTIONS,
    VALID_DECISIONS,
    VALID_OUTGOING_TYPES,
    VALID_WORKFLOW_TYPES,
    ActionPayload,
    AskCodePayload,
    ClientMessage,
    DeepAgentPayload,
    IngestPayload,
    MultiAgentPayload,
    ReconnectPayload,
    WSInputPayload,
    WSMessage,
    WSOutgoingMessage,
    WSStartPayload,
    build_outgoing_message,
)

ActionType = Literal["pause", "resume"]
OutgoingType = Literal["partial", "complete", "error", "progress", "preview"]
WSMsgType = Literal["start", "cancel", "input"]


class TestWSStartPayload:
    """Test WSStartPayload validation."""

    def test_valid_workflow_types(self):
        """All four workflow types are accepted."""
        for wt in cast(list[WorkflowType], ["ask-code", "ingest", "multi_agent", "deep"]):
            payload = WSStartPayload(workflow_type=wt)
            assert payload.workflow_type == wt

    def test_invalid_workflow_type_rejected(self):
        """Invalid workflow_type raises ValidationError."""
        with pytest.raises(ValidationError):
            WSStartPayload(workflow_type=cast(WorkflowType, "unknown"))

    def test_deep_workflow_type(self):
        """'deep' is a valid workflow type."""
        payload = WSStartPayload(workflow_type="deep", repo_id="repo-1", query="explain auth")
        assert payload.workflow_type == "deep"
        assert payload.repo_id == "repo-1"

    def test_optional_fields_default_none(self):
        payload = WSStartPayload(workflow_type="ask-code")
        assert payload.repo_id is None
        assert payload.query is None
        assert payload.task is None


class TestWSInputPayload:
    """Test WSInputPayload validation."""

    def test_valid_decisions(self):
        for decision in ["proceed", "configure", "cancel"]:
            payload = WSInputPayload(thread_id="t-1", decision=decision)
            assert payload.decision == decision

    def test_invalid_decision_rejected(self):
        # decision is now Optional[str] to support richer payloads;
        # arbitrary strings are accepted (validation happens in handler logic)
        payload = WSInputPayload(thread_id="t-1", decision="approve")
        assert payload.decision == "approve"

    def test_thread_id_required(self):
        with pytest.raises(ValidationError):
            WSInputPayload.model_validate({"decision": "proceed"})


class TestWSOutgoingMessage:
    """Test WSOutgoingMessage validation."""

    def test_valid_outgoing_types(self):
        for t in cast(list[OutgoingType], ["partial", "complete", "error", "progress", "preview"]):
            msg = WSOutgoingMessage(type=t)
            assert msg.type == t

    def test_invalid_outgoing_type_rejected(self):
        with pytest.raises(ValidationError):
            WSOutgoingMessage.model_validate({"type": "tool_call"})

    def test_agent_field_optional(self):
        msg = WSOutgoingMessage(type="partial", data={"content": "hi"}, agent="code_analyst")
        assert msg.agent == "code_analyst"

    def test_data_defaults_to_none(self):
        msg = WSOutgoingMessage(type="complete")
        assert msg.data is None


class TestWSMessage:
    """Test WSMessage (incoming) validation."""

    def test_valid_types(self):
        for t in cast(list[WSMsgType], ["start", "cancel", "input"]):
            msg = WSMessage(type=t)
            assert msg.type == t

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            WSMessage.model_validate({"type": "reconnect"})

    def test_payload_defaults_empty(self):
        msg = WSMessage(type="start")
        assert msg.payload == {}


class TestClientMessage:
    """Test extended ClientMessage with reconnect and action."""

    def test_all_message_types(self):
        for t in ["start", "input", "cancel", "reconnect", "action"]:
            msg = ClientMessage(type=t)
            assert msg.type == t

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            ClientMessage(type="unknown")

    def test_workflow_id_optional(self):
        msg = ClientMessage(type="cancel", workflow_id="wf-123")
        assert msg.workflow_id == "wf-123"

    def test_payload_defaults_empty(self):
        msg = ClientMessage(type="start")
        assert msg.payload == {}


class TestWorkflowPayloads:
    """Test workflow-specific payload models."""

    def test_ask_code_payload(self):
        p = AskCodePayload(query="what is X?", repo_id="repo-1")
        assert p.query == "what is X?"
        assert p.repo_id == "repo-1"

    def test_ingest_payload_defaults(self):
        p = IngestPayload(git_url="https://github.com/test/repo")
        assert p.branch == "main"
        assert p.force_reindex is False

    def test_deep_agent_payload(self):
        p = DeepAgentPayload(query="trace auth flow", repo_id="repo-2")
        assert p.query == "trace auth flow"

    def test_multi_agent_payload(self):
        p = MultiAgentPayload(query="refactor module")
        assert p.auto_review is True
        assert p.max_agents is None

    def test_reconnect_payload(self):
        p = ReconnectPayload(workflow_id="wf-abc")
        assert p.workflow_id == "wf-abc"
        assert p.last_event_id is None

    def test_action_payload_valid(self):
        for action in cast(list[ActionType], ["pause", "resume"]):
            p = ActionPayload(workflow_id="wf-1", action=action)
            assert p.action == action

    def test_action_payload_invalid(self):
        with pytest.raises(ValidationError):
            ActionPayload.model_validate({"workflow_id": "wf-1", "action": "stop"})


class TestWSInputPayloadPlan:
    """Test WSInputPayload for plan workflows."""

    def test_clarification_responses(self):
        p = WSInputPayload(
            thread_id="t-1",
            clarification_responses={"gap_1": "Use OAuth2", "gap_2": "PostgreSQL"},
        )
        assert p.clarification_responses == {
            "gap_1": "Use OAuth2",
            "gap_2": "PostgreSQL",
        }
        assert p.decision is None

    def test_approval_response(self):
        p = WSInputPayload(
            thread_id="t-1",
            approved=True,
            feedback="",
        )
        assert p.approved is True
        assert p.sections_to_revise is None

    def test_rejection_with_sections(self):
        p = WSInputPayload(
            thread_id="t-1",
            approved=False,
            feedback="Auth section needs more detail",
            sections_to_revise=["auth", "security"],
        )
        assert p.approved is False
        assert p.feedback == "Auth section needs more detail"
        assert p.sections_to_revise == ["auth", "security"]

    def test_thread_id_still_required(self):
        with pytest.raises(ValidationError):
            WSInputPayload.model_validate({"approved": True})


class TestConstants:
    """Test protocol constants."""

    def test_valid_workflow_types(self):
        assert VALID_WORKFLOW_TYPES == {
            "ask-code",
            "ingest",
            "multi_agent",
            "deep",
        }

    def test_valid_outgoing_types(self):
        assert VALID_OUTGOING_TYPES == {
            "partial",
            "complete",
            "error",
            "progress",
            "preview",
        }

    def test_valid_decisions(self):
        assert VALID_DECISIONS == {"proceed", "configure", "cancel"}

    def test_valid_actions(self):
        assert VALID_ACTIONS == {"pause", "resume"}


class TestBuildOutgoingMessage:
    """Test the build_outgoing_message helper."""

    def test_builds_valid_message(self):
        result = build_outgoing_message("complete", data={"answer": "done"})
        assert result["type"] == "complete"
        assert result["data"]["answer"] == "done"

    def test_agent_included_when_set(self):
        result = build_outgoing_message("partial", data={"content": "x"}, agent="researcher")
        assert result["agent"] == "researcher"

    def test_agent_excluded_when_none(self):
        result = build_outgoing_message("error", data={"message": "fail"})
        assert "agent" not in result

    def test_invalid_type_raises(self):
        with pytest.raises(ValidationError):
            build_outgoing_message(cast(OutgoingType, "invalid_type"), data={})
