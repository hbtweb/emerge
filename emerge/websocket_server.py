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
