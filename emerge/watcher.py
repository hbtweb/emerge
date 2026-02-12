"""
File system watcher for incremental graph updates.
Uses watchdog to monitor source changes and update graphs in real-time.
"""

# Authors: Grzegorz Lato <grzegorz.lato@gmail.com>
# License: MIT

import logging
import threading
import time
from pathlib import Path
from typing import Optional, Set, Callable, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum, auto

import coloredlogs
from watchdog.observers import Observer
from watchdog.events import (
    FileSystemEventHandler,
    FileCreatedEvent,
    FileModifiedEvent,
    FileDeletedEvent,
    FileMovedEvent,
    DirCreatedEvent,
    DirDeletedEvent,
    DirMovedEvent
)

from emerge.log import Logger
from emerge.languages.registry import get_registry
from emerge.constants import DEFAULT_IGNORE_DIRS

LOGGER = Logger(logging.getLogger('watcher'))
coloredlogs.install(level='E', logger=LOGGER.logger(), fmt=Logger.log_format)


class ChangeType(Enum):
    """Type of file system change."""
    CREATED = auto()
    MODIFIED = auto()
    DELETED = auto()
    MOVED = auto()


@dataclass
class FileChange:
    """Represents a file system change event."""
    change_type: ChangeType
    path: Path
    old_path: Optional[Path] = None  # For moves
    timestamp: float = field(default_factory=time.time)


@dataclass
class GraphUpdate:
    """Represents an update to the dependency graph."""
    change_type: ChangeType
    node: str
    old_node: Optional[str] = None  # For renames
    added_edges: List[tuple] = field(default_factory=list)
    removed_edges: List[tuple] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)


class SourceFileHandler(FileSystemEventHandler):
    """
    Handles file system events for source code files.
    Filters by extension and debounces rapid changes.
    """

    def __init__(
        self,
        extensions: Set[str],
        ignore_dirs: Set[str],
        on_change: Callable[[FileChange], None],
        debounce_ms: int = 100
    ):
        """
        Initialize the file handler.

        Args:
            extensions: File extensions to watch (e.g., {'.py', '.java'})
            ignore_dirs: Directories to ignore
            on_change: Callback for file changes
            debounce_ms: Debounce window in milliseconds
        """
        super().__init__()
        self.extensions = extensions
        self.ignore_dirs = ignore_dirs
        self.on_change = on_change
        self.debounce_ms = debounce_ms

        # Debouncing state
        self._pending: Dict[str, FileChange] = {}
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None

    def _should_process(self, path: str) -> bool:
        """Check if the path should be processed."""
        p = Path(path)

        # Check extension
        if p.suffix.lower() not in self.extensions:
            return False

        # Check ignored directories
        for ignore in self.ignore_dirs:
            if ignore in p.parts:
                return False

        return True

    def _queue_change(self, change: FileChange) -> None:
        """Queue a change with debouncing."""
        with self._lock:
            key = str(change.path)
            self._pending[key] = change

            # Reset debounce timer
            if self._timer:
                self._timer.cancel()

            self._timer = threading.Timer(
                self.debounce_ms / 1000.0,
                self._flush_pending
            )
            self._timer.start()

    def _flush_pending(self) -> None:
        """Flush pending changes to callback."""
        with self._lock:
            for change in self._pending.values():
                try:
                    self.on_change(change)
                except Exception as e:
                    LOGGER.error(f'Error handling change {change.path}: {e}')
            self._pending.clear()

    def on_created(self, event):
        if isinstance(event, DirCreatedEvent):
            return
        if not self._should_process(event.src_path):
            return

        change = FileChange(
            change_type=ChangeType.CREATED,
            path=Path(event.src_path)
        )
        LOGGER.debug(f'File created: {event.src_path}')
        self._queue_change(change)

    def on_modified(self, event):
        if isinstance(event, DirCreatedEvent):
            return
        if not self._should_process(event.src_path):
            return

        change = FileChange(
            change_type=ChangeType.MODIFIED,
            path=Path(event.src_path)
        )
        LOGGER.debug(f'File modified: {event.src_path}')
        self._queue_change(change)

    def on_deleted(self, event):
        if isinstance(event, DirDeletedEvent):
            return
        if not self._should_process(event.src_path):
            return

        change = FileChange(
            change_type=ChangeType.DELETED,
            path=Path(event.src_path)
        )
        LOGGER.debug(f'File deleted: {event.src_path}')
        self._queue_change(change)

    def on_moved(self, event):
        if isinstance(event, DirMovedEvent):
            return

        src_valid = self._should_process(event.src_path)
        dst_valid = self._should_process(event.dest_path)

        if not src_valid and not dst_valid:
            return

        if src_valid and dst_valid:
            # Real move within watched extensions
            change = FileChange(
                change_type=ChangeType.MOVED,
                path=Path(event.dest_path),
                old_path=Path(event.src_path)
            )
        elif src_valid:
            # Moved out of watched extensions (treat as delete)
            change = FileChange(
                change_type=ChangeType.DELETED,
                path=Path(event.src_path)
            )
        else:
            # Moved into watched extensions (treat as create)
            change = FileChange(
                change_type=ChangeType.CREATED,
                path=Path(event.dest_path)
            )

        LOGGER.debug(f'File moved: {event.src_path} -> {event.dest_path}')
        self._queue_change(change)


