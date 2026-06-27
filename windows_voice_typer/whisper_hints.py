from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
from typing import Sequence


_CANDIDATE_STRIP = " \t\r\n\"'`“”‘’()[]{}<>「」『』【】,、。.!?！？:;；/\\|"
_NUMERIC_ONLY_RE = re.compile(r"^[0-9０-９]+(?:[.,．。／/-][0-9０-９]+)*$")
_ALLOWED_RE = re.compile(r"[A-Za-z0-9ぁ-んァ-ヶ一-龠々〆ヵヶ]")


@dataclass(frozen=True)
class WhisperHints:
    terms: list[str]
    prompt: str
    hotwords: str | None


def build_whisper_hints(config: dict[str, Any], dictionary: Any) -> WhisperHints:
    prompt_terms_limit = max(0, _int_config(config.get("whisper_hint_max_terms", 40), 40))
    hotword_terms_limit = max(0, _int_config(config.get("whisper_hotwords_max_terms", 20), 20))
    max_terms = max(prompt_terms_limit, hotword_terms_limit)
    terms = collect_whisper_hint_terms(dictionary, max_terms=max_terms)
    prompt = compose_whisper_prompt(
        str(config.get("whisper_prompt", "")),
        terms,
        enabled=bool(config.get("whisper_auto_prompt_hints_enabled", True)),
        max_terms=prompt_terms_limit,
    )
    hotwords = compose_whisper_hotwords(
        terms,
        enabled=bool(config.get("whisper_hotwords_enabled", False)),
        max_terms=hotword_terms_limit,
    )
    return WhisperHints(terms=terms, prompt=prompt, hotwords=hotwords)


def collect_whisper_hint_terms(dictionary: Any, *, max_terms: int) -> list[str]:
    if max_terms <= 0:
        return []
    data = dictionary.data if hasattr(dictionary, "data") else dictionary
    if not isinstance(data, dict):
        return []

    seen: set[str] = set()
    terms: list[str] = []

    for rule in _iter_replacement_rules(data):
        if isinstance(rule, dict):
            _add_term(terms, seen, rule.get("to"))
        if len(terms) >= max_terms:
            return terms[:max_terms]

    for entry in _iter_url_entries(data):
        if not isinstance(entry, dict):
            continue
        _add_term(terms, seen, entry.get("title"))
        if len(terms) >= max_terms:
            return terms[:max_terms]

    return terms[:max_terms]


def compose_whisper_prompt(base_prompt: str, hint_terms: Sequence[str], *, enabled: bool, max_terms: int) -> str:
    base = _normalize_prompt(base_prompt)
    if not enabled or max_terms <= 0:
        return base
    suffix = _compose_hint_suffix(hint_terms, max_terms=max_terms)
    if not suffix:
        return base
    return "\n".join(part for part in (base, suffix) if part).strip()


def compose_whisper_hotwords(hint_terms: Sequence[str], *, enabled: bool, max_terms: int) -> str | None:
    if not enabled or max_terms <= 0:
        return None
    terms = [term for term in hint_terms if term][:max_terms]
    if not terms:
        return None
    return ", ".join(terms)


def _iter_replacement_rules(data: dict[str, Any]) -> list[dict[str, Any]]:
    value = data.get("replacements", [])
    return value if isinstance(value, list) else []


def _iter_url_entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    value = data.get("urls", [])
    return value if isinstance(value, list) else []


def _add_term(terms: list[str], seen: set[str], value: Any) -> None:
    text = _normalize_candidate(value)
    if not _is_valid_candidate(text):
        return
    key = text.casefold()
    if key in seen:
        return
    seen.add(key)
    terms.append(text)


def _normalize_candidate(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text.strip(_CANDIDATE_STRIP)


def _is_valid_candidate(text: str) -> bool:
    if len(text) < 2 or len(text) > 24:
        return False
    if _NUMERIC_ONLY_RE.fullmatch(text):
        return False
    if " " in text and len(text) > 18:
        return False
    if not _ALLOWED_RE.search(text):
        return False
    return True


def _normalize_prompt(text: str) -> str:
    return re.sub(r"\n\s+", "\n", re.sub(r"\s+\n", "\n", str(text or ""))).strip()


def _compose_hint_suffix(hint_terms: Sequence[str], *, max_terms: int) -> str:
    selected = [term for term in hint_terms if term][:max_terms]
    if not selected:
        return ""
    suffix = "補助語:"
    for term in selected:
        candidate = f"{suffix} {term}" if suffix == "補助語:" else f"{suffix}、{term}"
        if len(candidate) > 120:
            break
        suffix = candidate
    return "" if suffix == "補助語:" else suffix


def _int_config(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
