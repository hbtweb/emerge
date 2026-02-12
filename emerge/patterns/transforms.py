"""
Capture transforms for pattern matching.
Transforms extract and normalize captured values from regex matches.
"""

import logging
import re
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable, Union

import coloredlogs

from emerge.log import Logger

LOGGER = Logger(logging.getLogger('patterns.transforms'))
coloredlogs.install(level='E', logger=LOGGER.logger(), fmt=Logger.log_format)


class CaptureTransforms:
    """
    Collection of transform functions for captured values.
    
    Transforms normalize and extract data from raw regex captures.
    Multiple transforms can be chained together.
    
    Available transforms:
    - trim: Remove leading/trailing whitespace
    - lowercase: Convert to lowercase
    - uppercase: Convert to uppercase
    - strip_quotes: Remove surrounding quotes
    - resolve_class: Resolve to FQCN using namespace/use statements
    - normalize_path: Normalize file path separators
    - extract_class: Extract class name from callable pattern
    - extract_method: Extract method name from callable pattern
    """
    
    def __init__(self, file_content: Optional[str] = None, file_path: Optional[str] = None):
        """
        Initialize transforms with file context.
        
        Args:
            file_content: Content of the file being parsed (for namespace resolution)
            file_path: Path to the file being parsed
        """
        self.file_content = file_content
        self.file_path = file_path
        
        # Cache for namespace/use statement resolution
        self._namespace: Optional[str] = None
        self._use_statements: Optional[Dict[str, str]] = None
        
        # Register transform functions
        self._transforms: Dict[str, Callable[[str], str]] = {
            'trim': self.trim,
            'lowercase': self.lowercase,
            'uppercase': self.uppercase,
            'strip_quotes': self.strip_quotes,
            'resolve_class': self.resolve_class,
            'normalize_path': self.normalize_path,
            'extract_class': self.extract_class,
            'extract_method': self.extract_method,
        }
    
    def apply(self, value: str, transforms: Union[str, List[str], None]) -> str:
        """
        Apply one or more transforms to a value.
        
        Args:
            value: The captured value
            transforms: Single transform name, list of transforms, or None
            
        Returns:
            Transformed value
        """
        if transforms is None:
            return value
        
        if isinstance(transforms, str):
            transforms = [transforms]
        
        result = value
        for transform_name in transforms:
            transform_func = self._transforms.get(transform_name)
            if transform_func:
                try:
                    result = transform_func(result)
                except Exception as e:
                    LOGGER.debug(f'Transform {transform_name} failed on "{value}": {e}')
            else:
                LOGGER.warning(f'Unknown transform: {transform_name}')
        
        return result
    
    # ========================================================================
    # Basic Transforms
    # ========================================================================
    
    def trim(self, value: str) -> str:
        """Remove leading and trailing whitespace."""
        return value.strip()
    
    def lowercase(self, value: str) -> str:
        """Convert to lowercase."""
        return value.lower()
    
    def uppercase(self, value: str) -> str:
        """Convert to uppercase."""
        return value.upper()
    
    def strip_quotes(self, value: str) -> str:
        """Remove surrounding single or double quotes."""
        value = value.strip()
        if len(value) >= 2:
            if (value[0] == '"' and value[-1] == '"') or \
               (value[0] == "'" and value[-1] == "'"):
                return value[1:-1]
        return value
    
    def normalize_path(self, value: str) -> str:
        """Normalize path separators and resolve ../ components."""
        # Convert backslashes to forward slashes
        normalized = value.replace('\\', '/')
        # Use pathlib to normalize
        try:
            path = Path(normalized)
            return str(path)
        except Exception:
            return normalized
    
    # ========================================================================
    # PHP-specific Transforms
    # ========================================================================
    
    def resolve_class(self, value: str) -> str:
        """
        Resolve a class name to its fully qualified name.
        
        Uses the file's namespace and use statements to resolve:
        - "ClassName" -> "Namespace\\ClassName" (from current namespace)
        - "Alias" -> "Full\\Path\\Class" (from use statement)
        - "Relative\\Path" -> "Namespace\Relative\\Path"
        """
        value = value.strip()
        
        # Already fully qualified
        if value.startswith('\\'):
            return value[1:]  # Remove leading backslash
        
        # Parse namespace and use statements if not cached
        if self._use_statements is None:
            self._parse_namespace_context()
        
        # Check if it's an aliased import
        if self._use_statements and value in self._use_statements:
            return self._use_statements[value]
        
        # Check if it's a partial path matching a use statement
        if self._use_statements:
            parts = value.split('\\')
            if parts[0] in self._use_statements:
                base = self._use_statements[parts[0]]
                return base + '\\' + '\\'.join(parts[1:]) if len(parts) > 1 else base
        
        # Prepend current namespace
        if self._namespace:
            return f'{self._namespace}\\{value}'
        
        return value
    
    def _parse_namespace_context(self) -> None:
        """Parse namespace and use statements from file content."""
        self._namespace = None
        self._use_statements = {}
        
        if not self.file_content:
            return
        
        # Find namespace declaration
        namespace_match = re.search(
            r'^\s*namespace\s+([\w\\]+)\s*;',
            self.file_content,
            re.MULTILINE
        )
        if namespace_match:
            self._namespace = namespace_match.group(1)
        
        # Find use statements
        # Matches: use Foo\Bar; use Foo\Bar as Alias; use Foo\Bar\{Baz, Qux};
        use_pattern = re.compile(
            r'^\s*use\s+([\w\\]+)(?:\s+as\s+(\w+))?\s*;',
            re.MULTILINE
        )
        
        for match in use_pattern.finditer(self.file_content):
            full_class = match.group(1)
            alias = match.group(2)
            
            if alias:
                self._use_statements[alias] = full_class
            else:
                # Extract class name from full path
                class_name = full_class.split('\\')[-1]
                self._use_statements[class_name] = full_class
        
        # Handle grouped use statements: use Foo\Bar\{Baz, Qux};
        group_pattern = re.compile(
            r'^\s*use\s+([\w\\]+)\\\{([^}]+)\}\s*;',
            re.MULTILINE
        )
        
        for match in group_pattern.finditer(self.file_content):
            base = match.group(1)
            classes = match.group(2)
            
            for class_part in classes.split(','):
                class_part = class_part.strip()
                if ' as ' in class_part:
                    parts = class_part.split(' as ')
                    class_name = parts[0].strip()
                    alias = parts[1].strip()
                    self._use_statements[alias] = f'{base}\\{class_name}'
                else:
                    self._use_statements[class_part] = f'{base}\\{class_part}'
    
    def extract_class(self, value: str) -> str:
        """
        Extract class name from a PHP callable pattern.
        
        Handles:
        - [, 'method'] -> current class
        - [ClassName::class, 'method'] -> ClassName
        - ['ClassName', 'method'] -> ClassName
        - [new ClassName(), 'method'] -> ClassName
        - 'ClassName::method' -> ClassName
        """
        value = value.strip()
        
        # Static method string: 'ClassName::method'
        if '::' in value and not value.endswith('::class'):
            parts = value.split('::')
            return self.strip_quotes(parts[0])
        
        # Array callable patterns
        # [, 'method'] -> returns  (caller should handle)
        if '' in value:
            return ''
        
        # [ClassName::class, 'method']
        class_match = re.search(r'([\w\\]+)::class', value)
        if class_match:
            return self.resolve_class(class_match.group(1))
        
        # ['ClassName', 'method'] or ["ClassName", "method"]
        string_match = re.search(r"['\"]([\w\\]+)['\"]", value)
        if string_match:
            return self.resolve_class(string_match.group(1))
        
        # new ClassName()
        new_match = re.search(r'new\s+([\w\\]+)', value)
        if new_match:
            return self.resolve_class(new_match.group(1))
        
        return value
    
    def extract_method(self, value: str) -> str:
        """
        Extract method name from a PHP callable pattern.
        
        Handles:
        - [, 'method'] -> method
        - [ClassName::class, 'method'] -> method
        - 'ClassName::method' -> method
        """
        value = value.strip()
        
        # Static method string: 'ClassName::method'
        if '::' in value and not value.endswith('::class'):
            parts = value.split('::')
            return self.strip_quotes(parts[-1])
        
        # Array callable: last quoted string is usually the method
        # Look for the second quoted string in array
        matches = re.findall(r"['\"]([\w]+)['\"]", value)
        if len(matches) >= 2:
            return matches[-1]
        if len(matches) == 1:
            return matches[0]
        
        return value


def create_transforms(file_content: Optional[str] = None, file_path: Optional[str] = None) -> CaptureTransforms:
    """
    Create a CaptureTransforms instance with file context.
    
    Args:
        file_content: Content of the file being parsed
        file_path: Path to the file being parsed
        
    Returns:
        CaptureTransforms instance
    """
    return CaptureTransforms(file_content=file_content, file_path=file_path)
