"""Tests for solveig.config module."""

import json
import tempfile
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from solveig.config import SolveigConfig
from solveig.llm import APIType


class TestSolveigConfig:
    """Test SolveigConfig class functionality."""

    def test_default_config_values(self):
        """Test default configuration values."""
        config = SolveigConfig()
        assert config.url == "http://localhost:5001/v1/"
        assert config.api_type == APIType.OPENAI
        assert config.api_key is None
        assert config.model is None
        assert config.temperature == 0
        assert config.add_examples is False
        assert config.add_os_info is False
        assert config.exclude_username is False
        assert config.max_output_lines == 6
        assert config.max_output_size == 100
        assert config.verbose is False

    def test_post_init_api_type_conversion(self):
        """Test API type string conversion during post init."""
        config = SolveigConfig(api_type="OPENAI")
        assert config.api_type == APIType.OPENAI
        
        config = SolveigConfig(api_type="KOBOLDCPP")
        assert config.api_type == APIType.KOBOLDCPP

    def test_post_init_disk_space_parsing(self):
        """Test disk space parsing during post init."""
        config = SolveigConfig(min_disk_space_left="2GB")
        assert config.min_disk_space_left == 2000000000
        
        config = SolveigConfig(min_disk_space_left="1GiB")
        assert config.min_disk_space_left == 1024**3

    def test_parse_from_file_nonexistent(self):
        """Test parsing from non-existent file returns None."""
        result = SolveigConfig.parse_from_file("/nonexistent/path")
        assert result is None

    def test_parse_from_file_empty_path(self):
        """Test parsing with empty path returns None."""
        result = SolveigConfig.parse_from_file("")
        assert result is None

    def test_parse_from_file_none_path(self):
        """Test parsing with None path returns None."""
        result = SolveigConfig.parse_from_file(None)
        assert result is None

    def test_parse_from_file_success(self):
        """Test successful parsing from file."""
        test_config = {
            "api_type": "KOBOLDCPP",
            "temperature": 0.7,
            "verbose": True
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(test_config, f)
            temp_path = f.name
        
        try:
            result = SolveigConfig.parse_from_file(temp_path)
            assert result == test_config
        finally:
            Path(temp_path).unlink()

    @patch('argparse.ArgumentParser.parse_args')
    def test_parse_config_and_prompt_defaults(self, mock_parse_args):
        """Test parse_config_and_prompt with default arguments."""
        # Mock command line arguments using argparse.Namespace
        mock_args = Namespace(
            config='/nonexistent/config.json',
            url=None,
            api_type=None,
            api_key=None,
            model=None,
            temperature=None,
            add_examples=None,
            add_os_info=None,
            exclude_username=None,
            max_output_lines=None,
            max_output_size=None,
            min_disk_space_left='1GiB',
            verbose=None,
            prompt='test prompt'
        )
        mock_parse_args.return_value = mock_args
        
        config, prompt = SolveigConfig.parse_config_and_prompt()
        
        assert isinstance(config, SolveigConfig)
        assert prompt == 'test prompt'
        assert config.url == "http://localhost:5001/v1/"  # Default value

    @patch('argparse.ArgumentParser.parse_args')
    def test_parse_config_and_prompt_cli_overrides(self, mock_parse_args):
        """Test that CLI arguments override file config."""
        # Mock command line arguments with overrides using argparse.Namespace
        mock_args = Namespace(
            config='/nonexistent/config.json',
            url='http://custom-url:8080/v1',
            api_type='KOBOLDCPP',
            api_key='custom-key',
            model='custom-model',
            temperature=0.8,
            add_examples=True,
            add_os_info=True,
            exclude_username=True,
            max_output_lines=20,
            max_output_size=500,
            min_disk_space_left='2GB',
            verbose=True,
            prompt=None
        )
        mock_parse_args.return_value = mock_args
        
        config, prompt = SolveigConfig.parse_config_and_prompt()
        
        assert config.url == 'http://custom-url:8080/v1'
        assert config.api_type == APIType.KOBOLDCPP
        assert config.api_key == 'custom-key'
        assert config.model == 'custom-model'
        assert config.temperature == 0.8
        assert config.add_examples is True
        assert config.add_os_info is True
        assert config.exclude_username is True
        assert config.max_output_lines == 20
        assert config.max_output_size == 500
        assert config.verbose is True
        assert prompt is None

    @patch('builtins.print')
    @patch('argparse.ArgumentParser.parse_args')
    def test_parse_config_file_warning(self, mock_parse_args, mock_print):
        """Test warning when config file parsing fails."""
        mock_args = Namespace(
            config='/nonexistent/config.json',
            url=None,
            api_type=None,
            api_key=None,
            model=None,
            temperature=None,
            add_examples=None,
            add_os_info=None,
            exclude_username=None,
            max_output_lines=None,
            max_output_size=None,
            min_disk_space_left='1GiB',
            verbose=None,
            prompt='test'
        )
        mock_parse_args.return_value = mock_args
        
        SolveigConfig.parse_config_and_prompt()
        
        mock_print.assert_called_with("Warning: Failed to parse config file, falling back to defaults")