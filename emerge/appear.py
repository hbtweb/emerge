"""
This module defines the main Emerge class, that contains all parsers and the current configuration.
All analyses get started from here.
"""
# Authors: Grzegorz Lato <grzegorz.lato@gmail.com>
# License: MIT

from typing import Dict, Union, Optional
from pathlib import Path
import logging
import signal
import sys

import coloredlogs

from emerge.languages.abstractparser import AbstractParser
from emerge.languages.registry import get_registry
from emerge.languages.generic_parser import GenericParser

from emerge.config import Configuration
from emerge.analyzer import Analyzer
from emerge.analysis import Analysis
from emerge.graph import GraphType
from emerge.abstractresult import AbstractResult
from emerge.log import Logger, LogLevel
from emerge.graph_cache import GraphCache, get_cache

LOGGER = Logger(logging.getLogger('emerge'))
coloredlogs.install(level='E', logger=LOGGER.logger(), fmt=Logger.log_format)

__version__ = '2.2.0'
__updated__ = '2025-12-17'


class Emerge:
    _version: str = f'{__version__}'
    config = Configuration(_version)

    def __init__(self, use_registry: bool = True):
        """Initialize all collected results, available parsers and set the log level.

        Args:
            use_registry: If True (default), load parsers from YAML registry.
                         If False, use legacy hardcoded parsers.
        """
        self._results: Dict[str, AbstractResult] = {}

        if use_registry:
            self._parsers = self._create_registry_parsers()
        else:
            self._parsers = self._create_legacy_parsers()

        self.config.supported_languages = self._get_supported_languages()
        self.config.setup_commang_line_arguments()
        self.set_log_level(LogLevel.ERROR)

    def _create_registry_parsers(self) -> Dict[str, Union[AbstractParser, GenericParser]]:
        """Create parsers dynamically from the language registry."""
        registry = get_registry()
        parsers: Dict[str, Union[AbstractParser, GenericParser]] = {}

        for lang_name in registry.list_languages():
            parser = GenericParser.for_language(lang_name)
            # Use the language-specific parser name (e.g., "DART_PARSER")
            parsers[parser.get_parser_name()] = parser

        LOGGER.info(f'Loaded {len(parsers)} parsers from registry')
        return parsers

    def _create_legacy_parsers(self) -> Dict[str, AbstractParser]:
        """Create parsers using the legacy hardcoded approach."""
        # Import legacy parsers only when needed
        from emerge.languages.javaparser import JavaParser
        from emerge.languages.swiftparser import SwiftParser
        from emerge.languages.cparser import CParser
        from emerge.languages.cppparser import CPPParser
        from emerge.languages.groovyparser import GroovyParser
        from emerge.languages.javascriptparser import JavaScriptParser
        from emerge.languages.typescriptparser import TypeScriptParser
        from emerge.languages.kotlinparser import KotlinParser
        from emerge.languages.objcparser import ObjCParser
        from emerge.languages.rubyparser import RubyParser
        from emerge.languages.pyparser import PythonParser
        from emerge.languages.goparser import GoParser
        from emerge.languages.phpparser import PHPParser
        from emerge.languages.clojureparser import ClojureParser
        from emerge.languages.dartparser import DartParser

        return {
            JavaParser.parser_name(): JavaParser(),
            SwiftParser.parser_name(): SwiftParser(),
            CParser.parser_name(): CParser(),
            CPPParser.parser_name(): CPPParser(),
            GroovyParser.parser_name(): GroovyParser(),
            JavaScriptParser.parser_name(): JavaScriptParser(),
            TypeScriptParser.parser_name(): TypeScriptParser(),
            KotlinParser.parser_name(): KotlinParser(),
            ObjCParser.parser_name(): ObjCParser(),
            RubyParser.parser_name(): RubyParser(),
            PythonParser.parser_name(): PythonParser(),
            GoParser.parser_name(): GoParser(),
            PHPParser.parser_name(): PHPParser(),
            ClojureParser.parser_name(): ClojureParser(),
            DartParser.parser_name(): DartParser()
        }

    def _get_supported_languages(self) -> list:
        """Get list of supported language types."""
        languages = []
        for parser in self._parsers.values():
            if isinstance(parser, GenericParser):
                languages.append(parser.get_language_type())
            else:
                languages.append(parser.language_type())
        return languages

    def parse_args(self):
        self.config.parse_args()

    def load_config(self, path):
        self.config.load_config_from_yaml_file(path)

    def print_config(self):
        self.config.print_config_as_yaml()
        self.config.print_config_dict()

    def get_config(self) -> Dict:
        return self.config.get_config_as_dict()

    def print_version(self):
        LOGGER.info(f'emerge version: {self.get_version()}')

    def start(self):
        """Starts emerge by parsing arguments/configuration and starting the analysis from an analyzer instance.
        """

        self.parse_args()

        # Auto-scan mode takes precedence
        if self.config.has_scan_path():
            self._start_auto_scan()
            return

        if self.config.has_valid_config_path():
            self.load_config(self.config.yaml_config_path)
            if self.config.valid:
                self.start_analyzing()
            else:
                LOGGER.error('will not start with any analysis due configuration errors')
                return

    def _start_auto_scan(self):
        """Run analysis with auto-detected languages (no config file needed)."""
        registry = get_registry()
        scan_path = Path(self.config.scan_path).resolve()
        output_path = Path(self.config.output_dir).resolve()

        if not scan_path.exists():
            LOGGER.error(f'scan path does not exist: {scan_path}')
            return

        if not scan_path.is_dir():
            LOGGER.error(f'scan path is not a directory: {scan_path}')
            return

        # Create output directory if it doesn't exist
        output_path.mkdir(parents=True, exist_ok=True)

        # Detect languages used in the directory
        detected_languages = registry.detect_languages(scan_path)

        if not detected_languages:
            LOGGER.error(f'no supported languages detected in: {scan_path}')
            return

        # Collect file extensions for detected languages
        extensions = []
        for lang_name in detected_languages:
            lang_def = registry.get_language(lang_name)
            if lang_def:
                extensions.extend(lang_def.extensions)

        LOGGER.info(f'Auto-scan: detected languages: {", ".join(detected_languages)}')
        LOGGER.info(f'Auto-scan: scanning extensions: {", ".join(extensions)}')

        # Create analysis programmatically
        analysis = Analysis()
        analysis.project_name = scan_path.name
        analysis.analysis_name = f"auto-scan of {scan_path.name}"
        analysis.source_directory = str(scan_path)
        analysis.export_directory = str(output_path)
        analysis.emerge_version = self._version

        # Set language filters - use uppercase for language names
        analysis.only_permit_languages = [lang.upper() for lang in detected_languages]
        analysis.only_permit_file_extensions = extensions

        # Enable file and entity scans
        analysis.scan_types = ['file_scan', 'entity_scan']

        # Enable dependency graphs
        analysis.create_graph_representation(GraphType.FILE_RESULT_DEPENDENCY_GRAPH)
        analysis.create_graph_representation(GraphType.ENTITY_RESULT_DEPENDENCY_GRAPH)
        analysis.create_graph_representation(GraphType.ENTITY_RESULT_INHERITANCE_GRAPH)
        analysis.create_graph_representation(GraphType.ENTITY_RESULT_COMPLETE_GRAPH)

        # Enable all exports
        analysis.export_d3 = True
        analysis.export_json = True
        analysis.export_graphml = True
        analysis.export_tabular_file = True
        analysis.export_tabular_console_overall = True

        # Common directories to ignore
        analysis.ignore_directories_containing = [
            'node_modules', '.git', '__pycache__', '.idea',
            'build', 'dist', '.gradle', 'target', 'vendor',
            '.dart_tool', '.pub-cache'
        ]

        # Check cache first (if enabled)
        cache = get_cache(output_path / '.emerge_cache')

        if self.config.use_cache:
            source_hash = cache.compute_source_hash(scan_path, set(extensions))
            cached = cache.load(source_hash)

            if cached:
                LOGGER.info('Using cached analysis (source unchanged)')
                if self.config.watch_mode or self.config.mcp_mode or self.config.websocket_mode:
                    self._start_live_mode(scan_path, cached.graphs, extensions)
                else:
                    LOGGER.info(f'Cached graphs: {list(cached.graphs.keys())}')
                    LOGGER.info('Run with --no-cache to force rebuild')
                return

        # Add analysis to config and mark as valid
        self.config.analyses = [analysis]
        self.config.project_name = scan_path.name
        self.config.valid = True

        # Start analyzing
        self.start_analyzing()

        # Cache results after analysis
        if self.config.use_cache and self.config.analyses:
            completed = self.config.analyses[0]
            source_hash = cache.compute_source_hash(scan_path, set(extensions))
            cache.save(completed, source_hash)
            LOGGER.info('Analysis cached for future runs')

        # Start live modes if requested
        if self.config.watch_mode or self.config.mcp_mode or self.config.websocket_mode:
            graphs = {
                name: repr.digraph
                for name, repr in self.config.analyses[0].graph_representations.items()
                if repr is not None
            }
            self._start_live_mode(scan_path, graphs, extensions)

    def _start_live_mode(self, scan_path: Path, graphs: Dict, extensions: list):
        """Start live mode services (watch, MCP, WebSocket)."""
        watcher = None
        ws_server = None

        def shutdown(sig=None, frame=None):
            LOGGER.info('Shutting down...')
            if watcher:
                watcher.stop()
            if ws_server:
                ws_server.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)

        # Start WebSocket server
        if self.config.websocket_mode:
            from emerge.websocket_server import GraphWebSocketServer
            ws_server = GraphWebSocketServer(port=self.config.websocket_port, graphs=graphs)
            ws_server.start()
            LOGGER.info(f'WebSocket server: ws://localhost:{self.config.websocket_port}')

        # Start file watcher
        if self.config.watch_mode:
            from emerge.watcher import GraphWatcher
            watcher = GraphWatcher(scan_path, extensions=set(extensions))
            watcher.graphs = graphs
            if ws_server:
                watcher.add_listener(ws_server.broadcast_update)
            watcher.start()
            LOGGER.info(f'Watching: {scan_path}')

        # Start MCP server (blocking)
        if self.config.mcp_mode:
            from emerge import mcp_server
            mcp_server._graphs = graphs
            mcp_server._source_dir = scan_path
            LOGGER.info('Starting MCP server (stdio)...')
            mcp_server.run_server(transport="stdio")
            return

        # Keep alive for watch/websocket
        if self.config.watch_mode or self.config.websocket_mode:
            LOGGER.info('Press Ctrl+C to stop')
            import time
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                shutdown()

    def start_with_log_level(self, level: LogLevel):
        """Sets a custom log level and starts emerge.

        Args:
            level (LogLevel): A given log level.
        """
        Logger.set_log_level(level)
        self.start()

    def set_log_level(self, level: LogLevel):
        Logger.set_log_level(level)

    def start_analyzing(self):
        """Starts with the first analysis on an Analyzer instance.
        """
        analyzer = Analyzer(self.config, self._parsers)
        analyzer.start_analyzing()

    @staticmethod
    def get_version() -> str:
        return Emerge._version
