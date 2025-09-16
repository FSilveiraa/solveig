"""Tests for solveig.config module."""

import json
from json import JSONDecodeError

import pytest

from solveig.config import SolveigConfig
from solveig.llm import APIType
from tests.mocks import MockInterface


class TestSolveigConfigCore:
    """Test SolveigConfig core functionality and initialization."""

    def test_default_values(self):
        """Test default configuration values."""
        config = SolveigConfig()
        assert config.api_type == APIType.LOCAL
        assert config.api_key is None
        assert config.verbose is False
        assert config.plugins == {}

    def test_api_type_conversion_success(self):
        """Test API type string to enum conversion."""
        config = SolveigConfig(api_type="OPENAI")
        assert config.api_type == APIType.OPENAI

    def test_api_type_conversion_failure(self):
        """Test invalid API type string raises KeyError."""
        with pytest.raises(KeyError):
            SolveigConfig(api_type="INVALID_API_TYPE")

    def test_disk_space_parsing_success(self):
        """Test disk space parsing works."""
        config = SolveigConfig(min_disk_space_left="1.34GiB")
        assert config.min_disk_space_left == int(1.34 * 1024**3)

    def test_disk_space_parsing_failure(self):
        """Test invalid disk space format raises ValueError."""
        with pytest.raises(ValueError):
            SolveigConfig(min_disk_space_left="invalid")


class TestConfigFileParsing:
    """Test configuration file parsing functionality."""

    @pytest.mark.parametrize(
        "config_path", ["", "/nonexistent/path.json"]  # invalid path  # inexistent path
    )
    def test_parse_from_file_invalid_path(self, config_path):
        """Test parsing from invalid path returns empty dict."""
        result = SolveigConfig.parse_from_file(config_path)
        assert result == {}

    def test_parse_from_file_success(self, mock_filesystem):
        """Test successful config file parsing."""
        test_config = {"api_type": "LOCAL", "temperature": 0.7}
        config_path = "/test/config.json"
        mock_filesystem.write_file(config_path, json.dumps(test_config))

        result = SolveigConfig.parse_from_file(config_path)
        assert result == test_config

    def test_parse_from_file_malformed_json(self, mock_filesystem):
        """Test malformed JSON raises JSONDecodeError."""
        config_path = "/test/bad_config.json"
        mock_filesystem.write_file(config_path, "{invalid json")

        with pytest.raises(JSONDecodeError):
            SolveigConfig.parse_from_file(config_path)


class TestConfigSerialization:
    """Test configuration serialization methods."""

    def test_to_dict_enum_conversion(self):
        """Test to_dict converts enums to strings."""
        config = SolveigConfig(api_type=APIType.LOCAL)
        result = config.to_dict()
        assert result["api_type"] == "LOCAL"

    def test_to_json_works(self):
        """Test to_json produces valid JSON."""
        config = SolveigConfig(api_type=APIType.GEMINI, verbose=True)
        json_str = config.to_json()
        parsed = json.loads(json_str)
        assert parsed["verbose"] is True
        assert parsed["api_type"] == "GEMINI"

    def test_serialization_round_trip(self):
        """Test serialization preserves config data."""
        original = SolveigConfig(api_type=APIType.LOCAL, temperature=0.8)
        recreated = SolveigConfig(**original.to_dict())
        assert recreated.api_type == APIType.LOCAL
        assert recreated.temperature == 0.8


class TestCLIIntegration:
    """Test CLI argument parsing and integration."""

    def test_parse_config_returns_config_and_prompt(self):
        """Test CLI parsing returns config and prompt."""
        args = ["--api-type", "LOCAL", "test prompt"]
        config, prompt = SolveigConfig.parse_config_and_prompt(
            cli_args=args, interface=MockInterface()
        )
        assert isinstance(config, SolveigConfig)
        assert config.api_type == APIType.LOCAL
        assert prompt == "test prompt"

    def test_cli_overrides_work(self):
        """Test CLI arguments override defaults."""
        args = ["--temperature", "0.8", "--verbose", "test prompt"]
        config, prompt = SolveigConfig.parse_config_and_prompt(
            cli_args=args, interface=MockInterface()
        )
        assert config.temperature == 0.8
        assert config.verbose is True
        assert prompt == "test prompt"

    def test_file_and_cli_merge(self, mock_filesystem):
        """Test file config merges with CLI overrides."""
        file_config = {"verbose": True, "temperature": 0.2}
        config_path = "/test/config.json"
        mock_filesystem.write_file(config_path, json.dumps(file_config))

        args = ["--config", config_path, "--temperature", "0.5", "test prompt"]
        config, _ = SolveigConfig.parse_config_and_prompt(cli_args=args)
        assert config.verbose is True  # From file
        assert config.temperature == 0.5  # CLI override

    def test_config_parse_failure_shows_warning(self):
        """Test warning shown when config file parsing fails."""
        args = ["--config", "/nonexistent/config.json", "test prompt"]
        interface = MockInterface()

        SolveigConfig.parse_config_and_prompt(cli_args=args, interface=interface)

        assert any(
            "Failed to parse config file" in output for output in interface.outputs
        )
