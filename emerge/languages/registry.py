"""
Language registry that loads definitions from YAML files.
Enables drag-and-drop language support - just add a YAML file to definitions/.
"""

# Authors: Grzegorz Lato <grzegorz.lato@gmail.com>
# License: MIT

from pathlib import Path
from typing import Dict, List, Optional, Set, Any, Tuple
from dataclasses import dataclass, field
import re
import logging
import json

import yaml
import coloredlogs

from emerge.log import Logger

LOGGER = Logger(logging.getLogger('registry'))
coloredlogs.install(level='E', logger=LOGGER.logger(), fmt=Logger.log_format)


@dataclass
class ManifestConfig:
    """Configuration for a language's package manifest."""
    file: str                                    # Primary manifest filename
    format: str                                  # json, toml, edn, gomod
    fallback: List[str] = field(default_factory=list)  # Fallback filenames
    secondary: Optional[Dict[str, str]] = None  # Secondary config (e.g., tsconfig)
    autoload: Dict[str, Any] = field(default_factory=dict)
    module_resolution: Dict[str, Any] = field(default_factory=dict)
    path_aliases: Dict[str, str] = field(default_factory=dict)
    source_paths: Dict[str, Any] = field(default_factory=dict)
    dependencies: Dict[str, str] = field(default_factory=dict)
    module: Dict[str, str] = field(default_factory=dict)
    package: Dict[str, str] = field(default_factory=dict)


@dataclass
class LoadedManifest:
    """Parsed manifest data for a project."""
    path: Path                                   # Path to manifest file
    format: str                                  # Format used
    data: Dict[str, Any]                         # Raw parsed data
    autoload_mappings: Dict[str, str] = field(default_factory=dict)  # prefix -> dir
    dependencies: Dict[str, List[str]] = field(default_factory=dict)
    source_paths: List[str] = field(default_factory=list)


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

        # Parse manifest configuration
        self.manifest: Optional[ManifestConfig] = None
        if 'manifest' in data:
            self._parse_manifest_config(data['manifest'])

        # Compile regex patterns for performance
        self._compiled_patterns: Dict[str, Any] = {}
        self._compile_patterns()

    def _parse_manifest_config(self, manifest_data: dict) -> None:
        """Parse manifest configuration from YAML data."""
        self.manifest = ManifestConfig(
            file=manifest_data.get('file', ''),
            format=manifest_data.get('format', 'json'),
            fallback=manifest_data.get('fallback', []),
            secondary=manifest_data.get('secondary'),
            autoload=manifest_data.get('autoload', {}),
            module_resolution=manifest_data.get('module_resolution', {}),
            path_aliases=manifest_data.get('path_aliases', {}),
            source_paths=manifest_data.get('source_paths', {}),
            dependencies=manifest_data.get('dependencies', {}),
            module=manifest_data.get('module', {}),
            package=manifest_data.get('package', {}),
        )

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


