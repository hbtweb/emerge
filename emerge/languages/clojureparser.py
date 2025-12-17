"""
Contains the implementation of the Clojure language parser and a relevant keyword enum.
"""

# Authors: Grzegorz Lato <grzegorz.lato@gmail.com>
# License: MIT

from typing import Dict
from enum import Enum, unique

import logging
from pathlib import Path
import os
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
class ClojureParsingKeyword(Enum):
    NS = "ns"
    REQUIRE = ":require"
    REQUIRE_MACROS = ":require-macros"
    IMPORT = ":import"
    USE = ":use"
    DEFN = "defn"
    DEFN_PRIVATE = "defn-"
    DEFMACRO = "defmacro"
    DEFMULTI = "defmulti"
    DEFMETHOD = "defmethod"
    DEFPROTOCOL = "defprotocol"
    DEFRECORD = "defrecord"
    DEFTYPE = "deftype"
    DEFINTERFACE = "definterface"
    INLINE_COMMENT = ";"
    START_BLOCK_COMMENT = "#_"  # Clojure doesn't have block comments, but #_ ignores next form
    STOP_BLOCK_COMMENT = ""  # Not used for Clojure
    OPEN_PAREN = "("
    CLOSE_PAREN = ")"
    OPEN_BRACKET = "["
    CLOSE_BRACKET = "]"


