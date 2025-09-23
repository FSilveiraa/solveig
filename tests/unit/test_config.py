"""Tests for solveig.config module."""

import json
import tempfile
from json import JSONDecodeError
from pathlib import PurePath

import pytest

from solveig.config import SolveigConfig
from solveig.llm import APIType
from tests.mocks import DEFAULT_CONFIG, MockInterface


class TestSolveigConfigCore:
    """Test SolveigConfig core functionality and initialization."""

    def test_default_values(self):
        """Test default configuration values."""
        config = SolveigConfig()
        assert config.api_type == APIType.LOCAL
        assert config.api_key is None
        assert config.verbose is False
        assert config.plugins == {}
        assert config.auto_allowed_paths == []
        assert config.auto_send is False
        assert config.allow_commands is True

    def test_api_type_conversion_success(self):
        """Test API type string to enum conversion."""
        config = SolveigConfig(api_type="OPENAI")
        assert config.api_type == APIType.OPENAI

    def test_api_type_conversion_failure(self):
        """Test invalid API type string raises ValueError."""
        with pytest.raises(ValueError):
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

    @pytest.mark.no_file_mocking
    def test_parse_from_file_success(self):
        """Test successful config file parsing."""

        with tempfile.NamedTemporaryFile(mode="r+", suffix=".json") as temp_config:
            temp_config.write(DEFAULT_CONFIG.to_json())
            temp_config.flush()
            config_path = PurePath(temp_config.name)

            result = SolveigConfig(**SolveigConfig.parse_from_file(config_path))
            assert result == DEFAULT_CONFIG

    @pytest.mark.no_file_mocking
    def test_parse_from_file_malformed_json(self):
        """Test malformed JSON raises JSONDecodeError."""

        with tempfile.NamedTemporaryFile(mode="r+", suffix=".json") as temp_config:
            temp_config.write("{invalid json")  # Ensure data is written to disk
            temp_config.flush()
            config_path = temp_config.name

            with pytest.raises(JSONDecodeError):
                SolveigConfig.parse_from_file(config_path)


class TestConfigSerialization:
    """Test configuration serialization methods."""

    def test_to_dict_enum_conversion(self):
        """Test to_dict converts api_type to strings."""
        config = SolveigConfig(api_type=APIType.LOCAL)
        result = config.to_dict()
        assert result["api_type"] == "local"

    def test_to_json_works(self):
        """Test to_json produces valid JSON."""
        config = SolveigConfig(api_type=APIType.GEMINI, verbose=True)
        json_str = config.to_json()
        parsed = json.loads(json_str)
        assert parsed["verbose"] is True
        assert parsed["api_type"] == "gemini"

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
        args = ["--api-type", "local", "test prompt"]
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

    @pytest.mark.no_file_mocking
    def test_file_and_cli_merge(self):
        """Test file config merges with CLI overrides."""

        file_config = {"verbose": True, "temperature": 0.2}

        with tempfile.NamedTemporaryFile(mode="r+", suffix=".json") as temp_config:
            json.dump(file_config, temp_config)
            temp_config.flush()  # Ensure data is written to disk
            config_path = temp_config.name

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

    def test_no_commands_flag_sets_allow_commands_false(self):
        """Test --no-commands CLI flag sets allow_commands to False."""
        args = ["--no-commands", "test prompt"]
        config, prompt = SolveigConfig.parse_config_and_prompt(
            cli_args=args, interface=MockInterface()
        )
        assert config.allow_commands is False
        assert prompt == "test prompt"

    def test_allow_commands_defaults_to_true(self):
        """Test allow_commands defaults to True when not specified."""
        args = ["test prompt"]
        config, prompt = SolveigConfig.parse_config_and_prompt(
            cli_args=args, interface=MockInterface()
        )
        assert config.allow_commands is True
        assert prompt == "test prompt"
