"""
Contains the implementation of the Dart language parser and a relevant keyword enum.
"""

# Authors: Grzegorz Lato <grzegorz.lato@gmail.com>
# License: MIT

from typing import Dict
from enum import Enum, unique

import logging
from pathlib import Path
import re

import pyparsing as pp
import coloredlogs

from emerge.languages.abstractparser import AbstractParser, ParsingMixin, Parser, CoreParsingKeyword, LanguageType
from emerge.results import FileResult, EntityResult
from emerge.abstractresult import AbstractResult, AbstractFileResult, AbstractEntityResult
from emerge.stats import Statistics
from emerge.log import Logger

LOGGER = Logger(logging.getLogger('parser'))
coloredlogs.install(level='E', logger=LOGGER.logger(), fmt=Logger.log_format)


@unique
class DartParsingKeyword(Enum):
    IMPORT = "import"
    EXPORT = "export"
    PART = "part"
    PART_OF = "of"
    CLASS = "class"
    ABSTRACT = "abstract"
    MIXIN = "mixin"
    EXTENSION = "extension"
    EXTENDS = "extends"
    IMPLEMENTS = "implements"
    WITH = "with"
    ON = "on"
    INLINE_COMMENT = "//"
    START_BLOCK_COMMENT = "/*"
    STOP_BLOCK_COMMENT = "*/"
    LIBRARY = "library"