class ClojureParser(AbstractParser, ParsingMixin):

    def __init__(self):
        self._results: Dict[str, AbstractResult] = {}
        self._token_mappings: Dict[str, str] = {
            '(': ' ( ',
            ')': ' ) ',
            '[': ' [ ',
            ']': ' ] ',
            '{': ' { ',
            '}': ' } ',
            '"': ' " ',
            "'": " ' ",
            ':': ' : ',
        }

    @classmethod
    def parser_name(cls) -> str:
        return Parser.CLOJURE_PARSER.name

    @classmethod
    def language_type(cls) -> str:
        return LanguageType.CLOJURE.name

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
            scanned_language=LanguageType.CLOJURE,
            scanned_tokens=scanned_tokens,
            source=file_content,
            preprocessed_source=""
        )

        self._add_namespace_to_result(file_result, file_content)
        self._add_imports_to_result(file_result, analysis)
        self._results[file_result.unique_name] = file_result

    def after_generated_file_results(self, analysis) -> None:
        pass

    def create_unique_entity_name(self, entity: AbstractEntityResult) -> None:
        """Creates a unique entity name based on namespace and entity name."""
        if entity.module_name:
            entity.unique_name = f"{entity.module_name}/{entity.entity_name}"
        else:
            entity.unique_name = entity.entity_name

    def generate_entity_results_from_analysis(self, analysis):
        """Generate entity results for defrecord, defprotocol, deftype, and definterface."""
        LOGGER.debug('generating entity results for Clojure...')

        # Create filtered copy to avoid modifying dict during iteration
        filtered_results = {k: v for (k, v) in self._results.items()
                           if v.analysis is analysis and isinstance(v, AbstractFileResult)}

        for _, file_result in filtered_results.items():
            source = file_result.source
            self._extract_entities_from_source(source, file_result, analysis)

    def _extract_entities_from_source(self, source: str, file_result: AbstractFileResult, analysis):
        """Extract defrecord, defprotocol, deftype, and definterface declarations."""
        # Remove comments from source
        lines = source.split('\n')
        clean_lines = []
        for line in lines:
            # Remove line comments
            comment_idx = line.find(';')
            if comment_idx != -1:
                line = line[:comment_idx]
            clean_lines.append(line)
        clean_source = '\n'.join(clean_lines)

        # Pattern for entity definitions
        entity_patterns = [
            (r'\(\s*defrecord\s+([A-Za-z][A-Za-z0-9_-]*)', 'defrecord'),
            (r'\(\s*defprotocol\s+([A-Za-z][A-Za-z0-9_-]*)', 'defprotocol'),
            (r'\(\s*deftype\s+([A-Za-z][A-Za-z0-9_-]*)', 'deftype'),
            (r'\(\s*definterface\s+([A-Za-z][A-Za-z0-9_-]*)', 'definterface'),
        ]

        for pattern, entity_type in entity_patterns:
            for match in re.finditer(pattern, clean_source):
                entity_name = match.group(1)

                # Get scanned tokens for this entity (simplified - use file tokens)
                unique_entity_name = file_result.absolute_name + "/" + entity_name
                entity_result = EntityResult(
                    analysis=analysis,
                    scanned_file_name=file_result.scanned_file_name,
                    absolute_name=unique_entity_name,
                    display_name=entity_name,
                    scanned_by=self.parser_name(),
                    scanned_language=LanguageType.CLOJURE,
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

                self._results[entity_result.unique_name] = entity_result
                LOGGER.debug(f'added entity result: {entity_result.unique_name}')

    def _add_namespace_to_result(self, result: AbstractFileResult, source: str):
        """Extract namespace from (ns ...) form."""
        # Remove comments
        lines = source.split('\n')
        clean_lines = []
        for line in lines:
            comment_idx = line.find(';')
            if comment_idx != -1:
                line = line[:comment_idx]
            clean_lines.append(line)
        clean_source = '\n'.join(clean_lines)

        # Match (ns namespace.name ...) - namespace can have dots and hyphens
        ns_pattern = r'\(\s*ns\s+([a-zA-Z][a-zA-Z0-9._-]*)'
        match = re.search(ns_pattern, clean_source)
        if match:
            namespace = match.group(1)
            result.module_name = namespace
            LOGGER.debug(f'found namespace: {namespace}')

    def _add_imports_to_result(self, result: AbstractFileResult, analysis):
        """Extract require, import, and use dependencies from Clojure source."""
        LOGGER.debug(f'extracting imports from file result {result.scanned_file_name}...')

        source = result.source

        # Remove comments
        lines = source.split('\n')
        clean_lines = []
        for line in lines:
            comment_idx = line.find(';')
            if comment_idx != -1:
                line = line[:comment_idx]
            clean_lines.append(line)
        clean_source = '\n'.join(clean_lines)

        # Pattern for :require inside ns form
        # Matches: (:require [namespace.name] [namespace.name :as alias] [namespace.name :refer [a b]])
        require_pattern = r'\[\s*([a-zA-Z][a-zA-Z0-9._-]*)'

        # Find all content within :require blocks
        # This is simplified - we look for :require and extract namespace names
        require_block_pattern = r':require\s+((?:\[.*?\]|\(.*?\)|[a-zA-Z][a-zA-Z0-9._-]*)\s*)+'

        for match in re.finditer(require_block_pattern, clean_source, re.DOTALL):
            require_block = match.group(0)
            # Extract namespace names from vectors
            for ns_match in re.finditer(require_pattern, require_block):
                namespace = ns_match.group(1)
                # Convert namespace to file path
                dependency = self._namespace_to_path(namespace)
                if not self._is_dependency_in_ignore_list(dependency, analysis):
                    result.scanned_import_dependencies.append(dependency)
                    LOGGER.debug(f'adding import: {dependency}')

        # Also check for top-level (require ...) forms
        toplevel_require_pattern = r'\(\s*require\s+\'?\[([a-zA-Z][a-zA-Z0-9._-]*)'
        for match in re.finditer(toplevel_require_pattern, clean_source):
            namespace = match.group(1)
            dependency = self._namespace_to_path(namespace)
            if not self._is_dependency_in_ignore_list(dependency, analysis):
                result.scanned_import_dependencies.append(dependency)
                LOGGER.debug(f'adding import: {dependency}')

        # Check for :import (Java class imports)
        import_pattern = r':import\s+\[([a-zA-Z][a-zA-Z0-9._]*)'
        for match in re.finditer(import_pattern, clean_source):
            package = match.group(1)
            dependency = package.replace('.', '/')
            if not self._is_dependency_in_ignore_list(dependency, analysis):
                result.scanned_import_dependencies.append(dependency)
                LOGGER.debug(f'adding import: {dependency}')

    def _namespace_to_path(self, namespace: str) -> str:
        """Convert Clojure namespace to file path.

        In Clojure:
        - dots become directory separators
        - hyphens in namespace names become underscores in file names
        """
        # Replace dots with slashes for path
        path = namespace.replace('.', '/')
        # Replace hyphens with underscores (Clojure convention)
        path = path.replace('-', '_')
        return path


if __name__ == "__main__":
    LEXER = ClojureParser()
    print(f'{LEXER.results=}')