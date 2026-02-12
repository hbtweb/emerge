"""
MCP (Model Context Protocol) server for emerge.
Enables AI assistants like Claude to query codebase dependency graphs.
"""

# Authors: Grzegorz Lato <grzegorz.lato@gmail.com>
# License: MIT

import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

import networkx as nx
import coloredlogs
from mcp.server.fastmcp import FastMCP

from emerge.log import Logger
from emerge.graph_cache import GraphCache, CachedAnalysis, get_cache
from emerge.languages.registry import get_registry
from emerge.constants import EMERGE_CACHE_DIR, DEFAULT_IGNORE_DIRS

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
_watcher: Optional[Any] = None
_ws_server: Optional[Any] = None
_http_server: Optional[Any] = None
_http_thread: Optional[Any] = None
_config: Dict[str, Any] = {
    "ignore_dirs": list(DEFAULT_IGNORE_DIRS),
    "languages": [],  # Empty = auto-detect
    "websocket_port": 8765
}


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
    """Get the primary dependency graph (file or entity).

    Prefers non-empty dependency graphs, falls back to filesystem_graph.
    """
    # Preferred order: dependency graphs first, then filesystem
    preferred_order = [
        'file_result_dependency_graph',
        'entity_result_dependency_graph',
        'filesystem_graph'
    ]

    # First pass: find a non-empty graph in preferred order
    for name in preferred_order:
        if name in _graphs and _graphs[name].number_of_nodes() > 0:
            return _graphs[name]

    # Second pass: return any non-empty graph
    for graph in _graphs.values():
        if graph.number_of_nodes() > 0:
            return graph

    # Last resort: return first available graph
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
# MCP Tools - Project Operations
# ============================================================================

# Available graph types for filtering
GRAPH_TYPES = {
    "file_dependency": "FILE_RESULT_DEPENDENCY_GRAPH",
    "entity_dependency": "ENTITY_RESULT_DEPENDENCY_GRAPH",
    "inheritance": "ENTITY_RESULT_INHERITANCE_GRAPH",
    "complete": "ENTITY_RESULT_COMPLETE_GRAPH",
    "filesystem": "FILESYSTEM_GRAPH",
}


@mcp.tool()
def project_scan(
    directory: str = ".",
    force: bool = False,
    graphs: Optional[List[str]] = None,
    include_inheritance: bool = True,
) -> Dict[str, Any]:
    """
    Scan a directory and build dependency graphs.

    Args:
        directory: Path to source code directory (defaults to current directory ".")
        force: Force rebuild even if cache exists
        graphs: List of graph types to generate. Options: file_dependency, entity_dependency,
                inheritance, complete, filesystem. Default: all dependency + inheritance graphs.
        include_inheritance: Include inheritance graph (default: True). Shortcut for common case.

    Returns:
        Dict with scan results (languages detected, graphs built, node/edge counts)

    Examples:
        project_scan("/path/to/project")  # All graphs (default)
        project_scan("/path/to/project", graphs=["file_dependency"])  # Only file deps
        project_scan("/path/to/project", include_inheritance=False)  # Skip inheritance
    """
    global _analysis, _graphs, _source_dir

    # Default to current working directory if empty or "."
    if not directory or directory == ".":
        directory = os.getcwd()

    source_dir = Path(directory).resolve()
    if not source_dir.exists():
        return {"error": f"Directory not found: {directory}"}
    if not source_dir.is_dir():
        return {"error": f"Not a directory: {directory}"}

    registry = get_registry()
    detected = registry.detect_languages(source_dir)

    if not detected:
        return {"error": "No supported languages detected", "path": str(source_dir)}

    # Collect extensions
    extensions = set()
    for lang_name in detected:
        lang_def = registry.get_language(lang_name)
        if lang_def:
            extensions.update(lang_def.extensions)

    # Check cache unless forced
    cache_dir = source_dir / EMERGE_CACHE_DIR
    cache = get_cache(cache_dir)
    source_hash = cache.compute_source_hash(source_dir, extensions)

    if not force:
        cached = cache.load(source_hash)
        if cached:
            _analysis = cached
            _graphs = cached.graphs
            _source_dir = source_dir
            return {
                "status": "loaded_from_cache",
                "directory": str(source_dir),
                "languages": list(detected),
                "graphs": list(_graphs.keys()),
                "nodes": sum(g.number_of_nodes() for g in _graphs.values()),
                "edges": sum(g.number_of_edges() for g in _graphs.values())
            }

    # Determine which graphs to build
    from emerge.appear import Emerge
    from emerge.analysis import Analysis
    from emerge.graph import GraphType

    # Default graphs if none specified
    if graphs is None:
        requested_graphs = ["file_dependency", "entity_dependency"]
        if include_inheritance:
            requested_graphs.append("inheritance")
    else:
        # Validate requested graphs
        invalid = [g for g in graphs if g not in GRAPH_TYPES]
        if invalid:
            return {
                "error": f"Invalid graph types: {invalid}",
                "valid_types": list(GRAPH_TYPES.keys())
            }
        requested_graphs = graphs

    analysis = Analysis()
    analysis.project_name = source_dir.name
    analysis.analysis_name = f"mcp-scan of {source_dir.name}"
    analysis.source_directory = str(source_dir)
    analysis.export_directory = str(cache_dir)
    analysis.only_permit_languages = [lang.upper() for lang in detected]
    analysis.only_permit_file_extensions = list(extensions)
    analysis.scan_types = ['file_scan', 'entity_scan']
    analysis.ignore_directories_containing = _config["ignore_dirs"]

    # Create requested graph representations
    for graph_name in requested_graphs:
        graph_type_name = GRAPH_TYPES[graph_name]
        graph_type = GraphType[graph_type_name]
        analysis.create_graph_representation(graph_type)

    # Run analysis
    emerge = Emerge()
    emerge.config.analyses = [analysis]
    emerge.config.project_name = source_dir.name
    emerge.config.valid = True
    emerge.start_analyzing()

    # Extract graphs
    _graphs = {
        name: repr.digraph
        for name, repr in analysis.graph_representations.items()
        if repr is not None and repr.digraph is not None
    }
    _source_dir = source_dir

    # Cache results
    cache.save(analysis, source_hash)

    return {
        "status": "scanned",
        "directory": str(source_dir),
        "languages": list(detected),
        "graphs": list(_graphs.keys()),
        "requested_graphs": requested_graphs,
        "nodes": sum(g.number_of_nodes() for g in _graphs.values()),
        "edges": sum(g.number_of_edges() for g in _graphs.values())
    }