class ManifestLoader:
    """
    Generic manifest loader that handles different formats.
    Uses the manifest config from language definitions to parse project manifests.
    """

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self._cache: Dict[str, LoadedManifest] = {}

    def load_for_language(self, lang_def: LanguageDefinition) -> Optional[LoadedManifest]:
        """Load manifest for a language definition."""
        if not lang_def.manifest:
            return None

        # Check cache
        cache_key = f"{lang_def.name}:{self.project_root}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Find manifest file
        manifest_path = self._find_manifest(lang_def.manifest)
        if not manifest_path:
            return None

        # Load based on format
        data = self._load_file(manifest_path, lang_def.manifest.format)
        if data is None:
            return None

        # Build LoadedManifest with extracted mappings
        loaded = LoadedManifest(
            path=manifest_path,
            format=lang_def.manifest.format,
            data=data,
        )

        # Extract autoload mappings (for PHP PSR-4, etc.)
        self._extract_autoload(loaded, lang_def.manifest)

        # Extract dependencies
        self._extract_dependencies(loaded, lang_def.manifest)

        # Extract source paths
        self._extract_source_paths(loaded, lang_def.manifest)

        self._cache[cache_key] = loaded
        return loaded

    def _find_manifest(self, config: ManifestConfig) -> Optional[Path]:
        """Find the manifest file in project root."""
        # Try primary file
        primary = self.project_root / config.file
        if primary.exists():
            return primary

        # Try fallbacks
        for fallback in config.fallback:
            path = self.project_root / fallback
            if path.exists():
                return path

        return None

    def _load_file(self, path: Path, format_type: str) -> Optional[Dict[str, Any]]:
        """Load manifest file based on format."""
        try:
            content = path.read_text(encoding='utf-8')

            if format_type == 'json':
                return json.loads(content)

            elif format_type == 'toml':
                # Try tomllib (Python 3.11+) or tomli
                try:
                    import tomllib
                    return tomllib.loads(content)
                except ImportError:
                    try:
                        import tomli
                        return tomli.loads(content)
                    except ImportError:
                        LOGGER.warning('TOML support requires tomli package')
                        return None

            elif format_type == 'edn':
                # Parse EDN (Clojure data format)
                return self._parse_edn(content)

            elif format_type == 'gomod':
                # Parse go.mod format
                return self._parse_gomod(content)

            else:
                LOGGER.warning(f'Unknown manifest format: {format_type}')
                return None

        except Exception as e:
            LOGGER.error(f'Failed to load manifest {path}: {e}')
            return None

    def _parse_edn(self, content: str) -> Dict[str, Any]:
        """Parse EDN format (simplified parser for common cases)."""
        # Simple EDN parser for deps.edn structure
        # For full EDN support, would need edn_format package
        result: Dict[str, Any] = {}

        # Extract :paths vector
        paths_match = re.search(r':paths\s+\[([^\]]+)\]', content)
        if paths_match:
            paths_str = paths_match.group(1)
            result[':paths'] = [p.strip().strip('"') for p in paths_str.split() if p.strip()]

        # Extract :deps map (simplified - just get dependency names)
        deps_match = re.search(r':deps\s+\{([^}]+)\}', content, re.DOTALL)
        if deps_match:
            deps_str = deps_match.group(1)
            # Extract namespace/artifact names
            dep_names = re.findall(r'([a-zA-Z][a-zA-Z0-9._/-]+)\s+\{', deps_str)
            result[':deps'] = {name: {} for name in dep_names}

        return result

    def _parse_gomod(self, content: str) -> Dict[str, Any]:
        """Parse go.mod format."""
        result: Dict[str, Any] = {'require': [], 'replace': []}

        # Extract module path
        module_match = re.search(r'^module\s+(\S+)', content, re.MULTILINE)
        if module_match:
            result['module'] = module_match.group(1)

        # Extract require block
        require_match = re.search(r'require\s+\(([^)]+)\)', content, re.DOTALL)
        if require_match:
            for line in require_match.group(1).strip().split('\n'):
                line = line.strip()
                if line and not line.startswith('//'):
                    parts = line.split()
                    if parts:
                        result['require'].append(parts[0])

        # Single-line requires
        for match in re.finditer(r'^require\s+(\S+)\s+', content, re.MULTILINE):
            result['require'].append(match.group(1))

        return result

    def _get_nested_value(self, data: Dict[str, Any], path: str) -> Any:
        """Get nested value using dot-notation path."""
        keys = path.split('.')
        current = data

        for key in keys:
            if isinstance(current, dict):
                # Handle both regular keys and EDN-style keys
                if key in current:
                    current = current[key]
                elif key.startswith(':') and key[1:] in current:
                    current = current[key[1:]]
                else:
                    return None
            else:
                return None

        return current

    def _extract_autoload(self, loaded: LoadedManifest, config: ManifestConfig) -> None:
        """Extract autoload mappings from manifest data."""
        if not config.autoload:
            return

        for autoload_type, autoload_config in config.autoload.items():
            if not isinstance(autoload_config, dict):
                continue

            path = autoload_config.get('path', '')
            mappings = self._get_nested_value(loaded.data, path)

            if isinstance(mappings, dict):
                # PSR-4 style: {"Namespace\\": "src/"}
                for prefix, directory in mappings.items():
                    # Normalize directory path
                    if isinstance(directory, list):
                        directory = directory[0] if directory else ''
                    loaded.autoload_mappings[prefix] = str(directory)

    def _extract_dependencies(self, loaded: LoadedManifest, config: ManifestConfig) -> None:
        """Extract dependencies from manifest data."""
        for dep_type, path in config.dependencies.items():
            deps = self._get_nested_value(loaded.data, path)
            if isinstance(deps, dict):
                loaded.dependencies[dep_type] = list(deps.keys())
            elif isinstance(deps, list):
                loaded.dependencies[dep_type] = deps

    def _extract_source_paths(self, loaded: LoadedManifest, config: ManifestConfig) -> None:
        """Extract source paths from manifest data."""
        if not config.source_paths:
            return

        path = config.source_paths.get('path', '')
        paths = self._get_nested_value(loaded.data, path)

        if isinstance(paths, list):
            loaded.source_paths = paths
        elif paths is None and 'default' in config.source_paths:
            loaded.source_paths = config.source_paths['default']

    def resolve_namespace_to_file(
        self,
        namespace: str,
        loaded: LoadedManifest,
        lang_def: LanguageDefinition
    ) -> Optional[Path]:
        """
        Resolve a namespace/import to a file path using autoload mappings.

        For PHP PSR-4: "Jenga\\Mesh\\Services\\CacheManager"
                    -> includes/Services/CacheManager.php
        """
        if not loaded.autoload_mappings or not lang_def.manifest:
            return None

        autoload_config = lang_def.manifest.autoload

        # Try each autoload mapping
        for prefix, directory in loaded.autoload_mappings.items():
            # Check if namespace starts with this prefix
            if namespace.startswith(prefix):
                # Get the relative part after the prefix
                relative = namespace[len(prefix):]

                # Get separator and suffix from config
                psr4_config = autoload_config.get('psr4', {})
                separator = psr4_config.get('separator', '\\')
                suffix = psr4_config.get('file_suffix', '.php')

                # Convert namespace separators to path separators
                relative_path = relative.replace(separator, '/')

                # Build full path
                file_path = self.project_root / directory / (relative_path + suffix)

                if file_path.exists():
                    return file_path

        return None


def get_manifest_loader(project_root: Path) -> ManifestLoader:
    """Create a manifest loader for a project."""
    return ManifestLoader(project_root)