class GraphWatcher:
    """
    Watches source directory and updates graphs incrementally.

    Features:
    - Debounced file system events
    - Incremental graph updates (add/remove nodes and edges)
    - Listener notification for WebSocket broadcast
    - Thread-safe operation
    """

    def __init__(
        self,
        source_dir: Path,
        extensions: Optional[Set[str]] = None,
        ignore_dirs: Optional[Set[str]] = None
    ):
        """
        Initialize the graph watcher.

        Args:
            source_dir: Directory to watch
            extensions: File extensions to watch. Auto-detected if None.
            ignore_dirs: Directories to ignore
        """
        self.source_dir = Path(source_dir).resolve()
        self.ignore_dirs = ignore_dirs or set(DEFAULT_IGNORE_DIRS)

        # Auto-detect extensions from registry if not specified
        if extensions is None:
            registry = get_registry()
            self.extensions = set(registry.list_extensions())
        else:
            self.extensions = extensions

        self._observer: Optional[Observer] = None
        self._running = False
        self._listeners: List[Callable[[GraphUpdate], None]] = []
        self._lock = threading.Lock()

        # Graph reference (set by caller)
        self.graphs: Dict[str, 'nx.DiGraph'] = {}
        self.parser = None  # GenericParser instance for reparsing

    def add_listener(self, callback: Callable[[GraphUpdate], None]) -> None:
        """Add a listener for graph updates."""
        with self._lock:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[GraphUpdate], None]) -> None:
        """Remove a listener."""
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def _notify_listeners(self, update: GraphUpdate) -> None:
        """Notify all listeners of a graph update."""
        with self._lock:
            listeners = list(self._listeners)

        for listener in listeners:
            try:
                listener(update)
            except Exception as e:
                LOGGER.error(f'Listener error: {e}')

    def _handle_change(self, change: FileChange) -> None:
        """Handle a file change and update graphs."""
        LOGGER.info(f'{change.change_type.name}: {change.path}')

        # Calculate relative path for node name
        try:
            rel_path = change.path.relative_to(self.source_dir.parent)
            node_name = str(rel_path)
        except ValueError:
            node_name = str(change.path)

        if change.change_type == ChangeType.DELETED:
            update = self._handle_delete(node_name)
        elif change.change_type == ChangeType.CREATED:
            update = self._handle_create(change.path, node_name)
        elif change.change_type == ChangeType.MODIFIED:
            update = self._handle_modify(change.path, node_name)
        elif change.change_type == ChangeType.MOVED:
            old_rel = change.old_path.relative_to(self.source_dir.parent) if change.old_path else None
            old_node = str(old_rel) if old_rel else None
            update = self._handle_move(change.path, node_name, old_node)
        else:
            return

        if update:
            self._notify_listeners(update)

    def _handle_delete(self, node_name: str) -> Optional[GraphUpdate]:
        """Handle file deletion - remove node and edges."""
        removed_edges = []

        for graph_name, graph in self.graphs.items():
            if node_name in graph:
                # Collect edges before removal
                removed_edges.extend(list(graph.in_edges(node_name)))
                removed_edges.extend(list(graph.out_edges(node_name)))
                graph.remove_node(node_name)
                LOGGER.debug(f'Removed node {node_name} from {graph_name}')

        return GraphUpdate(
            change_type=ChangeType.DELETED,
            node=node_name,
            removed_edges=removed_edges
        )

    def _handle_create(self, path: Path, node_name: str) -> Optional[GraphUpdate]:
        """Handle file creation - parse and add to graphs."""
        if self.parser is None:
            LOGGER.warning('No parser configured, skipping create')
            return None

        try:
            # Read and parse file
            content = path.read_text(encoding='ISO-8859-1')
            dependencies = self._parse_dependencies(path, content)

            added_edges = []
            for graph_name, graph in self.graphs.items():
                if 'dependency' in graph_name.lower():
                    graph.add_node(node_name, display_name=path.name)
                    for dep in dependencies:
                        graph.add_edge(node_name, dep)
                        added_edges.append((node_name, dep))

            return GraphUpdate(
                change_type=ChangeType.CREATED,
                node=node_name,
                added_edges=added_edges
            )
        except Exception as e:
            LOGGER.error(f'Failed to parse {path}: {e}')
            return None

    def _handle_modify(self, path: Path, node_name: str) -> Optional[GraphUpdate]:
        """Handle file modification - reparse and update edges."""
        if self.parser is None:
            LOGGER.warning('No parser configured, skipping modify')
            return None

        try:
            content = path.read_text(encoding='ISO-8859-1')
            new_dependencies = set(self._parse_dependencies(path, content))

            added_edges = []
            removed_edges = []

            for graph_name, graph in self.graphs.items():
                if 'dependency' in graph_name.lower() and node_name in graph:
                    # Get current edges
                    current_deps = set(n for _, n in graph.out_edges(node_name))

                    # Calculate diff
                    to_add = new_dependencies - current_deps
                    to_remove = current_deps - new_dependencies

                    # Apply changes
                    for dep in to_remove:
                        graph.remove_edge(node_name, dep)
                        removed_edges.append((node_name, dep))

                    for dep in to_add:
                        graph.add_node(dep, display_name=dep)  # Ensure target exists
                        graph.add_edge(node_name, dep)
                        added_edges.append((node_name, dep))

            return GraphUpdate(
                change_type=ChangeType.MODIFIED,
                node=node_name,
                added_edges=added_edges,
                removed_edges=removed_edges
            )
        except Exception as e:
            LOGGER.error(f'Failed to parse {path}: {e}')
            return None

    def _handle_move(
        self,
        new_path: Path,
        new_node: str,
        old_node: Optional[str]
    ) -> Optional[GraphUpdate]:
        """Handle file move - rename node in graphs."""
        if old_node is None:
            return self._handle_create(new_path, new_node)

        for graph_name, graph in self.graphs.items():
            if old_node in graph:
                # NetworkX doesn't have rename, so we recreate
                attrs = dict(graph.nodes[old_node])
                in_edges = list(graph.in_edges(old_node))
                out_edges = list(graph.out_edges(old_node))

                graph.remove_node(old_node)
                graph.add_node(new_node, **attrs, display_name=new_path.name)

                for src, _ in in_edges:
                    if src in graph:
                        graph.add_edge(src, new_node)

                for _, dst in out_edges:
                    graph.add_edge(new_node, dst)

        return GraphUpdate(
            change_type=ChangeType.MOVED,
            node=new_node,
            old_node=old_node
        )

    def _parse_dependencies(self, path: Path, content: str) -> List[str]:
        """Parse dependencies from a file using the configured parser."""
        if self.parser is None:
            return []

        # Use generic parser to extract imports
        try:
            results = self.parser.generate_file_result_from_source(
                filename=str(path),
                full_file_path=str(path),
                file_content=content
            )
            if results and hasattr(results, 'scanned_import_dependencies'):
                return list(results.scanned_import_dependencies)
        except Exception as e:
            LOGGER.debug(f'Parse error for {path}: {e}')

        return []

    def start(self) -> None:
        """Start watching for file changes."""
        if self._running:
            LOGGER.warning('Watcher already running')
            return

        handler = SourceFileHandler(
            extensions=self.extensions,
            ignore_dirs=self.ignore_dirs,
            on_change=self._handle_change
        )

        self._observer = Observer()
        self._observer.schedule(handler, str(self.source_dir), recursive=True)
        self._observer.start()
        self._running = True

        LOGGER.info(f'Started watching: {self.source_dir}')
        LOGGER.info(f'Extensions: {", ".join(sorted(self.extensions))}')

    def stop(self) -> None:
        """Stop watching for file changes."""
        if not self._running:
            return

        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None

        self._running = False
        LOGGER.info('Stopped watching')

    def is_running(self) -> bool:
        """Check if the watcher is running."""
        return self._running

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()