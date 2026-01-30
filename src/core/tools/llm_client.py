from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional
from google import genai
from google.genai import types


def _extract_json(text: str) -> Any:
    text = (text or "").strip()

    # 1) direct parse
    try:
        return json.loads(text)
    except Exception:
        pass

    # 2) extract first JSON block
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start:end + 1])

    # 3) extract list block
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start:end + 1])

    raise ValueError("Model output is not valid JSON.")



def generate_json(prompt: str, schema_name: str, temperature: float = 0.2) -> Any:
    """
    Gemini-backed JSON generator.
    
    """
    model = os.getenv("GEMINI_MODEL", None) or "gemini-2.0-flash"
    api_key = os.getenv( "LLM_API_KEY", None)

    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY in settings/.env")


    client = genai.Client(api_key=api_key)

    system = (
        "You are a strict JSON generator. "
        "Return ONLY a JSON object that matches the requested schema. "
        "Do not include markdown fences, commentary, or extra keys."
    )

    # embed schema_name so the model knows which shape you want.
    user = f"Schema name: {schema_name}\n\n{prompt}"

    resp = client.models.generate_content(
        model=model,
        contents=[
            types.Content(role="user", parts=[types.Part(text=f"{system}\n\n{user}")])
        ],
        config=types.GenerateContentConfig(
            temperature=temperature,
            response_mime_type="application/json",  
        ),
    )

    # New SDK usually returns text in resp.text
    text = getattr(resp, "text", None)
    if not text and getattr(resp, "candidates", None):
        # fallback extraction
        try:
            text = resp.candidates[0].content.parts[0].text
        except Exception:
            text = ""

    data = _extract_json(text)

    if data in ({}, [], None):
        raise ValueError("LLM returned empty JSON")

    return data


def generate_text(
    prompt: str,
    *,
    temperature: float = 0.3,
    max_output_tokens: Optional[int] = None,
) -> str:
    """
    Generate free-form text (Markdown) using Gemini.

    Used for:
    - section writing
    - summaries
    - recommendations
    """

    model = os.getenv("GEMINI_MODEL", None) or "gemini-2.0-flash"
    api_key = os.getenv( "LLM_API_KEY", None)

    client = genai.Client(api_key=api_key)
    system = (
        "You are a helpful assistant. "
        "Provide clear, professional, consulting-style responses."
        "Use Markdown formatting."
    )

    user = prompt

    resp = client.models.generate_content(
        model=model,
        contents=[
            types.Content(role="user", parts=[types.Part(text=f"{system}\n\n{user}")])
        ],
        config=types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        ),
    )

    text = getattr(resp, "text", None)
    if not text:
        raise RuntimeError("LLM returned empty text response")

    return text.strip()