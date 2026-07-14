from solveig import APIType, SolveigConfig

from .interface import MockInterface
from .llm_client import create_mock_model

DEFAULT_CONFIG = SolveigConfig(
    api_type=APIType.OPENAI,
    api_key="test-key",
    url="test-url",
    model="test-model",
    temperature=0.0,
    verbose=False,
    min_disk_space_left="1gb",
    auto_save_session=False,
)

VERBOSE_CONFIG = DEFAULT_CONFIG.with_(verbose=True)

__all__ = [
    "DEFAULT_CONFIG",
    "VERBOSE_CONFIG",
    "MockInterface",
    "create_mock_model",
]
