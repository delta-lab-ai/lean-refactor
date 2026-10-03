"""
Task metadata and result definitions for proof golfing.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class GolfTaskMetadata:
    """Metadata for a single proof optimization task."""

    # From JSONL input
    name: str                       # theorem name (e.g., "IsElementary.measure_le_cover_sum")
    original_path: Path             # absolute path to original .lean file
    initial_proof_length: int       # current token count from JSONL
    src: str                        # full source code (statement + proof)
    signature: str                  # theorem signature
    contexts: list                  # context dicts from JSONL

    # Derived paths
    temp_file_path: Path            # path to temp .lean file (same dir as original)
    best_proof_file: Path           # path to .txt storing current shortest proof
    current_proof_file: Path        # path to .txt where agent writes current proof attempt
    progress_file: Path             # path to JSONL progress file for this task
    project_root: Path              # Lean project root (cwd for claude)

    # Configuration
    max_turns: int = 40
    timeout_minutes: Optional[float] = 60  # per-task wall-clock limit; None = no limit
    model: Optional[str] = None          # e.g. "opus", "sonnet", "haiku"
    effort: Optional[str] = None         # e.g. "low", "medium", "high", "max"
    max_budget_usd: Optional[float] = None
    # Multi-objective mode: written to <task_dir>/objective.json for check_proof.py
    # (length_weight, heartbeat_weight, initial_length, initial_heartbeat, project_root, heartbeat_timeout)
    objective: Optional[dict] = None
    task_id: str = field(default="")

    def __post_init__(self):
        self.original_path = Path(self.original_path).resolve()
        self.temp_file_path = Path(self.temp_file_path).resolve()
        self.best_proof_file = Path(self.best_proof_file).resolve()
        self.current_proof_file = Path(self.current_proof_file).resolve()
        self.progress_file = Path(self.progress_file).resolve()
        self.project_root = Path(self.project_root).resolve()

        if not self.task_id:
            sanitized = self.name.replace(".", "_")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.task_id = f"golf_{sanitized}_{timestamp}"

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "original_path": str(self.original_path),
            "temp_file_path": str(self.temp_file_path),
            "current_proof_file": str(self.current_proof_file),
            "initial_proof_length": self.initial_proof_length,
            "max_turns": self.max_turns,
            "max_budget_usd": self.max_budget_usd,
            "project_root": str(self.project_root),
        }


@dataclass
class GolfTaskResult:
    """Result of a proof optimization task."""

    task_id: str
    name: str
    success: bool                   # whether any improvement was found
    initial_length: int
    final_length: int
    attempts: int                   # number of check_proof calls
    start_time: datetime
    end_time: datetime
    error_message: Optional[str] = None
    terminal_reason: Optional[str] = None   # e.g. "completed", "max_turns", "budget_exceeded"
    model: Optional[str] = None             # resolved model slug/id
    cost_usd: float = 0.0                   # reported by Claude Code
    # Token usage (from claude --output-format stream-json result line)
    # output_tokens includes thinking tokens when --effort is set
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    # Multi-objective mode only (None otherwise)
    initial_heartbeat: Optional[int] = None
    final_heartbeat: Optional[int] = None
    final_score: Optional[float] = None

    @property
    def duration_seconds(self) -> float:
        return (self.end_time - self.start_time).total_seconds()

    @property
    def total_input_tokens(self) -> int:
        """Total effective input tokens: fresh + cache_read + cache_creation."""
        return self.input_tokens + self.cache_read_tokens + self.cache_creation_tokens

    @property
    def tokens_saved(self) -> int:
        return self.initial_length - self.final_length

    @property
    def reduction_pct(self) -> float:
        if self.initial_length <= 0:
            return 0.0
        return round(100.0 * self.tokens_saved / self.initial_length, 2)

    @property
    def heartbeat_reduction_pct(self) -> Optional[float]:
        if not self.initial_heartbeat or self.final_heartbeat is None:
            return None
        return round(100.0 * (self.initial_heartbeat - self.final_heartbeat) / self.initial_heartbeat, 2)

    def to_dict(self) -> dict:
        data = {
            "task_id": self.task_id,
            "name": self.name,
            "success": self.success,
            "initial_length": self.initial_length,
            "final_length": self.final_length,
            "tokens_saved": self.tokens_saved,
            "reduction_pct": self.reduction_pct,
            "attempts": self.attempts,
            "duration_seconds": self.duration_seconds,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "error_message": self.error_message,
            "terminal_reason": self.terminal_reason,
            "model": self.model,
            "cost_usd": self.cost_usd,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "total_input_tokens": self.total_input_tokens,
        }
        if self.final_score is not None:
            data.update({
                "initial_heartbeat": self.initial_heartbeat,
                "final_heartbeat": self.final_heartbeat,
                "heartbeat_reduction_pct": self.heartbeat_reduction_pct,
                "final_score": self.final_score,
            })
        return data
