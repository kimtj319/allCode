"""Tool policy decisions derived from routing results."""

from __future__ import annotations

from typing import Literal

from allCode.agent.router import RoutingDecision
from allCode.core.models import CoreModel, ToolCall
from allCode.tools.base import ToolDefinition

ToolCategory = Literal["read", "mutation", "shell", "validation", "web", "unknown"]


class ToolPolicyDecision(CoreModel):
    allowed: bool
    reason: str
    category: ToolCategory
    approval_required: bool = False


class ToolPolicy:
    READ_TOOLS = {"list_directory", "read_file", "search_files", "glob_files", "list_tree", "source_overview", "source_probe"}
    MUTATION_TOOLS = {"write_file", "patch_file", "delete_path"}
    SHELL_TOOLS = {"run_command"}
    VALIDATION_TOOLS = {"run_tests"}
    WEB_TOOLS = {"web_search", "web_fetch"}

    def check(
        self,
        *,
        routing: RoutingDecision | None,
        tool_call: ToolCall,
        definition: ToolDefinition | None = None,
        destructive: bool = False,
    ) -> ToolPolicyDecision:
        name = tool_call.name
        category = self.category_for_tool(name)
        if category == "unknown" and definition is not None:
            category = "read" if definition.read_only else "mutation"
        if routing is None:
            return ToolPolicyDecision(
                allowed=True,
                reason="No routing decision supplied; only approval policy applies.",
                category=category,
                approval_required=bool(destructive or (definition and definition.requires_approval)),
            )

        if routing.read_only_requested and category in {"mutation", "shell", "validation"}:
            return ToolPolicyDecision(
                allowed=False,
                reason="Read-only request blocks mutation, shell, and validation tools.",
                category=category,
            )
        if "no_shell" in routing.flags and category in {"shell", "validation"}:
            return ToolPolicyDecision(allowed=False, reason="No-shell request blocks shell execution.", category=category)
        if "no_external_network" in routing.flags and category == "web":
            return ToolPolicyDecision(allowed=False, reason="No-network request blocks web tools.", category=category)

        allowed_by_route = self._allowed_by_route_and_capability(routing, category, name)
        if not allowed_by_route:
            return ToolPolicyDecision(
                allowed=False,
                reason=f"Tool category {category} is not allowed for route {routing.kind}.",
                category=category,
            )
        return ToolPolicyDecision(
            allowed=True,
            reason="Tool allowed by route policy.",
            category=category,
            approval_required=bool(destructive or (definition and definition.requires_approval)),
        )

    def allowed_tool_names(self, routing: RoutingDecision) -> set[str]:
        names = set()
        for tool_name in self.READ_TOOLS | self.MUTATION_TOOLS | self.SHELL_TOOLS | self.VALIDATION_TOOLS | self.WEB_TOOLS:
            decision = self.check(routing=routing, tool_call=ToolCall(id="policy", name=tool_name), definition=None)
            if decision.allowed:
                names.add(tool_name)
        return names

    def allowed_registered_tool_names(
        self,
        routing: RoutingDecision,
        definitions: list[ToolDefinition],
    ) -> set[str]:
        """Return route-allowed names from the concrete registered tool definitions."""

        names = set()
        for definition in definitions:
            decision = self.check(
                routing=routing,
                tool_call=ToolCall(id="policy", name=definition.name, arguments={}),
                definition=definition,
            )
            if decision.allowed:
                names.add(definition.name)
        return names

    def category_for_tool(self, tool_name: str) -> ToolCategory:
        name = tool_name.strip().lower().replace("-", "_")
        if name in self.READ_TOOLS:
            return "read"
        if name in self.MUTATION_TOOLS:
            return "mutation"
        if name in self.SHELL_TOOLS:
            return "shell"
        if name in self.VALIDATION_TOOLS:
            return "validation"
        if name in self.WEB_TOOLS:
            return "web"
        return "unknown"

    def _allowed_by_route_and_capability(self, routing: RoutingDecision, category: ToolCategory, tool_name: str) -> bool:
        capabilities = routing.tool_capabilities
        if routing.kind in {"answer", "inspect"} and category in {"mutation", "shell", "validation"}:
            return False
        if category == "read":
            if routing.kind in {"inspect", "modify", "operate"}:
                return True
            if tool_name in {"search_files", "glob_files", "list_tree", "source_overview", "source_probe"} and "search_workspace" in capabilities:
                return True
            if tool_name in {"read_file", "list_directory", "list_tree", "source_overview", "source_probe"} and (
                "read_file" in capabilities or "search_workspace" in capabilities
            ):
                return True
            if tool_name not in self.READ_TOOLS and routing.kind in {"inspect", "modify", "operate"}:
                return "read_file" in capabilities or "search_workspace" in capabilities
        if category == "mutation":
            if routing.kind != "modify" or routing.read_only_requested:
                return False
            if tool_name == "delete_path":
                return "delete_file" in capabilities or "mutate_file" in capabilities
            return "mutate_file" in capabilities
        if category == "shell":
            if routing.kind != "operate":
                return False
            return "run_shell" in capabilities
        if category == "validation":
            if routing.kind not in {"modify", "operate"}:
                return False
            return "run_validation" in capabilities or (routing.kind in {"modify", "operate"} and routing.requires_validation)
        if category == "web":
            return "web_search" in capabilities or routing.requires_external_knowledge
        return {
            "answer": category == "web" and routing.requires_external_knowledge,
            "inspect": category in {"read", "web"} and (category != "web" or routing.requires_external_knowledge),
            "modify": category in {"read", "mutation", "validation"},
            "operate": category in {"read", "shell", "validation"},
        }[routing.kind]
