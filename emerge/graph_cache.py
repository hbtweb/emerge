"""
Graph persistence using pickle.
Caches analysis results to skip expensive rebuilds when source unchanged.
"""

# Authors: Grzegorz Lato <grzegorz.lato@gmail.com>
# License: MIT

import pickle
import hashlib
import logging
from pathlib import Path
from typing import Optional, Dict, Any, Set
from dataclasses import dataclass
from datetime import datetime

import networkx as nx
import coloredlogs

from emerge.log import Logger

LOGGER = Logger(logging.getLogger('graph_cache'))
coloredlogs.install(level='E', logger=LOGGER.logger(), fmt=Logger.log_format)


@dataclass
class CachedAnalysis:
    """Container for cached analysis data."""
    source_hash: str
    timestamp: datetime
    graphs: Dict[str, nx.DiGraph]
    local_metrics: Dict[str, Dict[str, Any]]
    overall_metrics: Dict[str, Any]
    statistics: Dict[str, Any]
    file_results: Dict[str, Any]
    entity_results: Dict[str, Any]


class GraphCache:
    """
    Persistent cache for emerge analysis results.

    Uses content-addressable storage:
    - Hash of source files (mtime + size) determines cache validity
    - Pickle serialization for networkx graphs
    - Automatic invalidation on source changes
    """

    CACHE_VERSION = 1  # Bump when format changes

    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Initialize the graph cache.

        Args:
            cache_dir: Directory for cache files. Defaults to .emerge_cache/
        """
        self.cache_dir = cache_dir or Path('.emerge_cache')
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_file = self.cache_dir / 'analysis.pkl'
        self._hash_file = self.cache_dir / 'source.hash'

    def compute_source_hash(
        self,
        source_dir: Path,
        extensions: Set[str],
        ignore_dirs: Optional[Set[str]] = None
    ) -> str:
        """
        Compute hash of source files based on mtime and size.

        Args:
            source_dir: Root directory to scan
            extensions: File extensions to include (e.g., {'.py', '.java'})
            ignore_dirs: Directories to skip

        Returns:
            SHA256 hash string
        """
        ignore_dirs = ignore_dirs or {
            'node_modules', '.git', '__pycache__', '.idea',
            'build', 'dist', '.gradle', 'target', 'vendor',
            '.dart_tool', '.pub-cache', '.venv', 'venv'
        }

        hasher = hashlib.sha256()

        # Include cache version in hash
        hasher.update(f"v{self.CACHE_VERSION}".encode())

        file_data = []
        for path in sorted(source_dir.rglob('*')):
            # Skip ignored directories
            if any(ignore_dir in path.parts for ignore_dir in ignore_dirs):
                continue

            if path.is_file() and path.suffix.lower() in extensions:
                stat = path.stat()
                file_data.append(f"{path}:{stat.st_mtime}:{stat.st_size}")

        for entry in file_data:
            hasher.update(entry.encode())

        return hasher.hexdigest()

    def save(self, analysis: 'Analysis', source_hash: str) -> None:
        """
        Save analysis results to cache.

        Args:
            analysis: The Analysis object to cache
            source_hash: Hash of source files for validation
        """
        try:
            # Extract graphs from analysis
            graphs = {}
            for name, repr in analysis.graph_representations.items():
                if repr is not None:
                    graphs[name] = repr.digraph

            cached = CachedAnalysis(
                source_hash=source_hash,
                timestamp=datetime.now(),
                graphs=graphs,
                local_metrics=analysis.local_metric_results,
                overall_metrics=analysis.overall_metric_results,
                statistics=analysis.get_statistics(),
                file_results={k: self._serialize_result(v) for k, v in analysis.file_results.items()},
                entity_results={k: self._serialize_result(v) for k, v in analysis.entity_results.items()}
            )

            with open(self._cache_file, 'wb') as f:
                pickle.dump(cached, f, protocol=pickle.HIGHEST_PROTOCOL)

            with open(self._hash_file, 'w') as f:
                f.write(source_hash)

            LOGGER.info(f'Saved analysis cache ({len(graphs)} graphs)')

        except Exception as e:
            LOGGER.error(f'Failed to save cache: {e}')

    def _serialize_result(self, result: Any) -> Dict[str, Any]:
        """Serialize an AbstractResult to a dictionary."""
        return {
            'unique_name': result.unique_name,
            'absolute_name': getattr(result, 'absolute_name', None),
            'display_name': getattr(result, 'display_name', None),
            'scanned_import_dependencies': list(getattr(result, 'scanned_import_dependencies', [])),
            'scanned_inheritance_dependencies': list(getattr(result, 'scanned_inheritance_dependencies', []))
        }

    def load(self, current_hash: str) -> Optional[CachedAnalysis]:
        """
        Load analysis from cache if hash matches.

        Args:
            current_hash: Current source hash to validate against

        Returns:
            CachedAnalysis if valid cache exists, None otherwise
        """
        if not self._cache_file.exists():
            LOGGER.info('No cache file found')
            return None

        if not self._hash_file.exists():
            LOGGER.info('No hash file found')
            return None

        try:
            with open(self._hash_file, 'r') as f:
                cached_hash = f.read().strip()

            if cached_hash != current_hash:
                LOGGER.info('Source changed, cache invalidated')
                return None

            with open(self._cache_file, 'rb') as f:
                cached = pickle.load(f)

            if not isinstance(cached, CachedAnalysis):
                LOGGER.warning('Invalid cache format')
                return None

            if cached.source_hash != current_hash:
                LOGGER.info('Cache hash mismatch')
                return None

            age = datetime.now() - cached.timestamp
            LOGGER.info(f'Loaded cache (age: {age}, {len(cached.graphs)} graphs)')
            return cached

        except Exception as e:
            LOGGER.error(f'Failed to load cache: {e}')
            return None

    def invalidate(self) -> None:
        """Force invalidate the cache."""
        try:
            if self._cache_file.exists():
                self._cache_file.unlink()
            if self._hash_file.exists():
                self._hash_file.unlink()
            LOGGER.info('Cache invalidated')
        except Exception as e:
            LOGGER.error(f'Failed to invalidate cache: {e}')

    def get_cache_info(self) -> Optional[Dict[str, Any]]:
        """Get information about the current cache."""
        if not self._cache_file.exists():
            return None

        try:
            stat = self._cache_file.stat()
            with open(self._cache_file, 'rb') as f:
                cached = pickle.load(f)

            return {
                'size_bytes': stat.st_size,
                'timestamp': cached.timestamp.isoformat(),
                'source_hash': cached.source_hash[:16] + '...',
                'num_graphs': len(cached.graphs),
                'graph_names': list(cached.graphs.keys())
            }
        except Exception:
            return None


# Module-level cache instance
_cache: Optional[GraphCache] = None


def get_cache(cache_dir: Optional[Path] = None) -> GraphCache:
    """Get the singleton cache instance."""
    global _cache
    if _cache is None:
        _cache = GraphCache(cache_dir)
    return _cache