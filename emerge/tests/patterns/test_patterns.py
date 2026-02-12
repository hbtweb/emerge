"""Tests for the custom patterns system."""
import pytest
from emerge.patterns import PatternConfig, PatternMatcher, CaptureTransforms


class TestPatternConfig:
    def test_parse_simple_pattern(self):
        data = {
            "version": "1.0",
            "patterns": [{
                "id": "test",
                "name": "Test",
                "match": {"type": "regex", "pattern": r"test\(\)"},
                "captures": [],
                "creates": {}
            }]
        }
        config = PatternConfig.from_dict(data)
        assert len(config.patterns) == 1
        assert config.patterns[0].id == "test"


class TestPatternMatcher:
    def test_match_simple_pattern(self):
        config = PatternConfig.from_dict({
            "version": "1.0",
            "patterns": [{
                "id": "test",
                "name": "Test",
                "match": {"type": "regex", "pattern": r"hello\s+(\w+)"},
                "captures": [{"name": "name", "group": 1}],
                "creates": {}
            }]
        })
        matcher = PatternMatcher(config)
        matches = matcher.match_file("test.txt", "hello world", None)
        assert matches.match_count == 1
        assert matches.matches[0].captures["name"] == "world"


class TestCaptureTransforms:
    def test_trim(self):
        t = CaptureTransforms()
        assert t.apply("  hello  ", "trim") == "hello"

    def test_lowercase(self):
        t = CaptureTransforms()
        assert t.apply("HELLO", "lowercase") == "hello"

    def test_chain(self):
        t = CaptureTransforms()
        assert t.apply("  HELLO  ", ["trim", "lowercase"]) == "hello"
