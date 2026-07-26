"""Composition-root reactions to runtime config changes.

`AppConfigSubscriber` is one `ConfigObserver` that closes over the interface
and provider session. It is packaging of several reactions — not a second bus
that routes to other observers. Config itself still owns the observer list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from solveig.config.editor import fetch_and_apply_model_info

if TYPE_CHECKING:
    from solveig.api import ProviderRef
    from solveig.config.config import SolveigConfig
    from solveig.interface.base import SolveigInterface


@dataclass
class AppConfigSubscriber:
    """Reacts to user-driven config edits that need interface/provider deps."""

    interface: SolveigInterface
    provider_ref: ProviderRef

    async def config_changed(
        self, config: SolveigConfig, paths: frozenset[str]
    ) -> None:
        if "interface.theme" in paths:
            self.interface.set_theme(config.interface.theme)

        if "interface.code_theme" in paths:
            self.interface.set_code_theme(config.interface.code_theme)

        if "api.max_context" in paths:
            await self.interface.update_stats(max_context=config.api.max_context)

        if "api.model" in paths:
            # Invalidate cached model details, then refetch. Fetch assigns
            # model/max_context directly and updates stats itself without
            # notify_changed (re-entrancy guard — see SolveigConfig.subscribe).
            self.provider_ref.model_info = None
            await fetch_and_apply_model_info(config, self.provider_ref, self.interface)
