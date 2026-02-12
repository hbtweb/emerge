"""
Node and edge creator - creates graph nodes and edges from pattern matches.
"""

import logging
import re
from typing import Optional, List, Dict, Any, Set, Tuple
from dataclasses import dataclass, field

import networkx as nx
import coloredlogs

from emerge.log import Logger
from emerge.patterns.config import (
    PatternConfig,
    PatternDefinition,
    NodeCreation,
    EdgeCreation,
    EdgeRule,
    EdgeRuleMatch,
    EdgeMatchType,
)
from emerge.patterns.matcher import PatternMatch, FileMatches

LOGGER = Logger(logging.getLogger("patterns.creator"))
coloredlogs.install(level="E", logger=LOGGER.logger(), fmt=Logger.log_format)


@dataclass
class CreatedNode:
    """A node created from a pattern match."""
    node_id: str
    node_type: str
    label: Optional[str] = None
    properties: Dict[str, Any] = field(default_factory=dict)
    source_pattern: str = ""
    source_file: str = ""
    source_line: int = 0


@dataclass
class CreatedEdge:
    """An edge created from a pattern match or edge rule."""
    from_node: str
    to_node: str
    edge_type: str
    directed: bool = True
    properties: Dict[str, Any] = field(default_factory=dict)
    source_pattern: Optional[str] = None
    source_rule: Optional[str] = None


@dataclass
class GraphChanges:
    """Changes to apply to a graph."""
    nodes: List[CreatedNode] = field(default_factory=list)
    edges: List[CreatedEdge] = field(default_factory=list)
    nodes_by_id: Dict[str, CreatedNode] = field(default_factory=dict)
    
    def add_node(self, node: CreatedNode) -> None:
        if node.node_id not in self.nodes_by_id:
            self.nodes.append(node)
            self.nodes_by_id[node.node_id] = node
    
    def add_edge(self, edge: CreatedEdge) -> None:
        self.edges.append(edge)


