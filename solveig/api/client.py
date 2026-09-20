"""`Client` — the live provider connection, plus the `/model` subcommands.

`Client` holds the runtime provider and subscribes to config changes reactively.
Unlike `types`, this module sits above config and the interface protocol, so it
names both directly.
"""

from __future__ import annotations

from pydantic_ai.providers import Provider

from solveig.api.types import (
    APIError,
    APIRejected,
    APIUnreachable,
    ModelInfo,
    ModelNotFound,
    ProviderCapabilityMissing,
    ApiConfig,
)
from config import SolveigConfig
from solveig.interface.base import Level, SolveigInterface
from solveig.subcommands import subcommand


def _classify(err: Exception) -> APIError:
    """Sort a provider-client exception into the user-actionable kinds.

    NOTE: keyed on whether a RESPONSE came back, not on message text. The OpenAI SDK
    wraps httpx and re-raises its own types (`APIConnectionError` has no `.response`;
    `AuthenticationError`/`APIStatusError` carry `.response.status_code`) - but "the
    server answered with a status" vs "nothing answered" is the distinction that
    actually separates a bad URL from a bad key, independent of the wrapper type."""
    status = getattr(getattr(err, "response", None), "status_code", None)
    if status is not None:
        return APIRejected(f"The endpoint refused the request (HTTP {status}): {err}")
    return APIUnreachable(f"Could not reach the endpoint: {err}")


class Client:
    """Mutable holder for the live provider connection.  Subscribes to
    api.model / api.url / api.type changes at construction: builds a new
    provider locally and only swaps on success — the old provider stays
    live until the replacement is proven.  On failure, reverts the model
    so the UI sees the reversion."""

    def __init__(
        self,
        config: ApiConfig,
        interface: SolveigInterface,
        provider: Provider | None = None,
    ) -> None:
        self.config = config
        self.provider = provider or config.type.get_provider(
            api_key=config.key.get_secret_value() or None,
            url=config.url,
        )
        # self.type: APIType = config.type
        # self.model_info: ModelInfo | None = None

        self.interface = interface

        # TODO: review refresh behavior, does it make sense to just react to any of these with a blanket "reconnect"?
        #  The contract promises that we only get changes that actually changed anything, so we don't need per-field checking of "did the model really change, so I know if it's worth to reconnect"

        @config.on_change("model", "url", "type", "key")
        async def on_change(_config: SolveigConfig, paths: frozenset[str]):
            await self.refresh()


    @property
    def max_context(self) -> int | None:
        config_limit = self.config.max_context
        if config_limit is not None and config_limit < 0:
            config_limit = None
        model_limit = (
            self.config.model_info.context_length
            if self.config.model_info else None
        )
        if model_limit is None:
            return config_limit
        if config_limit is None:
            return model_limit
        return min(config_limit, model_limit)


    async def fetch_model_info(self) -> tuple[Provider, ModelInfo]:
        """Build a provider from config and ask it about the configured model.

        Raises a classified `APIError`; the caller decides whether to display, revert,
        or both. Classification lives here because this is the only place holding both
        the request and the provider that made it."""
        provider = self.config.type.get_provider(
            url=self.config.url,
            api_key=self.config.key.get_secret_value() or None,
        )
        try:
            info = await self.config.type.get_model_details(
                provider=provider,
                model=self.config.model,
            )
        except APIError:
            raise
        except Exception as err:
            raise _classify(err) from err
        if info is None:
            raise ModelNotFound(self.config.model or "(unset)")
        return provider, info

    async def refresh(self) -> None:
        """Build provider from config, fetch model details, atomic swap.

        On failure the model reverts to the last one that actually WORKED, held
        on `self.model_info` - not to `config.api.model`, which by the time this
        runs is already the new value the observer fired on. Reading it here
        made the revert set the failing model back over itself: equal values,
        so `config.set` returned early, no notification, and the bad name stayed
        on screen as though it had been accepted."""
        previous_model = self.config.model_info.model if self.config.model_info else None
        try:
            new_provider, info = await self.fetch_model_info()
        except APIError as err:
            # TODO: this is triggered when config.model is changed, confirm
            #  resetting it to the previous config model works for triggering
            #  another model refresh.
            #  Also this is an explicit config.model = something set, so
            #  exporting the config will include the model name.
            if previous_model is not None:
                self.config.model = previous_model
            # TODO: raise instead, the above will call the interface to print
            if self.interface is not None:
                await self.interface.print(str(err), level=Level.ERROR)
            return

        self.provider = new_provider
        # NOTE: writing an excluded field
        self.config.model_info = info
        # model_info is now the new model's - stats reading it (price, context)
        # are stale until told, and this is the moment it stopped being true.
        # self.interface.refresh_stats()


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
    except ProviderCapabilityMissing as e:
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
def model_set(
    config: SolveigConfig,
    model: str,
) -> None:
    """Set the active model."""
    config.api.model = model.strip()


@subcommand("/model info", section="model", detail=True)
async def model_info(
    config: SolveigConfig,
    interface: SolveigInterface,
) -> None:
    """Show current model details."""
    info = config.api.model_info
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
    # TODO: likely a bad idea to reset model_info, review needs.
    #  Also if it's set within the init chain it can use self.client
    config.api.model_info = None
    await client.refresh()
