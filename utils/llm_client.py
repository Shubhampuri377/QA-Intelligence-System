"""
Multi-provider LLM client (Gemini / Claude / OpenAI) shared across all workflows.
Usage:
    from utils.llm_client import LLMClient
    client = LLMClient(provider, api_key, model)
    result = client.run(prompt, debug_log)   # -> {"text","input_tokens","output_tokens","total_tokens"}
"""

import re
import time
import traceback

PROVIDER_MODELS = {
    "Gemini (Google)":    ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash", "gemini-1.5-pro"],
    "Claude (Anthropic)": ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
    "OpenAI (GPT)":       ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
}

KEY_PLACEHOLDERS = {
    "Gemini (Google)": "AIza••••••••••••••••",
    "Claude (Anthropic)": "sk-ant-••••••••••••",
    "OpenAI (GPT)": "sk-••••••••••••••••",
}


def estimate_cost(provider: str, input_tokens: int, output_tokens: int) -> float:
    if provider == "Gemini (Google)":
        return (input_tokens * 0.000075 + output_tokens * 0.0003) / 1000
    if provider == "Claude (Anthropic)":
        return input_tokens * 0.000003 + output_tokens * 0.000015
    if provider == "OpenAI (GPT)":
        return input_tokens * 0.000005 + output_tokens * 0.000015
    return 0.0


def classify_api_error(err_str: str, provider: str) -> str:
    s = err_str.lower()
    if any(x in s for x in ["insufficient", "balance", "payment", "billing", "credit"]):
        return "BILLING ERROR — Insufficient funds / payment required"
    if any(x in s for x in ["401", "unauthorized", "invalid api key", "authentication"]):
        return "AUTH ERROR — Invalid or expired API key"
    if any(x in s for x in ["429", "rate limit", "quota", "resource_exhausted"]):
        return "RATE LIMIT / QUOTA — Too many requests or quota exceeded"
    if any(x in s for x in ["403", "forbidden", "permission"]):
        return "PERMISSION ERROR — Key lacks access to this model"
    if any(x in s for x in ["404", "not found", "model"]):
        return "MODEL NOT FOUND — Check model name spelling"
    if any(x in s for x in ["500", "502", "503", "internal", "server"]):
        return "SERVER ERROR — Provider-side issue, retry later"
    if any(x in s for x in ["timeout", "timed out", "connection"]):
        return "NETWORK TIMEOUT — Connection issue"
    if any(x in s for x in ["context", "token", "length", "max_tokens"]):
        return "CONTEXT LENGTH — Prompt too long for this model"
    return "UNKNOWN API ERROR"


def _parse_retry_delay(err_str: str, default: float = 5.0, cap: float = 30.0) -> float:
    """Pulls a provider-suggested retry delay out of an error message (e.g.
    Gemini's `'retryDelay': '43s'` or "Please retry in 43.7s"), capped so a
    single retry never stalls the UI for too long."""
    m = re.search(r"retrydelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)", err_str, re.IGNORECASE)
    if not m:
        m = re.search(r"retry in (\d+(?:\.\d+)?)", err_str, re.IGNORECASE)
    if m:
        try:
            return min(float(m.group(1)), cap)
        except ValueError:
            pass
    return default


