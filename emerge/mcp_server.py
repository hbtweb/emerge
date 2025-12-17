"""
MCP (Model Context Protocol) server for emerge.
Enables AI assistants like Claude to query codebase dependency graphs.
"""

# Authors: Grzegorz Lato <grzegorz.lato@gmail.com>
# License: MIT

import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

import networkx as nx
import coloredlogs
from mcp.server.fastmcp import FastMCP

from emerge.log import Logger
from emerge.graph_cache import GraphCache, CachedAnalysis, get_cache
from emerge.languages.registry import get_registry

LOGGER = Logger(logging.getLogger('mcp_server'))
coloredlogs.install(level='E', logger=LOGGER.logger(), fmt=Logger.log_format)

# Initialize FastMCP server
mcp = FastMCP(
    "emerge",
    instructions="Codebase dependency graph analysis - query imports, coupling, and impact"
)

# Global state for the loaded analysis
_analysis: Optional[CachedAnalysis] = None
_graphs: Dict[str, nx.DiGraph] = {}
_source_dir: Optional[Path] = None


def load_analysis(source_dir: Path, cache_dir: Optional[Path] = None) -> bool:
    """
    Load analysis from cache for the given source directory.

    Args:
        source_dir: Path to the source code
        cache_dir: Path to cache directory

    Returns:
        True if loaded successfully
    """
    global _analysis, _graphs, _source_dir

    cache = get_cache(cache_dir)
    registry = get_registry()

    # Detect extensions
    detected = registry.detect_languages(source_dir)
    extensions = set()
    for lang_name in detected:
        lang_def = registry.get_language(lang_name)
        if lang_def:
            extensions.update(lang_def.extensions)

    if not extensions:
        LOGGER.error('No supported languages detected')
        return False

    # Compute hash and try to load
    source_hash = cache.compute_source_hash(source_dir, extensions)
    cached = cache.load(source_hash)

    if cached is None:
        LOGGER.warning('No valid cache found. Run emerge --scan first.')
        return False

    _analysis = cached
    _graphs = cached.graphs
    _source_dir = source_dir

    LOGGER.info(f'Loaded {len(_graphs)} graphs for {source_dir.name}')
    return True


def _get_primary_graph() -> Optional[nx.DiGraph]:
    """Get the primary dependency graph (file or entity)."""
    for name in ['file_result_dependency_graph', 'entity_result_dependency_graph']:
        if name in _graphs:
            return _graphs[name]
    return next(iter(_graphs.values())) if _graphs else None


# ============================================================================
# MCP Tools - Graph Queries
# ============================================================================

@mcp.tool()
def find_dependencies(entity: str) -> List[str]:
    """
    Find what a file or entity depends on (imports/uses).

    Args:
        entity: File path or entity name (e.g., 'src/main.py' or 'UserService')

    Returns:
        List of dependencies
    """
    graph = _get_primary_graph()
    if graph is None:
        return []

    # Try exact match first
    if entity in graph:
        return list(graph.successors(entity))

    # Try partial match
    for node in graph.nodes():
        if entity in node or node.endswith(entity):
            return list(graph.successors(node))

    return []


@mcp.tool()
def find_dependents(entity: str) -> List[str]:
    """
    Find what depends on a file or entity (reverse dependencies).

    Args:
        entity: File path or entity name

    Returns:
        List of files/entities that depend on this one
    """
    graph = _get_primary_graph()
    if graph is None:
        return []

    if entity in graph:
        return list(graph.predecessors(entity))

    # Try partial match
    for node in graph.nodes():
        if entity in node or node.endswith(entity):
            return list(graph.predecessors(node))

    return []


@mcp.tool()
def coupling_metrics(entity: str) -> Dict[str, Any]:
    """
    Get coupling metrics for a file or entity.

    Args:
        entity: File path or entity name

    Returns:
        Dict with fan_in, fan_out, instability, and afferent/efferent coupling
    """
    graph = _get_primary_graph()
    if graph is None:
        return {"error": "No graph loaded"}

    # Find the node
    node = None
    if entity in graph:
        node = entity
    else:
        for n in graph.nodes():
            if entity in n or n.endswith(entity):
                node = n
                break

    if node is None:
        return {"error": f"Entity not found: {entity}"}

    fan_in = graph.in_degree(node)
    fan_out = graph.out_degree(node)

    # Martin's instability metric: I = Ce / (Ca + Ce)
    total = fan_in + fan_out
    instability = fan_out / total if total > 0 else 0.0

    return {
        "entity": node,
        "fan_in": fan_in,
        "fan_out": fan_out,
        "afferent_coupling": fan_in,
        "efferent_coupling": fan_out,
        "instability": round(instability, 3),
        "stability": round(1 - instability, 3)
    }


