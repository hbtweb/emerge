"""
Pattern matcher - applies patterns to source code files.
"""

import logging
import fnmatch
from pathlib import Path
from typing import Optional, List, Dict, Any, Iterator
from dataclasses import dataclass, field

import coloredlogs

from emerge.log import Logger
from emerge.patterns.config import (
    PatternConfig,
    PatternDefinition,
    MatchType,
    CaptureDefinition,
)
from emerge.patterns.transforms import CaptureTransforms, create_transforms

LOGGER = Logger(logging.getLogger('patterns.matcher'))
coloredlogs.install(level='E', logger=LOGGER.logger(), fmt=Logger.log_format)


@dataclass
class PatternMatch:
    """Represents a single pattern match in a file."""
    pattern_id: str
    pattern_name: str
    file_path: str
    line_number: int
    match_text: str
    captures: Dict[str, str] = field(default_factory=dict)
    
    # Context for node/edge creation
    raw_captures: Dict[str, str] = field(default_factory=dict)  # Before transforms


@dataclass
class FileMatches:
    """All pattern matches in a single file."""
    file_path: str
    language: Optional[str] = None
    matches: List[PatternMatch] = field(default_factory=list)
    
    @property
    def match_count(self) -> int:
        return len(self.matches)
    
    def get_matches_by_pattern(self, pattern_id: str) -> List[PatternMatch]:
        """Get all matches for a specific pattern."""
        return [m for m in self.matches if m.pattern_id == pattern_id]


