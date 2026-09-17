"""Select an installed local model. Does not hardcode a specific Ollama tag."""

from __future__ import annotations

from app.models.base import ModelInfo, ProviderError


class ModelRouter:
    def __init__(self, preferred: str = "") -> None:
        self.preferred = preferred.strip()

    def select(self, models: list[ModelInfo], *, prompt: str = "", complexity: str = "auto") -> ModelInfo:
        usable = [m for m in models if m.available]
        if not usable:
            raise ProviderError(
                "No usable local models are installed in Ollama. Install a model with Ollama, then retry.",
                code="model_unavailable",
            )
        if self.preferred:
            for model in usable:
                if model.id == self.preferred or model.name == self.preferred:
                    return model
            # partial match on preferred string
            pref = self.preferred.lower()
            for model in usable:
                if pref in model.id.lower() or pref in model.name.lower():
                    return model

        scored: list[tuple[float, ModelInfo]] = []
        need_code = _looks_like_code_task(prompt) or complexity == "high"
        for model in usable:
            score = 1.0
            blob = f"{model.id} {model.family} {' '.join(model.capabilities)}".lower()
            if "code" in blob or "coder" in blob:
                score += 3
            if "qwen" in blob:
                score += 2
            if "instruct" in blob or "chat" in blob:
                score += 1
            if need_code and "code" in model.capabilities:
                score += 2
            size = _size_score(model.parameter_size, model.id)
            if complexity == "high":
                score += size
            else:
                # Prefer a capable but not necessarily largest model for latency
                score += min(size, 3)
            scored.append((score, model))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]


def _looks_like_code_task(prompt: str) -> bool:
    tokens = ("fix", "test", "refactor", "implement", "bug", "api", "refactor", "implement", "code")
    lower = prompt.lower()
    return any(t in lower for t in tokens)


def _size_score(parameter_size: str, model_id: str) -> float:
    blob = f"{parameter_size} {model_id}".lower()
    for label, score in (("70b", 8), ("34b", 6), ("32b", 6), ("30b", 6), ("14b", 5), ("13b", 5), ("8b", 4), ("7b", 4), ("3b", 3), ("1.5b", 2), ("1b", 1)):
        if label in blob:
            return float(score)
    return 2.0
