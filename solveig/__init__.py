"""
Solveig: A safe bridge between AI assistants and your computer.

This package provides a security-focused interface that translates
LLM responses into structured requests (file operations and shell commands)
that require explicit user approval before execution.
"""

__version__ = "0.1.0"
__author__ = "Francisco"
__license__ = "MIT"

# Import main classes for easy access
from .config import SolveigConfig
from .llm import APIType, get_instructor_client

__all__ = ["SolveigConfig", "APIType", "get_instructor_client", "__version__"]
