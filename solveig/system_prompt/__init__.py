"""System-prompt package.

Deliberately empty. The composition machinery — assembling the final prompt
from config, briefing files, OS info, and stories — is in ``compose``, which
imports upward into ``sessions``; keeping this ``__init__`` bare means the
package sits wholly in the app layer with nothing below depending on it.
``DEFAULT_SYSTEM_PROMPT`` and the ``system_prompt`` config section live in
``config``, the leaf beside this one — the default text is the subsystem, not a
config default that happens to be about it.
"""