class PatternMatcher:
    """
    Applies custom patterns to source code files.
    
    Usage:
        matcher = PatternMatcher(config)
        
        # Match single file
        matches = matcher.match_file('/path/to/file.php', content)
        
        # Match multiple files
        for file_matches in matcher.match_files(file_list):
            process(file_matches)
    """
    
    def __init__(self, config: PatternConfig):
        """
        Initialize the pattern matcher.
        
        Args:
            config: Pattern configuration
        """
        self.config = config
        
        # Build pattern lookup by language
        self._patterns_by_language: Dict[str, List[PatternDefinition]] = {}
        self._universal_patterns: List[PatternDefinition] = []
        
        for pattern in config.patterns:
            if pattern.language is None or pattern.language == 'any':
                self._universal_patterns.append(pattern)
            else:
                lang = pattern.language.lower()
                if lang not in self._patterns_by_language:
                    self._patterns_by_language[lang] = []
                self._patterns_by_language[lang].append(pattern)
    
    def get_applicable_patterns(
        self,
        file_path: str,
        language: Optional[str] = None
    ) -> List[PatternDefinition]:
        """
        Get patterns that apply to a file.
        
        Args:
            file_path: Path to the file
            language: Language of the file (optional)
            
        Returns:
            List of applicable patterns
        """
        applicable = []
        
        # Add language-specific patterns
        if language:
            lang_patterns = self._patterns_by_language.get(language.lower(), [])
            applicable.extend(lang_patterns)
        
        # Add universal patterns
        applicable.extend(self._universal_patterns)
        
        # Filter by file pattern and exclusions
        result = []
        for pattern in applicable:
            # Check file pattern
            if pattern.file_pattern:
                if not fnmatch.fnmatch(file_path, pattern.file_pattern):
                    continue
            
            # Check exclusions
            excluded = False
            for exclude in pattern.exclude:
                if fnmatch.fnmatch(file_path, exclude):
                    excluded = True
                    break
            
            if not excluded:
                result.append(pattern)
        
        return result
    
    def match_file(
        self,
        file_path: str,
        content: str,
        language: Optional[str] = None
    ) -> FileMatches:
        """
        Apply all applicable patterns to a file.
        
        Args:
            file_path: Path to the file
            content: File content
            language: Language of the file (optional)
            
        Returns:
            FileMatches with all matches found
        """
        file_matches = FileMatches(file_path=file_path, language=language)
        
        # Create transforms with file context
        transforms = create_transforms(file_content=content, file_path=file_path)
        
        # Get applicable patterns
        patterns = self.get_applicable_patterns(file_path, language)
        
        if not patterns:
            return file_matches
        
        # Split content into lines for line number tracking
        lines = content.split('\n')
        line_offsets = self._calculate_line_offsets(content)
        
        # Apply each pattern
        for pattern in patterns:
            if pattern.match is None:
                continue
            
            if pattern.match.type != MatchType.REGEX:
                LOGGER.debug(f'Skipping non-regex pattern: {pattern.id}')
                continue
            
            if pattern.match.compiled is None:
                LOGGER.warning(f'Pattern {pattern.id} has no compiled regex')
                continue
            
            # Find all matches
            for match in pattern.match.compiled.finditer(content):
                # Calculate line number
                line_num = self._get_line_number(match.start(), line_offsets)
                
                # Extract captures
                captures = {}
                raw_captures = {}
                
                for capture_def in pattern.captures:
                    try:
                        group_value = match.group(capture_def.group)
                        if group_value is None:
                            group_value = capture_def.default or ''
                    except IndexError:
                        group_value = capture_def.default or ''
                    
                    raw_captures[capture_def.name] = group_value
                    
                    # Apply transforms
                    transformed = transforms.apply(group_value, capture_def.transform)
                    captures[capture_def.name] = transformed
                
                # Create match result
                pattern_match = PatternMatch(
                    pattern_id=pattern.id,
                    pattern_name=pattern.name,
                    file_path=file_path,
                    line_number=line_num,
                    match_text=match.group(0),
                    captures=captures,
                    raw_captures=raw_captures,
                )
                
                file_matches.matches.append(pattern_match)
        
        return file_matches
    
    def match_files(
        self,
        files: List[Dict[str, Any]],
    ) -> Iterator[FileMatches]:
        """
        Apply patterns to multiple files.
        
        Args:
            files: List of dicts with 'path', 'content', and optional 'language'
            
        Yields:
            FileMatches for each file
        """
        for file_info in files:
            file_path = file_info.get('path', '')
            content = file_info.get('content', '')
            language = file_info.get('language')
            
            matches = self.match_file(file_path, content, language)
            if matches.match_count > 0:
                yield matches
    
    def _calculate_line_offsets(self, content: str) -> List[int]:
        """Calculate byte offsets for each line."""
        offsets = [0]
        for i, char in enumerate(content):
            if char == '\n':
                offsets.append(i + 1)
        return offsets
    
    def _get_line_number(self, position: int, line_offsets: List[int]) -> int:
        """Get line number (1-indexed) for a position in content."""
        for i, offset in enumerate(line_offsets):
            if position < offset:
                return i
        return len(line_offsets)
    
    def test_pattern(
        self,
        pattern_id: str,
        content: str,
        file_path: str = 'test.txt'
    ) -> List[PatternMatch]:
        """
        Test a specific pattern against content.
        
        Args:
            pattern_id: ID of the pattern to test
            content: Content to test against
            file_path: Mock file path for context
            
        Returns:
            List of matches found
        """
        # Find the pattern
        pattern = None
        for p in self.config.patterns:
            if p.id == pattern_id:
                pattern = p
                break
        
        if pattern is None:
            raise ValueError(f'Pattern not found: {pattern_id}')
        
        # Create a temporary config with just this pattern
        temp_config = PatternConfig(
            version=self.config.version,
            patterns=[pattern]
        )
        
        temp_matcher = PatternMatcher(temp_config)
        matches = temp_matcher.match_file(file_path, content, pattern.language)
        
        return matches.matches


def match_patterns(
    config: PatternConfig,
    file_path: str,
    content: str,
    language: Optional[str] = None
) -> FileMatches:
    """
    Convenience function to match patterns in a file.
    
    Args:
        config: Pattern configuration
        file_path: Path to the file
        content: File content
        language: Language of the file
        
    Returns:
        FileMatches with all matches
    """
    matcher = PatternMatcher(config)
    return matcher.match_file(file_path, content, language)
