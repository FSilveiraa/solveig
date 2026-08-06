"""`Client` — the live provider connection, plus the `/model` subcommands.

`Client` holds the runtime provider and subscribes to config changes reactively.
Unlike `types`, this module sits above config and the interface protocol, so it
names both directly.
"""

from __future__ import annotations

from pydantic_ai.providers import Provider

from solveig.api.types import ModelInfo
from solveig.config import SolveigConfig
from solveig.interface.base import Level, SolveigInterface
from solveig.subcommands import subcommand


class Client:
    """Mutable holder for the live provider connection.  Subscribes to
    api.model / api.url / api.type changes at construction: builds a new
    provider locally and only swaps on success — the old provider stays
    live until the replacement is proven.  On failure, reverts the model
    so the UI sees the reversion."""

    def __init__(
        self,
        config: SolveigConfig,
        provider: Provider | None = None,
        interface: SolveigInterface | None = None,
    ) -> None:
        self.provider = provider or config.api.type.get_provider(
            api_key=config.api.key.get_secret_value() or None,
            url=config.api.url,
        )
        self.type = config.api.type
        self.model_info: ModelInfo | None = None
        #: Told when `model_info` is replaced, because the Price and Context
        #: stats read it. NOT so the client can display anything - it never
        #: does. The alternative was registering the price stat's observer
        #: after this one and relying on observer ORDER: a config-change
        #: listener firing before `refresh` has swapped `model_info` would read
        #: the previous model's prices. Optional so a headless Client works.
        self._interface = interface

        @config.on_change("api.model", "api.url", "api.type")
        async def _on_api_change(_config: SolveigConfig, paths: frozenset[str]):
            return await self._on_api_change(_config, paths)

    async def _on_api_change(
        self, config: SolveigConfig, paths: frozenset[str]
    ) -> None:
        if (
            self.model_info
            and self.model_info.model == config.api.model
            and self.provider.base_url == config.api.url
            and type(self.type) is type(config.api.type)
        ):
            return
        await self.refresh(config)

    async def refresh(self, config: SolveigConfig) -> None:
        """Build provider from config, fetch model details, atomic swap.

        On failure the model reverts to the last one that actually WORKED, held
        on `self.model_info` - not to `config.api.model`, which by the time this
        runs is already the new value the observer fired on. Reading it here
        made the revert set the failing model back over itself: equal values,
        so `config.set` returned early, no notification, and the bad name stayed
        on screen as though it had been accepted."""
        last_good = self.model_info.model if self.model_info else None
        api_type = config.api.type
        try:
            new_provider = api_type.get_provider(
                url=config.api.url,
                api_key=config.api.key.get_secret_value() or None,
            )
            info = await api_type.get_model_details(
                provider=new_provider, model=config.api.model
            )
        except Exception as e:
            if self._interface is not None:
                await self._interface.print(
                    f"Could not connect to {config.api.url}: {e}", level=Level.ERROR
                )
            await self._revert(config, last_good)
            return

        if info is None:
            await self._revert(config, last_good)
            return

        self.provider = new_provider
        self.type = api_type
        self.model_info = info
        # model_info is now the new model's - stats reading it (price, context)
        # are stale until told, and this is the moment it stopped being true.
        if self._interface is not None:
            self._interface.refresh_stats()
        # Apply the model's max context length if the user didn't specify a
        # limit (-1 is the "model's limit" sentinel; None can never occur).
        if info.context_length is not None and config.api.max_context == -1:
            await config.set("api.max_context", info.context_length)

    @staticmethod
    async def _revert(config: SolveigConfig, last_good: str | None) -> None:
        """Put the last working model back, if there was one.

        `None` means nothing has ever resolved (a bad model at startup), so
        there is nothing to revert TO - leaving the failing name in place is
        better than blanking the config, and the caller already surfaced the
        failure."""
        if last_good is not None:
            await config.set("api.model", last_good)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


@subcommand("/model list", section="model")
async def model_list(
    config: SolveigConfig,
    client: Client,
    interface: SolveigInterface,
) -> None:
    """List available models from the provider."""
    try:
        models = await config.api.type.list_models(client.provider)
    except NotImplementedError as e:
        await interface.print(str(e), level=Level.ERROR)
        return
    except Exception as e:
        await interface.print(f"Could not list models: {e}", level=Level.ERROR)
        return

    if not models:
        await interface.print("No models available.", level=Level.INFO)
        return

    current = config.api.model
    lines = []
    for m in models:
        prefix = "→ " if m == current else "  "
        lines.append(f"{prefix}{m}")

    await interface.add_text_box(
        "\n".join(lines), title=f"Models ({config.api.type.name})"
    )


@subcommand("/model set", section="model", detail=True)
async def model_set(
    config: SolveigConfig,
    model: str,
) -> None:
    """Set the active model."""
    await config.set("api.model", model.strip())


@subcommand("/model info", section="model", detail=True)
async def model_info(
    client: Client,
    interface: SolveigInterface,
) -> None:
    """Show current model details."""
    info = client.model_info
    if info is None:
        await interface.print(
            "No model info loaded. Run /model refresh.", level=Level.INFO
        )
        return

    lines = [f"Model:           {info.model}"]
    if info.context_length is not None:
        lines.append(f"Context length:  {info.context_length:,} tokens")
    if info.input_price is not None:
        lines.append(f"Input price:    ${info.input_price:.2f}/M tokens")
    if info.output_price is not None:
        lines.append(f"Output price:   ${info.output_price:.2f}/M tokens")

    await interface.add_text_box("\n".join(lines), title="Model Info")


@subcommand("/model refresh", section="model", detail=True)
async def model_refresh(
    config: SolveigConfig,
    client: Client,
) -> None:
    """Refresh model details from the API."""
    client.model_info = None
    await client.refresh(config)