class NodeEdgeCreator:
    """Creates nodes and edges in the graph from pattern matches."""
    
    TEMPLATE_VAR = re.compile(r"\$([a-zA-Z_][a-zA-Z0-9_]*)")
    
    def __init__(self, config: PatternConfig):
        self.config = config
        self._patterns_by_id: Dict[str, PatternDefinition] = {
            p.id: p for p in config.patterns
        }
        self._nodes_by_type: Dict[str, List[CreatedNode]] = {}
    
    def create_from_match(self, match: PatternMatch, file_path: str) -> GraphChanges:
        changes = GraphChanges()
        pattern = self._patterns_by_id.get(match.pattern_id)
        if pattern is None or pattern.creates is None:
            return changes
        
        context = self._build_context(match, file_path)
        
        for node_def in pattern.creates.nodes:
            node = self._create_node(node_def, context, match)
            if node:
                changes.add_node(node)
                if node.node_type not in self._nodes_by_type:
                    self._nodes_by_type[node.node_type] = []
                self._nodes_by_type[node.node_type].append(node)
        
        for edge_def in pattern.creates.edges:
            edge = self._create_edge(edge_def, context, match)
            if edge:
                changes.add_edge(edge)
        
        return changes
    
    def create_from_matches(self, file_matches: FileMatches) -> GraphChanges:
        combined = GraphChanges()
        for match in file_matches.matches:
            changes = self.create_from_match(match, file_matches.file_path)
            for node in changes.nodes:
                combined.add_node(node)
            for edge in changes.edges:
                combined.add_edge(edge)
        return combined
    
    def apply_to_graph(self, graph: nx.DiGraph, changes: GraphChanges, graph_name: str = "custom_patterns") -> Tuple[int, int]:
        nodes_added = 0
        edges_added = 0
        
        for node in changes.nodes:
            if node.node_id not in graph:
                graph.add_node(
                    node.node_id,
                    display_name=node.label or node.node_id,
                    node_type=node.node_type,
                    _pattern_source=node.source_pattern,
                    _source_file=node.source_file,
                    _source_line=node.source_line,
                    **node.properties
                )
                nodes_added += 1
        
        for edge in changes.edges:
            if edge.from_node not in graph:
                graph.add_node(edge.from_node, display_name=edge.from_node)
            if edge.to_node not in graph:
                graph.add_node(edge.to_node, display_name=edge.to_node)
            graph.add_edge(
                edge.from_node,
                edge.to_node,
                edge_type=edge.edge_type,
                _pattern_source=edge.source_pattern,
                _rule_source=edge.source_rule,
                **edge.properties
            )
            edges_added += 1
        
        return nodes_added, edges_added
    
    def process_file(self, graph: nx.DiGraph, file_matches: FileMatches) -> Tuple[int, int]:
        changes = self.create_from_matches(file_matches)
        return self.apply_to_graph(graph, changes)
    
    def _build_context(self, match: PatternMatch, file_path: str) -> Dict[str, str]:
        context = dict(match.captures)
        context["file"] = file_path
        context["line"] = str(match.line_number)
        context["current_file"] = file_path
        context["match"] = match.match_text
        return context
    
    def _substitute_template(self, template: str, context: Dict[str, str]) -> str:
        def replace(m):
            var_name = m.group(1)
            return context.get(var_name, f"${var_name}")
        return self.TEMPLATE_VAR.sub(replace, template)
    
    def _create_node(self, node_def: NodeCreation, context: Dict[str, str], match: PatternMatch) -> Optional[CreatedNode]:
        node_id = self._substitute_template(node_def.id_template, context)
        label = None
        if node_def.label_template:
            label = self._substitute_template(node_def.label_template, context)
        
        properties = {}
        for key, value_template in node_def.properties.items():
            properties[key] = self._substitute_template(str(value_template), context)
        
        return CreatedNode(
            node_id=node_id,
            node_type=node_def.type,
            label=label,
            properties=properties,
            source_pattern=match.pattern_id,
            source_file=match.file_path,
            source_line=match.line_number,
        )
    
    def _create_edge(self, edge_def: EdgeCreation, context: Dict[str, str], match: PatternMatch) -> Optional[CreatedEdge]:
        from_node = self._substitute_template(edge_def.from_template, context)
        to_node = self._substitute_template(edge_def.to_template, context)
        
        properties = {}
        for key, value_template in edge_def.properties.items():
            properties[key] = self._substitute_template(str(value_template), context)
        
        return CreatedEdge(
            from_node=from_node,
            to_node=to_node,
            edge_type=edge_def.type,
            directed=edge_def.directed,
            properties=properties,
            source_pattern=match.pattern_id,
        )
    
    def apply_edge_rules(self, all_changes: GraphChanges) -> List[CreatedEdge]:
        new_edges = []
        for rule in self.config.edge_rules:
            edges = self._apply_edge_rule(rule, all_changes)
            new_edges.extend(edges)
        return new_edges
    
    def _apply_edge_rule(self, rule: EdgeRule, changes: GraphChanges) -> List[CreatedEdge]:
        edges = []
        from_nodes = self._get_nodes_for_endpoint(rule.from_endpoint.pattern_id, rule.from_endpoint.node_type, changes)
        to_nodes = self._get_nodes_for_endpoint(rule.to_endpoint.pattern_id, rule.to_endpoint.node_type, changes)
        
        for from_node in from_nodes:
            for to_node in to_nodes:
                if self._nodes_match(from_node, to_node, rule.match):
                    edge = CreatedEdge(
                        from_node=from_node.node_id,
                        to_node=to_node.node_id,
                        edge_type=rule.edge_type,
                        directed=rule.directed,
                        properties=dict(rule.properties),
                        source_rule=rule.id,
                    )
                    edges.append(edge)
        return edges
    
    def _get_nodes_for_endpoint(self, pattern_id: Optional[str], node_type: Optional[str], changes: GraphChanges) -> List[CreatedNode]:
        nodes = []
        for node in changes.nodes:
            if pattern_id and node.source_pattern != pattern_id:
                continue
            if node_type and node.node_type != node_type:
                continue
            nodes.append(node)
        return nodes
    
    def _nodes_match(self, from_node: CreatedNode, to_node: CreatedNode, match: EdgeRuleMatch) -> bool:
        if match.type == EdgeMatchType.PROPERTY_EQUALS:
            for prop in match.properties:
                from_val = from_node.properties.get(prop)
                to_val = to_node.properties.get(prop)
                if from_val != to_val or from_val is None:
                    return False
            return True
        elif match.type == EdgeMatchType.PROPERTY_CONTAINS:
            if match.from_property and match.to_property:
                from_val = from_node.properties.get(match.from_property, "")
                to_val = to_node.properties.get(match.to_property, "")
                return to_val in from_val
            return False
        elif match.type == EdgeMatchType.PROPERTY_REGEX:
            if match.from_property and match.to_property:
                pattern = from_node.properties.get(match.from_property, "")
                value = to_node.properties.get(match.to_property, "")
                try:
                    return bool(re.search(pattern, value))
                except re.error:
                    return False
            return False
        return False


def process_patterns(config: PatternConfig, graph: nx.DiGraph, file_matches: FileMatches) -> Tuple[int, int]:
    creator = NodeEdgeCreator(config)
    return creator.process_file(graph, file_matches)