@mcp.tool()
def hotspots(limit: int = 10, metric: str = "fan_in") -> List[Dict[str, Any]]:
    """
    Find highest-coupled entities (potential maintenance hotspots).

    Args:
        limit: Maximum number of results
        metric: Sorting metric - 'fan_in', 'fan_out', or 'total'

    Returns:
        List of entities with highest coupling
    """
    graph = _get_primary_graph()
    if graph is None:
        return []

    results = []
    for node in graph.nodes():
        fan_in = graph.in_degree(node)
        fan_out = graph.out_degree(node)
        total = fan_in + fan_out

        if total == 0:
            continue

        instability = fan_out / total if total > 0 else 0.0

        results.append({
            "entity": node,
            "fan_in": fan_in,
            "fan_out": fan_out,
            "total_coupling": total,
            "instability": round(instability, 3)
        })

    # Sort by requested metric
    if metric == "fan_in":
        results.sort(key=lambda x: x["fan_in"], reverse=True)
    elif metric == "fan_out":
        results.sort(key=lambda x: x["fan_out"], reverse=True)
    else:
        results.sort(key=lambda x: x["total_coupling"], reverse=True)

    return results[:limit]


@mcp.tool()
def impact_analysis(entity: str) -> Dict[str, Any]:
    """
    Analyze impact of changing an entity - what might break?

    Args:
        entity: File path or entity name

    Returns:
        Dict with direct dependents, transitive dependents, and risk score
    """
    graph = _get_primary_graph()
    if graph is None:
        return {"error": "No graph loaded"}

    # Find the node
    node = None
    if entity in graph:
        node = entity
    else:
        for n in graph.nodes():
            if entity in n or n.endswith(entity):
                node = n
                break

    if node is None:
        return {"error": f"Entity not found: {entity}"}

    # Direct dependents (one hop)
    direct = list(graph.predecessors(node))

    # Transitive dependents (all reachable)
    try:
        reversed_graph = graph.reverse()
        transitive = list(nx.descendants(reversed_graph, node))
    except Exception:
        transitive = direct

    # Risk score based on impact radius
    total_nodes = graph.number_of_nodes()
    impact_ratio = len(transitive) / total_nodes if total_nodes > 0 else 0

    if impact_ratio > 0.3:
        risk_level = "HIGH"
    elif impact_ratio > 0.1:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    return {
        "entity": node,
        "direct_dependents": len(direct),
        "direct_dependents_list": direct[:20],
        "transitive_dependents": len(transitive),
        "transitive_dependents_list": sorted(transitive)[:50],
        "impact_ratio": round(impact_ratio, 3),
        "risk_level": risk_level
    }


@mcp.tool()
def dependency_path(source: str, target: str) -> Dict[str, Any]:
    """
    Find the shortest dependency path between two entities.

    Args:
        source: Starting file/entity
        target: Target file/entity

    Returns:
        Dict with path if found, or indication that no path exists
    """
    graph = _get_primary_graph()
    if graph is None:
        return {"error": "No graph loaded"}

    def find_node(name: str) -> Optional[str]:
        if name in graph:
            return name
        for n in graph.nodes():
            if name in n or n.endswith(name):
                return n
        return None

    src_node = find_node(source)
    tgt_node = find_node(target)

    if src_node is None:
        return {"error": f"Source not found: {source}"}
    if tgt_node is None:
        return {"error": f"Target not found: {target}"}

    try:
        path = nx.shortest_path(graph, src_node, tgt_node)
        return {
            "source": src_node,
            "target": tgt_node,
            "path": path,
            "length": len(path) - 1,
            "exists": True
        }
    except nx.NetworkXNoPath:
        return {
            "source": src_node,
            "target": tgt_node,
            "path": [],
            "length": -1,
            "exists": False
        }


