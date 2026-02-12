"""
Data structures for custom pattern configuration.
Defines the schema for .emerge/patterns.yaml files.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Union
from enum import Enum, auto
import re


class MatchType(Enum):
    """Type of pattern matching."""
    REGEX = auto()
    AST = auto()      # Future: tree-sitter
    SEMANTIC = auto()  # Future: semantic analysis


class EdgeMatchType(Enum):
    """How to match nodes for edge creation."""
    PROPERTY_EQUALS = auto()
    PROPERTY_CONTAINS = auto()
    PROPERTY_REGEX = auto()
    EXPRESSION = auto()


@dataclass
class CaptureDefinition:
    """Defines how to capture and transform a regex group."""
    name: str
    group: int
    transform: Optional[Union[str, List[str]]] = None
    default: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CaptureDefinition":
        return cls(
            name=data["name"],
            group=data["group"],
            transform=data.get("transform"),
            default=data.get("default"),
        )


@dataclass
class NodeCreation:
    """Defines a node to create from a pattern match."""
    type: str
    id_template: str  # e.g., "hook:$hook_name"
    label_template: Optional[str] = None
    singleton: bool = False
    properties: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NodeCreation":
        return cls(
            type=data["type"],
            id_template=data["id"],
            label_template=data.get("label"),
            singleton=data.get("singleton", False),
            properties=data.get("properties", {}),
        )


@dataclass
class EdgeCreation:
    """Defines an edge to create from a pattern match."""
    from_template: str  # Node ID or $current_file
    to_template: str
    type: str
    directed: bool = True
    properties: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EdgeCreation":
        return cls(
            from_template=data["from"],
            to_template=data["to"],
            type=data["type"],
            directed=data.get("directed", True),
            properties=data.get("properties", {}),
        )


@dataclass
class PatternCreates:
    """What a pattern match creates in the graph."""
    nodes: List[NodeCreation] = field(default_factory=list)
    edges: List[EdgeCreation] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PatternCreates":
        nodes = []
        edges = []

        # Handle single node
        if "node" in data:
            nodes.append(NodeCreation.from_dict(data["node"]))

        # Handle multiple nodes
        if "nodes" in data:
            for node_data in data["nodes"]:
                nodes.append(NodeCreation.from_dict(node_data))

        # Handle single edge
        if "edge" in data:
            edges.append(EdgeCreation.from_dict(data["edge"]))

        # Handle multiple edges
        if "edges" in data:
            for edge_data in data["edges"]:
                edges.append(EdgeCreation.from_dict(edge_data))

        return cls(nodes=nodes, edges=edges)


@dataclass
class PatternMatch:
    """How to match content in source files."""
    type: MatchType
    pattern: str
    flags: List[str] = field(default_factory=list)
    compiled: Optional[re.Pattern] = None

    def compile(self) -> None:
        """Compile the regex pattern."""
        if self.type == MatchType.REGEX:
            re_flags = 0
            for flag in self.flags:
                if flag.lower() == "multiline":
                    re_flags |= re.MULTILINE
                elif flag.lower() == "ignorecase":
                    re_flags |= re.IGNORECASE
                elif flag.lower() == "dotall":
                    re_flags |= re.DOTALL
                elif flag.lower() == "extended":
                    re_flags |= re.VERBOSE
            self.compiled = re.compile(self.pattern, re_flags)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PatternMatch":
        match_type = MatchType.REGEX
        if data.get("type") == "ast":
            match_type = MatchType.AST
        elif data.get("type") == "semantic":
            match_type = MatchType.SEMANTIC

        match = cls(
            type=match_type,
            pattern=data["pattern"],
            flags=data.get("flags", []),
        )
        match.compile()
        return match


@dataclass
class PatternDefinition:
    """A complete pattern definition."""
    id: str
    name: str
    description: Optional[str] = None
    language: Optional[str] = None  # "php", "any", etc.
    file_pattern: Optional[str] = None  # Glob pattern like "**/*.php"
    exclude: List[str] = field(default_factory=list)
    match: Optional[PatternMatch] = None
    captures: List[CaptureDefinition] = field(default_factory=list)
    creates: Optional[PatternCreates] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PatternDefinition":
        captures = []
        if "captures" in data:
            for cap_data in data["captures"]:
                captures.append(CaptureDefinition.from_dict(cap_data))

        match = None
        if "match" in data:
            match = PatternMatch.from_dict(data["match"])

        creates = None
        if "creates" in data:
            creates = PatternCreates.from_dict(data["creates"])

        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description"),
            language=data.get("language"),
            file_pattern=data.get("file_pattern"),
            exclude=data.get("exclude", []),
            match=match,
            captures=captures,
            creates=creates,
        )


@dataclass
class NodeTypeDefinition:
    """Definition of a custom node type."""
    name: str
    description: Optional[str] = None
    properties: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "NodeTypeDefinition":
        props = []
        if "properties" in data:
            for prop in data["properties"]:
                if isinstance(prop, dict):
                    props.append(prop.get("name", str(prop)))
                else:
                    props.append(str(prop))
        return cls(
            name=name,
            description=data.get("description"),
            properties=props,
        )


@dataclass
class EdgeRuleMatch:
    """How to match nodes for edge rules."""
    type: EdgeMatchType
    properties: List[str] = field(default_factory=list)
    from_property: Optional[str] = None
    to_property: Optional[str] = None
    expression: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EdgeRuleMatch":
        match_type = EdgeMatchType.PROPERTY_EQUALS
        type_str = data.get("type", "property_equals")
        if type_str == "property_contains":
            match_type = EdgeMatchType.PROPERTY_CONTAINS
        elif type_str == "property_regex":
            match_type = EdgeMatchType.PROPERTY_REGEX
        elif type_str == "expression":
            match_type = EdgeMatchType.EXPRESSION

        return cls(
            type=match_type,
            properties=data.get("properties", []),
            from_property=data.get("from_property"),
            to_property=data.get("to_property"),
            expression=data.get("expr"),
        )


@dataclass
class EdgeRuleEndpoint:
    """From/to endpoint for an edge rule."""
    pattern_id: Optional[str] = None
    node_type: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EdgeRuleEndpoint":
        return cls(
            pattern_id=data.get("pattern"),
            node_type=data.get("node_type"),
        )


@dataclass
class EdgeRule:
    """Rule for connecting patterns found separately."""
    id: str
    name: str
    from_endpoint: EdgeRuleEndpoint
    to_endpoint: EdgeRuleEndpoint
    match: EdgeRuleMatch
    edge_type: str
    directed: bool = True
    properties: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EdgeRule":
        edge_data = data.get("edge", {})
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            from_endpoint=EdgeRuleEndpoint.from_dict(data["from"]),
            to_endpoint=EdgeRuleEndpoint.from_dict(data["to"]),
            match=EdgeRuleMatch.from_dict(data["match"]),
            edge_type=edge_data.get("type", "relates_to"),
            directed=edge_data.get("directed", True),
            properties=edge_data.get("properties", {}),
        )


@dataclass
class PatternMeta:
    """Metadata for the patterns file."""
    name: str
    description: Optional[str] = None
    frameworks: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PatternMeta":
        return cls(
            name=data.get("name", "Custom Patterns"),
            description=data.get("description"),
            frameworks=data.get("frameworks", []),
        )


@dataclass
class PatternSettings:
    """Settings for pattern processing."""
    on_pattern_error: str = "warn"  # warn, error, ignore
    on_capture_missing: str = "skip"  # skip, default, error
    strict_mode: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PatternSettings":
        return cls(
            on_pattern_error=data.get("on_pattern_error", "warn"),
            on_capture_missing=data.get("on_capture_missing", "skip"),
            strict_mode=data.get("strict_mode", False),
        )


@dataclass
class PatternConfig:
    """Complete custom patterns configuration."""
    version: str = "1.0"
    meta: Optional[PatternMeta] = None
    settings: Optional[PatternSettings] = None
    node_types: Dict[str, NodeTypeDefinition] = field(default_factory=dict)
    patterns: List[PatternDefinition] = field(default_factory=list)
    edge_rules: List[EdgeRule] = field(default_factory=list)

    # Source tracking
    source_file: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any], source_file: Optional[str] = None) -> "PatternConfig":
        node_types = {}
        if "node_types" in data:
            for name, type_data in data["node_types"].items():
                node_types[name] = NodeTypeDefinition.from_dict(name, type_data)

        patterns = []
        if "patterns" in data:
            for pattern_data in data["patterns"]:
                patterns.append(PatternDefinition.from_dict(pattern_data))

        edge_rules = []
        if "edges" in data:
            for edge_data in data["edges"]:
                edge_rules.append(EdgeRule.from_dict(edge_data))

        return cls(
            version=data.get("version", "1.0"),
            meta=PatternMeta.from_dict(data["meta"]) if "meta" in data else None,
            settings=PatternSettings.from_dict(data["settings"]) if "settings" in data else None,
            node_types=node_types,
            patterns=patterns,
            edge_rules=edge_rules,
            source_file=source_file,
        )

    def get_patterns_for_language(self, language: str) -> List[PatternDefinition]:
        """Get patterns that apply to a specific language."""
        result = []
        for pattern in self.patterns:
            if pattern.language is None or pattern.language == "any":
                result.append(pattern)
            elif pattern.language.lower() == language.lower():
                result.append(pattern)
        return result

    def get_patterns_for_file(self, file_path: str, language: Optional[str] = None) -> List[PatternDefinition]:
        """Get patterns that apply to a specific file."""
        import fnmatch

        result = []
        for pattern in self.patterns:
            # Check language filter
            if language and pattern.language and pattern.language != "any":
                if pattern.language.lower() != language.lower():
                    continue

            # Check file pattern
            if pattern.file_pattern:
                if not fnmatch.fnmatch(file_path, pattern.file_pattern):
                    continue

            # Check exclusions
            excluded = False
            for exclude in pattern.exclude:
                if fnmatch.fnmatch(file_path, exclude):
                    excluded = True
                    break

            if not excluded:
                result.append(pattern)

        return result
