"""Load the pinned Qwen3 model and expose a small generation interface.

Important Qwen3 details handled here
------------------------------------
* Non-thinking mode is requested through the chat template
  (``enable_thinking=False``) and verified before serving requests.
* The model's generation config declares two EOS ids for Qwen3:
  ``<|im_end|>`` (151645) and ``<|endoftext|>`` (151643). Both are validated and
  passed to ``generate`` as a list. Replacing this with the tokenizer's single
  ``eos_token_id`` is a known cause of runaway/repeating generation.
* The completion is decoded separately from the prompt and is not stripped or
  repaired. EOS handling, truncation, and loop warnings are recorded instead.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from generation_utils import (
    GenerationConfigError,
    detect_repetition,
    determine_finish_reason,
    normalize_eos_token_ids,
    truncation_warning,
)

LOGGER = logging.getLogger(__name__)

PRECISION_CHOICES = ("float16", "bfloat16", "float32", "auto")
DEVICE_CHOICES_PREFIX = "cuda"


class ModelLoadError(RuntimeError):
    """Raised when the configured model cannot be loaded safely."""


class ModelGenerationError(RuntimeError):
    """Raised when a generation request fails technically."""


@dataclass
class LoadedModel:
    model: Any
    tokenizer: Any
    model_id: str
    model_revision: str
    tokenizer_id: str
    tokenizer_revision: str
    precision: str
    device: str
    non_thinking_mode: bool
    eos_token_ids: list[int]
    pad_token_id: int
    actual_model_revision: str | None = None
    actual_tokenizer_revision: str | None = None
    loaded_at_utc: str | None = None
    load_duration_seconds: float | None = None
    warnings: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ info
    def info(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "actual_model_revision": self.actual_model_revision,
            "tokenizer_id": self.tokenizer_id,
            "tokenizer_revision": self.tokenizer_revision,
            "actual_tokenizer_revision": self.actual_tokenizer_revision,
            "precision": self.precision,
            "device": self.device,
            "non_thinking_mode": self.non_thinking_mode,
            "eos_token_ids": self.eos_token_ids,
            "pad_token_id": self.pad_token_id,
            "loaded_at_utc": self.loaded_at_utc,
            "load_duration_seconds": self.load_duration_seconds,
            "warnings": list(self.warnings),
        }

    # -------------------------------------------------------------- prompt side
    def format_prompt(self, messages: Sequence[dict[str, str]]) -> str:
        """Render chat messages in Qwen3 non-thinking mode."""

        if not isinstance(messages, Sequence) or not messages:
            raise ModelGenerationError("messages must be a non-empty sequence")
        cleaned: list[dict[str, str]] = []
        for message in messages:
            if not isinstance(message, dict):
                raise ModelGenerationError("each message must be an object")
            role = message.get("role")
            content = message.get("content")
            if role not in ("system", "user"):
                raise ModelGenerationError(f"unsupported message role: {role!r}")
            if not isinstance(content, str) or not content.strip():
                raise ModelGenerationError("message content must be a non-empty string")
            cleaned.append({"role": role, "content": content})

        try:
            prompt = self.tokenizer.apply_chat_template(
                cleaned,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
        except TypeError as exc:
            raise ModelGenerationError(
                "The tokenizer chat template does not accept enable_thinking=False. "
                "This model/tokenizer revision cannot be served in the required "
                "non-thinking mode."
            ) from exc

        if "<think>" not in prompt or "</think>" not in prompt:
            raise ModelGenerationError(
                "Non-thinking chat template verification failed: the rendered prompt "
                "does not contain the expected empty thinking block."
            )
        if not prompt.rstrip().endswith("</think>"):
            LOGGER.warning("Rendered prompt does not end with the empty thinking block")
        return prompt

    # -------------------------------------------------------------- generation
    def generate(
        self,
        messages: Sequence[dict[str, str]],
        generation_config: dict[str, Any],
        seed: int,
    ) -> dict[str, Any]:
        """Generate one completion and return text plus audit metadata."""

        import torch
        from transformers import set_seed

        if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
            raise ModelGenerationError("seed must be a non-negative integer")

        max_new_tokens = generation_config.get("max_new_tokens")
        if (
            not isinstance(max_new_tokens, int)
            or isinstance(max_new_tokens, bool)
            or max_new_tokens < 1
        ):
            raise ModelGenerationError("max_new_tokens must be a positive integer")

        do_sample = generation_config.get("do_sample", False)
        if not isinstance(do_sample, bool):
            raise ModelGenerationError("do_sample must be a boolean")

        temperature = generation_config.get("temperature")
        top_p = generation_config.get("top_p")
        top_k = generation_config.get("top_k")
        repetition_penalty = generation_config.get("repetition_penalty", 1.0)

        if do_sample:
            if not isinstance(temperature, (int, float)) or not 0 < float(temperature) <= 2:
                raise ModelGenerationError("temperature must be in (0, 2] when sampling")
            if not isinstance(top_p, (int, float)) or not 0 < float(top_p) <= 1:
                raise ModelGenerationError("top_p must be in (0, 1] when sampling")
            if not isinstance(top_k, int) or isinstance(top_k, bool) or not 0 <= top_k <= 200:
                raise ModelGenerationError("top_k must be an integer in [0, 200]")

        if not isinstance(repetition_penalty, (int, float)) or not 0.5 <= float(
            repetition_penalty
        ) <= 2.0:
            raise ModelGenerationError("repetition_penalty must be in [0.5, 2.0]")

        prompt = self.format_prompt(messages)
        encoded = self.tokenizer(
            prompt,
            return_tensors="pt",
            add_special_tokens=False,
            return_attention_mask=True,
        )
        prompt_token_count = int(encoded["input_ids"].shape[-1])
        if prompt_token_count < 1:
            raise ModelGenerationError("tokenized prompt is empty")

        model_limit = getattr(self.tokenizer, "model_max_length", None)
        if isinstance(model_limit, int) and 0 < model_limit < 1_000_000:
            if prompt_token_count + max_new_tokens > model_limit:
                raise ModelGenerationError(
                    f"Prompt ({prompt_token_count} tokens) plus max_new_tokens "
                    f"({max_new_tokens}) exceeds the tokenizer limit ({model_limit})."
                )

        device = torch.device(self.device)
        encoded = {key: value.to(device) for key, value in encoded.items()}

        generate_kwargs: dict[str, Any] = {
            "max_new_tokens": max_new_tokens,
            "do_sample": do_sample,
            "eos_token_id": list(self.eos_token_ids),
            "pad_token_id": self.pad_token_id,
            "use_cache": True,
        }
        if do_sample:
            generate_kwargs["temperature"] = float(temperature)
            generate_kwargs["top_p"] = float(top_p)
            generate_kwargs["top_k"] = int(top_k)
        if not math.isclose(float(repetition_penalty), 1.0, rel_tol=0.0, abs_tol=1e-12):
            generate_kwargs["repetition_penalty"] = float(repetition_penalty)

        set_seed(seed)
        if device.type == "cuda":
            torch.cuda.synchronize(device)
            torch.cuda.reset_peak_memory_stats(device)

        started = time.perf_counter()
        try:
            with torch.inference_mode():
                sequences = self.model.generate(**encoded, **generate_kwargs)
        except torch.cuda.OutOfMemoryError as exc:
            raise ModelGenerationError(
                "CUDA out of memory during generation. The model and KV cache did not "
                "fit. Do not auto-switch precision; restart the runtime and document "
                "an explicit configuration change."
            ) from exc
        except Exception as exc:
            raise ModelGenerationError(
                f"Model generation failed: {type(exc).__name__}: {exc}"
            ) from exc

        if device.type == "cuda":
            torch.cuda.synchronize(device)
        duration = time.perf_counter() - started

        completion_ids = sequences[0, prompt_token_count:].tolist()
        completion_ids = [int(token_id) for token_id in completion_ids]
        finish_reason = determine_finish_reason(completion_ids, self.eos_token_ids)
        text = self.tokenizer.decode(
            completion_ids,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )

        warnings: list[str] = []
        truncation_message = truncation_warning(finish_reason)
        if truncation_message:
            warnings.append(truncation_message)
        if text == "":
            warnings.append(
                "The model returned an empty completion. It is recorded and scored as "
                "an empty successful generation; it was not retried."
            )
        repetition = detect_repetition(text)
        if repetition["suspected_loop"]:
            warnings.append(
                "Suspected generation loop detected. The output is preserved and scored "
                "exactly as generated; it was not retried or truncated."
            )
        if "<|im_start|>" in text or "<|im_end|>" in text or "<|endoftext|>" in text:
            warnings.append(
                "Special-token text leaked into the decoded completion. It is preserved "
                "verbatim and included in scoring."
            )

        peak_memory = None
        if device.type == "cuda":
            peak_memory = int(torch.cuda.max_memory_allocated(device))

        return {
            "generated_text": text,
            "finish_reason": finish_reason,
            "warnings": warnings,
            "metadata": {
                "model_id": self.model_id,
                "model_revision": self.model_revision,
                "precision": self.precision,
                "device": self.device,
                "seed": seed,
                "prompt_tokens": prompt_token_count,
                "generated_tokens": len(completion_ids),
                "generation_duration_seconds": duration,
                "eos_token_ids": list(self.eos_token_ids),
                "pad_token_id": self.pad_token_id,
                "do_sample": do_sample,
                "temperature": float(temperature) if do_sample else None,
                "top_p": float(top_p) if do_sample else None,
                "top_k": int(top_k) if do_sample else None,
                "repetition_penalty": float(repetition_penalty),
                "max_new_tokens": max_new_tokens,
                "peak_gpu_memory_bytes": peak_memory,
                "non_thinking_mode": self.non_thinking_mode,
                "repetition_heuristic": repetition,
            },
        }


def _resolve_dtype(torch: Any, precision: str, device: Any) -> Any:
    if precision == "float16":
        return torch.float16
    if precision == "bfloat16":
        if device.type == "cuda" and not torch.cuda.is_bf16_supported():
            raise ModelLoadError(
                "precision='bfloat16' was requested, but this GPU does not report "
                "bfloat16 support. No automatic precision switch is performed. "
                "Set model.precision to 'float16' in config.json explicitly if that "
                "is the intended configuration."
            )
        return torch.bfloat16
    if precision == "float32":
        return torch.float32
    if precision == "auto":
        if device.type == "cuda":
            return torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        return torch.float32
    raise ModelLoadError(
        f"Unsupported precision {precision!r}; expected one of {PRECISION_CHOICES}"
    )


def _resolve_device(torch: Any, requested: str) -> Any:
    if requested == "cpu":
        return torch.device("cpu")
    if requested == "cuda":
        requested = "cuda:0"
    if not requested.startswith("cuda"):
        raise ModelLoadError(
            f"Unsupported device {requested!r}; expected 'cpu', 'cuda', or 'cuda:<index>'"
        )
    if not torch.cuda.is_available():
        raise ModelLoadError(
            "CUDA was requested but is not available in this process. In Colab, "
            "select Runtime > Change runtime type > GPU, then restart the model "
            "server. No automatic CPU fallback is performed."
        )
    try:
        device = torch.device(requested)
        index = device.index if device.index is not None else 0
        if index >= torch.cuda.device_count():
            raise ModelLoadError(
                f"Requested device {requested} but only "
                f"{torch.cuda.device_count()} CUDA device(s) are visible."
            )
        return torch.device(f"cuda:{index}")
    except (RuntimeError, ValueError) as exc:
        raise ModelLoadError(f"Invalid CUDA device {requested!r}: {exc}") from exc


def load_model(config: dict[str, Any]) -> LoadedModel:
    """Load the pinned model and tokenizer once for a server process."""

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    model_section = config.get("model")
    if not isinstance(model_section, dict):
        raise ModelLoadError("config is missing the 'model' object")

    model_id = model_section.get("id")
    revision = model_section.get("revision")
    tokenizer_id = model_section.get("tokenizer_id", model_id)
    tokenizer_revision = model_section.get("tokenizer_revision", revision)
    precision = model_section.get("precision", "float16")
    requested_device = model_section.get("device", "cuda")
    trust_remote_code = model_section.get("trust_remote_code", False)
    non_thinking_mode = model_section.get("non_thinking_mode", True)
    min_free_gb = float(model_section.get("min_free_gpu_memory_gb", 0.0))

    for name, value in (
        ("model.id", model_id),
        ("model.revision", revision),
        ("model.tokenizer_id", tokenizer_id),
        ("model.tokenizer_revision", tokenizer_revision),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ModelLoadError(f"{name} must be a non-empty string")
    if not isinstance(non_thinking_mode, bool) or not non_thinking_mode:
        raise ModelLoadError(
            "The primary experiment requires model.non_thinking_mode=true."
        )
    if not isinstance(trust_remote_code, bool):
        raise ModelLoadError("model.trust_remote_code must be a boolean")

    device = _resolve_device(torch, requested_device)
    dtype = _resolve_dtype(torch, precision, device)

    if device.type == "cuda":
        index = device.index or 0
        free_bytes, total_bytes = torch.cuda.mem_get_info(index)
        free_gb = free_bytes / (1024**3)
        LOGGER.info(
            "GPU %s: %.2f GiB free of %.2f GiB",
            torch.cuda.get_device_name(index),
            free_gb,
            total_bytes / (1024**3),
        )
        if min_free_gb > 0 and free_gb < min_free_gb:
            raise ModelLoadError(
                f"GPU {index} has {free_gb:.2f} GiB free, below the configured "
                f"min_free_gpu_memory_gb={min_free_gb:.2f}. Free memory or document "
                "an explicit configuration change. No automatic fallback is performed."
            )

    warnings: list[str] = []
    if device.type == "cpu":
        warnings.append(
            "Model is running on CPU. This is unusually slow and is not the primary "
            "Colab GPU configuration."
        )

    started = time.perf_counter()
    LOGGER.info("Loading tokenizer %s @ %s", tokenizer_id, tokenizer_revision)
    try:
        tokenizer = AutoTokenizer.from_pretrained(
            tokenizer_id,
            revision=tokenizer_revision,
            trust_remote_code=trust_remote_code,
        )
    except Exception as exc:
        raise ModelLoadError(
            f"Could not load tokenizer {tokenizer_id!r} at revision "
            f"{tokenizer_revision!r}: {type(exc).__name__}: {exc}"
        ) from exc

    LOGGER.info("Loading model %s @ %s (%s, %s)", model_id, revision, precision, device)
    try:
        model = AutoModelForCausalLM.from_pretrained(
            model_id,
            revision=revision,
            torch_dtype=dtype,
            trust_remote_code=trust_remote_code,
            low_cpu_mem_usage=True,
        )
        model.to(device)
        model.eval()
    except torch.cuda.OutOfMemoryError as exc:
        raise ModelLoadError(
            "CUDA out of memory while loading the model. No automatic precision or "
            "quantization change is performed. Restart with a free GPU or document "
            "an explicit configuration change."
        ) from exc
    except Exception as exc:
        raise ModelLoadError(
            f"Could not load model {model_id!r} at revision {revision!r}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    if getattr(model, "generation_config", None) is None:
        raise ModelLoadError("Loaded model has no generation_config")
    if getattr(tokenizer, "chat_template", None) is None:
        raise ModelLoadError(
            "Tokenizer has no chat template; Qwen3 chat formatting cannot be applied."
        )
    if tokenizer.pad_token_id is None:
        LOGGER.warning("Tokenizer has no pad token; using the first EOS id as pad")
        tokenizer.pad_token = tokenizer.eos_token

    try:
        eos_token_ids = normalize_eos_token_ids(
            getattr(model.generation_config, "eos_token_id", None),
            getattr(tokenizer, "eos_token_id", None),
        )
    except GenerationConfigError as exc:
        raise ModelLoadError(str(exc)) from exc

    pad_token_id = tokenizer.pad_token_id
    if pad_token_id is None:
        pad_token_id = eos_token_ids[0]
    if not isinstance(pad_token_id, int) or isinstance(pad_token_id, bool):
        raise ModelLoadError("Resolved pad_token_id is not an integer")

    # Keep model defaults coherent with the explicit values passed per request.
    model.generation_config.eos_token_id = list(eos_token_ids)
    model.generation_config.pad_token_id = int(pad_token_id)

    actual_model_revision = getattr(getattr(model, "config", None), "_commit_hash", None)
    actual_tokenizer_revision = getattr(tokenizer, "init_kwargs", {}).get("_commit_hash")
    for label, actual, requested in (
        ("model", actual_model_revision, revision),
        ("tokenizer", actual_tokenizer_revision, tokenizer_revision),
    ):
        if actual and requested and not (
            str(actual).startswith(str(requested)) or str(requested).startswith(str(actual))
        ):
            raise ModelLoadError(
                f"Loaded {label} commit {actual} does not match the pinned revision "
                f"{requested}. Refusing to serve a different revision."
            )

    loaded = LoadedModel(
        model=model,
        tokenizer=tokenizer,
        model_id=model_id,
        model_revision=revision,
        tokenizer_id=tokenizer_id,
        tokenizer_revision=tokenizer_revision,
        precision=precision,
        device=str(device),
        non_thinking_mode=non_thinking_mode,
        eos_token_ids=eos_token_ids,
        pad_token_id=int(pad_token_id),
        actual_model_revision=actual_model_revision,
        actual_tokenizer_revision=actual_tokenizer_revision,
        load_duration_seconds=time.perf_counter() - started,
        warnings=warnings,
    )

    # Verify non-thinking rendering now, not on the first real request.
    loaded.format_prompt([{"role": "user", "content": "health check"}])

    if device.type == "cuda":
        torch.cuda.empty_cache()
    LOGGER.info(
        "Model ready: eos_token_ids=%s pad_token_id=%s precision=%s device=%s",
        eos_token_ids,
        pad_token_id,
        precision,
        device,
    )
    return loaded
