"""Clone progress handler for translating GitPython progress to callbacks.

Uses GitPython's RemoteProgress to translate op_code stages into
human-readable phase names and invoke a callback during clone operations.
"""

from typing import Callable, Union

import git

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)

# Map GitPython OP_MASK operation codes to human-readable stage names
_OP_CODE_STAGE_MAP = {
    git.RemoteProgress.COUNTING: "counting_objects",
    git.RemoteProgress.COMPRESSING: "compressing_objects",
    git.RemoteProgress.RECEIVING: "receiving_objects",
    git.RemoteProgress.RESOLVING: "resolving_deltas",
    git.RemoteProgress.CHECKING_OUT: "checking_out",
    git.RemoteProgress.WRITING: "writing_objects",
    git.RemoteProgress.FINDING_SOURCES: "finding_sources",
}


class CloneProgressHandler(git.RemoteProgress):
    """Translates GitPython clone progress into human-readable callback invocations.

    Subclasses ``git.RemoteProgress`` and overrides ``update()`` to map
    ``OP_MASK`` stages to friendly names, then forwards them to a callback.
    All callback invocations are wrapped in try/except so that a misbehaving
    callback can never break the clone operation.
    """

    def __init__(
        self,
        callback: Callable[[str, int, int, str], None],
    ) -> None:
        super().__init__()
        self._callback = callback

    def update(
        self,
        op_code: int,
        cur_count: Union[str, float],
        max_count: Union[str, float, None] = None,
        message: str = "",
    ) -> None:
        """Called by GitPython for each progress update during clone.

        Translates the numeric *op_code* to a human-readable stage name and
        invokes the stored callback with ``(phase, cur_count, max_count, message)``.
        """
        try:
            # Extract the operation type using OP_MASK (strip stage bits)
            op_type = op_code & git.RemoteProgress.OP_MASK
            phase = _OP_CODE_STAGE_MAP.get(op_type, "cloning")

            cur = int(cur_count) if cur_count is not None else 0
            mx = int(max_count) if max_count is not None else 0

            logger.debug(
                "Git clone progress | phase=%s progress=%d/%d message=%s",
                phase,
                cur,
                mx,
                message or "",
            )

            self._callback(phase, cur, mx, message or "")
        except Exception:
            # Never let a callback error break the clone operation
            logger.debug(
                "CloneProgressHandler callback error (suppressed)", exc_info=True
            )
