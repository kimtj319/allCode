"""DTOs for source-analysis evidence synthesis."""

from __future__ import annotations

from pydantic import Field

from allCode.core.models import CoreModel


class RepresentativeFile(CoreModel):
    path: str
    evidence: str = ""
    symbols: list[str] = Field(default_factory=list)
    ranges: list[str] = Field(default_factory=list)
    wiring: list[str] = Field(default_factory=list)
    wide_symbols: list[str] = Field(default_factory=list)


class PackageRole(CoreModel):
    path: str
    role: str
    evidence: str = ""


class SourceEdge(CoreModel):
    source: str
    target: str
    kind: str = "reference"


class SourceAnalysisBrief(CoreModel):
    requested_scope: str = ""
    observed_paths: list[str] = Field(default_factory=list)
    representative_files: list[RepresentativeFile] = Field(default_factory=list)
    package_roles: list[PackageRole] = Field(default_factory=list)
    entrypoints: list[str] = Field(default_factory=list)
    cross_module_edges: list[SourceEdge] = Field(default_factory=list)
    inferred_flows: list[str] = Field(default_factory=list)
    responsibility_graph: dict[str, object] = Field(default_factory=dict)
    unobserved_scopes: list[str] = Field(default_factory=list)
    confidence_notes: list[str] = Field(default_factory=list)
