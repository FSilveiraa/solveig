"""The wire vocabulary — the SolveigInterface contract as typed frames.

A frame is one JSON object per line on a socket. The two ends of a connection
speak the SAME vocabulary: the daemon encodes its ABC verbs and broadcasts
them; every client decodes a frame and calls the matching method on its real
interface, then sends back answers, actions, input and cancels.

**A frame is a model, not a dict.** Its `type` is a `Literal` field, so the
class IS the tag, and the payload is pinned by the same declaration that names
it. The two ends can no longer disagree about a key: there is one place the
key is written down and both import it. This follows what the two hand-rolled
protocols already in the dependency tree do — MCP's `method: Literal[...]` per
message, pydantic-ai's `kind: Literal[...]` per part — and what pydantic
documents as the way to model a tagged union.

**Direction is part of the type.** `ServerFrame` is what a daemon may send and
a client may receive; `ClientFrame` is the reverse. A client cannot construct a
`Print` for the daemon to misread, and the daemon cannot receive one, because
each end validates against one union only. Who may say what is a type here, not
a comment.

**Forward compat is one explicit branch.** A discriminated union REJECTS a
`type` it does not know, so "a client MUST ignore a frame it does not
understand" is now a `ValidationError` the reader catches and skips - see
`WireClient`. That is deliberate: under the old dict frames the same rule
silently swallowed real bugs (a `stat` frame the client never handled looked
exactly like a future frame being politely skipped). Adding a FIELD to an
existing frame stays compatible on its own, because the models do not forbid
extra keys - only an unknown `type` is rejected.

The vocabulary is the ABC's, so a plugin cannot add a frame and a client never
needs a plugin to render one.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    Discriminator,
    PlainSerializer,
    TypeAdapter,
)

from solveig.interface.base import Level
from solveig.interface.base.actions import Role
from solveig.todo import TodoItem
from solveig.utils.file import FileMetadata

# --------------------------------------------------------------------------- #
# Field types                                                                  #
# --------------------------------------------------------------------------- #
#
# NOTE: `FileMetadata` and `TodoItem` need no help at all. `TodoItem` is already
# a pydantic model, and pydantic round-trips the `FileMetadata` dataclass
# recursively (nested `listing` included) on its own. The hand-written
# to_json/from_json pairs that used to live here are gone, and with them the
# placeholder fields the reduced form invented - a client used to be told every
# file was writable and owned by nobody.


WireLevel = Annotated[
    Level,
    # `Level` is an `auto()` enum, so its values are integers. The NAME is what
    # crosses, because a JS client reading `"level": "WARNING"` can act on it
    # and one reading `"level": 3` cannot.
    PlainSerializer(lambda level: level.name, return_type=str),
    BeforeValidator(lambda v: Level[v] if isinstance(v, str) else v),
]


class ActionName(StrEnum):
    """The message actions that can cross the wire.

    The daemon holds the real closures (`MessageActions`); only their NAMES
    travel, and a client rebuilds closures that send them back. An enum rather
    than bare strings so the offer side and the invoke side cannot drift, and
    so a typo is an `AttributeError` at the definition instead of a comparison
    that is quietly always false.
    """

    EDIT = "edit"
    RETRY = "retry"
    DELETE = "delete"
    BRANCH = "branch"


# --------------------------------------------------------------------------- #
# Server → client                                                              #
# --------------------------------------------------------------------------- #


class ServerFrame(BaseModel):
    """A frame the daemon broadcasts and every client renders.

    `group` is the one thing every server frame carries: which open group it
    draws into, `None` for the root. It is stamped by `_publish` from the
    OBJECT doing the publishing, never from a stack, which is what lets two
    parallel groups each draw into their own.
    """

    group: int | None = None


# -- display verbs ----------------------------------------------------------


class Print(ServerFrame):
    type: Literal["print"] = "print"
    text: str
    level: WireLevel = Level.TEXT
    prefix: str | None = None


class AddReasoning(ServerFrame):
    type: Literal["add_reasoning"] = "add_reasoning"
    id: int
    text: str


class DisplayFileMetadata(ServerFrame):
    # NOTE: lossy on purpose, for now - the ABC verb also takes a `FileMetadata`
    # and an `is_directory`, and the wire has never carried either. Now that
    # metadata crosses for free (see AddTreeBox) there is no cost reason left to
    # drop it; it stays out only because widening a verb is a behaviour change,
    # not part of the shape conversion.
    type: Literal["display_file_metadata"] = "display_file_metadata"
    path: str
    prefix: str | None = None


class DisplayTodos(ServerFrame):
    type: Literal["display_todos"] = "display_todos"
    todos: list[TodoItem]


class AddDiffBox(ServerFrame):
    type: Literal["add_diff_box"] = "add_diff_box"
    id: int
    title: str | None = None
    old: str
    new: str


class AddTreeBox(ServerFrame):
    type: Literal["add_tree_box"] = "add_tree_box"
    id: int
    title: str | None = None
    metadata: FileMetadata


class AddTextBox(ServerFrame):
    type: Literal["add_text_box"] = "add_text_box"
    id: int
    title: str | None = None
    text: str
    language: str | None = None
    collapsed: bool = False


class AddMessage(ServerFrame):
    type: Literal["add_message"] = "add_message"
    id: int
    text: str
    role: Role
    #: Only the buttons the daemon actually offered. An action that does not
    #: apply is ABSENT, exactly as in `MessageActions`, so a client draws no
    #: control for it without knowing why.
    actions: list[ActionName] = []


class SetStatus(ServerFrame):
    type: Literal["set_status"] = "set_status"
    status: str | None = None
    duration: float | None = None


# -- box mutations ----------------------------------------------------------
#
# NOTE: one frame per (box type, method), where the old dict form had a single
# `invoke` carrying a method NAME. That name was not enough: `replace` meant
# three different signatures depending on which box it reached, and the client
# disambiguated by sniffing whether the args happened to contain a `metadata`
# key. Here each is its own type, so the signature is the frame.


class BoxFrame(ServerFrame):
    """A mutation addressed to a box handle the client stored under `id`."""

    id: int


class TextAppend(BoxFrame):
    type: Literal["text_append"] = "text_append"
    text: str


class TextClear(BoxFrame):
    type: Literal["text_clear"] = "text_clear"


class TextReplace(BoxFrame):
    type: Literal["text_replace"] = "text_replace"
    text: str


class DiffReplace(BoxFrame):
    type: Literal["diff_replace"] = "diff_replace"
    old: str
    new: str


class TreeReplace(BoxFrame):
    type: Literal["tree_replace"] = "tree_replace"
    metadata: FileMetadata


class TreeRefresh(BoxFrame):
    type: Literal["tree_refresh"] = "tree_refresh"


class MessageReplace(BoxFrame):
    type: Literal["message_replace"] = "message_replace"
    text: str


class MessageRemove(BoxFrame):
    type: Literal["message_remove"] = "message_remove"


# -- control ----------------------------------------------------------------


class AskQuestion(ServerFrame):
    type: Literal["ask_question"] = "ask_question"
    id: int
    question: str
    default: str = ""


class AskChoice(ServerFrame):
    type: Literal["ask_choice"] = "ask_choice"
    id: int
    question: str
    choices: list[str]


class AskResolved(ServerFrame):
    """One client answered; every other client retracts its prompt and shows
    the winner's answer."""

    type: Literal["ask_resolved"] = "ask_resolved"
    id: int
    answer: str


