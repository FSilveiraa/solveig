from pydantic import ByteSize

from solveig import SolveigConfig
from solveig.api import OpenAI

from .client import create_mock_model
from .interface import MockInterface

# The mock config relies on the core-tools schema being composed. It was
# previously an import-time side effect; now it's an explicit bootstrap call
# (same mechanism as the plugin two-phase bootstrap, phase 1).
SolveigConfig.compose_core_tools()

DEFAULT_CONFIG = SolveigConfig(
    cli_args=[],  # hermetic: don't parse pytest's process argv
    api={
        "type": "openai",
        "key": "test-key",
        "url": "test-url",
        "model": "test-model",
        "temperature": 0.0,
    },
    min_disk_space_left=ByteSize(1_000_000_000),  # 1 GB
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
