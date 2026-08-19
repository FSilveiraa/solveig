"""The socket wire — connecting remote interfaces to a Solveig daemon.

`WireInterface` (interface.py) is the daemon's broadcast face: a
`SolveigInterface` whose verbs serialize to type-tagged JSONL frames and fan out
to every connected client socket. `WireClient` (client.py) is the other end: it
reads those frames and drives a concrete `SolveigInterface`, so any UI can attach
to a daemon through the one ABC seam.

The wire vocabulary is `SolveigInterface` itself (protocol.py holds the value
(code/decode helpers). A plugin cannot add a verb, so a client renders any stream
without plugin config.
"""

from solveig.interface.wire.client import WireClient
from solveig.interface.wire.interface import WireInterface

__all__ = ["WireClient", "WireInterface"]
