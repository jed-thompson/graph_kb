"""LLM Response Recorder & Mock Playback.

Captures all LLM calls during plan workflow execution and saves them as
JSON files. In mock mode, returns pre-recorded responses instead of
calling the real LLM, enabling fast E2E test replay.

Toggle via env vars:
  LLM_RECORDING_MODE=record  LLM_RECORDING_DIR=/path/to/recordings
  LLM_RECORDING_MODE=mock     LLM_MOCK_DIR=/path/to/recordings
"""

from __future__ import annotations

import json
import os
import threading
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

_llm_call_context: ContextVar[dict[str, str] | None] = ContextVar(
    "llm_call_context", default=None
)


@dataclass
class RecordingEntry:
    """A single LLM call recording."""

    index: int
    step: str
    phase: str
    input_messages: list[dict[str, Any]]
    output: dict[str, Any]
    timestamp: str


def _serialize_message(msg: BaseMessage) -> dict[str, Any]:
    """Serialize a LangChain message to a JSON-safe dict."""
    d: dict[str, Any] = {"type": msg.__class__.__name__, "content": msg.content}
    if isinstance(msg.content, list):
        d["content"] = [
            (
                {"type": c["type"], "text": c.get("text", "")}
                if isinstance(c, dict)
                else str(c)
            )
            for c in msg.content
        ]
    if isinstance(msg, AIMessage) and msg.tool_calls:
        d["tool_calls"] = [
            {"id": tc["id"], "name": tc["name"], "args": tc["args"]}
            for tc in msg.tool_calls
        ]
    if hasattr(msg, "name") and msg.name:
        d["name"] = msg.name
    if hasattr(msg, "additional_kwargs"):
        extra = {
            k: v
            for k, v in msg.additional_kwargs.items()
            if k not in ("tool_calls",)
        }
        if extra:
            d["additional_kwargs"] = extra
    return d


def _deserialize_message(d: dict[str, Any]) -> BaseMessage:
    """Deserialize a dict back to a LangChain message."""
    msg_type = d.get("type", "HumanMessage")
    content = d.get("content", "")
    name = d.get("name")
    kwargs: dict[str, Any] = {"content": content}
    if name:
        kwargs["name"] = name
    if msg_type == "SystemMessage":
        return SystemMessage(**kwargs)
    elif msg_type == "AIMessage":
        tool_calls = d.get("tool_calls")
        if tool_calls:
            kwargs["tool_calls"] = tool_calls
        additional = d.get("additional_kwargs", {})
        if additional:
            kwargs["additional_kwargs"] = additional
        return AIMessage(**kwargs)
    else:
        return HumanMessage(**kwargs)


