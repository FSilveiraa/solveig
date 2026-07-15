from solveig import APIType, SolveigConfig
from solveig.utils.misc import parse_human_readable_size

from .client import create_mock_model
from .interface import MockInterface

DEFAULT_CONFIG = SolveigConfig(
    api_type=APIType.OPENAI,
    api_key="test-key",
    url="test-url",
    model="test-model",
    temperature=0.0,
    verbose=False,
    min_disk_space_left=parse_human_readable_size("1gb"),
    auto_save_session=False,
)

VERBOSE_CONFIG = DEFAULT_CONFIG.with_(verbose=True)

__all__ = [
    "DEFAULT_CONFIG",
    "VERBOSE_CONFIG",
    "MockInterface",
    "create_mock_model",
]
