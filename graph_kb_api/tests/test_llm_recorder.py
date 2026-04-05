from graph_kb_api.config.settings import settings
from graph_kb_api.core.llm_recorder import LLMRecorder


def _entry(index: int, phase: str, step: str, content: str) -> dict:
    return {
        "index": index,
        "phase": phase,
        "step": step,
        "input_messages": [],
        "output": {
            "type": "AIMessage",
            "content": content,
        },
        "timestamp": "2026-04-01T00:00:00+00:00",
    }


def _mock_recorder(entries: list[dict]) -> LLMRecorder:
    recorder = LLMRecorder("mock", None, None)
    recorder._mock_entries = entries
    return recorder


def test_get_mock_response_requires_exact_phase_and_step_match():
    recorder = _mock_recorder(
        [
            _entry(1, "orchestrate", "gap", "gap-1"),
            _entry(2, "orchestrate", "worker", "worker-1"),
            _entry(3, "orchestrate", "gap", "gap-2"),
        ]
    )

    entry = recorder.get_mock_response(step="worker", phase="orchestrate")

    assert entry is not None
    assert entry["index"] == 2
    assert recorder._counter == 2


def test_from_settings_does_not_implicitly_rewind_mock_counter(monkeypatch):
    LLMRecorder.reset()
    monkeypatch.setattr(settings, "llm_recording_mode", "mock")
    monkeypatch.setattr(settings, "llm_recording_dir", None)
    monkeypatch.setattr(settings, "llm_mock_dir", None)

    recorder = LLMRecorder.from_settings()
    recorder._mock_entries = [
        _entry(1, "orchestrate", "gap", "gap-1"),
        _entry(2, "orchestrate", "worker", "worker-1"),
    ]
    recorder._counter = 1

    same_recorder = LLMRecorder.from_settings()

    assert same_recorder is recorder
    assert same_recorder._counter == 1

    LLMRecorder.reset()


def test_rewind_mock_run_explicitly_resets_counter():
    recorder = _mock_recorder([_entry(1, "planning", "decompose", "decompose-1")])
    recorder._counter = 1

    recorder.rewind_mock_run()

    assert recorder._counter == 0