class LLMRecorder:
    """Records LLM calls to JSON files and replays them in mock mode."""

    _instance: Optional[LLMRecorder] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self, mode: str, record_dir: str | None, mock_dir: str | None) -> None:
        self.mode = mode
        self.record_dir = Path(record_dir) if record_dir else None
        self.mock_dir = Path(mock_dir) if mock_dir else None

        self._counter = 0
        self._manifest: list[dict[str, Any]] = []
        self._mock_entries: list[dict[str, Any]] | None = None

        if self.mode == "record" and self.record_dir:
            self.record_dir.mkdir(parents=True, exist_ok=True)
        if self.mode == "mock" and self.mock_dir:
            self._load_mock_entries()

    @classmethod
    def from_settings(cls) -> LLMRecorder:
        """Create a recorder from application settings.

        Resets the singleton only when the configured mode changes.
        Mock playback rewinds must be explicit so unrelated LLMService
        construction cannot rewind an active workflow mid-run.
        Thread-safe via class-level lock.
        """
        from graph_kb_api.config.settings import settings

        mode = settings.llm_recording_mode
        record_dir = settings.llm_recording_dir
        mock_dir = settings.llm_mock_dir if mode == "mock" else settings.llm_recording_dir

        with cls._lock:
            # Reset singleton only when mode changes.
            if cls._instance is not None:
                if cls._instance.mode != mode:
                    cls._instance = None

            if cls._instance is None:
                cls._instance = cls(mode, record_dir, mock_dir)
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        with cls._lock:
            cls._instance = None

    @property
    def should_record(self) -> bool:
        return self.mode == "record"

    @property
    def should_mock(self) -> bool:
        return self.mode == "mock"

    def rewind_mock_run(self) -> None:
        """Restart mock playback from the first recording.

        This should be invoked only when a caller intentionally starts a new
        workflow replay. Implicit rewinds cause sessions and phases to consume
        each other's responses.
        """
        if not self.should_mock:
            return
        self._counter = 0
        self._manifest = []

    # ── Recording ─────────────────────────────────────────────────

    def record_call(
        self,
        messages: list[BaseMessage],
        response: BaseMessage,
        step: str = "",
        phase: str = "",
    ) -> None:
        """Save a single LLM call to disk."""
        if not self.should_record or not self.record_dir:
            return

        self._counter += 1
        entry = RecordingEntry(
            index=self._counter,
            step=step,
            phase=phase,
            input_messages=[_serialize_message(m) for m in messages],
            output=_serialize_message(response),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        filename = f"{self._counter:03d}_{phase}_{step}.json"
        filepath = self.record_dir / filename
        filepath.write_text(
            json.dumps(entry.__dict__, indent=2, default=str), encoding="utf-8"
        )

        self._manifest.append(
            {"index": self._counter, "step": step, "phase": phase, "file": filename}
        )

        print(f"[LLMRecorder] Recorded #{self._counter}: {phase}/{step} → {filename}")

    def save_manifest(self) -> None:
        """Write the index.json manifest."""
        if not self.should_record or not self.record_dir:
            return
        manifest_path = self.record_dir / "index.json"
        manifest_path.write_text(
            json.dumps(self._manifest, indent=2), encoding="utf-8"
        )
        print(f"[LLMRecorder] Manifest saved: {len(self._manifest)} entries")

    # ── Mock Playback ─────────────────────────────────────────────

    def _load_mock_entries(self) -> None:
        """Load all recording files from the mock directory in order."""
        if not self.mock_dir:
            return
        files = sorted(self.mock_dir.glob("[0-9][0-9][0-9]_*.json"))
        self._mock_entries = []
        for f in files:
            data = json.loads(f.read_text(encoding="utf-8"))
            self._mock_entries.append(data)
        print(f"[LLMRecorder] Loaded {len(self._mock_entries)} mock entries")

    def get_mock_response(self, step: str = "", phase: str = "") -> dict[str, Any] | None:
        """Return the next mock response, or None if exhausted.

        Tries to match by the most specific available scope first:

        - exact ``(phase, step)`` when both are provided
        - exact ``step`` when only step is provided
        - exact ``phase`` when only phase is provided

        Positional fallback is used only for completely unscoped calls.
        """
        if not self.should_mock or self._mock_entries is None:
            return None

        if self._counter >= len(self._mock_entries):
            print(
                f"[LLMRecorder] Mock exhausted! {self._counter} calls, "
                f"{len(self._mock_entries)} recordings. Falling through to real LLM."
            )
            return None

        # Try scoped matching first. When both phase and step are present,
        # require BOTH to match. Using OR here allows any later call in the
        # same phase to consume the wrong recording, desynchronizing replay.
        if step and phase:
            for i in range(self._counter, len(self._mock_entries)):
                entry = self._mock_entries[i]
                entry_step = entry.get("step", "")
                entry_phase = entry.get("phase", "")
                if entry_step == step and entry_phase == phase:
                    if i > self._counter:
                        skipped = i - self._counter
                        print(
                            f"[LLMRecorder] Skipped {skipped} entries to match "
                            f"{entry_phase}/{entry_step}"
                        )
                    self._counter = i + 1
                    print(
                        f"[LLMRecorder] Mock #{entry.get('index', self._counter)}: "
                        f"{entry.get('phase', '?')}/{entry.get('step', '?')} (matched exact)"
                    )
                    return entry
        elif step or phase:
            scope_key = "step" if step else "phase"
            scope_value = step or phase
            for i in range(self._counter, len(self._mock_entries)):
                entry = self._mock_entries[i]
                if entry.get(scope_key, "") == scope_value:
                    if i > self._counter:
                        skipped = i - self._counter
                        print(
                            f"[LLMRecorder] Skipped {skipped} entries to match "
                            f"{entry.get('phase', '?')}/{entry.get('step', '?')}"
                        )
                    self._counter = i + 1
                    print(
                        f"[LLMRecorder] Mock #{entry.get('index', self._counter)}: "
                        f"{entry.get('phase', '?')}/{entry.get('step', '?')} (matched {scope_key})"
                    )
                    return entry

        # Fallback: positional only for unscoped calls.
        entry = self._mock_entries[self._counter]
        self._counter += 1
        print(
            f"[LLMRecorder] Mock #{entry.get('index', self._counter)}: "
            f"{entry.get('phase', '?')}/{entry.get('step', '?')}"
        )
        return entry

    def get_mock_ai_message(self, step: str = "", phase: str = "") -> AIMessage | None:
        """Return the next mock response as an AIMessage."""
        entry = self.get_mock_response(step, phase)
        if entry is None:
            return None
        output = entry.get("output", {})
        tool_calls = output.get("tool_calls")
        additional = output.get("additional_kwargs", {})
        msg = AIMessage(content=output.get("content", ""), **additional)
        if tool_calls:
            msg.tool_calls = tool_calls
        return msg
