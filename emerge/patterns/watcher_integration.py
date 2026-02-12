"""Pattern watcher integration for hot-reloading custom patterns."""

import logging
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List
from dataclasses import dataclass

import coloredlogs

from emerge.log import Logger
from emerge.patterns.loader import PatternLoader, PATTERNS_FILE
from emerge.patterns.config import PatternConfig

LOGGER = Logger(logging.getLogger('patterns.watcher'))
coloredlogs.install(level='E', logger=LOGGER.logger(), fmt=Logger.log_format)


@dataclass
class PatternChange:
    """Represents a change to pattern configuration."""
    change_type: str  # 'loaded', 'reloaded', 'error'
    patterns_added: int = 0
    patterns_removed: int = 0
    patterns_modified: int = 0
    error: Optional[str] = None


class PatternWatcherMixin:
    """
    Mixin to add pattern hot-reload support to GraphWatcher.
    
    Usage:
        class EnhancedWatcher(PatternWatcherMixin, GraphWatcher):
            pass
        
        watcher = EnhancedWatcher(source_dir)
        watcher.set_pattern_callback(on_patterns_changed)
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pattern_loader: Optional[PatternLoader] = None
        self._pattern_config: Optional[PatternConfig] = None
        self._pattern_callbacks: List[Callable[[PatternChange], None]] = []
    
    def init_patterns(self, project_root: Path) -> Optional[PatternConfig]:
        """Initialize pattern loading for a project."""
        self._pattern_loader = PatternLoader(project_root)
        self._pattern_config = self._pattern_loader.load()
        
        if self._pattern_config:
            LOGGER.info(f'Loaded {len(self._pattern_config.patterns)} custom patterns')
        
        return self._pattern_config
    
    def add_pattern_callback(self, callback: Callable[[PatternChange], None]) -> None:
        """Add a callback for pattern changes."""
        self._pattern_callbacks.append(callback)
    
    def remove_pattern_callback(self, callback: Callable[[PatternChange], None]) -> None:
        """Remove a pattern change callback."""
        if callback in self._pattern_callbacks:
            self._pattern_callbacks.remove(callback)
    
    def _notify_pattern_change(self, change: PatternChange) -> None:
        """Notify all callbacks of a pattern change."""
        for callback in self._pattern_callbacks:
            try:
                callback(change)
            except Exception as e:
                LOGGER.error(f'Pattern callback error: {e}')
    
    def check_pattern_file_change(self, file_path: Path) -> bool:
        """
        Check if a file change affects patterns.
        
        Returns True if patterns were reloaded.
        """
        # Check if this is the patterns file
        if file_path.name == 'patterns.yaml' and '.emerge' in str(file_path):
            return self._reload_patterns()
        return False
    
    def _reload_patterns(self) -> bool:
        """Reload patterns from file."""
        if self._pattern_loader is None:
            return False
        
        old_config = self._pattern_config
        old_patterns = set(p.id for p in old_config.patterns) if old_config else set()
        
        try:
            new_config = self._pattern_loader.reload()
            
            if new_config is None:
                change = PatternChange(
                    change_type='error',
                    error='Failed to reload patterns - check YAML syntax'
                )
                self._notify_pattern_change(change)
                return False
            
            new_patterns = set(p.id for p in new_config.patterns)
            
            # Calculate diff
            added = len(new_patterns - old_patterns)
            removed = len(old_patterns - new_patterns)
            # Modified = patterns that exist in both but may have changed
            common = old_patterns & new_patterns
            modified = len(common)  # Simplified - assume all common patterns modified
            
            self._pattern_config = new_config
            
            change = PatternChange(
                change_type='reloaded',
                patterns_added=added,
                patterns_removed=removed,
                patterns_modified=modified
            )
            
            LOGGER.info(f'Patterns reloaded: +{added} -{removed} ~{modified}')
            self._notify_pattern_change(change)
            
            return True
            
        except Exception as e:
            LOGGER.error(f'Pattern reload error: {e}')
            change = PatternChange(
                change_type='error',
                error=str(e)
            )
            self._notify_pattern_change(change)
            return False
    
    @property
    def pattern_config(self) -> Optional[PatternConfig]:
        """Get the current pattern configuration."""
        return self._pattern_config


def integrate_patterns_with_watcher(watcher, project_root: Path) -> Optional[PatternConfig]:
    """
    Integrate pattern support into an existing watcher.
    
    This is a simple integration that adds pattern awareness to
    the watcher's file change handling.
    
    Args:
        watcher: GraphWatcher instance
        project_root: Project root directory
        
    Returns:
        PatternConfig if patterns were loaded, None otherwise
    """
    loader = PatternLoader(project_root)
    config = loader.load()
    
    if config is None:
        return None
    
    # Store pattern state on watcher
    watcher._pattern_loader = loader
    watcher._pattern_config = config
    
    # Wrap the watcher's change handler to check for pattern file changes
    original_handler = getattr(watcher, '_handle_change', None)
    
    if original_handler:
        def enhanced_handler(change):
            # Check if this is a pattern file change
            if change.path.name == 'patterns.yaml':
                LOGGER.info('Patterns file changed - reloading')
                watcher._pattern_config = loader.reload()
            
            # Call original handler
            return original_handler(change)
        
        watcher._handle_change = enhanced_handler
    
    LOGGER.info(f'Pattern integration complete: {len(config.patterns)} patterns')
    return config