@mcp.tool()
def cyclic_dependencies(limit: int = 10) -> List[List[str]]:
    """
    Find cyclic dependencies in the codebase.

    Args:
        limit: Maximum number of cycles to return

    Returns:
        List of cycles (each cycle is a list of entities)
    """
    graph = _get_primary_graph()
    if graph is None:
        return []

    try:
        cycles = list(nx.simple_cycles(graph))
        cycles.sort(key=len)
        return cycles[:limit]
    except Exception as e:
        LOGGER.error(f'Error finding cycles: {e}')
        return []


@mcp.tool()
def graph_summary() -> Dict[str, Any]:
    """
    Get a summary of the codebase graph.

    Returns:
        Dict with node count, edge count, density, and component info
    """
    graph = _get_primary_graph()
    if graph is None:
        return {"error": "No graph loaded"}

    num_nodes = graph.number_of_nodes()
    num_edges = graph.number_of_edges()

    try:
        components = list(nx.weakly_connected_components(graph))
        num_components = len(components)
        largest_component = max(len(c) for c in components) if components else 0
    except Exception:
        num_components = 1
        largest_component = num_nodes

    density = nx.density(graph) if num_nodes > 1 else 0
    avg_in = sum(d for _, d in graph.in_degree()) / num_nodes if num_nodes > 0 else 0
    avg_out = sum(d for _, d in graph.out_degree()) / num_nodes if num_nodes > 0 else 0

    return {
        "source_directory": str(_source_dir) if _source_dir else None,
        "graphs_loaded": list(_graphs.keys()),
        "nodes": num_nodes,
        "edges": num_edges,
        "density": round(density, 4),
        "components": num_components,
        "largest_component_size": largest_component,
        "average_in_degree": round(avg_in, 2),
        "average_out_degree": round(avg_out, 2),
        "has_cycles": not nx.is_directed_acyclic_graph(graph)
    }


@mcp.tool()
def search_entities(pattern: str, limit: int = 20) -> List[str]:
    """
    Search for entities matching a pattern.

    Args:
        pattern: Substring to search for (case-insensitive)
        limit: Maximum results

    Returns:
        List of matching entity names
    """
    graph = _get_primary_graph()
    if graph is None:
        return []

    pattern_lower = pattern.lower()
    matches = [
        node for node in graph.nodes()
        if pattern_lower in node.lower()
    ]

    return sorted(matches)[:limit]


# ============================================================================
# MCP Resources
# ============================================================================

@mcp.resource("graph://summary")
def resource_summary() -> str:
    """Overview of the loaded codebase graph."""
    summary = graph_summary()
    if "error" in summary:
        return summary["error"]

    return f"""
Codebase: {summary.get('source_directory', 'Unknown')}
Graphs: {', '.join(summary.get('graphs_loaded', []))}

Nodes: {summary['nodes']}
Edges: {summary['edges']}
Density: {summary['density']}
Components: {summary['components']}
Has Cycles: {summary['has_cycles']}

Average In-Degree: {summary['average_in_degree']}
Average Out-Degree: {summary['average_out_degree']}
"""


@mcp.resource("graph://hotspots")
def resource_hotspots() -> str:
    """Top coupling hotspots in the codebase."""
    spots = hotspots(limit=20, metric="total")
    if not spots:
        return "No hotspots found or graph not loaded."

    lines = ["Top 20 Coupling Hotspots:", ""]
    for i, h in enumerate(spots, 1):
        lines.append(
            f"{i:2}. {h['entity']}\n"
            f"    Fan-In: {h['fan_in']}, Fan-Out: {h['fan_out']}, "
            f"Instability: {h['instability']}"
        )

    return "\n".join(lines)


# ============================================================================
# Server Entry Point
# ============================================================================

def run_server(
    source_dir: Optional[Path] = None,
    cache_dir: Optional[Path] = None,
    transport: str = "stdio"
) -> None:
    """
    Run the MCP server.

    Args:
        source_dir: Path to source code (loads from cache)
        cache_dir: Path to cache directory
        transport: MCP transport ('stdio' or 'sse')
    """
    if source_dir:
        if not load_analysis(source_dir, cache_dir):
            LOGGER.warning('Running without pre-loaded analysis')

    LOGGER.info(f'Starting MCP server (transport: {transport})')
    mcp.run(transport=transport)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        source = Path(sys.argv[1])
        run_server(source_dir=source)
    else:
        run_server()
