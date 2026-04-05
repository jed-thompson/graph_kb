"""Unit tests for CloneProgressHandler and clone_repo progress_callback wiring.

Validates Requirements 7.1, 7.2, 7.3.
"""

from unittest.mock import MagicMock, patch

import git
import pytest

from graph_kb_api.graph_kb.repositories.clone_progress import (
    _OP_CODE_STAGE_MAP,
    CloneProgressHandler,
)

# ---------------------------------------------------------------------------
# Requirement 7.2 – op_code → stage name translation
# ---------------------------------------------------------------------------


class TestOpCodeTranslation:
    """Known op_codes are translated to the correct human-readable stage names."""

    @pytest.mark.parametrize(
        "op_code_const, expected_stage",
        [
            (git.RemoteProgress.COUNTING, "counting_objects"),
            (git.RemoteProgress.COMPRESSING, "compressing_objects"),
            (git.RemoteProgress.RECEIVING, "receiving_objects"),
            (git.RemoteProgress.RESOLVING, "resolving_deltas"),
            (git.RemoteProgress.CHECKING_OUT, "checking_out"),
            (git.RemoteProgress.WRITING, "writing_objects"),
            (git.RemoteProgress.FINDING_SOURCES, "finding_sources"),
        ],
    )
    def test_known_op_code_maps_to_stage(self, op_code_const, expected_stage):
        cb = MagicMock()
        handler = CloneProgressHandler(cb)

        handler.update(op_code_const, cur_count=10, max_count=100, message="progress")

        cb.assert_called_once_with(expected_stage, 10, 100, "progress")

    def test_unknown_op_code_falls_back_to_cloning(self):
        cb = MagicMock()
        handler = CloneProgressHandler(cb)

        # Use a value that doesn't match any known OP_MASK entry
        unknown_op = 0xFF00
        handler.update(unknown_op, cur_count=5, max_count=50, message="")

        cb.assert_called_once_with("cloning", 5, 50, "")

    def test_op_code_with_stage_bits_still_resolves(self):
        """op_code may have BEGIN/END stage bits OR'd in; OP_MASK strips them."""
        cb = MagicMock()
        handler = CloneProgressHandler(cb)

        # RECEIVING | BEGIN (stage bit)
        op_code = git.RemoteProgress.RECEIVING | git.RemoteProgress.BEGIN
        handler.update(op_code, cur_count=1, max_count=200, message="recv")

        cb.assert_called_once_with("receiving_objects", 1, 200, "recv")

    def test_all_stage_map_entries_covered(self):
        """Sanity check: every entry in _OP_CODE_STAGE_MAP is tested above."""
        expected_keys = {
            git.RemoteProgress.COUNTING,
            git.RemoteProgress.COMPRESSING,
            git.RemoteProgress.RECEIVING,
            git.RemoteProgress.RESOLVING,
            git.RemoteProgress.CHECKING_OUT,
            git.RemoteProgress.WRITING,
            git.RemoteProgress.FINDING_SOURCES,
        }
        assert set(_OP_CODE_STAGE_MAP.keys()) == expected_keys


# ---------------------------------------------------------------------------
# Requirement 7.2 – callback exceptions are caught
# ---------------------------------------------------------------------------


class TestCallbackExceptionHandling:
    """Callback exceptions must be caught so they never break the clone."""

    def test_callback_raising_does_not_propagate(self):
        def bad_callback(phase, cur, mx, msg):
            raise RuntimeError("boom")

        handler = CloneProgressHandler(bad_callback)

        # Should NOT raise
        handler.update(git.RemoteProgress.COUNTING, 1, 10, "test")

    def test_callback_raising_type_error_does_not_propagate(self):
        def bad_callback(phase, cur, mx, msg):
            raise TypeError("bad type")

        handler = CloneProgressHandler(bad_callback)
        handler.update(git.RemoteProgress.COMPRESSING, 5, 50, "")

    def test_callback_raising_value_error_does_not_propagate(self):
        def bad_callback(phase, cur, mx, msg):
            raise ValueError("bad value")

        handler = CloneProgressHandler(bad_callback)
        handler.update(git.RemoteProgress.RESOLVING, 0, 0, "msg")


