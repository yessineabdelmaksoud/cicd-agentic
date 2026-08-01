"""
OpenRouter Client — Unified LLM client for all 3 agents (v5 §3/§7.6/§FIX-9/§FIX-10).

- Model assignments match the pinned plan (qwen3-coder / deepseek-v3 / claude-sonnet),
  not the drifted cohere placeholder that was hard-coded before.
- The Diagnostician has a paid fallback model: `:free` OpenRouter tiers have daily
  caps and flaky availability, which is a real reliability risk for a system meant
  to run unattended.
- Structured output: try `response_format: json_schema` (derived straight from the
  Pydantic model) first; fall back to `json_object` mode if the upstream model
  doesn't support schema-constrained output. Either way, parsing is
  `schema.model_validate_json(content)` directly — no markdown-fence stripping.
  One retry with the validation error appended, then raise.
"""

import os
import structlog
from typing import Type, TypeVar
import httpx
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from services.metrics import record_llm_cost

log = structlog.get_logger()

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

# Model assignments per agent role (v5 §3 — the pinned stack, not the drifted one)
AGENT_MODELS = {
    "diagnostician":   "qwen/qwen3-coder:free",
    "patch_generator": "deepseek/deepseek-chat-v3-0324",
    "reviewer":        "anthropic/claude-sonnet-4-5",
}

# Tried in order after the primary fails. Live testing showed OpenRouter's
# `:free` rate-limiting is upstream-provider-wide, not per-model (several
# unrelated :free models failed together from the same provider), and paid
# billing can intermittently 402 even with credits present — so each chain
# mixes providers/tiers rather than a single paid fallback, to survive either
# failure mode independently (fix.md FIX-9, extended past a single fallback
# after a live outage).
FALLBACK_MODELS = {
    "diagnostician": ["qwen/qwen3-coder", "google/gemma-4-31b-it:free", "nvidia/nemotron-3-super-120b-a12b:free"],
    "patch_generator": ["nvidia/nemotron-3-super-120b-a12b:free", "openai/gpt-oss-20b:free"],
    "reviewer": ["openai/gpt-oss-20b:free", "google/gemma-4-31b-it:free"],
}

# Best-effort $/million-token estimate used only when OpenRouter doesn't report
# actual generation cost in the response (usage.cost) — approximate, for the
# cost_per_remediation metric, not billing.
PRICE_PER_MTOK = {
    "qwen/qwen3-coder:free": {"in": 0.0, "out": 0.0},
    "qwen/qwen3-coder": {"in": 0.3, "out": 1.2},
    "deepseek/deepseek-chat-v3-0324": {"in": 0.28, "out": 0.88},
    "anthropic/claude-sonnet-4-5": {"in": 3.0, "out": 15.0},
    "google/gemma-4-31b-it:free": {"in": 0.0, "out": 0.0},
    "nvidia/nemotron-3-super-120b-a12b:free": {"in": 0.0, "out": 0.0},
    "openai/gpt-oss-20b:free": {"in": 0.0, "out": 0.0},
}

T = TypeVar("T", bound=BaseModel)

_client_instance: "OpenRouterClient | None" = None


class OpenRouterClient:
    """Unified async HTTP client for OpenRouter API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://agent.ai-agent.svc.cluster.local",
            "X-Title": "AI-CICD-Embedded",
            "Content-Type": "application/json",
        }

    def model_for(self, agent_role: str) -> str:
        model = AGENT_MODELS.get(agent_role)
        if not model:
            raise ValueError(f"Unknown agent role: {agent_role}")
        return model

    async def call(self, agent_role: str, messages: list[dict], schema: Type[T]) -> T:
        """Call the model assigned to agent_role; walk the fallback chain on
        failure (each entry tried once) so a single model/provider outage
        doesn't stall the whole pipeline; parse+validate against `schema`."""
        chain = [self.model_for(agent_role), *FALLBACK_MODELS.get(agent_role, [])]
        last_exc: Exception | None = None

        for i, model in enumerate(chain):
            try:
                return await self._call_model(model, agent_role, messages, schema)
            except Exception as e:
                last_exc = e
                if i < len(chain) - 1:
                    log.warning(
                        "openrouter.fallback",
                        agent_role=agent_role,
                        failed_model=model,
                        next_model=chain[i + 1],
                        error=str(e),
                    )

        raise last_exc

    @retry(
        # Only retry genuine network hiccups (timeout/connection) — NOT
        # HTTPStatusError (429/402/404/5xx). A 429/402 will not succeed by
        # retrying the SAME model; the outer fallback chain in call() should
        # move to the next model immediately instead of burning the RQ job's
        # timeout budget retrying a doomed request (found live: a 3x/30s-max
        # retry on a hanging free-tier model alone exhausted the 300s job
        # timeout before the chain ever reached a working model).
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError, httpx.ReadError)),
        reraise=True,
    )
    async def _request(self, model: str, messages: list[dict], use_json_schema: bool, schema_name: str, json_schema: dict | None) -> dict:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "usage": {"include": True},
        }
        if use_json_schema and json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": json_schema},
            }
        else:
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(f"{OPENROUTER_BASE}/chat/completions", headers=self.headers, json=payload)
            resp.raise_for_status()
            return resp.json()

    async def _call_model(self, model: str, agent_role: str, messages: list[dict], schema: Type[T]) -> T:
        json_schema = schema.model_json_schema()
        log.info("openrouter.request", agent_role=agent_role, model=model)

        try:
            data = await self._request(model, messages, use_json_schema=True, schema_name=schema.__name__, json_schema=json_schema)
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (400, 404, 422):
                log.warning("openrouter.json_schema_unsupported", model=model, status=e.response.status_code)
                data = await self._request(model, messages, use_json_schema=False, schema_name=schema.__name__, json_schema=None)
            else:
                raise

        self._record_cost(agent_role, model, data.get("usage", {}))
        content = data["choices"][0]["message"]["content"]

        try:
            return schema.model_validate_json(content)
        except Exception as e:
            log.warning("openrouter.validation_failed_retrying", model=model, error=str(e), content=content[:300])
            retry_messages = messages + [
                {"role": "assistant", "content": content},
                {"role": "user", "content": f"That response did not match the required JSON schema: {e}. Respond again with ONLY valid JSON matching the schema."},
            ]
            data = await self._request(model, retry_messages, use_json_schema=False, schema_name=schema.__name__, json_schema=None)
            self._record_cost(agent_role, model, data.get("usage", {}))
            content = data["choices"][0]["message"]["content"]
            return schema.model_validate_json(content)

    def _record_cost(self, agent_role: str, model: str, usage: dict) -> None:
        cost_usd = usage.get("cost")
        if cost_usd is None:
            price = PRICE_PER_MTOK.get(model, {"in": 0.5, "out": 1.5})
            cost_usd = (
                usage.get("prompt_tokens", 0) * price["in"] + usage.get("completion_tokens", 0) * price["out"]
            ) / 1_000_000
        record_llm_cost(agent_role, model, cost_usd)

    async def check_models(self) -> dict:
        """Verify the configured models are accessible (for health check)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{OPENROUTER_BASE}/models", headers=self.headers)
            if resp.status_code == 200:
                return {"status": "ok", "models": AGENT_MODELS}
            return {"status": "error", "code": resp.status_code}


def get_openrouter_client() -> OpenRouterClient:
    """Return the singleton OpenRouter client."""
    global _client_instance
    if _client_instance is None:
        api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY environment variable is not set")
        _client_instance = OpenRouterClient(api_key)
    return _client_instance
