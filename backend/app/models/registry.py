"""Installed-model registry with refresh from a provider."""

from __future__ import annotations

from app.models.base import ModelInfo, ModelProvider, ProviderError


class ModelRegistry:
    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider
        self._models: list[ModelInfo] = []
        self._error: str | None = None

    @property
    def models(self) -> list[ModelInfo]:
        return list(self._models)

    @property
    def last_error(self) -> str | None:
        return self._error

    async def refresh(self) -> list[ModelInfo]:
        try:
            self._models = await self.provider.list_models()
            self._error = None
        except ProviderError as exc:
            self._models = []
            self._error = str(exc)
            raise
        return self._models

    def get(self, model_id: str) -> ModelInfo | None:
        for model in self._models:
            if model.id == model_id or model.name == model_id:
                return model
        return None