@mcp.tool()
def project_status() -> Dict[str, Any]:
    """
    Get current project status (loaded directory, watcher state, etc.).

    Returns:
        Dict with current state information
    """
    graph = _get_primary_graph()

    return {
        "cwd": os.getcwd(),
        "directory": str(_source_dir) if _source_dir else None,
        "loaded": _source_dir is not None,
        "graphs": list(_graphs.keys()),
        "nodes": graph.number_of_nodes() if graph else 0,
        "edges": graph.number_of_edges() if graph else 0,
        "watcher_running": _watcher is not None and _watcher.is_running() if _watcher else False,
        "websocket_running": _ws_server is not None,
        "websocket_port": _config["websocket_port"],
        "config": _config
    }


@mcp.tool()
def languages_list() -> Dict[str, Any]:
    """
    List all supported languages and their file extensions.

    Returns:
        Dict with languages and extensions
    """
    registry = get_registry()
    languages = {}

    for lang_name in registry.list_languages():
        lang_def = registry.get_language(lang_name)
        if lang_def:
            patterns = lang_def.patterns
            languages[lang_name] = {
                "extensions": lang_def.extensions,
                "import_patterns": len(patterns.get("imports", [])),
                "entity_patterns": len(patterns.get("entities", [])),
                "has_manifest": lang_def.manifest is not None
            }

    return {
        "count": len(languages),
        "languages": languages,
        "all_extensions": registry.list_extensions()
    }


@mcp.tool()
def graph_types() -> Dict[str, Any]:
    """
    List available graph types for project_scan.

    Returns:
        Dict with graph type names and descriptions
    """
    return {
        "types": {
            "file_dependency": {
                "description": "Dependencies between files based on imports",
                "default": True,
                "requires_entity_scan": False
            },
            "entity_dependency": {
                "description": "Dependencies between classes/interfaces/functions",
                "default": True,
                "requires_entity_scan": True
            },
            "inheritance": {
                "description": "Class inheritance and interface implementation",
                "default": True,
                "requires_entity_scan": True
            },
            "complete": {
                "description": "Combined dependency + inheritance graph",
                "default": False,
                "requires_entity_scan": True
            },
            "filesystem": {
                "description": "Directory/file tree structure",
                "default": False,
                "requires_entity_scan": False
            }
        },
        "default_graphs": ["file_dependency", "entity_dependency", "inheritance"],
        "usage": "project_scan(graphs=['file_dependency', 'inheritance'])"
    }


@mcp.tool()
def watcher_start(directory: str = "") -> Dict[str, Any]:
    """
    Start file watcher for real-time graph updates.

    Args:
        directory: Directory to watch (uses current project if empty)

    Returns:
        Dict with watcher status
    """
    global _watcher

    if _watcher and _watcher.is_running():
        return {"status": "already_running", "directory": str(_source_dir)}

    # Resolve directory: explicit path > loaded project > current working directory
    if directory and directory != ".":
        watch_dir = Path(directory).resolve()
    elif _source_dir:
        watch_dir = _source_dir
    else:
        watch_dir = Path(os.getcwd()).resolve()

    if not _graphs:
        return {"error": "No graphs loaded. Run project_scan first."}

    from emerge.watcher import GraphWatcher

    # Get extensions from registry
    registry = get_registry()
    extensions = set(registry.list_extensions())

    _watcher = GraphWatcher(watch_dir, extensions=extensions, ignore_dirs=set(_config["ignore_dirs"]))
    _watcher.graphs = _graphs

    # Connect to WebSocket if running
    if _ws_server:
        _watcher.add_listener(_ws_server.broadcast_update)

    _watcher.start()

    return {
        "status": "started",
        "directory": str(watch_dir),
        "extensions": list(extensions)[:20]
    }


