"""System-prompt package.

Deliberately empty. The composition machinery — assembling the final prompt
from config, briefing files, OS info, and stories — is in ``compose``, which
imports upward into ``sessions``; keeping this ``__init__`` bare means the
package sits wholly in the app layer with nothing below depending on it.
``DEFAULT_SYSTEM_PROMPT`` lives in ``solveig.config`` alongside the other
static defaults.
"""