# ---------------------------------------------------------------------------
# Requirement 7.1, 7.3 – progress_callback=None doesn't change clone behavior
# ---------------------------------------------------------------------------


class TestCloneRepoProgressCallbackNone:
    """When progress_callback is None, Repo.clone_from must NOT receive a progress kwarg."""

    @patch("graph_kb_api.graph_kb.repositories.repo_fetcher.Repo.clone_from")
    def test_no_progress_kwarg_when_callback_is_none(self, mock_clone_from):
        """clone_repo(progress_callback=None) must not pass `progress` to Repo.clone_from."""
        from graph_kb_api.graph_kb.repositories.repo_fetcher import GitRepoFetcher

        # Set up mock to return a repo-like object
        mock_repo = MagicMock()
        mock_repo.head.commit.hexsha = "abc1234567890"
        mock_clone_from.return_value = mock_repo

        fetcher = GitRepoFetcher.__new__(GitRepoFetcher)
        fetcher.config = MagicMock()
        fetcher.config.max_repo_size_mb = 500
        fetcher.storage_path = MagicMock()

        # Stub out helper methods
        fetcher.validate_url = MagicMock()
        fetcher.create_repo_id = MagicMock(return_value="test-repo-id")
        fetcher._get_authenticated_url = MagicMock(
            return_value="https://github.com/test/repo.git"
        )
        fetcher._normalize_url = MagicMock(return_value="https://github.com/test/repo")

        mock_path = MagicMock()
        mock_path.exists.return_value = False
        fetcher.get_repo_path = MagicMock(return_value=mock_path)
        fetcher._get_repo_size_mb = MagicMock(return_value=1.0)

        fetcher.clone_repo(
            repo_url="https://github.com/test/repo.git",
            branch="main",
            progress_callback=None,
        )

        # Verify clone_from was called
        mock_clone_from.assert_called_once()
        _, kwargs = mock_clone_from.call_args
        # The 'progress' key must NOT be present
        assert "progress" not in kwargs, (
            "Repo.clone_from should not receive a 'progress' kwarg when progress_callback is None"
        )

    @patch("graph_kb_api.graph_kb.repositories.repo_fetcher.Repo.clone_from")
    def test_progress_kwarg_present_when_callback_provided(self, mock_clone_from):
        """clone_repo(progress_callback=<fn>) must pass `progress` to Repo.clone_from."""
        from graph_kb_api.graph_kb.repositories.repo_fetcher import GitRepoFetcher

        mock_repo = MagicMock()
        mock_repo.head.commit.hexsha = "abc1234567890"
        mock_clone_from.return_value = mock_repo

        fetcher = GitRepoFetcher.__new__(GitRepoFetcher)
        fetcher.config = MagicMock()
        fetcher.config.max_repo_size_mb = 500
        fetcher.storage_path = MagicMock()

        fetcher.validate_url = MagicMock()
        fetcher.create_repo_id = MagicMock(return_value="test-repo-id")
        fetcher._get_authenticated_url = MagicMock(
            return_value="https://github.com/test/repo.git"
        )
        fetcher._normalize_url = MagicMock(return_value="https://github.com/test/repo")

        mock_path = MagicMock()
        mock_path.exists.return_value = False
        fetcher.get_repo_path = MagicMock(return_value=mock_path)
        fetcher._get_repo_size_mb = MagicMock(return_value=1.0)

        my_callback = MagicMock()
        fetcher.clone_repo(
            repo_url="https://github.com/test/repo.git",
            branch="main",
            progress_callback=my_callback,
        )

        mock_clone_from.assert_called_once()
        _, kwargs = mock_clone_from.call_args
        assert "progress" in kwargs, (
            "Repo.clone_from should receive a 'progress' kwarg when progress_callback is provided"
        )
        assert isinstance(kwargs["progress"], CloneProgressHandler)
