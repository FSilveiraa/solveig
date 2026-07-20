from solveig import APIType, SolveigConfig
from solveig.utils.misc import parse_human_readable_size

from .client import create_mock_model
from .interface import MockInterface

DEFAULT_CONFIG = SolveigConfig(
    api={
        "type": APIType.OPENAI,
        "key": "test-key",
        "url": "test-url",
        "model": "test-model",
        "temperature": 0.0,
    },
    min_disk_space_left=parse_human_readable_size("1gb"),
    session={"auto_save": False},
    interface={"stream": False},
)

VERBOSE_CONFIG = DEFAULT_CONFIG

__all__ = [
    "DEFAULT_CONFIG",
    "VERBOSE_CONFIG",
    "MockInterface",
    "create_mock_model",
]
