from instructor import patch, OpenAISchema
import openai
from schemas import Request, Requirement, FinalResponse
from typing import List
from enum import Enum


class APIType(Enum):
    OPENAI = "openai"
    KOBOLDCPP = "openai"
    CLAUDE = "claude"
