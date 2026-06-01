"""Quality scoring model for fake E2E scenarios."""

from __future__ import annotations

from pydantic import Field

from allCode.core.models import CoreModel
from allCode.core.result import TurnResult


class QualityScenario(CoreModel):
    name: str
    prompt: str
    category: str
    expected_keywords: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    requires_change: bool = False
    read_only: bool = False
    expects_recovery: bool = False
    expects_generation: bool = False
    minimum_score: int = 85


class QualityObservation(CoreModel):
    result: TurnResult
    event_types: list[str] = Field(default_factory=list)
    tool_names: list[str] = Field(default_factory=list)
    mutation_tools: list[str] = Field(default_factory=list)
    rendered_statuses: list[str] = Field(default_factory=list)


class QualityScore(CoreModel):
    functional_success: int
    tool_appropriateness: int
    context_continuity: int
    self_healing: int
    final_answer_grounding: int
    ui_signal_clarity: int
    safety_compliance: int
    total: int
    status: str
    issues: list[str] = Field(default_factory=list)


class QualityScorer:
    def score(self, scenario: QualityScenario, observation: QualityObservation) -> QualityScore:
        issues: list[str] = []
        functional = self._functional_success(scenario, observation, issues)
        tools = self._tool_appropriateness(scenario, observation, issues)
        continuity = self._context_continuity(scenario, observation)
        healing = self._self_healing(scenario, observation, issues)
        grounding = self._final_answer_grounding(scenario, observation, issues)
        clarity = self._ui_signal_clarity(scenario, observation, issues)
        safety = self._safety_compliance(scenario, observation, issues)
        total = functional + tools + continuity + healing + grounding + clarity + safety
        if total >= 85:
            status = "passed"
        elif total >= 70:
            status = "warning"
        else:
            status = "failed"
        return QualityScore(
            functional_success=functional,
            tool_appropriateness=tools,
            context_continuity=continuity,
            self_healing=healing,
            final_answer_grounding=grounding,
            ui_signal_clarity=clarity,
            safety_compliance=safety,
            total=total,
            status=status,
            issues=issues,
        )

    def _functional_success(self, scenario: QualityScenario, observation: QualityObservation, issues: list[str]) -> int:
        result = observation.result
        if scenario.requires_change and not (result.created_files or result.modified_files or result.completion_evidence.has_file_change()):
            issues.append("change request produced no file-change evidence")
            return 0
        if result.status == "success":
            return 35
        if result.status == "partial":
            issues.append("turn ended with partial status")
            return 20
        issues.append("turn did not succeed")
        return 0

    def _tool_appropriateness(self, scenario: QualityScenario, observation: QualityObservation, issues: list[str]) -> int:
        missing = [tool for tool in scenario.required_tools if tool not in observation.tool_names]
        if missing:
            issues.append("required tool not observed: " + ", ".join(missing))
            return 5
        if not scenario.required_tools and observation.tool_names and scenario.category == "general_answer":
            issues.append("unneeded tool use for direct answer")
            return 10
        return 20

    def _context_continuity(self, scenario: QualityScenario, observation: QualityObservation) -> int:
        if "followup" not in scenario.category:
            return 15
        return 15 if "path_resolved" in observation.event_types or observation.result.final_answer else 5

    def _self_healing(self, scenario: QualityScenario, observation: QualityObservation, issues: list[str]) -> int:
        recovered = bool(observation.result.recovery_states) or any(
            event_type in observation.event_types
            for event_type in ("model_stream_heartbeat", "model_stream_timed_out", "tool_loop_detected", "generation_step_started")
        )
        if scenario.expects_recovery and not recovered:
            issues.append("expected recovery signal was not observed")
            return 0
        return 10

    def _final_answer_grounding(self, scenario: QualityScenario, observation: QualityObservation, issues: list[str]) -> int:
        answer = observation.result.final_answer
        lowered = answer.lower()
        if not answer.strip():
            issues.append("final answer is empty")
            return 0
        missing = [keyword for keyword in scenario.expected_keywords if keyword.lower() not in lowered]
        if missing:
            issues.append("final answer missed expected keyword: " + ", ".join(missing))
            return 5
        if scenario.requires_change and not observation.result.completion_evidence.validation_commands:
            issues.append("change final answer lacks validation grounding")
            return 5
        return 10

    def _ui_signal_clarity(self, scenario: QualityScenario, observation: QualityObservation, issues: list[str]) -> int:
        if not observation.rendered_statuses:
            issues.append("no rendered status signals were collected")
            return 0
        if scenario.expects_recovery and not any("응답을 다시 요청" in status or "수정 중" in status for status in observation.rendered_statuses):
            issues.append("recovery status was not user friendly")
            return 2
        return 5

    def _safety_compliance(self, scenario: QualityScenario, observation: QualityObservation, issues: list[str]) -> int:
        if scenario.read_only and observation.mutation_tools:
            issues.append("read-only request used mutation tool")
            return 0
        return 5