class DartParser(AbstractParser, ParsingMixin):

    def __init__(self):
        self._results: Dict[str, AbstractResult] = {}
        self._token_mappings: Dict[str, str] = {
            ':': ' : ',
            ';': ' ; ',
            '{': ' { ',
            '}': ' } ',
            '(': ' ( ',
            ')': ' ) ',
            '[': ' [ ',
            ']': ' ] ',
            '?': ' ? ',
            '!': ' ! ',
            ',': ' , ',
            '<': ' < ',
            '>': ' > ',
            '"': ' " ',
            "'": " ' ",
            '@': ' @ '
        }

    @classmethod
    def parser_name(cls) -> str:
        return Parser.DART_PARSER.name

    @classmethod
    def language_type(cls) -> str:
        return LanguageType.DART.name

    @property
    def results(self) -> Dict[str, AbstractResult]:
        return self._results

    @results.setter
    def results(self, value):
        self._results = value

    def generate_file_result_from_analysis(self, analysis, *, file_name: str, full_file_path: str, file_content: str) -> None:
        LOGGER.debug('generating file results...')
        scanned_tokens = self.preprocess_file_content_and_generate_token_list_by_mapping(file_content, self._token_mappings)

        # make sure to create unique names by using the relative analysis path as a base for the result
        parent_analysis_source_path = f"{Path(analysis.source_directory).parent}/"
        relative_file_path_to_analysis = full_file_path.replace(parent_analysis_source_path, "")

        file_result = FileResult.create_file_result(
            analysis=analysis,
            scanned_file_name=file_name,
            relative_file_path_to_analysis=relative_file_path_to_analysis,
            absolute_name=full_file_path,
            display_name=file_name,
            module_name="",
            scanned_by=self.parser_name(),
            scanned_language=LanguageType.DART,
            scanned_tokens=scanned_tokens,
            source=file_content,
            preprocessed_source=""
        )

        self._add_package_to_result(file_result, file_content)
        self._add_imports_to_result(file_result, analysis)
        self._results[file_result.unique_name] = file_result

    def after_generated_file_results(self, analysis) -> None:
        pass

    def create_unique_entity_name(self, entity: AbstractEntityResult) -> None:
        """Creates a unique entity name based on module and entity name."""
        if entity.module_name:
            entity.unique_name = f"{entity.module_name}/{entity.entity_name}"
        else:
            entity.unique_name = entity.entity_name

    def generate_entity_results_from_analysis(self, analysis):
        """Generate entity results for class, abstract class, mixin, and extension declarations."""
        LOGGER.debug('generating entity results for Dart...')

        # Create filtered copy to avoid modifying dict during iteration
        filtered_results = {k: v for (k, v) in self._results.items()
                           if v.analysis is analysis and isinstance(v, AbstractFileResult)}

        for _, file_result in filtered_results.items():
            source = file_result.source
            self._extract_entities_from_source(source, file_result, analysis)

    def _extract_entities_from_source(self, source: str, file_result: AbstractFileResult, analysis):
        """Extract class, abstract class, mixin, and extension declarations."""
        # Remove comments from source
        clean_source = self._remove_comments(source)

        # Pattern for entity definitions
        entity_patterns = [
            # abstract class ClassName
            (r'\babstract\s+class\s+([A-Za-z_][A-Za-z0-9_]*)', 'abstract_class'),
            # class ClassName (but not abstract class)
            (r'(?<!\babstract\s)\bclass\s+([A-Za-z_][A-Za-z0-9_]*)', 'class'),
            # mixin MixinName
            (r'\bmixin\s+([A-Za-z_][A-Za-z0-9_]*)', 'mixin'),
            # extension ExtensionName on Type
            (r'\bextension\s+([A-Za-z_][A-Za-z0-9_]*)\s+on', 'extension'),
        ]

        for pattern, entity_type in entity_patterns:
            for match in re.finditer(pattern, clean_source):
                entity_name = match.group(1)

                unique_entity_name = file_result.absolute_name + "/" + entity_name
                entity_result = EntityResult(
                    analysis=analysis,
                    scanned_file_name=file_result.scanned_file_name,
                    absolute_name=unique_entity_name,
                    display_name=entity_name,
                    scanned_by=self.parser_name(),
                    scanned_language=LanguageType.DART,
                    scanned_tokens=file_result.scanned_tokens,
                    scanned_import_dependencies=[],
                    entity_name=entity_name,
                    module_name=file_result.module_name,
                    unique_name=entity_name,
                    parent_file_result=file_result
                )

                self.create_unique_entity_name(entity_result)

                # Copy file dependencies to entity
                for dep in file_result.scanned_import_dependencies:
                    if self._is_dependency_in_ignore_list(dep, analysis):
                        continue
                    entity_result.scanned_import_dependencies.append(dep)

                # Extract inheritance relationships
                self._extract_inheritance(clean_source, entity_name, entity_result)

                self._results[entity_result.unique_name] = entity_result
                LOGGER.debug(f'added entity result: {entity_result.unique_name}')

    def _extract_inheritance(self, source: str, entity_name: str, entity_result: AbstractEntityResult):
        """Extract extends, implements, and with relationships."""
        # Find the class/mixin declaration and extract inheritance
        # Pattern: class/mixin EntityName extends Parent implements I1, I2 with M1, M2 {
        pattern = rf'\b(?:abstract\s+)?(?:class|mixin)\s+{re.escape(entity_name)}\s*(?:<[^>]*>)?\s*([^{{]*)\{{'
        match = re.search(pattern, source)
        if match:
            declaration = match.group(1)

            # Extract extends
            extends_match = re.search(r'\bextends\s+([A-Za-z_][A-Za-z0-9_]*)', declaration)
            if extends_match:
                parent = extends_match.group(1)
                entity_result.scanned_inheritance_dependencies.append(parent)
                LOGGER.debug(f'{entity_name} extends {parent}')

            # Extract implements
            implements_match = re.search(r'\bimplements\s+([^{]+?)(?:\bwith\b|$)', declaration)
            if implements_match:
                interfaces = implements_match.group(1)
                for iface in re.findall(r'([A-Za-z_][A-Za-z0-9_]*)', interfaces):
                    if iface not in ['with', 'extends', 'implements']:
                        entity_result.scanned_inheritance_dependencies.append(iface)
                        LOGGER.debug(f'{entity_name} implements {iface}')

            # Extract with (mixins)
            with_match = re.search(r'\bwith\s+([^{]+)', declaration)
            if with_match:
                mixins = with_match.group(1)
                for mixin in re.findall(r'([A-Za-z_][A-Za-z0-9_]*)', mixins):
                    entity_result.scanned_inheritance_dependencies.append(mixin)
                    LOGGER.debug(f'{entity_name} with {mixin}')

    def _remove_comments(self, source: str) -> str:
        """Remove single-line and multi-line comments from source."""
        # Remove block comments
        source = re.sub(r'/\*.*?\*/', '', source, flags=re.DOTALL)
        # Remove line comments
        source = re.sub(r'//.*$', '', source, flags=re.MULTILINE)
        return source

    def _add_package_to_result(self, result: AbstractFileResult, source: str):
        """Extract library name from library directive."""
        clean_source = self._remove_comments(source)

        # Match library directive: library package_name;
        library_pattern = r'\blibrary\s+([a-zA-Z_][a-zA-Z0-9_\.]*)\s*;'
        match = re.search(library_pattern, clean_source)
        if match:
            library_name = match.group(1)
            result.module_name = library_name
            LOGGER.debug(f'found library: {library_name}')

    def _add_imports_to_result(self, result: AbstractFileResult, analysis):
        """Extract import dependencies from Dart source."""
        LOGGER.debug(f'extracting imports from file result {result.scanned_file_name}...')

        source = result.source
        clean_source = self._remove_comments(source)

        # Pattern for imports: import 'package:name/path.dart';
        # or import 'dart:core';
        # or import 'relative/path.dart';
        import_patterns = [
            # package imports: import 'package:package_name/path.dart';
            r"import\s+['\"]package:([^'\"]+)['\"]",
            # dart SDK imports: import 'dart:core';
            r"import\s+['\"]dart:([^'\"]+)['\"]",
            # relative imports: import 'path/to/file.dart';
            r"import\s+['\"]([^':]+\.dart)['\"]",
        ]

        for pattern in import_patterns:
            for match in re.finditer(pattern, clean_source):
                import_path = match.group(1)

                # Convert package import to dependency name
                if 'package:' in pattern:
                    # Extract package name from package:name/path.dart
                    dependency = import_path.replace('/', '.')
                elif 'dart:' in pattern:
                    # Dart SDK - prefix with dart:
                    dependency = f"dart:{import_path}"
                else:
                    # Relative import - convert path to dots
                    dependency = import_path.replace('/', '.').replace('.dart', '')

                if not self._is_dependency_in_ignore_list(dependency, analysis):
                    result.scanned_import_dependencies.append(dependency)
                    LOGGER.debug(f'adding import: {dependency}')

        # Also handle export and part directives
        export_pattern = r"export\s+['\"]package:([^'\"]+)['\"]"
        for match in re.finditer(export_pattern, clean_source):
            export_path = match.group(1)
            dependency = export_path.replace('/', '.')
            if not self._is_dependency_in_ignore_list(dependency, analysis):
                result.scanned_import_dependencies.append(dependency)
                LOGGER.debug(f'adding export: {dependency}')

        part_pattern = r"part\s+['\"]([^'\"]+)['\"]"
        for match in re.finditer(part_pattern, clean_source):
            part_path = match.group(1)
            dependency = part_path.replace('/', '.').replace('.dart', '')
            if not self._is_dependency_in_ignore_list(dependency, analysis):
                result.scanned_import_dependencies.append(dependency)
                LOGGER.debug(f'adding part: {dependency}')


if __name__ == "__main__":
    LEXER = DartParser()
    print(f'{LEXER.results=}')
