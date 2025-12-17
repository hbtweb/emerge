"""
Language registry that loads definitions from YAML files.
Enables drag-and-drop language support - just add a YAML file to definitions/.
"""

# Authors: Grzegorz Lato <grzegorz.lato@gmail.com>
# License: MIT

from pathlib import Path
from typing import Dict, List, Optional, Set, Any
import re
import logging

import yaml
import coloredlogs

from emerge.log import Logger

LOGGER = Logger(logging.getLogger('registry'))
coloredlogs.install(level='E', logger=LOGGER.logger(), fmt=Logger.log_format)


class LanguageDefinition:
    """Parsed language definition from YAML."""

    def __init__(self, data: dict):
        self.name: str = data['name']
        self.display_name: str = data.get('display_name', self.name.title())
        self.extensions: List[str] = data['extensions']
        self.comments: Dict[str, str] = data.get('comments', {})
        self.token_mappings: Dict[str, str] = data.get('token_mappings', {})
        self.patterns: Dict[str, Any] = data.get('patterns', {})
        self.tfidf_stopwords: Set[str] = set(data.get('tfidf_stopwords', []))

        # Compile regex patterns for performance
        self._compiled_patterns: Dict[str, Any] = {}
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Pre-compile all regex patterns for performance."""
        for category, patterns in self.patterns.items():
            if isinstance(patterns, list):
                # List of pattern definitions (imports, entities)
                self._compiled_patterns[category] = []
                for p in patterns:
                    if isinstance(p, dict) and 'regex' in p:
                        compiled_pattern = {**p, 'compiled': re.compile(p['regex'])}
                        self._compiled_patterns[category].append(compiled_pattern)
            elif isinstance(patterns, dict):
                # Dict of pattern definitions (inheritance, module)
                if 'regex' in patterns:
                    # Single pattern like module
                    self._compiled_patterns[category] = {
                        **patterns,
                        'compiled': re.compile(patterns['regex'])
                    }
                else:
                    # Nested patterns like inheritance
                    self._compiled_patterns[category] = {}
                    for key, pattern in patterns.items():
                        if isinstance(pattern, dict) and 'regex' in pattern:
                            self._compiled_patterns[category][key] = {
                                **pattern,
                                'compiled': re.compile(pattern['regex'])
                            }

    def get_compiled_patterns(self, category: str) -> Any:
        """Get pre-compiled patterns for a category."""
        return self._compiled_patterns.get(category, [])

    def __repr__(self) -> str:
        return f"LanguageDefinition({self.name}, extensions={self.extensions})"


class LanguageRegistry:
    """
    Registry for language definitions.
    Loads YAML files from definitions/ directory on initialization.
    Singleton pattern ensures definitions are loaded once.
    """

    _instance: Optional['LanguageRegistry'] = None
    _languages: Dict[str, LanguageDefinition] = {}
    _extension_map: Dict[str, str] = {}  # .dart -> dart
    _initialized: bool = False

    def __new__(cls) -> 'LanguageRegistry':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def initialize(self, definitions_dir: Optional[Path] = None) -> None:
        """Load all language definitions from directory."""
        if self._initialized:
            return

        if definitions_dir is None:
            definitions_dir = Path(__file__).parent / 'definitions'

        if not definitions_dir.exists():
            LOGGER.warning(f'Definitions directory not found: {definitions_dir}')
            self._initialized = True
            return

        for yaml_file in definitions_dir.glob('*.yaml'):
            try:
                self._load_definition(yaml_file)
            except Exception as e:
                LOGGER.error(f'Failed to load {yaml_file}: {e}')

        self._initialized = True
        LOGGER.info(f'Loaded {len(self._languages)} language definitions from registry')

    def _load_definition(self, yaml_file: Path) -> None:
        """Load a single language definition from YAML file."""
        with open(yaml_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        if data is None:
            LOGGER.warning(f'Empty YAML file: {yaml_file}')
            return

        lang_def = LanguageDefinition(data)
        self._languages[lang_def.name] = lang_def

        # Build extension map
        for ext in lang_def.extensions:
            self._extension_map[ext] = lang_def.name

        LOGGER.debug(f'Loaded language definition: {lang_def.name}')

    def get_language(self, name: str) -> Optional[LanguageDefinition]:
        """Get language definition by name."""
        return self._languages.get(name)

    def get_language_for_extension(self, ext: str) -> Optional[LanguageDefinition]:
        """Get language definition by file extension."""
        lang_name = self._extension_map.get(ext)
        if lang_name:
            return self._languages.get(lang_name)
        return None

    def list_languages(self) -> List[str]:
        """List all registered language names."""
        return list(self._languages.keys())

    def list_extensions(self) -> List[str]:
        """List all registered file extensions."""
        return list(self._extension_map.keys())

    def detect_languages(self, path: Path) -> Set[str]:
        """Detect languages used in a directory by scanning file extensions."""
        languages: Set[str] = set()
        for file in path.rglob('*'):
            if file.is_file():
                ext = file.suffix.lower()
                if ext in self._extension_map:
                    languages.add(self._extension_map[ext])
        return languages

    def get_all_tfidf_stopwords(self) -> Dict[str, Set[str]]:
        """Get TF-IDF stopwords for all languages, keyed by uppercase name."""
        return {
            name.upper(): lang.tfidf_stopwords
            for name, lang in self._languages.items()
        }

    def has_language(self, name: str) -> bool:
        """Check if a language is registered."""
        return name in self._languages

    def reset(self) -> None:
        """Reset the registry (mainly for testing)."""
        self._languages = {}
        self._extension_map = {}
        self._initialized = False


def get_registry() -> LanguageRegistry:
    """Get the singleton registry instance, initializing if needed."""
    registry = LanguageRegistry()
    registry.initialize()
    return registry
