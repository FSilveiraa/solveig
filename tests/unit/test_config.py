"""Tests for solveig.config module."""

import json
from json import JSONDecodeError

import pytest
from argparse import Namespace
from unittest.mock import patch

from solveig.config import SolveigConfig
from solveig.llm import APIType
from tests.mocks import MockInterface


class TestSolveigConfigCore:
    """Test SolveigConfig core functionality and initialization."""

    def test_default_values(self):
        """Test default configuration values we're strict about."""
        config = SolveigConfig()
        
        # Network and API settings
        assert config.api_type == APIType.LOCAL
        assert config.api_key is None
        assert config.model is None
        
        # Prompt and display settings
        assert config.add_examples is False
        assert config.add_os_info is False
        assert config.exclude_username is False
        
        # System settings
        assert config.verbose is False
        assert config.plugins == {}

    @pytest.mark.parametrize("api_type_str,expected_enum", [
        ("OPENAI", APIType.OPENAI),
        ("LOCAL", APIType.LOCAL),
    ])
    def test_api_type_conversion_success(self, api_type_str, expected_enum):
        """Test successful API type string to enum conversion."""
        config = SolveigConfig(api_type=api_type_str)
        assert config.api_type == expected_enum

    def test_api_type_conversion_failure(self):
        """Test invalid API type string raises KeyError."""
        with pytest.raises(KeyError):
            SolveigConfig(api_type="INVALID_API_TYPE")

    @pytest.mark.parametrize("size_input,expected_bytes", [
        ("2GB", 2000000000),
        ("1GiB", 1073741824),
        ("500MB", 500000000),
        ("1.5GiB", int(1.5 * 1024**3)),
        (1024, 1024),  # Already an int
        ("1024", 1024),  # String integer
    ])
    def test_disk_space_parsing_success(self, size_input, expected_bytes):
        """Test successful disk space parsing with various formats."""
        config = SolveigConfig(min_disk_space_left=size_input)
        assert config.min_disk_space_left == expected_bytes

    @pytest.mark.parametrize("invalid_size", [
        "invalid",
        "1.5XB", 
        "",
        "GB",
    ])
    def test_disk_space_parsing_failure(self, invalid_size):
        """Test invalid disk space formats raise ValueError."""
        with pytest.raises(ValueError):
            SolveigConfig(min_disk_space_left=invalid_size)


class TestConfigFileParsing:
    """Test configuration file parsing functionality."""

    @pytest.mark.parametrize("invalid_path", [
        "/nonexistent/path.json",
        "",
        None,
    ])
    def test_parse_from_file_invalid_paths(self, invalid_path):
        """Test parsing from invalid/nonexistent paths returns empty dict."""
        result = SolveigConfig.parse_from_file(invalid_path)
        assert result == {}

    def test_parse_from_file_success(self, mock_all_file_operations):
        """Test successful config file parsing."""
        test_config = {
            "api_type": "LOCAL", 
            "temperature": 0.7, 
            "verbose": True,
            "plugins": {"test_plugin": {"enabled": True}}
        }
        config_path = "/test/config.json"
        mock_all_file_operations.write_file(
            config_path, json.dumps(test_config, indent=2)
        )
        
        result = SolveigConfig.parse_from_file(config_path)
        assert result == test_config

    def test_parse_from_file_malformed_json(self, mock_all_file_operations):
        """Test malformed JSON file returns empty dict."""
        config_path = "/test/bad_config.json"
        mock_all_file_operations.write_file(config_path, "{invalid json content")
        
        with pytest.raises(JSONDecodeError):
            SolveigConfig.parse_from_file(config_path)


class TestConfigSerialization:
    """Test configuration serialization methods."""

    def test_to_dict_basic(self):
        """Test basic dictionary serialization."""
        config = SolveigConfig(
            api_type=APIType.LOCAL,
            temperature=0.5,
            verbose=True
        )
        
        result = config.to_dict()
        
        # Verify enum conversion
        assert result["api_type"] == "LOCAL"
        assert result["temperature"] == 0.5
        assert result["verbose"] is True
        # Verify all fields present
        assert "url" in result
        assert "plugins" in result

    def test_serialization_round_trip(self):
        """Test that serialization -> deserialization preserves config."""
        original_config = SolveigConfig(
            api_type=APIType.LOCAL,
            temperature=0.8,
            model="test-model",
            plugins={"test": {"value": 42}}
        )
        
        # Serialize and deserialize
        config_dict = original_config.to_dict() 
        recreated_config = SolveigConfig(**config_dict)
        
        # Compare important fields
        assert recreated_config.api_type == APIType.LOCAL
        assert recreated_config.temperature == 0.8
        assert recreated_config.model == "test-model"
        assert recreated_config.plugins == {"test": {"value": 42}}


