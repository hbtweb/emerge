"""
Custom patterns module for project-specific dependency recognition.
Enables framework-specific patterns (WordPress hooks, Laravel facades, DI containers)
through YAML configuration files.

Usage:
    from emerge.patterns import load_patterns, PatternMatcher, NodeEdgeCreator
    
    # Load patterns from .emerge/patterns.yaml
    config = load_patterns(Path('/path/to/project'))
    
    # Match patterns in a file
    matcher = PatternMatcher(config)
    matches = matcher.match_file('src/plugin.php', content, 'php')
    
    # Create graph nodes/edges from matches
    creator = NodeEdgeCreator(config)
    for match in matches.matches:
        nodes, edges = creator.process_match(match)
    
    # Apply edge rules to connect patterns
    creator.apply_edge_rules()
    
    # Get networkx graph
    graph = creator.to_networkx()
"""

from emerge.patterns.config import (
    PatternConfig,
    PatternDefinition,
    NodeCreation,
    EdgeCreation,
    EdgeRule,
    CaptureDefinition,
    PatternMatch as MatchConfig,
    MatchType,
)
from emerge.patterns.loader import PatternLoader, load_patterns
from emerge.patterns.matcher import PatternMatcher, PatternMatch, FileMatches, match_patterns
from emerge.patterns.creator import NodeEdgeCreator, CreatedNode, CreatedEdge
from emerge.patterns.transforms import CaptureTransforms, create_transforms

__all__ = [
    # Config classes
    "PatternConfig",
    "PatternDefinition",
    "NodeCreation",
    "EdgeCreation",
    "EdgeRule",
    "CaptureDefinition",
    "MatchConfig",
    "MatchType",
    # Loader
    "PatternLoader",
    "load_patterns",
    # Matcher
    "PatternMatcher",
    "PatternMatch",
    "FileMatches",
    "match_patterns",
    # Creator
    "NodeEdgeCreator",
    "CreatedNode",
    "CreatedEdge",
    # Transforms
    "CaptureTransforms",
    "create_transforms",
]