@mcp.tool()
def watcher_stop() -> Dict[str, Any]:
    """
    Stop the file watcher.

    Returns:
        Dict with status
    """
    global _watcher

    if not _watcher or not _watcher.is_running():
        return {"status": "not_running"}

    _watcher.stop()
    _watcher = None

    return {"status": "stopped"}


def _generate_viewer_html(ws_port: int) -> str:
    """Generate the unified viewer HTML with all features."""
    from emerge.viewer_template import generate_unified_viewer_html
    return generate_unified_viewer_html(ws_port)


@mcp.tool()
def viewer_open(port: int = 0, http_port: int = 8080) -> Dict[str, Any]:
    """
    Start WebSocket server and open D3 viewer in browser.

    The viewer HTML is stored in the project's cache/viewer/ directory.

    Args:
        port: WebSocket port (0 = use default from config)
        http_port: HTTP server port for serving the viewer

    Returns:
        Dict with viewer URL and status
    """
    global _ws_server, _http_server, _http_thread
    import webbrowser
    import http.server
    import socketserver
    import threading

    if not _graphs:
        return {"error": "No graphs loaded. Run project_scan first."}

    if not _source_dir:
        return {"error": "No project directory set. Run project_scan first."}

    ws_port = port if port > 0 else _config["websocket_port"]

    # Start WebSocket server if not running
    if not _ws_server:
        from emerge.websocket_server import GraphWebSocketServer
        _ws_server = GraphWebSocketServer(port=ws_port, graphs=_graphs)
        _ws_server.start()

    # Create viewer directory in project's cache
    viewer_dir = _source_dir / EMERGE_CACHE_DIR / 'viewer'
    viewer_dir.mkdir(parents=True, exist_ok=True)

    # Write/update the viewer HTML (always regenerate to ensure correct WS port)
    viewer_file = viewer_dir / 'index.html'
    viewer_file.write_text(_generate_viewer_html(ws_port))

    # Start HTTP server if not running
    if _http_server is None:
        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(viewer_dir), **kwargs)
            def log_message(self, format, *args):
                pass  # Suppress HTTP logs

        try:
            _http_server = socketserver.TCPServer(("", http_port), Handler)
        except OSError:
            # Port in use, try another
            http_port = http_port + 1
            _http_server = socketserver.TCPServer(("", http_port), Handler)

        _http_thread = threading.Thread(target=_http_server.serve_forever, daemon=True)
        _http_thread.start()

    viewer_url = f"http://localhost:{http_port}"

    # Try to open browser
    try:
        webbrowser.open(viewer_url)
        opened = True
    except Exception:
        opened = False

    return {
        "status": "started",
        "websocket_url": f"ws://localhost:{ws_port}",
        "viewer_url": viewer_url,
        "viewer_file": str(viewer_file),
        "browser_opened": opened,
        "client_count": _ws_server.client_count if _ws_server else 0
    }


@mcp.tool()
def viewer_close() -> Dict[str, Any]:
    """
    Stop the WebSocket and HTTP servers.

    Returns:
        Dict with status
    """
    global _ws_server, _http_server, _http_thread

    stopped = []

    if _http_server:
        _http_server.shutdown()
        _http_server = None
        _http_thread = None
        stopped.append("http")

    if _ws_server:
        _ws_server.stop()
        _ws_server = None
        stopped.append("websocket")

    if not stopped:
        return {"status": "not_running"}

    return {"status": "stopped", "services": stopped}


@mcp.tool()
def config_get() -> Dict[str, Any]:
    """
    Get current configuration.

    Returns:
        Current config dict
    """
    return _config.copy()


@mcp.tool()
def config_set(
    ignore_dirs: Optional[List[str]] = None,
    languages: Optional[List[str]] = None,
    websocket_port: Optional[int] = None
) -> Dict[str, Any]:
    """
    Update configuration.

    Args:
        ignore_dirs: Directories to ignore during scanning
        languages: Languages to scan (empty = auto-detect)
        websocket_port: Port for WebSocket server

    Returns:
        Updated config
    """
    if ignore_dirs is not None:
        _config["ignore_dirs"] = ignore_dirs
    if languages is not None:
        _config["languages"] = languages
    if websocket_port is not None:
        _config["websocket_port"] = websocket_port

    return _config.copy()


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



# ============================================================================
# Custom Patterns Tools
# ============================================================================

try:
    from emerge.patterns.mcp_tools import get_pattern_tools
    
    def _get_source_dir():
        return _source_dir
    
    def _get_graphs():
        return _graphs
    
    # Register pattern tools
    _pattern_tools = get_pattern_tools(mcp, _get_source_dir, _get_graphs)
    LOGGER.debug(f"Registered {len(_pattern_tools)} pattern tools")
except ImportError as e:
    LOGGER.debug(f"Pattern tools not available: {e}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        source = Path(sys.argv[1])
        run_server(source_dir=source)
    else:
        run_server()
