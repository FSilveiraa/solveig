from solveig import APIType, SolveigConfig
from solveig.schema import LLMMessage
from solveig.schema.requirement import (
    CommandRequirement,
    CopyRequirement,
    DeleteRequirement,
    MoveRequirement,
    ReadRequirement,
    WriteRequirement,
)

from .interface import MockInterface

DEFAULT_CONFIG = SolveigConfig(
    api_type=APIType.OPENAI,
    api_key="test-key",
    url="test-url",
    model="test-model",
    temperature=0.0,
    verbose=False,
    min_disk_space_left="1gb",
)

VERBOSE_CONFIG = SolveigConfig(
    api_type=APIType.OPENAI,
    api_key="test-key",
    url="test-url",
    model="test-model",
    temperature=0.0,
    verbose=True,
    min_disk_space_left="1gb",
)

# Create test requirements using real requirement classes (will be mocked at utils.file level)
ALL_REQUIREMENTS_MESSAGE = LLMMessage(
    comment="I need to read, write, run commands, move, copy, and delete files",
    requirements=[
        ReadRequirement(
            path="/test/file.txt", only_read_metadata=False, comment="Read test file"
        ),
        WriteRequirement(
            path="/test/output.txt",
            content="test content",
            is_directory=False,
            comment="Write test file",
        ),
        CommandRequirement(command="ls -la", comment="List files"),
        MoveRequirement(
            source_path="/test/source.txt",
            destination_path="/test/dest.txt",
            comment="Move file",
        ),
        CopyRequirement(
            source_path="/test/original.txt",
            destination_path="/test/copy.txt",
            comment="Copy file",
        ),
        DeleteRequirement(path="/test/unwanted.txt", comment="Delete file"),
    ],
)

__all__ = [
    "ALL_REQUIREMENTS_MESSAGE",
    "DEFAULT_CONFIG",
    "VERBOSE_CONFIG",
    "MockInterface",
]
