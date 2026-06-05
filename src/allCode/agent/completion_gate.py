"""Completion evidence helpers for agent turn results."""

from __future__ import annotations

from allCode.agent.intent import IntentExtractor
from allCode.agent.phase_gate import ensure_requested_artifacts, satisfy_requested_artifacts
from allCode.agent.router import RoutingDecision
from allCode.core.models import TurnInput, TurnState
from allCode.core.result import CompletionEvidence, ToolLoopSignature

_INTENT_EXTRACTOR = IntentExtractor()


def build_completion_evidence(
    *,
    turn_input: TurnInput,
    state: TurnState,
    outcome_status: str,
    outcome_answer: str,
    base_evidence: CompletionEvidence | None = None,
    routing: RoutingDecision | None = None,
) -> CompletionEvidence:
    requires_change = requires_change_evidence(turn_input.user_prompt, routing=routing)
    changed_files = _merge_unique(
        list(state.modified_files),
        list(base_evidence.changed_files if base_evidence is not None else []),
    )
    created_files = _merge_unique(
        list(state.created_files),
        list(base_evidence.created_files if base_evidence is not None else []),
    )
    deleted_files = _merge_unique(
        list(state.deleted_files),
        list(base_evidence.deleted_files if base_evidence is not None else []),
    )
    noop_targets = list(base_evidence.noop_targets if base_evidence is not None else [])
    safe_noop = bool(base_evidence.safe_noop if base_evidence is not None else False)
    noop_reason = base_evidence.noop_reason if base_evidence is not None else None
    search_candidate_paths = list(base_evidence.search_candidate_paths if base_evidence is not None else [])
    inspected_paths = list(base_evidence.inspected_paths if base_evidence is not None else [])
    source_overview_paths = list(base_evidence.source_overview_paths if base_evidence is not None else [])
    source_overview_summaries = list(base_evidence.source_overview_summaries if base_evidence is not None else [])
    source_overview_truncated = bool(base_evidence.source_overview_truncated if base_evidence is not None else False)
    source_package_roles = list(base_evidence.source_package_roles if base_evidence is not None else [])
    source_representative_candidates = list(
        base_evidence.source_representative_candidates if base_evidence is not None else []
    )
    source_representative_reasons = list(
        base_evidence.source_representative_reasons if base_evidence is not None else []
    )
    source_representative_scores = dict(
        base_evidence.source_representative_scores if base_evidence is not None else {}
    )
    representative_read_paths = list(base_evidence.representative_read_paths if base_evidence is not None else [])
    source_analysis_coverage = dict(base_evidence.source_analysis_coverage if base_evidence is not None else {})
    inspect_observation_count = int(base_evidence.inspect_observation_count if base_evidence is not None else 0)
    zero_result_queries = list(base_evidence.zero_result_queries if base_evidence is not None else [])
    not_found_targets = list(base_evidence.not_found_targets if base_evidence is not None else [])
    validation_failure_symbols = list(base_evidence.validation_failure_symbols if base_evidence is not None else [])
    policy_denied_tools = list(base_evidence.policy_denied_tools if base_evidence is not None else [])
    web_unavailable_queries = list(base_evidence.web_unavailable_queries if base_evidence is not None else [])
    grounding_required = bool(base_evidence.grounding_required if base_evidence is not None else False)
    project_manifest = base_evidence.project_manifest if base_evidence is not None else None
    document_manifest = base_evidence.document_manifest if base_evidence is not None else None
    requested_artifacts = list(base_evidence.requested_artifacts if base_evidence is not None else [])
    feature_objectives = list(base_evidence.feature_objectives if base_evidence is not None else [])
    file_change_present = bool(changed_files or created_files or deleted_files or safe_noop)
    final_answer_ready = outcome_status == "success" and bool(outcome_answer.strip())
    if requires_change and not file_change_present:
        final_answer_ready = False
    if final_answer_ready and file_change_present:
        status = "changed"
    elif final_answer_ready:
        status = "reported"
    elif outcome_status in {"failed", "partial"}:
        status = "blocked"
    else:
        status = "not_started"
    evidence = CompletionEvidence(
        status=status,
        changed_files=changed_files,
        created_files=created_files,
        deleted_files=deleted_files,
        noop_targets=noop_targets,
        noop_reason=noop_reason,
        safe_noop=safe_noop,
        validation_commands=list(base_evidence.validation_commands if base_evidence is not None else []),
        validation_passed=base_evidence.validation_passed if base_evidence is not None else None,
        final_answer_ready=final_answer_ready,
        grounding_required=grounding_required,
        search_candidate_paths=search_candidate_paths,
        inspected_paths=inspected_paths,
        source_overview_paths=source_overview_paths,
        source_overview_summaries=source_overview_summaries,
        source_overview_truncated=source_overview_truncated,
        source_package_roles=source_package_roles,
        source_representative_candidates=source_representative_candidates,
        source_representative_reasons=source_representative_reasons,
        source_representative_scores=source_representative_scores,
        representative_read_paths=representative_read_paths,
        source_analysis_coverage=source_analysis_coverage,
        inspect_observation_count=inspect_observation_count,
        zero_result_queries=zero_result_queries,
        not_found_targets=not_found_targets,
        validation_failure_symbols=validation_failure_symbols,
        policy_denied_tools=policy_denied_tools,
        web_unavailable_queries=web_unavailable_queries,
        project_manifest=project_manifest,
        document_manifest=document_manifest,
        requested_artifacts=requested_artifacts,
        feature_objectives=feature_objectives,
    )
    ensure_requested_artifacts(
        turn_input.user_prompt,
        evidence,
        workspace_root=turn_input.workspace.root,
        routing=routing,
    )
    satisfy_requested_artifacts(evidence, workspace_root=turn_input.workspace.root)
    if evidence.has_unsatisfied_artifacts("source", "test", "document", "validation"):
        evidence.final_answer_ready = False
        if evidence.status in {"changed", "validated", "reported"}:
            evidence.status = "blocked"
    return evidence


def requires_change_evidence(prompt: str, *, routing: RoutingDecision | None = None) -> bool:
    if routing is not None:
        if routing.kind in {"answer", "inspect"} or routing.read_only_requested:
            return False
        return routing.kind == "modify" and routing.requires_mutation and not routing.read_only_requested
    signals = _INTENT_EXTRACTOR.extract(prompt)
    if signals.read_only_requested:
        return False
    return signals.modify_action


def tool_loop_signatures(loop_guard) -> list[ToolLoopSignature]:
    counts = getattr(loop_guard, "_counts", {})
    signatures_by_key = getattr(loop_guard, "signatures_by_key", {})
    signatures = []
    for key, count in counts.items():
        if count >= 3:
            signatures.append(
                signatures_by_key.get(
                    key,
                    ToolLoopSignature(tool_name="unknown", arguments_hash=key, count=count),
                )
            )
    return signatures


def _merge_unique(left: list[str], right: list[str]) -> list[str]:
    merged = list(left)
    for item in right:
        if item not in merged:
            merged.append(item)
    return merged
