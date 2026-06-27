from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_DICTIONARY: dict[str, Any] = {
    "version": 1,
    "replacements": [
        {"from": "オープンAI", "to": "OpenAI", "mode": "literal"},
        {"from": "オープンエーアイ", "to": "OpenAI", "mode": "literal"},
        {"from": "声基地", "to": "声吉", "mode": "literal"},
        {"from": "声機値", "to": "声吉", "mode": "literal"},
        {"from": "声キチ", "to": "声吉", "mode": "literal"},
        {"from": "ウィスパー", "to": "Whisper", "mode": "literal"},
        {"from": "ウイスパー", "to": "Whisper", "mode": "literal"},
        {"from": "ミスパー", "to": "Whisper", "mode": "literal"},
        {"from": "5人式", "to": "誤認識", "mode": "literal"},
        {"from": "五人式", "to": "誤認識", "mode": "literal"},
        {"from": "5認識", "to": "誤認識", "mode": "literal"},
        {"from": "五認識", "to": "誤認識", "mode": "literal"},
        {"from": "5時たち", "to": "誤字たち", "mode": "literal"},
        {"from": "五時たち", "to": "誤字たち", "mode": "literal"},
        {"from": "自処的", "to": "自動的", "mode": "literal"},
        {"from": "自処に", "to": "自動的に", "mode": "literal"},
        {"from": "実過", "to": "実装", "mode": "literal"},
        {"from": "春シネーション", "to": "ハルシネーション", "mode": "literal"},
        {"from": "春市ネーション", "to": "ハルシネーション", "mode": "literal"},
        {"from": "春子ネーション", "to": "ハルシネーション", "mode": "literal"},
        {"from": "チャットGPT", "to": "ChatGPT", "mode": "literal"},
        {"from": "オラマ", "to": "Ollama", "mode": "literal"},
        {"from": "オラーマ", "to": "Ollama", "mode": "literal"},
        {"from": "コーデックス", "to": "Codex", "mode": "literal"},
        {"from": "パイソン", "to": "Python", "mode": "literal"},
        {"from": "ジーピーユー", "to": "GPU", "mode": "literal"},
        {"from": "シーピーユー", "to": "CPU", "mode": "literal"},
        {"from": "オルト", "to": "Alt", "mode": "literal"},
        {"from": "アクアボイス", "to": "AquaVoice", "mode": "literal"},
        {"from": "チャットジーピーティー", "to": "ChatGPT", "mode": "literal"},
        {"from": "苦闘点", "to": "句読点", "mode": "literal"},
    ],
    "urls": [
        {
            "title": "ChatGPT",
            "url": "https://chatgpt.com/",
            "aliases": ["ChatGPT", "チャットGPT", "チャットジーピーティー"],
        },
        {
            "title": "OpenAI",
            "url": "https://openai.com/",
            "aliases": ["OpenAI", "オープンAI", "オープンエーアイ"],
        },
        {
            "title": "note",
            "url": "https://note.com/",
            "aliases": ["note", "ノート"],
        },
    ],
}

URL_WORD = r"(?:URL|url|ＵＲＬ|ユーアールエル|アドレス|リンク)"
SITE_WORD = r"(?:公式)?(?:サイト|ホームページ|HP|ページ)?"
ACTION_WORD = r"(?:を)?(?:貼って|貼る|入れて|入力して|挿入して|書いて|ください|お願い)?"


class VoiceDictionary:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.data: dict[str, Any] = {}

    def ensure(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self.load()
        else:
            self.data = json.loads(json.dumps(DEFAULT_DICTIONARY, ensure_ascii=False))
            self.save()

    def load(self) -> None:
        with self.path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if not isinstance(loaded, dict):
            raise ValueError(f"Dictionary must be an object: {self.path}")
        self.data = _merge_defaults(loaded)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    @property
    def replacements(self) -> list[dict[str, Any]]:
        value = self.data.setdefault("replacements", [])
        return value if isinstance(value, list) else []

    @property
    def urls(self) -> list[dict[str, Any]]:
        value = self.data.setdefault("urls", [])
        return value if isinstance(value, list) else []

    def process(self, text: str, template: str = "{url}") -> str:
        return self.apply_replacements(self.expand_urls(text, template=template))

    def apply_replacements(self, text: str) -> str:
        result = text
        literal_rules = [
            rule
            for rule in self.replacements
            if str(rule.get("mode", "literal")).lower() == "literal"
        ]
        for rule in sorted(literal_rules, key=lambda item: len(str(item.get("from", ""))), reverse=True):
            source = str(rule.get("from", ""))
            target = str(rule.get("to", ""))
            if source:
                result = result.replace(source, target)
        return result

    def expand_urls(self, text: str, template: str = "{url}") -> str:
        result = text
        for entry in self.urls:
            title = str(entry.get("title", "")).strip()
            url = str(entry.get("url", "")).strip()
            aliases = [title, *[str(alias).strip() for alias in entry.get("aliases", [])]]
            aliases = [alias for alias in dict.fromkeys(aliases) if alias]
            if not url or not aliases:
                continue
            rendered = template.format(title=title, url=url)
            for alias in sorted(aliases, key=len, reverse=True):
                result = _replace_url_command(result, alias, rendered)
        return result


def _replace_url_command(text: str, alias: str, rendered: str) -> str:
    alias_pattern = re.escape(alias).replace(r"\ ", r"\s*")
    patterns = [
        re.compile(rf"{alias_pattern}\s*(?:の)?\s*{SITE_WORD}\s*(?:の)?\s*{URL_WORD}\s*{ACTION_WORD}", re.I),
        re.compile(rf"{alias_pattern}\s*(?:の)?\s*{URL_WORD}\s*{ACTION_WORD}", re.I),
    ]
    result = text
    for pattern in patterns:
        result = pattern.sub(rendered, result)
    return result


def _merge_defaults(loaded: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(DEFAULT_DICTIONARY, ensure_ascii=False))
    for key, value in loaded.items():
        if key in ("replacements", "urls") and isinstance(value, list):
            merged[key] = value
        elif key not in ("replacements", "urls"):
            merged[key] = value
    return merged
