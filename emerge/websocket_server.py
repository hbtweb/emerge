"""
WebSocket server for real-time D3 graph updates.
Broadcasts graph changes to connected browser clients.
"""

# Authors: Grzegorz Lato <grzegorz.lato@gmail.com>
# License: MIT

import asyncio
import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any, Set, List, Callable
from dataclasses import dataclass, asdict
from enum import Enum

import networkx as nx
import coloredlogs
import websockets
from websockets.server import WebSocketServerProtocol

from emerge.log import Logger
from emerge.watcher import GraphWatcher, GraphUpdate, ChangeType

LOGGER = Logger(logging.getLogger('websocket'))
coloredlogs.install(level='E', logger=LOGGER.logger(), fmt=Logger.log_format)


class MessageType(str, Enum):
    """WebSocket message types."""
    GRAPH_UPDATE = "graph_update"
    FULL_GRAPH = "full_graph"
    METRICS = "metrics"
    ERROR = "error"
    CONNECTED = "connected"
    SUBSCRIBE = "subscribe"
    GET_GRAPH = "get_graph"
    GET_NODE = "get_node"
    GET_METRICS = "get_metrics"
    # New message types for unified viewer
    GET_STATISTICS = "get_statistics"
    GET_CLUSTERS = "get_clusters"
    GET_CONFIG = "get_config"
    SEARCH_NODES = "search_nodes"
    STATISTICS = "statistics"
    CLUSTERS = "clusters"
    CONFIG = "config"
    SEARCH_RESULTS = "search_results"


@dataclass
class WebSocketMessage:
    """Standard message format."""
    type: MessageType
    data: Dict[str, Any]
    timestamp: Optional[float] = None


