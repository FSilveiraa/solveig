"""Tests for solveig.config module."""

import json
from json import JSONDecodeError
from pathlib import PurePath

import pytest

from solveig.config import SolveigConfig
from solveig.llm import APIType
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = pytest.mark.anyio


class TestSolveigConfigCore:
    """Test SolveigConfig core functionality and initialization."""

    async def test_default_values(self):
        """Test default configuration values."""
        config = SolveigConfig()
        assert config.api_type == APIType.LOCAL
        assert config.api_key == ""
        assert config.verbose is False
        assert config.plugins == {}
        assert config.auto_allowed_paths == []
        assert config.no_commands is False

    async def test_api_type_conversion_success(self):
        """Test API type string to enum conversion."""
        config = SolveigConfig(api_type="OPENAI")
        assert config.api_type == APIType.OPENAI

    async def test_api_type_conversion_failure(self):
        """Test invalid API type string raises ValueError."""
        with pytest.raises(ValueError):
            SolveigConfig(api_type="INVALID_API_TYPE")

    async def test_disk_space_parsing_success(self):
        """Test disk space parsing works."""
        config = SolveigConfig(min_disk_space_left="1.34GiB")
        assert config.min_disk_space_left == int(1.34 * 1024**3)

    async def test_disk_space_parsing_failure(self):
        """Test invalid disk space format raises ValueError."""
        with pytest.raises(ValueError):
            SolveigConfig(min_disk_space_left="invalid")


class TestConfigFileParsing:
    """Test configuration file parsing functionality."""

    @pytest.mark.parametrize(
        "config_path",
        ["", "/nonexistent/path.json"],  # invalid path  # inexistent path
    )
    async def test_parse_from_file_invalid_path(self, config_path):
        """Test parsing from invalid path returns empty dict."""
        with pytest.raises(FileNotFoundError):
            await SolveigConfig.parse_from_file(config_path)

    async def test_parse_from_file_default_path_missing(self):
        """Test parsing from missing default config path returns empty dict."""
        from unittest.mock import patch

        # Mock the DEFAULT_CONFIG_PATH to a non-existent path
        with patch(
            "solveig.config.config.DEFAULT_CONFIG_PATH",
            "/tmp/nonexistent_solveig_config.json",
        ):
            result = await SolveigConfig.parse_from_file(
                "/tmp/nonexistent_solveig_config.json"
            )
            assert result == {}

    @pytest.mark.no_file_mocking
    async def test_parse_from_file_success(self, tmp_path):
        """Test successful config file parsing."""
        config_file = tmp_path / "config.json"
        config_file.write_text(DEFAULT_CONFIG.to_json())
        result = SolveigConfig(**(await SolveigConfig.parse_from_file(PurePath(str(config_file)))))
        assert result == DEFAULT_CONFIG

    @pytest.mark.no_file_mocking
    async def test_parse_from_file_malformed_json(self, tmp_path):
        """Test malformed JSON raises JSONDecodeError."""
        config_file = tmp_path / "config.json"
        config_file.write_text("{invalid json")
        with pytest.raises(JSONDecodeError):
            await SolveigConfig.parse_from_file(str(config_file))


class TestConfigSerialization:
    """Test configuration serialization methods."""

    async def test_to_dict_enum_conversion(self):
        """Test to_dict converts api_type to strings."""
        config = SolveigConfig(api_type=APIType.LOCAL)
        result = config.to_dict()
        assert result["api_type"] == "local"

    async def test_to_json_works(self):
        """Test to_json produces valid JSON."""
        config = SolveigConfig(api_type=APIType.GEMINI, verbose=True)
        json_str = config.to_json()
        parsed = json.loads(json_str)
        assert parsed["verbose"] is True
        assert parsed["api_type"] == "gemini"

    async def test_serialization_round_trip(self):
        """Test serialization preserves config data."""
        original = SolveigConfig(api_type=APIType.LOCAL, temperature=0.8)
        recreated = SolveigConfig(**original.to_dict())
        assert recreated.api_type == APIType.LOCAL
        assert recreated.temperature == 0.8


class TestCLIIntegration:
    """Test CLI argument parsing and integration."""

    async def test_parse_config_returns_config_and_prompt(self):
        """Test CLI parsing returns config and prompt."""
        args = ["--api-type", "local", "test prompt"]
        config, prompt, _ = await SolveigConfig.parse_config_and_prompt(
            cli_args=args, interface=MockInterface()
        )
        assert isinstance(config, SolveigConfig)
        assert config.api_type == APIType.LOCAL
        assert prompt == "test prompt"

    async def test_cli_overrides_work(self):
        """Test CLI arguments override defaults."""
        args = ["-a", "openai", "--temperature", "0.8", "--verbose", "test prompt"]
        config, prompt, _ = await SolveigConfig.parse_config_and_prompt(
            cli_args=args, interface=MockInterface()
        )
        assert config.temperature == 0.8
        assert config.verbose is True
        assert config.api_type == APIType.OPENAI
        assert prompt == "test prompt"

    @pytest.mark.no_file_mocking
    async def test_file_and_cli_merge(self, tmp_path):
        """Test file config merges with CLI overrides."""
        file_config = {"api_type": "gemini", "verbose": True, "temperature": 0.2}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(file_config))

        args = ["--config", str(config_file), "--temperature", "0.5", "test prompt"]
        config, _, __ = await SolveigConfig.parse_config_and_prompt(cli_args=args)
        assert config.verbose is True  # From file
        assert config.api_type == APIType.GEMINI
        assert config.temperature == 0.5  # CLI override

    async def test_default_config_missing_shows_warning(self):
        """Test warning shown when default config file doesn't exist."""
        from unittest.mock import patch

        # Mock default config to non-existent path
        with patch(
            "solveig.config.config.DEFAULT_CONFIG_PATH", "/tmp/nonexistent_default.json"
        ):
            args = ["--api-type", "local", "test prompt"]  # Must provide required args
            interface = MockInterface()

            config, _, __ = await SolveigConfig.parse_config_and_prompt(
                cli_args=args, interface=interface
            )

            # Should succeed and show warning about missing default config
            assert any(
                "Failed to parse config file" in output for output in interface.outputs
            )

    async def test_no_commands_flag_sets_no_commands_true(self):
        """Test --no-commands CLI flag sets allow_commands to False."""
        args = ["--url", "http://localhost:5001/api/v1", "--no-commands", "test prompt"]
        config, prompt, _ = await SolveigConfig.parse_config_and_prompt(
            cli_args=args, interface=MockInterface()
        )
        assert config.no_commands is True
        assert prompt == "test prompt"

    async def test_allow_commands_defaults_to_true(self):
        """Test allow_commands defaults to True when not specified."""
        args = ["-a", "local", "test prompt"]
        config, prompt, _ = await SolveigConfig.parse_config_and_prompt(
            cli_args=args, interface=MockInterface()
        )
        assert config.no_commands is False
        assert prompt == "test prompt"
