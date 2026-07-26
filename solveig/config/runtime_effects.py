"""Composition-root reactions to runtime config changes.

`AppConfigSubscriber` is one `ConfigObserver` that closes over the interface
and provider session. `fetch_and_apply_model_info` lives here because fetching
model details from the API in reaction to a config change IS a runtime effect
— same drawer as theme switching and stats updates.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from solveig.api import ModelInfo, ModelNotFound

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


async def fetch_and_apply_model_info(
    config: SolveigConfig,
    provider_ref: ProviderRef,
    interface: SolveigInterface,
) -> bool:
    """Fetch model details from the API and apply them — a runtime effect
    triggered by the subscriber on api.model changes or called at boot.

    Updates config.api.model (if None, resolved), provider_ref.model_info,
    config.api.max_context (if model reports a tighter limit), and the stats
    bar. Direct setattr, never notify_changed (re-entrancy guard).

    Always animates while in-flight. Returns True on success."""
    try:
        async with interface.with_cancellable(
            config.api.type.get_model_details(
                provider=provider_ref.provider, model=config.api.model
            ),
            status="Connecting to assistant",
        ) as task:
            model_info = await task
    except asyncio.CancelledError:
        await interface.display_info("Model info fetch cancelled")
        return False
    except NotImplementedError:
        if config.api.model:
            provider_ref.model_info = ModelInfo(model=config.api.model)
        return True
    except ModelNotFound as e:
        await e.print(interface)
        return False
    except Exception as e:
        await interface.display_error(
            f"Found error when trying to fetch model details: {e}"
        )
        return False

    if model_info is None:
        return False

    config.api.model = model_info.model
    provider_ref.model_info = model_info

    if model_info.context_length is not None:
        if (
            config.api.max_context < 0
            or config.api.max_context > model_info.context_length
        ):
            config.api.max_context = model_info.context_length

    await interface.update_stats(
        model=config.api.model,
        max_context=config.api.max_context,
        input_price=model_info.input_price,
        output_price=model_info.output_price,
    )
    return True