class GraphWebSocketServer:
    """
    WebSocket server for broadcasting graph updates to D3 clients.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8765,
        graphs: Optional[Dict[str, nx.DiGraph]] = None
    ):
        self.host = host
        self.port = port
        self.graphs = graphs or {}
        self._clients: Set[WebSocketServerProtocol] = set()
        self._server = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def set_graphs(self, graphs: Dict[str, nx.DiGraph]) -> None:
        """Update the graphs being served."""
        self.graphs = graphs

    async def _handler(self, websocket: WebSocketServerProtocol) -> None:
        """Handle a WebSocket connection."""
        self._clients.add(websocket)
        client_id = id(websocket)
        LOGGER.info(f'Client connected: {client_id}')

        try:
            await self._send(websocket, WebSocketMessage(
                type=MessageType.CONNECTED,
                data={"client_id": client_id, "graphs": list(self.graphs.keys())}
            ))

            async for message in websocket:
                await self._handle_message(websocket, message)

        except websockets.exceptions.ConnectionClosed:
            LOGGER.info(f'Client disconnected: {client_id}')
        except Exception as e:
            LOGGER.error(f'Client error: {e}')
        finally:
            self._clients.discard(websocket)

    async def _handle_message(self, websocket: WebSocketServerProtocol, message: str) -> None:
        """Handle an incoming message."""
        try:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == MessageType.GET_GRAPH:
                graph_name = data.get("graph", "file_result_dependency_graph")
                await self._send_graph(websocket, graph_name)
            elif msg_type == MessageType.GET_NODE:
                node = data.get("node")
                graph_name = data.get("graph", "file_result_dependency_graph")
                await self._send_node_info(websocket, node, graph_name)
            elif msg_type == MessageType.GET_METRICS:
                await self._send_metrics(websocket)
            elif msg_type == MessageType.GET_STATISTICS:
                graph_name = data.get("graph", "file_result_dependency_graph")
                await self._send_statistics(websocket, graph_name)
            elif msg_type == MessageType.GET_CLUSTERS:
                graph_name = data.get("graph", "file_result_dependency_graph")
                await self._send_clusters(websocket, graph_name)
            elif msg_type == MessageType.GET_CONFIG:
                await self._send_config(websocket)
            elif msg_type == MessageType.SEARCH_NODES:
                query = data.get("query", "")
                graph_name = data.get("graph", "file_result_dependency_graph")
                semantic = data.get("semantic", False)
                await self._send_search_results(websocket, query, graph_name, semantic)
            else:
                await self._send(websocket, WebSocketMessage(
                    type=MessageType.ERROR,
                    data={"error": f"Unknown message type: {msg_type}"}
                ))
        except json.JSONDecodeError as e:
            await self._send(websocket, WebSocketMessage(
                type=MessageType.ERROR,
                data={"error": f"Invalid JSON: {e}"}
            ))

    async def _send(self, websocket: WebSocketServerProtocol, message: WebSocketMessage) -> None:
        """Send a message to a client."""
        try:
            message.timestamp = time.time()
            await websocket.send(json.dumps(asdict(message), default=str))
        except Exception as e:
            LOGGER.error(f'Send error: {e}')

    async def _send_graph(self, websocket: WebSocketServerProtocol, graph_name: str) -> None:
        """Send full graph data to a client."""
        if graph_name not in self.graphs:
            await self._send(websocket, WebSocketMessage(
                type=MessageType.ERROR,
                data={"error": f"Graph not found: {graph_name}"}
            ))
            return

        graph = self.graphs[graph_name]
        nodes = [
            {"id": node, "label": graph.nodes[node].get("display_name", node),
             **{k: v for k, v in graph.nodes[node].items() if k != "display_name"}}
            for node in graph.nodes()
        ]
        links = [{"source": src, "target": tgt} for src, tgt in graph.edges()]

        await self._send(websocket, WebSocketMessage(
            type=MessageType.FULL_GRAPH,
            data={"graph": graph_name, "nodes": nodes, "links": links,
                  "node_count": len(nodes), "link_count": len(links)}
        ))

    async def _send_node_info(self, websocket: WebSocketServerProtocol, node: str, graph_name: str) -> None:
        """Send detailed node information."""
        if graph_name not in self.graphs:
            await self._send(websocket, WebSocketMessage(
                type=MessageType.ERROR, data={"error": f"Graph not found: {graph_name}"}
            ))
            return

        graph = self.graphs[graph_name]
        if node not in graph:
            await self._send(websocket, WebSocketMessage(
                type=MessageType.ERROR, data={"error": f"Node not found: {node}"}
            ))
            return

        attrs = dict(graph.nodes[node])
        in_edges = list(graph.predecessors(node))
        out_edges = list(graph.successors(node))

        await self._send(websocket, WebSocketMessage(
            type=MessageType.METRICS,
            data={"node": node, "attributes": attrs, "fan_in": len(in_edges),
                  "fan_out": len(out_edges), "dependents": in_edges[:50],
                  "dependencies": out_edges[:50]}
        ))

    async def _send_metrics(self, websocket: WebSocketServerProtocol) -> None:
        """Send overall metrics."""
        metrics = {}
        for name, graph in self.graphs.items():
            metrics[name] = {
                "nodes": graph.number_of_nodes(),
                "edges": graph.number_of_edges(),
                "density": round(nx.density(graph), 4) if graph.number_of_nodes() > 1 else 0
            }
        await self._send(websocket, WebSocketMessage(type=MessageType.METRICS, data={"graphs": metrics}))

    async def _send_statistics(self, websocket: WebSocketServerProtocol, graph_name: str) -> None:
        """Send detailed statistics for a graph (compatible with traditional viewer)."""
        if graph_name not in self.graphs:
            await self._send(websocket, WebSocketMessage(
                type=MessageType.ERROR, data={"error": f"Graph not found: {graph_name}"}
            ))
            return

        graph = self.graphs[graph_name]
        n_nodes = graph.number_of_nodes()
        n_edges = graph.number_of_edges()

        # Calculate statistics like the traditional viewer expects
        in_degrees = [d for _, d in graph.in_degree()]
        out_degrees = [d for _, d in graph.out_degree()]

        stats = {
            "number_of_nodes": n_nodes,
            "number_of_edges": n_edges,
            "average_in_degree": round(sum(in_degrees) / n_nodes, 2) if n_nodes > 0 else 0,
            "average_out_degree": round(sum(out_degrees) / n_nodes, 2) if n_nodes > 0 else 0,
            "max_in_degree": max(in_degrees) if in_degrees else 0,
            "max_out_degree": max(out_degrees) if out_degrees else 0,
            "density": round(nx.density(graph), 4) if n_nodes > 1 else 0,
            "is_dag": nx.is_directed_acyclic_graph(graph),
        }

        # Try to compute connected components (for weakly connected)
        try:
            n_components = nx.number_weakly_connected_components(graph)
            stats["number_of_connected_components"] = n_components
        except Exception:
            stats["number_of_connected_components"] = 1

        await self._send(websocket, WebSocketMessage(
            type=MessageType.STATISTICS,
            data={"graph": graph_name, "statistics": stats}
        ))

    async def _send_clusters(self, websocket: WebSocketServerProtocol, graph_name: str) -> None:
        """Send cluster/community data (Louvain modularity)."""
        if graph_name not in self.graphs:
            await self._send(websocket, WebSocketMessage(
                type=MessageType.ERROR, data={"error": f"Graph not found: {graph_name}"}
            ))
            return

        graph = self.graphs[graph_name]
        clusters = {}
        cluster_metrics = {}

        # Group nodes by their modularity metric if present
        modularity_key = None
        for key in ['metric_file_result_dependency_graph_louvain_modularity_in_file',
                    'metric_entity_result_dependency_graph_louvain_modularity_in_entity',
                    'metric_entity_result_inheritance_graph_louvain_modularity_in_entity',
                    'metric_entity_result_complete_graph_louvain_modularity_in_entity']:
            sample_node = next(iter(graph.nodes()), None)
            if sample_node and key in graph.nodes.get(sample_node, {}):
                modularity_key = key
                break

        if modularity_key:
            for node in graph.nodes():
                attrs = graph.nodes[node]
                cluster_id = str(attrs.get(modularity_key, 0))
                if cluster_id not in clusters:
                    clusters[cluster_id] = []
                clusters[cluster_id].append(node)

            # Calculate cluster metrics
            for cluster_id, members in clusters.items():
                subgraph = graph.subgraph(members)
                cluster_metrics[cluster_id] = {
                    "node_count": len(members),
                    "edge_count": subgraph.number_of_edges(),
                    "density": round(nx.density(subgraph), 4) if len(members) > 1 else 0
                }
        else:
            # No modularity computed, return single cluster
            clusters["0"] = list(graph.nodes())[:100]  # Limit for large graphs
            cluster_metrics["0"] = {
                "node_count": graph.number_of_nodes(),
                "edge_count": graph.number_of_edges()
            }

        await self._send(websocket, WebSocketMessage(
            type=MessageType.CLUSTERS,
            data={"graph": graph_name, "clusters": clusters, "cluster_metrics": cluster_metrics}
        ))

    async def _send_config(self, websocket: WebSocketServerProtocol) -> None:
        """Send analysis configuration (for heatmap, metrics, etc.)."""
        # Default config matching traditional viewer expectations
        config = {
            "emerge_version": "2.0.0-mcp",
            "project_name": "Project",
            "analysis_name": "MCP Analysis",
            "analysis_date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "metrics": {
                "radius_multiplication": {
                    "metric_sloc_in_file": 0.02,
                    "metric_sloc_in_entity": 0.02,
                    "metric_number_of_methods_in_file": 0.5,
                    "metric_number_of_methods_in_entity": 0.5,
                    "metric_fan_in_dependency_graph": 1.0,
                    "metric_fan_out_dependency_graph": 1.0,
                    "metric_ws_complexity_in_file": 0.01,
                    "metric_git_code_churn": 0.005,
                    "metric_git_ws_complexity": 0.01,
                    "metric_git_sloc": 0.01,
                    "metric_git_number_authors": 2.0
                }
            },
            "heatmap": {
                "score": {"base": 10, "limit": 500},
                "metrics": {
                    "active": {"sloc": True, "fan_out": True},
                    "weights": {"sloc": 0.3, "fan_out": 5.0}
                }
            },
            "churn_heatmap": {
                "score": {"base": 10, "limit": 500},
                "metrics": {
                    "active": {"churn": True},
                    "weights": {"churn": 0.1}
                }
            },
            "hotspot_heatmap": {
                "score": {"base": 10, "limit": 500},
                "metrics": {
                    "active": {"churn": True, "ws_complexity": True},
                    "weights": {"churn": 0.05, "ws_complexity": 0.01}
                }
            }
        }

        await self._send(websocket, WebSocketMessage(
            type=MessageType.CONFIG,
            data={"config": config}
        ))

    async def _send_search_results(
        self,
        websocket: WebSocketServerProtocol,
        query: str,
        graph_name: str,
        semantic: bool = False
    ) -> None:
        """Search nodes by name or semantic tags."""
        if graph_name not in self.graphs:
            await self._send(websocket, WebSocketMessage(
                type=MessageType.ERROR, data={"error": f"Graph not found: {graph_name}"}
            ))
            return

        if not query or len(query) < 2:
            await self._send(websocket, WebSocketMessage(
                type=MessageType.SEARCH_RESULTS,
                data={"graph": graph_name, "query": query, "results": [], "count": 0}
            ))
            return

        graph = self.graphs[graph_name]
        query_lower = query.lower()
        results = []

        for node in graph.nodes():
            # Basic name search
            if query_lower in node.lower():
                results.append({
                    "id": node,
                    "match_type": "name",
                    "label": graph.nodes[node].get("display_name", node)
                })
            elif semantic:
                # Search in semantic tags if available
                attrs = graph.nodes[node]
                tags = attrs.get("metric_tag_tfidf", [])
                if isinstance(tags, list) and any(query_lower in str(tag).lower() for tag in tags):
                    results.append({
                        "id": node,
                        "match_type": "semantic",
                        "label": graph.nodes[node].get("display_name", node)
                    })

            if len(results) >= 100:  # Limit results
                break

        await self._send(websocket, WebSocketMessage(
            type=MessageType.SEARCH_RESULTS,
            data={"graph": graph_name, "query": query, "results": results, "count": len(results)}
        ))

    async def broadcast(self, message: WebSocketMessage) -> None:
        """Broadcast a message to all connected clients."""
        if not self._clients:
            return
        message.timestamp = time.time()
        payload = json.dumps(asdict(message), default=str)
        await asyncio.gather(*[client.send(payload) for client in self._clients], return_exceptions=True)

    def broadcast_update(self, update: GraphUpdate) -> None:
        """Broadcast a graph update (called from watcher)."""
        if not self._running or not self._loop:
            return

        message = WebSocketMessage(
            type=MessageType.GRAPH_UPDATE,
            data={
                "change_type": update.change_type.name,
                "node": update.node,
                "old_node": update.old_node,
                "added_edges": [{"source": s, "target": t} for s, t in update.added_edges],
                "removed_edges": [{"source": s, "target": t} for s, t in update.removed_edges],
                "metrics": update.metrics
            }
        )
        asyncio.run_coroutine_threadsafe(self.broadcast(message), self._loop)

    async def _run_server(self) -> None:
        """Run the WebSocket server."""
        async with websockets.serve(self._handler, self.host, self.port):
            LOGGER.info(f'WebSocket server running on ws://{self.host}:{self.port}')
            self._running = True
            while self._running:
                await asyncio.sleep(1)

    def start(self) -> None:
        """Start the WebSocket server in a background thread."""
        if self._running:
            return

        def run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self._run_server())
            finally:
                self._loop.close()

        self._thread = threading.Thread(target=run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the WebSocket server."""
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        LOGGER.info('WebSocket server stopped')

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()


