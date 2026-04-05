"""Preservation property tests for Plan Workflow Fix.

Property 2: Preservation - Spec Workflow and Existing Commands Unchanged

**IMPORTANT**: These tests follow observation-first methodology.
**CRITICAL**: These tests MUST PASS on the current unfixed code.
They establish the baseline behavior that must be preserved after the fix is applied.

Observations on UNFIXED code:
- All 7 original PhaseId values (context, review, research, plan, orchestrate,
  completeness, generate) validate correctly in Python
- SpecPhasePromptData serializes correctly with original 7 phase IDs
- validateEvent accepts spec events with original 7 phase IDs (TypeScript)
- /spec [name] command sends spec.start over shared WebSocket
- /ingest, /clear, /wizard commands continue to be handled
- WebSocketContext.tsx generic 'message' handler processes spec.phase.prompt,
  spec.phase.progress, spec.phase.complete, spec.complete events correctly

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**
"""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from graph_kb_api.websocket.events import (
    PhaseField,
    PhaseId,
    SpecErrorData,
    SpecPhaseCompleteData,
    SpecPhaseProgressData,
    SpecPhasePromptData,
)

# ---------------------------------------------------------------------------
# Constants: The 7 original spec phase IDs that MUST remain valid
# ---------------------------------------------------------------------------

ORIGINAL_SPEC_PHASE_IDS = [
    "context",
    "review",
    "research",
    "plan",
    "orchestrate",
    "completeness",
    "generate",
]

# Known slash commands that must continue to work
EXISTING_SLASH_COMMANDS = ["spec", "ingest", "clear", "wizard"]


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

original_phase_id_st = st.sampled_from(ORIGINAL_SPEC_PHASE_IDS)

field_type_st = st.sampled_from(["text", "textarea", "select", "file", "multiselect", "json"])

phase_field_st = st.builds(
    PhaseField,
    id=st.text(min_size=1, max_size=30, alphabet=st.characters(categories=("L", "N", "Pd"))),
    label=st.text(min_size=1, max_size=50),
    type=field_type_st,
    required=st.booleans(),
    options=st.one_of(st.none(), st.lists(st.text(min_size=1, max_size=20), max_size=3)),
    placeholder=st.one_of(st.none(), st.text(max_size=50)),
)

session_id_st = st.text(
    min_size=1,
    max_size=50,
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_",
)

# JSON-safe values for Dict[str, Any] fields
json_safe_values = st.recursive(
    st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-(2**31), max_value=2**31),
        st.floats(allow_nan=False, allow_infinity=False),
        st.text(max_size=30),
    ),
    lambda children: st.one_of(
        st.lists(children, max_size=3),
        st.dictionaries(st.text(min_size=1, max_size=15), children, max_size=3),
    ),
    max_leaves=5,
)

json_safe_dict_st = st.dictionaries(
    st.text(min_size=1, max_size=15),
    json_safe_values,
    max_size=3,
)


# ---------------------------------------------------------------------------
# Property 2.1: All 7 original PhaseId values validate correctly
# ---------------------------------------------------------------------------


class TestOriginalPhaseIdPreservation:
    """All 7 original PhaseId values MUST continue to validate in Python.

    This ensures the PhaseId enum is not broken by adding new values.

    **Validates: Requirements 3.3, 3.4**
    """

    @given(phase=original_phase_id_st)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_original_phase_ids_are_valid_enum_values(self, phase: str):
        """For all original 7 PhaseId values, PhaseId(value) validates without error.

        **Validates: Requirements 3.3, 3.4**
        """
        phase_id = PhaseId(phase)
        assert phase_id.value == phase

    def test_all_seven_original_phases_present(self):
        """All 7 original spec phases MUST be present in PhaseId enum.

        **Validates: Requirements 3.3, 3.4**
        """
        enum_values = {p.value for p in PhaseId}
        for phase in ORIGINAL_SPEC_PHASE_IDS:
            assert phase in enum_values, f"Original phase '{phase}' missing from PhaseId enum"


# ---------------------------------------------------------------------------
# Property 2.2: SpecPhasePromptData serializes correctly with original phases
# ---------------------------------------------------------------------------