class TestCLIIntegration:
    """Test CLI argument parsing and integration."""

    def create_mock_args(self, **overrides):
        """Helper to create mock CLI arguments with defaults."""
        default_args = {
            "config": "/nonexistent/config.json",
            "url": None,
            "api_type": None,
            "api_key": None,
            "model": None,
            "temperature": None,
            "add_examples": None,
            "add_os_info": None,
            "exclude_username": None,
            "max_output_lines": None,
            "max_output_size": None,
            "min_disk_space_left": "1GiB",
            "verbose": None,
            "prompt": "test prompt",
        }
        default_args.update(overrides)
        return Namespace(**default_args)

    @patch("argparse.ArgumentParser.parse_args")
    def test_parse_config_defaults(self, mock_parse_args):
        """Test parsing with all default values."""
        mock_parse_args.return_value = self.create_mock_args()
        
        config, prompt = SolveigConfig.parse_config_and_prompt()
        
        assert isinstance(config, SolveigConfig)
        assert prompt == "test prompt"
        assert config.url == "http://localhost:5001/v1/"  # Default value

    @patch("argparse.ArgumentParser.parse_args")
    def test_parse_config_cli_overrides(self, mock_parse_args):
        """Test CLI arguments override defaults and file config."""
        mock_parse_args.return_value = self.create_mock_args(
            url="http://custom-url:8080/v1",
            api_type="LOCAL",
            api_key="custom-key", 
            model="custom-model",
            temperature=0.8,
            add_examples=True,
            verbose=True,
            prompt=None
        )
        
        config, prompt = SolveigConfig.parse_config_and_prompt()
        
        assert config.url == "http://custom-url:8080/v1"
        assert config.api_type == APIType.LOCAL
        assert config.api_key == "custom-key"
        assert config.model == "custom-model"
        assert config.temperature == 0.8
        assert config.add_examples is True
        assert config.verbose is True
        assert prompt is None

    @patch("argparse.ArgumentParser.parse_args") 
    def test_config_file_cli_merge(self, mock_parse_args, mock_all_file_operations):
        """Test merging file config with CLI overrides."""
        # Setup config file with some values
        file_config = {
            "api_type": "LOCAL",
            "verbose": True,
            "plugins": {"file_plugin": {"enabled": True}}
        }
        config_path = "/test/merge_config.json"
        mock_all_file_operations.write_file(
            config_path, json.dumps(file_config)
        )
        
        # CLI args that should override some file values
        mock_parse_args.return_value = self.create_mock_args(
            config=config_path,
            temperature=0.5,  # New value not in file
            verbose=False,    # Override file value
        )
        
        config, prompt = SolveigConfig.parse_config_and_prompt()
        
        # File value preserved when not overridden
        assert config.api_type == APIType.LOCAL
        assert config.plugins == {"file_plugin": {"enabled": True}}
        # CLI override takes precedence  
        assert config.verbose is False
        # CLI-only value added
        assert config.temperature == 0.5

    @patch("argparse.ArgumentParser.parse_args")
    def test_config_file_parse_failure_warning(self, mock_parse_args):
        """Test warning display when config file parsing fails."""
        mock_parse_args.return_value = self.create_mock_args(
            config="/nonexistent/config.json"
        )
        mock_interface = MockInterface()
        
        config, prompt = SolveigConfig.parse_config_and_prompt(
            interface=mock_interface
        )
        
        # Should display warning about failed config file parsing
        warning_found = any(
            "Failed to parse config file, falling back to defaults" in output
            for output in mock_interface.outputs
        )
        assert warning_found
        
        # Should still return valid config with defaults
        assert isinstance(config, SolveigConfig)
        assert config.url == "http://localhost:5001/v1/"  # Default value