class LLMClient:
    def __init__(self, provider: str, api_key: str, model: str):
        self.provider = provider
        self.api_key = api_key
        self.model = model

    def run(self, prompt: str, debug, max_retries: int = 2) -> dict:
        debug.add("info", "LLM-CALL", f"Provider: {self.provider}  Model: {self.model}",
                  f"Prompt length: {len(prompt):,} chars")
        dispatch = {
            "Gemini (Google)": self._run_gemini,
            "Claude (Anthropic)": self._run_claude,
            "OpenAI (GPT)": self._run_openai,
        }.get(self.provider)
        if not dispatch:
            raise ValueError(f"Unknown provider: {self.provider}")

        for attempt in range(max_retries + 1):
            try:
                return dispatch(prompt, debug)
            except Exception as e:
                err_type = classify_api_error(str(e), self.provider)
                if err_type.startswith("RATE LIMIT") and attempt < max_retries:
                    delay = _parse_retry_delay(str(e))
                    debug.add("warn", "RETRY",
                              f"{err_type} — waiting {delay:.0f}s before retry {attempt + 1}/{max_retries}")
                    time.sleep(delay)
                    continue
                raise

    def _run_gemini(self, prompt, debug):
        try:
            from google import genai as gai
        except ImportError:
            debug.add("err", "IMPORT", "google-generativeai not installed", "Run: pip install google-generativeai")
            raise
        # Gemini 2.5 counts THINKING tokens against the output budget, and the
        # default budget is small enough that a long structured response gets cut
        # off mid-JSON — the model spends the allowance reasoning and never
        # finishes the object. Raise the ceiling and, since these prompts ask for
        # a strict JSON document rather than analysis, turn thinking off so the
        # whole budget goes to the answer.
        cfg = None
        try:
            from google.genai import types as gtypes
            kwargs = {"max_output_tokens": 32768, "response_mime_type": "application/json"}
            try:
                kwargs["thinking_config"] = gtypes.ThinkingConfig(thinking_budget=0)
            except Exception:
                pass
            cfg = gtypes.GenerateContentConfig(**kwargs)
        except Exception as e:
            debug.add("warn", "GEMINI-CFG",
                      f"Could not build generation config ({e}) — using provider defaults, "
                      f"a long response may be truncated")

        try:
            client = gai.Client(api_key=self.api_key)
            debug.add("info", "GEMINI", "Client created, sending request…"
                      + (" (max_output_tokens=32768, thinking off)" if cfg else ""))
            r = (client.models.generate_content(model=self.model, contents=prompt, config=cfg)
                 if cfg else client.models.generate_content(model=self.model, contents=prompt))
        except Exception as e:
            err_type = classify_api_error(str(e), self.provider)
            debug.add("err", "GEMINI-API", f"{err_type}: {str(e)[:200]}", traceback.format_exc()[:600])
            raise
        text = r.text or ""
        u = r.usage_metadata
        inp = u.prompt_token_count or 0
        out = u.candidates_token_count or 0
        tot = u.total_token_count or 0
        debug.add("ok", "GEMINI-RESP", f"Response received — {len(text):,} chars",
                  f"Tokens: input={inp}, output={out}, total={tot}")
        if not text.strip():
            debug.add("warn", "GEMINI-EMPTY", "Model returned empty text — possible safety block or quota issue")
        return {"text": text, "input_tokens": inp, "output_tokens": out, "total_tokens": tot}

    def _run_claude(self, prompt, debug):
        try:
            import anthropic
        except ImportError:
            debug.add("err", "IMPORT", "anthropic SDK not installed", "Run: pip install anthropic")
            raise
        try:
            client = anthropic.Anthropic(api_key=self.api_key)
            debug.add("info", "CLAUDE", "Streaming request started…")
            text_chunks = []
            with client.messages.stream(
                    model=self.model,
                    max_tokens=64000,
                    messages=[{"role": "user", "content": prompt}]
            ) as stream:
                for event in stream:
                    if event.type == "content_block_delta" and hasattr(event.delta, "text"):
                        text_chunks.append(event.delta.text)
                final_msg = stream.get_final_message()
            text = "".join(text_chunks)
            inp = final_msg.usage.input_tokens or 0
            out = final_msg.usage.output_tokens or 0
            debug.add("ok", "CLAUDE-RESP", f"Response received — {len(text):,} chars",
                      f"Tokens: input={inp}, output={out}, total={inp + out}  stop_reason={final_msg.stop_reason}")
            if not text.strip():
                debug.add("warn", "CLAUDE-EMPTY", "Model returned empty text — check prompt or API limits")
            return {"text": text, "input_tokens": inp, "output_tokens": out, "total_tokens": inp + out}
        except Exception as e:
            err_type = classify_api_error(str(e), self.provider)
            debug.add("err", "CLAUDE-API", f"{err_type}: {str(e)[:200]}", traceback.format_exc()[:600])
            raise

    def _run_openai(self, prompt, debug):
        try:
            from openai import OpenAI
        except ImportError:
            debug.add("err", "IMPORT", "openai SDK not installed", "Run: pip install openai")
            raise
        try:
            client = OpenAI(api_key=self.api_key)
            debug.add("info", "OPENAI", "Client created, sending request…")
            resp = client.chat.completions.create(model=self.model, temperature=0.2,
                messages=[{"role": "user", "content": prompt}], max_tokens=16000)
        except Exception as e:
            err_type = classify_api_error(str(e), self.provider)
            debug.add("err", "OPENAI-API", f"{err_type}: {str(e)[:200]}", traceback.format_exc()[:600])
            raise
        text = resp.choices[0].message.content or ""
        inp = resp.usage.prompt_tokens or 0
        out = resp.usage.completion_tokens or 0
        debug.add("ok", "OPENAI-RESP", f"Response received — {len(text):,} chars",
                  f"Tokens: input={inp}, output={out}, total={resp.usage.total_tokens}  finish={resp.choices[0].finish_reason}")
        if not text.strip():
            debug.add("warn", "OPENAI-EMPTY", "Model returned empty text — check prompt or billing")
        return {"text": text, "input_tokens": inp, "output_tokens": out, "total_tokens": resp.usage.total_tokens}