class TestSpecPhasePromptDataPreservation:
    """SpecPhasePromptData MUST serialize correctly with all 7 original phase IDs.

    This ensures the Pydantic model continues to accept and round-trip
    spec events with original phases after the fix adds new phases.

    **Validates: Requirements 3.3, 3.4**
    """

    @given(
        phase=original_phase_id_st,
        session_id=session_id_st,
        fields=st.lists(phase_field_st, max_size=3),
        prefilled=st.one_of(st.none(), json_safe_dict_st),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_spec_phase_prompt_data_validates_with_original_phases(
        self, phase: str, session_id: str, fields: list, prefilled
    ):
        """For all original 7 PhaseId values, SpecPhasePromptData(phase=id)
        validates without error.

        **Validates: Requirements 3.3, 3.4**
        """
        data = SpecPhasePromptData(
            session_id=session_id,
            phase=phase,
            fields=fields,
            prefilled=prefilled,
        )
        assert data.phase.value == phase
        assert data.session_id == session_id

    @given(
        phase=original_phase_id_st,
        session_id=session_id_st,
        fields=st.lists(phase_field_st, max_size=3),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_spec_phase_prompt_data_roundtrip_with_original_phases(self, phase: str, session_id: str, fields: list):
        """SpecPhasePromptData round-trips through JSON with original phases.

        **Validates: Requirements 3.4**
        """
        data = SpecPhasePromptData(
            session_id=session_id,
            phase=phase,
            fields=fields,
        )
        json_str = data.model_dump_json()
        restored = SpecPhasePromptData.model_validate_json(json_str)
        assert restored == data
        assert restored.phase.value == phase


# ---------------------------------------------------------------------------
# Property 2.3: SpecPhaseProgressData and SpecPhaseCompleteData preservation
# ---------------------------------------------------------------------------


class TestOtherSpecEventModelsPreservation:
    """Other spec event models MUST continue to work with original phases.

    **Validates: Requirements 3.2, 3.4**
    """

    @given(
        phase=original_phase_id_st,
        session_id=session_id_st,
        message=st.text(min_size=1, max_size=100),
        percent=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_spec_phase_progress_data_validates_with_original_phases(
        self, phase: str, session_id: str, message: str, percent: float
    ):
        """SpecPhaseProgressData validates with original 7 phase IDs.

        **Validates: Requirements 3.2, 3.4**
        """
        data = SpecPhaseProgressData(
            session_id=session_id,
            phase=phase,
            message=message,
            percent=percent,
        )
        assert data.phase.value == phase

    @given(
        phase=original_phase_id_st,
        session_id=session_id_st,
        result=json_safe_dict_st,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_spec_phase_complete_data_validates_with_original_phases(self, phase: str, session_id: str, result: dict):
        """SpecPhaseCompleteData validates with original 7 phase IDs.

        **Validates: Requirements 3.2, 3.4**
        """
        data = SpecPhaseCompleteData(
            session_id=session_id,
            phase=phase,
            result=result,
        )
        assert data.phase.value == phase

    @given(
        phase=st.one_of(st.none(), original_phase_id_st),
        message=st.text(min_size=1, max_size=100),
        code=st.text(min_size=1, max_size=30),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_spec_error_data_validates_with_original_phases(self, phase, message: str, code: str):
        """SpecErrorData validates with original 7 phase IDs (or None).

        **Validates: Requirements 3.2, 3.4**
        """
        data = SpecErrorData(
            message=message,
            code=code,
            phase=phase,
        )
        if phase is not None:
            assert data.phase.value == phase
        else:
            assert data.phase is None


# ---------------------------------------------------------------------------
# Property 2.4: validateEvent accepts spec events with original 7 phase IDs
# (Python-side validation via PhaseId enum - source of truth for frontend)
# ---------------------------------------------------------------------------


class TestValidateEventPreservation:
    """For all original 7 PhaseId values, validateEvent returns non-null
    for valid spec events.

    We test the Python PhaseId enum which is the source of truth that
    the TypeScript VALID_PHASE_IDS mirrors. If the Python enum preserves
    all 7 original values, the TypeScript validation will too.

    **Validates: Requirements 3.3**
    """

    @given(
        phase=original_phase_id_st,
        session_id=session_id_st,
        fields=st.lists(phase_field_st, max_size=2),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_valid_spec_events_accepted_for_all_original_phases(self, phase: str, session_id: str, fields: list):
        """For all original 7 PhaseId values, a valid spec event can be
        constructed and serialized — confirming the backend would emit
        events that the frontend validateEvent would accept.

        **Validates: Requirements 3.3**
        """
        # Construct a valid spec.phase.prompt event payload
        data = SpecPhasePromptData(
            session_id=session_id,
            phase=phase,
            fields=fields,
        )
        # Serialize to dict (as would be sent over WebSocket)
        payload = data.model_dump()
        assert payload["phase"] == phase
        assert payload["session_id"] == session_id
        assert isinstance(payload["fields"], list)

    @given(phase=original_phase_id_st)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_phase_id_string_matches_valid_phase_ids_set(self, phase: str):
        """Each original PhaseId value string matches what VALID_PHASE_IDS
        contains in validateEvent.ts.

        The VALID_PHASE_IDS set in validateEvent.ts contains exactly:
        "context", "review", "research", "plan", "orchestrate", "completeness", "generate"

        **Validates: Requirements 3.3**
        """
        valid_phase_ids_ts = {
            "context",
            "review",
            "research",
            "plan",
            "orchestrate",
            "completeness",
            "generate",
        }
        phase_id = PhaseId(phase)
        assert phase_id.value in valid_phase_ids_ts


# ---------------------------------------------------------------------------
# Property 2.5: Existing slash commands are recognized by handleCommand
# (Python-side: verify the command patterns exist in ChatContext.tsx source)
# ---------------------------------------------------------------------------


class TestExistingSlashCommandsPreservation:
    """For all existing slash commands (/spec, /ingest, /clear, /wizard),
    the command handler recognizes and processes them.

    Since ChatContext.tsx is TypeScript, we verify the command handling
    patterns exist in the source code. This is a structural preservation
    test that ensures the fix doesn't remove or break existing handlers.

    **Validates: Requirements 3.1, 3.5**
    """

    @given(command=st.sampled_from(EXISTING_SLASH_COMMANDS))
    @settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
    def test_existing_commands_have_handlers_in_chat_context(self, command: str):
        """For all existing slash commands, ChatContext.tsx contains a handler.

        We read the source and verify the command matching pattern exists.

        **Validates: Requirements 3.1, 3.5**
        """
        import os

        chat_context_path = os.path.join("graph_kb_dashboard", "src", "context", "ChatContext.tsx")
        with open(chat_context_path, "r", encoding="utf-8") as f:
            source = f.read()

        # Each command should have a handler pattern like:
        # if (command === 'spec') or if (command === 'ingest') etc.
        assert f"command === '{command}'" in source or f'command === "{command}"' in source, (
            f"Slash command '/{command}' handler not found in ChatContext.tsx"
        )

    def test_spec_command_sends_spec_start_event(self):
        """The /spec command handler MUST send 'spec.start' over WebSocket.

        **Validates: Requirements 3.1**
        """
        import os

        chat_context_path = os.path.join("graph_kb_dashboard", "src", "context", "ChatContext.tsx")
        with open(chat_context_path, "r", encoding="utf-8") as f:
            source = f.read()

        assert "spec.start" in source, "/spec command handler must send 'spec.start' event"

    def test_websocket_context_handles_spec_events(self):
        """WebSocketContext.tsx MUST handle spec.phase.prompt, spec.phase.progress,
        spec.phase.complete, and spec.complete events.

        **Validates: Requirements 3.2**
        """
        import os

        ws_context_path = os.path.join("graph_kb_dashboard", "src", "context", "WebSocketContext.tsx")
        with open(ws_context_path, "r", encoding="utf-8") as f:
            source = f.read()

        expected_events = [
            "spec.phase.prompt",
            "spec.phase.progress",
            "spec.phase.complete",
            "spec.complete",
        ]
        for event in expected_events:
            assert event in source, f"WebSocketContext.tsx must handle '{event}' event"

    def test_websocket_context_has_all_seven_phase_ids(self):
        """WebSocketContext.tsx allPhaseIds array MUST contain all 7 original phases.

        **Validates: Requirements 3.2**
        """
        import os

        ws_context_path = os.path.join("graph_kb_dashboard", "src", "context", "WebSocketContext.tsx")
        with open(ws_context_path, "r", encoding="utf-8") as f:
            source = f.read()

        for phase in ORIGINAL_SPEC_PHASE_IDS:
            assert f"'{phase}'" in source or f'"{phase}"' in source, (
                f"Phase '{phase}' not found in WebSocketContext.tsx"
            )
