"""Deterministic, model-independent task plan for the live activity area.

The model rarely calls ``update_plan`` on its own, so progress display cannot
depend on it. Instead the TUI synthesizes a plan from the *route kind* at turn
start and advances it as tool steps complete — entirely from observed events, so
it works no matter what the model does. The plan renders as a small checklist in
the live composer activity area (which redraws each frame, so no scrollback
noise).
"""

from __future__ import annotations

from dataclasses import dataclass

# Tool name -> the plan stage it advances. Tools not listed do not move the plan.
_TOOL_STAGE = {
    "read_file": "investigate",
    "source_probe": "investigate",
    "list_dir": "investigate",
    "grep": "investigate",
    "search": "investigate",
    "write_file": "modify",
    "patch_file": "modify",
    "apply_patch": "modify",
    "run_command": "execute",
    "run_tests": "validate",
}

# Ordered (label, stage) steps per route kind. Single-step routes (answer) get no
# plan — an empty plan renders nothing, preserving the prior behavior.
_ROUTE_STEPS: dict[str, list[tuple[str, str]]] = {
    "inspect": [("관련 코드 조사", "investigate"), ("결과 정리", "finalize")],
    "modify": [("관련 코드 조사", "investigate"), ("코드 수정", "modify"), ("검증", "validate")],
    "operate": [("준비 조사", "investigate"), ("명령 실행", "execute"), ("결과 확인", "validate")],
}


@dataclass
class TurnPlan:
    steps: list[tuple[str, str]]
    # Index of the step currently in progress; steps before it are completed.
    current: int = 0
    finalized: bool = False

    @classmethod
    def for_route(cls, kind: str) -> "TurnPlan | None":
        steps = _ROUTE_STEPS.get(kind)
        if not steps:
            return None
        return cls(steps=list(steps))

    def note_tool(self, name: str) -> bool:
        """Advance the plan when ``name`` belongs to a stage at or after the
        current step. Marks every step up to and including the matched one as
        completed. Returns True when the plan changed (so the caller repaints)."""
        if self.finalized:
            return False
        stage = _TOOL_STAGE.get(name)
        if stage is None:
            return False
        for index in range(self.current, len(self.steps)):
            if self.steps[index][1] == stage:
                self.current = index + 1  # steps 0..index now completed
                return True
        return False

    def finalize(self) -> None:
        self.current = len(self.steps)
        self.finalized = True

    def display_lines(self) -> list[str]:
        done = self.current
        lines: list[str] = []
        for index, (label, _stage) in enumerate(self.steps):
            if index < done:
                marker = "✔"
            elif index == done:
                marker = "▶"
            else:
                marker = "☐"
            lines.append(f"  {marker} {label}")
        completed = min(done, len(self.steps))
        header = f"계획 ({completed}/{len(self.steps)})"
        return [header, *lines]