D3_CLIENT_JS = """
class EmergeWebSocket {
    constructor(url = 'ws://localhost:8765') {
        this.url = url;
        this.ws = null;
        this.listeners = new Map();
        this.reconnectAttempts = 0;
    }

    connect() {
        this.ws = new WebSocket(this.url);
        this.ws.onopen = () => { this.reconnectAttempts = 0; this.emit('connected'); };
        this.ws.onmessage = (e) => { const m = JSON.parse(e.data); this.emit(m.type, m.data); };
        this.ws.onclose = () => { this.emit('disconnected'); this.attemptReconnect(); };
        this.ws.onerror = (e) => this.emit('error', e);
    }

    attemptReconnect() {
        if (this.reconnectAttempts < 5) {
            this.reconnectAttempts++;
            setTimeout(() => this.connect(), 2000 * this.reconnectAttempts);
        }
    }

    send(type, data = {}) {
        if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type, ...data }));
        }
    }

    getGraph(name = 'file_result_dependency_graph') { this.send('get_graph', { graph: name }); }
    getNode(node, graph) { this.send('get_node', { node, graph }); }
    getMetrics() { this.send('get_metrics'); }

    on(event, cb) {
        if (!this.listeners.has(event)) this.listeners.set(event, []);
        this.listeners.get(event).push(cb);
        return () => this.off(event, cb);
    }

    off(event, cb) {
        const cbs = this.listeners.get(event);
        if (cbs) { const i = cbs.indexOf(cb); if (i > -1) cbs.splice(i, 1); }
    }

    emit(event, data) { (this.listeners.get(event) || []).forEach(cb => cb(data)); }
    disconnect() { this.ws?.close(); this.ws = null; }
}
"""


def get_d3_client_js() -> str:
    """Get the JavaScript client code for D3 integration."""
    return D3_CLIENT_JS


def run_live_server(
    source_dir: Path,
    graphs: Dict[str, nx.DiGraph],
    host: str = "localhost",
    port: int = 8765
) -> tuple:
    """Start both watcher and WebSocket server for live updates."""
    ws_server = GraphWebSocketServer(host=host, port=port, graphs=graphs)
    ws_server.start()

    watcher = GraphWatcher(source_dir)
    watcher.graphs = graphs
    watcher.add_listener(ws_server.broadcast_update)
    watcher.start()

    LOGGER.info(f'Live server running: ws://{host}:{port}')
    return watcher, ws_server


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765

    G = nx.DiGraph()
    G.add_edge("main.py", "utils.py")
    G.add_edge("main.py", "config.py")

    server = GraphWebSocketServer(port=port, graphs={"test_graph": G})
    try:
        server.start()
        print(f"WebSocket server running on ws://localhost:{port}")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