class GroupStart(ServerFrame):
    type: Literal["group_start"] = "group_start"
    id: int
    title: str
    #: Who CONTAINS this group, so nesting survives frames interleaving with a
    #: sibling's - it is never inferred from arrival order. Published through
    #: the parent, so the inherited `group` tag is the enclosing one, not this.
    parent: int | None = None
    collapse_when_done: bool = True


class GroupEnd(ServerFrame):
    type: Literal["group_end"] = "group_end"
    id: int


class StatValue(ServerFrame):
    """One stats entry and its rendered text.

    A `Stat`'s value is computed daemon-side (it closes over a `get` callable
    that only exists there), so what crosses is the label and the text it
    currently renders to - one frame per value, re-sent on every refresh.
    """

    type: Literal["stat"] = "stat"
    label: str
    text: str


class RefreshStats(ServerFrame):
    type: Literal["refresh_stats"] = "refresh_stats"


class ConfigUpdate(ServerFrame):
    type: Literal["config_update"] = "config_update"
    #: Dotted path -> the field's string representation, not its object.
    updates: dict[str, Any] = {}


class Ready(ServerFrame):
    """Retained history ends here; everything after this frame is live."""

    type: Literal["ready"] = "ready"


# --------------------------------------------------------------------------- #
# Client → server                                                              #
# --------------------------------------------------------------------------- #


class ClientFrame(BaseModel):
    """A frame a client sends back to the daemon.

    Deliberately WITHOUT the `group` field every server frame carries: a group
    is a place to draw, and a client never asks the daemon to draw. The one
    client frame that names a group (`Cancel`) declares its own, because there
    it means something else entirely - what to stop, not where to put it.
    """


class Answer(ClientFrame):
    type: Literal["answer"] = "answer"
    id: int
    value: str


class Input(ClientFrame):
    """The user typed a prompt on this client; it goes to the agent's queue."""

    type: Literal["input"] = "input"
    text: str


class Action(ClientFrame):
    type: Literal["action"] = "action"
    message_id: int
    action: ActionName
    #: Only `ActionName.EDIT` carries one - it is the new message text.
    text: str | None = None


class Cancel(ClientFrame):
    """Stop daemon work. Cancellation reaches downward from what it names.

    NOTE: nothing here cancels work in another process. Every cancel scope
    lives in the daemon, because the agent loop, the tools and the model
    requests all run there; a client draws and runs nothing. So what travels is
    the REQUEST, and the daemon then cancels its own local scope.
    """

    type: Literal["cancel"] = "cancel"
    #: The group whose work to stop; `None` means everything the daemon is
    #: doing, which is what a bare Ctrl+C on a client means.
    group: int | None = None


# --------------------------------------------------------------------------- #
# The two unions                                                               #
# --------------------------------------------------------------------------- #

ServerFrameType = Annotated[
    Print
    | AddReasoning
    | DisplayFileMetadata
    | DisplayTodos
    | AddDiffBox
    | AddTreeBox
    | AddTextBox
    | AddMessage
    | SetStatus
    | TextAppend
    | TextClear
    | TextReplace
    | DiffReplace
    | TreeReplace
    | TreeRefresh
    | MessageReplace
    | MessageRemove
    | AskQuestion
    | AskChoice
    | AskResolved
    | GroupStart
    | GroupEnd
    | StatValue
    | RefreshStats
    | ConfigUpdate
    | Ready,
    Discriminator("type"),
]

ClientFrameType = Annotated[
    Answer | Input | Action | Cancel,
    Discriminator("type"),
]

#: What a client parses off the socket, and what a daemon parses off it. Each
#: end validates against the union it is allowed to RECEIVE, which is the whole
#: of the direction rule - there is no runtime check to remember.
SERVER_FRAMES: TypeAdapter[ServerFrameType] = TypeAdapter(ServerFrameType)
CLIENT_FRAMES: TypeAdapter[ClientFrameType] = TypeAdapter(ClientFrameType)
