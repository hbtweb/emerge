"""
Generic parser that handles any language via registry definitions.
One parser class, configured by YAML language definitions.
"""

# Authors: Grzegorz Lato <grzegorz.lato@gmail.com>
# License: MIT

from typing import Dict, Any, List
from pathlib import Path
import re
import logging

import coloredlogs

from emerge.languages.abstractparser import AbstractParser, ParsingMixin
from emerge.languages.registry import LanguageDefinition, get_registry
from emerge.results import FileResult, EntityResult
from emerge.abstractresult import AbstractResult, AbstractFileResult, AbstractEntityResult
from emerge.log import Logger

LOGGER = Logger(logging.getLogger('parser'))
coloredlogs.install(level='E', logger=LOGGER.logger(), fmt=Logger.log_format)


class GenericParser(AbstractParser, ParsingMixin):
    """
    A parser that uses language definitions from the registry.
    One instance per language, configured via YAML definition file.
    """

    def __init__(self, language_def: LanguageDefinition):
        self._def = language_def
        self._results: Dict[str, AbstractResult] = {}
        self._language_name = language_def.name.upper()

    @classmethod
    def for_language(cls, language_name: str) -> 'GenericParser':
        """Factory method to create parser for a language."""
        registry = get_registry()
        lang_def = registry.get_language(language_name)
        if not lang_def:
            raise ValueError(f'Unknown language: {language_name}')
        return cls(lang_def)

    @classmethod
    def parser_name(cls) -> str:
        # This is overridden per-instance, but needed for ABC compliance
        return "GENERIC_PARSER"

    def get_parser_name(self) -> str:
        """Instance-specific parser name."""
        return f"{self._language_name}_PARSER"

    @classmethod
    def language_type(cls) -> str:
        # This is overridden per-instance, but needed for ABC compliance
        return "GENERIC"

    def get_language_type(self) -> str:
        """Instance-specific language type."""
        return self._language_name

    @property
    def results(self) -> Dict[str, AbstractResult]:
        return self._results

    @results.setter
    def results(self, value: Dict[str, AbstractResult]) -> None:
        self._results = value

    def _remove_comments(self, source: str) -> str:
        """Remove comments using language-specific patterns."""
        comments = self._def.comments
        if not comments:
            return source

        # Remove block comments
        if 'block_start' in comments and 'block_end' in comments:
            start = re.escape(comments['block_start'])
            end = re.escape(comments['block_end'])
            source = re.sub(f'{start}.*?{end}', '', source, flags=re.DOTALL)

        # Remove line comments
        if 'line' in comments:
            line = re.escape(comments['line'])
            source = re.sub(f'{line}.*$', '', source, flags=re.MULTILINE)

        return source

    def _preprocess_tokens(self, content: str) -> List[str]:
        """Tokenize content using language-specific mappings."""
        for orig, mapped in self._def.token_mappings.items():
            content = content.replace(orig, mapped)
        return re.findall(r'\S+|\n', content)

    def _apply_transform(self, value: str, transform: str) -> str:
        """Apply transform operations from YAML pattern definition."""
        if not transform:
            return value

        result = value

        # Parse and apply each transform operation
        # Supports chained transforms like: replace('/', '.').removesuffix('.dart')
        # Use regex to find complete function calls rather than splitting on '.'
        transform_pattern = re.compile(
            r"(replace|prefix|removesuffix|removeprefix)\s*\(\s*'([^']*)'\s*(?:,\s*'([^']*)'\s*)?\)"
        )

        for match in transform_pattern.finditer(transform):
            func_name = match.group(1)
            arg1 = match.group(2)
            arg2 = match.group(3)  # May be None for single-arg functions

            if func_name == 'replace' and arg2 is not None:
                result = result.replace(arg1, arg2)
            elif func_name == 'prefix':
                result = arg1 + result
            elif func_name == 'removesuffix':
                if result.endswith(arg1):
                    result = result[:-len(arg1)]
            elif func_name == 'removeprefix':
                if result.startswith(arg1):
                    result = result[len(arg1):]

        return result

    def _extract_imports(self, source: str, analysis: Any) -> List[str]:
        """Extract imports using language patterns."""
        imports: List[str] = []
        clean_source = self._remove_comments(source)

        import_patterns = self._def.get_compiled_patterns('imports')
        if not isinstance(import_patterns, list):
            return imports

        for pattern_def in import_patterns:
            regex = pattern_def.get('compiled')
            if regex is None:
                continue

            group = pattern_def.get('group', 1)
            transform = pattern_def.get('transform', '')

            for match in regex.finditer(clean_source):
                try:
                    dep = match.group(group)
                except IndexError:
                    continue

                # Apply transform
                dep = self._apply_transform(dep, transform)

                if not self._is_dependency_in_ignore_list(dep, analysis):
                    imports.append(dep)
                    LOGGER.debug(f'adding import: {dep}')

        return imports

    def _extract_module_name(self, source: str) -> str:
        """Extract module/package name using language patterns."""
        clean_source = self._remove_comments(source)
        module_pattern = self._def.get_compiled_patterns('module')

        if isinstance(module_pattern, dict) and 'compiled' in module_pattern:
            match = module_pattern['compiled'].search(clean_source)
            if match:
                group = module_pattern.get('group', 1)
                try:
                    return match.group(group)
                except IndexError:
                    pass
        return ""

    def generate_file_result_from_analysis(self, analysis: Any, *, file_name: str,
                                           full_file_path: str, file_content: str) -> None:
        """Generate file result using registry patterns."""
        LOGGER.debug(f'generating file results for {file_name}...')

        scanned_tokens = self._preprocess_tokens(file_content)

        parent_analysis_source_path = f"{Path(analysis.source_directory).parent}/"
        relative_file_path_to_analysis = full_file_path.replace(parent_analysis_source_path, "")

        module_name = self._extract_module_name(file_content)

        file_result = FileResult.create_file_result(
            analysis=analysis,
            scanned_file_name=file_name,
            relative_file_path_to_analysis=relative_file_path_to_analysis,
            absolute_name=full_file_path,
            display_name=file_name,
            module_name=module_name,
            scanned_by=self.get_parser_name(),
            scanned_language=self._language_name,  # String, not enum
            scanned_tokens=scanned_tokens,
            source=file_content,
            preprocessed_source=""
        )

        # Extract imports
        imports = self._extract_imports(file_content, analysis)
        file_result.scanned_import_dependencies = imports

        self._results[file_result.unique_name] = file_result

    def generate_entity_results_from_analysis(self, analysis: Any) -> None:
        """Generate entity results using registry patterns."""
        LOGGER.debug(f'generating entity results for {self._language_name}...')

        filtered_results = {k: v for k, v in self._results.items()
                          if v.analysis is analysis and isinstance(v, AbstractFileResult)}

        for _, file_result in filtered_results.items():
            clean_source = self._remove_comments(file_result.source)
            self._extract_entities(clean_source, file_result, analysis)

    def _extract_entities(self, source: str, file_result: AbstractFileResult, analysis: Any) -> None:
        """Extract entities using language patterns."""
        entity_patterns = self._def.get_compiled_patterns('entities')
        if not isinstance(entity_patterns, list):
            return

        for pattern_def in entity_patterns:
            regex = pattern_def.get('compiled')
            if regex is None:
                continue

            group = pattern_def.get('group', 1)
            entity_type = pattern_def.get('type', 'class')

            for match in regex.finditer(source):
                try:
                    entity_name = match.group(group)
                except IndexError:
                    continue

                if self.is_entity_in_ignore_list(entity_name, analysis):
                    continue

                unique_entity_name = f"{file_result.absolute_name}/{entity_name}"

                entity_result = EntityResult(
                    analysis=analysis,
                    scanned_file_name=file_result.scanned_file_name,
                    absolute_name=unique_entity_name,
                    display_name=entity_name,
                    scanned_by=self.get_parser_name(),
                    scanned_language=self._language_name,
                    scanned_tokens=file_result.scanned_tokens,
                    scanned_import_dependencies=list(file_result.scanned_import_dependencies),
                    entity_name=entity_name,
                    module_name=file_result.module_name,
                    unique_name=entity_name,
                    parent_file_result=file_result
                )

                self.create_unique_entity_name(entity_result)

                # Extract inheritance
                self._extract_inheritance(source, entity_name, entity_result)

                self._results[entity_result.unique_name] = entity_result
                LOGGER.debug(f'added entity result: {entity_result.unique_name}')

    def _extract_inheritance(self, source: str, entity_name: str,
                            entity_result: AbstractEntityResult) -> None:
        """Extract inheritance relationships using language patterns."""
        inheritance_patterns = self._def.get_compiled_patterns('inheritance')
        if not inheritance_patterns or not isinstance(inheritance_patterns, dict):
            return

        for key, pattern_def in inheritance_patterns.items():
            if not isinstance(pattern_def, dict) or 'compiled' not in pattern_def:
                continue

            regex = pattern_def['compiled']
            group = pattern_def.get('group', 1)
            split_char = pattern_def.get('split', None)

            for match in regex.finditer(source):
                try:
                    value = match.group(group)
                except IndexError:
                    continue

                if split_char:
                    # Multiple values (implements A, B, C)
                    for item in value.split(split_char):
                        item = item.strip()
                        # Extract just the type name (ignore generics, etc)
                        type_match = re.search(r'([A-Za-z_][A-Za-z0-9_]*)', item)
                        if type_match:
                            dep = type_match.group(1)
                            # Skip keywords
                            if dep not in ['with', 'extends', 'implements', 'on']:
                                entity_result.scanned_inheritance_dependencies.append(dep)
                                LOGGER.debug(f'{entity_name} {key} {dep}')
                else:
                    entity_result.scanned_inheritance_dependencies.append(value)
                    LOGGER.debug(f'{entity_name} {key} {value}')

    def after_generated_file_results(self, analysis: Any) -> None:
        """Hook for post-processing after file results."""
        pass

    def create_unique_entity_name(self, entity: AbstractEntityResult) -> None:
        """Create unique entity name based on module and entity name."""
        if entity.module_name:
            entity.unique_name = f"{entity.module_name}/{entity.entity_name}"
        else:
            entity.unique_name = entity.entity_name