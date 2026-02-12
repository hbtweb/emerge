"""
Emerge constants - single source of truth for configuration values.
"""

# Cache directory name (created in project root during analysis)
EMERGE_CACHE_DIR = '.emerge'

# Default directories to ignore during scanning
DEFAULT_IGNORE_DIRS = frozenset({
    'node_modules', '.git', '__pycache__', '.idea',
    'build', 'dist', '.gradle', 'target', 'vendor',
    '.dart_tool', '.pub-cache', '.venv', 'venv',
    EMERGE_CACHE_DIR  # Always ignore our own cache directory
})
