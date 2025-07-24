from plugins.hooks import before
from schema.requirement import CommandRequirement, ReadRequirement, WriteRequirement, ReadResult, WriteResult


@before(requirements=(CommandRequirement,))
def check_command(config, requirement: CommandRequirement):
    pass
