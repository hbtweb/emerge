"""Pattern loader - loads and validates .emerge/patterns.yaml files."""
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
import yaml
import coloredlogs
from emerge.log import Logger
from emerge.patterns.config import PatternConfig, PatternDefinition

LOGGER = Logger(logging.getLogger("patterns.loader"))
coloredlogs.install(level="E", logger=LOGGER.logger(), fmt=Logger.log_format)

PATTERNS_FILE = ".emerge/patterns.yaml"

class PatternLoader:
    """Loads and validates custom pattern configurations."""
    
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self._config: Optional[PatternConfig] = None
        self._patterns_path: Optional[Path] = None
    
    @property
    def patterns_path(self) -> Optional[Path]:
        if self._patterns_path is None:
            path = self.project_root / PATTERNS_FILE
            if path.exists():
                self._patterns_path = path
        return self._patterns_path
    
    @property
    def has_patterns(self) -> bool:
        return self.patterns_path is not None
    
    def load(self, force: bool = False) -> Optional[PatternConfig]:
        """Load patterns from .emerge/patterns.yaml."""
        if self._config is not None and not force:
            return self._config
            
        if not self.has_patterns:
            LOGGER.debug(f"No patterns file found at {self.project_root / PATTERNS_FILE}")
            return None
        
        try:
            with open(self.patterns_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            
            if data is None:
                LOGGER.warning(f"Empty patterns file: {self.patterns_path}")
                return None
            
            self._config = PatternConfig.from_dict(data, str(self.patterns_path))
            LOGGER.info(f"Loaded {len(self._config.patterns)} patterns from {self.patterns_path}")
            return self._config
            
        except yaml.YAMLError as e:
            LOGGER.error(f"YAML parse error in {self.patterns_path}: {e}")
            return None
        except Exception as e:
            LOGGER.error(f"Failed to load patterns: {e}")
            return None
    
    def reload(self) -> Optional[PatternConfig]:
        """Force reload patterns from file."""
        self._config = None
        self._patterns_path = None
        return self.load(force=True)
    
    def validate(self) -> List[str]:
        """Validate the patterns configuration. Returns list of errors."""
        errors = []
        config = self.load()
        
        if config is None:
            return ["No patterns configuration loaded"]
        
        # Check pattern IDs are unique
        ids = set()
        for pattern in config.patterns:
            if pattern.id in ids:
                errors.append(f"Duplicate pattern ID: {pattern.id}")
            ids.add(pattern.id)
            
            # Validate pattern has required fields
            if not pattern.match:
                errors.append(f"Pattern '{pattern.id}' missing 'match' definition")
            elif pattern.match.compiled is None:
                errors.append(f"Pattern '{pattern.id}' has invalid regex")
        
        # Validate edge rules reference valid patterns
        for rule in config.edge_rules:
            if rule.from_endpoint.pattern_id:
                if rule.from_endpoint.pattern_id not in ids:
                    errors.append(f"Edge rule '{rule.id}' references unknown pattern: {rule.from_endpoint.pattern_id}")
            if rule.to_endpoint.pattern_id:
                if rule.to_endpoint.pattern_id not in ids:
                    errors.append(f"Edge rule '{rule.id}' references unknown pattern: {rule.to_endpoint.pattern_id}")
        
        return errors


def load_patterns(project_root: Path) -> Optional[PatternConfig]:
    """Convenience function to load patterns from a project."""
    loader = PatternLoader(project_root)
    return loader.load()
