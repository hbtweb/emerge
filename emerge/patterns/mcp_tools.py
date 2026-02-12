"""MCP tools for custom patterns system."""
from typing import Dict, Any, List, Optional
from pathlib import Path

# These tools will be added to mcp_server.py


def get_pattern_tools(mcp, source_dir_getter, graphs_getter):
    """Register pattern-related MCP tools."""
    
    # Pattern state
    _pattern_config = None
    _pattern_matcher = None
    _pattern_creator = None
    
    @mcp.tool()
    def patterns_load(force: bool = False) -> Dict[str, Any]:
        """
        Load custom patterns from .emerge/patterns.yaml.
        
        Args:
            force: Force reload even if already loaded
            
        Returns:
            Dict with loaded pattern info
        """
        nonlocal _pattern_config, _pattern_matcher, _pattern_creator
        
        source_dir = source_dir_getter()
        if not source_dir:
            return {"error": "No project loaded. Run project_scan first."}
        
        from emerge.patterns.loader import PatternLoader
        from emerge.patterns.matcher import PatternMatcher
        from emerge.patterns.creator import NodeEdgeCreator
        
        loader = PatternLoader(source_dir)
        
        if not loader.has_patterns:
            return {"status": "no_patterns", "message": f"No .emerge/patterns.yaml found in {source_dir}"}
        
        _pattern_config = loader.load(force=force)
        if _pattern_config is None:
            return {"error": "Failed to load patterns. Check YAML syntax."}
        
        _pattern_matcher = PatternMatcher(_pattern_config)
        _pattern_creator = NodeEdgeCreator(_pattern_config)
        
        return {
            "status": "loaded",
            "patterns": len(_pattern_config.patterns),
            "edge_rules": len(_pattern_config.edge_rules),
            "node_types": len(_pattern_config.node_types),
            "source_file": _pattern_config.source_file,
            "meta": {
                "name": _pattern_config.meta.name if _pattern_config.meta else "Custom Patterns",
                "frameworks": _pattern_config.meta.frameworks if _pattern_config.meta else []
            }
        }
    
    @mcp.tool()
    def patterns_list() -> List[Dict[str, Any]]:
        """
        List all loaded patterns.
        
        Returns:
            List of pattern info dicts
        """
        if _pattern_config is None:
            return [{"error": "No patterns loaded. Run patterns_load first."}]
        
        return [
            {
                "id": p.id,
                "name": p.name,
                "language": p.language or "any",
                "file_pattern": p.file_pattern,
                "creates_nodes": len(p.creates.nodes) if p.creates else 0,
                "creates_edges": len(p.creates.edges) if p.creates else 0
            }
            for p in _pattern_config.patterns
        ]
    
    @mcp.tool()
    def patterns_validate() -> Dict[str, Any]:
        """
        Validate the patterns configuration.
        
        Returns:
            Dict with validation results
        """
        source_dir = source_dir_getter()
        if not source_dir:
            return {"error": "No project loaded. Run project_scan first."}
        
        from emerge.patterns.loader import PatternLoader
        
        loader = PatternLoader(source_dir)
        errors = loader.validate()
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "patterns_file": str(source_dir / ".emerge" / "patterns.yaml")
        }
    
    @mcp.tool()
    def patterns_test(pattern_id: str, content: str) -> Dict[str, Any]:
        """
        Test a specific pattern against content.
        
        Args:
            pattern_id: ID of the pattern to test
            content: Source code content to test against
            
        Returns:
            Dict with match results
        """
        if _pattern_matcher is None:
            return {"error": "No patterns loaded. Run patterns_load first."}
        
        try:
            matches = _pattern_matcher.test_pattern(pattern_id, content)
            return {
                "pattern_id": pattern_id,
                "match_count": len(matches),
                "matches": [
                    {
                        "line": m.line,
                        "match_text": m.match_text[:100],
                        "captures": m.captures
                    }
                    for m in matches
                ]
            }
        except ValueError as e:
            return {"error": str(e)}
    
    @mcp.tool()
    def patterns_match_file(file_path: str) -> Dict[str, Any]:
        """
        Apply all patterns to a file and return matches.
        
        Args:
            file_path: Path to file (relative to project root)
            
        Returns:
            Dict with match results
        """
        if _pattern_matcher is None:
            return {"error": "No patterns loaded. Run patterns_load first."}
        
        source_dir = source_dir_getter()
        full_path = source_dir / file_path if source_dir else Path(file_path)
        
        if not full_path.exists():
            return {"error": f"File not found: {full_path}"}
        
        content = full_path.read_text(encoding="ISO-8859-1")
        
        # Detect language from extension
        ext = full_path.suffix.lower()
        lang_map = {".php": "php", ".py": "python", ".js": "javascript", ".ts": "typescript"}
        language = lang_map.get(ext)
        
        matches = _pattern_matcher.match_file(
            file_path,
            content,
            language=language,
            project_root=str(source_dir) if source_dir else None
        )
        
        return {
            "file": file_path,
            "language": language,
            "match_count": len(matches),
            "matches": [
                {
                    "pattern_id": m.pattern_id,
                    "pattern_name": m.pattern_name,
                    "line": m.line,
                    "match_text": m.match_text[:100],
                    "captures": m.captures
                }
                for m in matches
            ]
        }
    
    @mcp.tool()
    def patterns_build_graph() -> Dict[str, Any]:
        """
        Build a custom graph from all pattern matches in the project.
        
        Returns:
            Dict with graph statistics
        """
        nonlocal _pattern_creator
        
        if _pattern_config is None or _pattern_matcher is None:
            return {"error": "No patterns loaded. Run patterns_load first."}
        
        source_dir = source_dir_getter()
        if not source_dir:
            return {"error": "No project loaded."}
        
        from emerge.patterns.creator import NodeEdgeCreator
        from emerge.languages.registry import get_registry
        
        _pattern_creator = NodeEdgeCreator(_pattern_config)
        
        # Get file extensions to scan
        registry = get_registry()
        extensions = set(registry.list_extensions())
        
        # Find and process all matching files
        total_matches = 0
        files_processed = 0
        
        for file_path in source_dir.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in extensions:
                continue
            
            # Skip common ignore dirs
            parts = file_path.parts
            if any(d in parts for d in ["vendor", "node_modules", ".git", "__pycache__"]):
                continue
            
            try:
                content = file_path.read_text(encoding="ISO-8859-1")
                rel_path = str(file_path.relative_to(source_dir))
                
                ext = file_path.suffix.lower()
                lang_map = {".php": "php", ".py": "python", ".js": "javascript", ".ts": "typescript"}
                language = lang_map.get(ext)
                
                matches = _pattern_matcher.match_file(rel_path, content, language, str(source_dir))
                
                for match in matches:
                    _pattern_creator.process_match(match)
                
                total_matches += len(matches)
                files_processed += 1
            except Exception:
                continue
        
        # Apply edge rules
        edge_rules_applied = _pattern_creator.apply_edge_rules()
        
        # Get graph stats
        graph = _pattern_creator.to_networkx()
        
        return {
            "files_processed": files_processed,
            "total_matches": total_matches,
            "nodes_created": graph.number_of_nodes(),
            "edges_created": graph.number_of_edges(),
            "edge_rules_applied": len(edge_rules_applied)
        }
    
    @mcp.tool()
    def patterns_query_nodes(node_type: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Query nodes created by custom patterns.
        
        Args:
            node_type: Filter by node type (optional)
            limit: Maximum results
            
        Returns:
            List of node info
        """
        if _pattern_creator is None:
            return [{"error": "No pattern graph built. Run patterns_build_graph first."}]
        
        graph = _pattern_creator.to_networkx()
        
        results = []
        for node, attrs in graph.nodes(data=True):
            if node_type and attrs.get("type") != node_type:
                continue
            results.append({
                "id": node,
                "type": attrs.get("type"),
                "display_name": attrs.get("display_name"),
                "source_pattern": attrs.get("custom_pattern"),
                "properties": {k: v for k, v in attrs.items() if k not in ["type", "display_name", "custom_pattern"]}
            })
            if len(results) >= limit:
                break
        
        return results
    
    return {
        "patterns_load": patterns_load,
        "patterns_list": patterns_list,
        "patterns_validate": patterns_validate,
        "patterns_test": patterns_test,
        "patterns_match_file": patterns_match_file,
        "patterns_build_graph": patterns_build_graph,
        "patterns_query_nodes": patterns_query_nodes,
    }
