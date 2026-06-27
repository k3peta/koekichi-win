from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PostprocessResult:
    text: str
    provider: str
    error: str = ""


JAPANESE_CHARS = r"一-龠々〆ヵヶぁ-んァ-ン"
COMMON_TRANSCRIPT_HALLUCINATIONS = (
    "それではご視聴ありがとうございました",
    "ではご視聴ありがとうございました",
    "ご視聴ありがとうございました",
    "ご清聴ありがとうございました",
    "ご視聴ありがとうございます",
)


def postprocess(text: str, config: dict[str, Any]) -> PostprocessResult:
    mode = str(config.get("postprocess_mode", "local_punctuation"))
    if mode in ("", "off", "none", "false"):
        return PostprocessResult(text=text, provider="none")
    cleaned = normalize_transcript_artifacts(text)
    if mode == "local_punctuation":
        return PostprocessResult(text=basic_punctuation(cleaned), provider="local")
    if mode in ("openai_compatible_punctuation", "openai_compatible_rewrite"):
        try:
            rewritten = rewrite_with_openai_compatible(cleaned, config, rewrite=mode.endswith("_rewrite"))
            rewritten = tune_punctuation(sanitize_model_output(rewritten))
            if mode.endswith("_punctuation"):
                validate_punctuation_rewrite(cleaned, rewritten)
            return PostprocessResult(text=rewritten, provider="openai-compatible")
        except Exception as error:
            return PostprocessResult(text=basic_punctuation(cleaned), provider="local", error=str(error))
    return PostprocessResult(text=basic_punctuation(cleaned), provider="local", error=f"unknown postprocess_mode: {mode}")


def rewrite_with_openai_compatible(text: str, config: dict[str, Any], *, rewrite: bool) -> str:
    base_url = str(config.get("openai_compatible_base_url", "")).rstrip("/")
    if not base_url:
        base_url = "https://api.openai.com/v1"
    env_name = str(config.get("openai_compatible_api_key_env", "OPENAI_API_KEY"))
    key = os.environ.get(env_name, "")
    if not key and "localhost" not in base_url and "127.0.0.1" not in base_url:
        raise RuntimeError(f"{env_name} is not set")
    instructions = str(config.get("openai_compatible_custom_prompt", "")).strip()
    if not instructions:
        instructions = default_instructions(rewrite=rewrite)
    payload = {
        "model": str(config.get("openai_compatible_model", "gpt-4.1-mini")),
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": prompt_for_mode(text, rewrite=rewrite)},
        ],
        "temperature": 0,
        "max_tokens": int(config.get("openai_compatible_max_tokens", 512)),
    }
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    timeout = float(config.get("openai_compatible_timeout_seconds", 8.0))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API error {error.code}: {body}") from error
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("API response did not contain choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("API response did not contain text")
    return content


def basic_punctuation(text: str) -> str:
    result = normalize_transcript_artifacts(text)
    if not result:
        return result
    result = result.replace("?", "？").replace("!", "！")
    result = re.sub(r"\s+([、。！？])", r"\1", result)
    boundary = r"(ちゃんと|これ|それ|あれ|では|でも|ただ|あと|あとは|今|次|句読点|自動|[一-龠ぁ-んァ-ン])"
    result = re.sub(rf"(ですね|ますね|ましたね|でしたね|だね|みたいだね)\s+(?={boundary})", r"\1。", result)
    result = re.sub(rf"(でしょうか|ですか|ますか|かね)(?={boundary})", r"\1。", result)
    result = re.sub(
        rf"(ですね|ますね|ました|でした|です(?![がけのでからし]|けど|けれど)|ます(?![がけのでからしねよ]|けど|けれど)|だね|みたいだね)(?={boundary})",
        r"\1。",
        result,
    )
    if result[-1] not in "。！？!?.,、，．":
        result += "。"
    return tune_punctuation(result)


def tune_punctuation(text: str) -> str:
    result = normalize_transcript_artifacts(text)
    result = re.sub(r"今。(?=[はがをにのでへとも])", "今", result)
    result = re.sub(r"今回。(?=[はがをにのでへとも])", "今回", result)
    result = re.sub(r"なかな(?:。|\s+)か", "なかなか", result)
    result = re.sub(
        r"(とりあえず|ひとまず|まず|では|じゃあ|それでは|あと|あとは|ちなみに|ただ|それで|なので)。(?=[一-龠ぁ-んァ-ンA-Za-z0-9])",
        r"\1、",
        result,
    )
    result = re.sub(
        r"(かもしれません|かもしれない|でしょうか|でしょう|みたいです|みたいだ|ません|です|ます|でした|ました|だ|だった)(?:。|\s+)ね([。、])",
        r"\1ね\2",
        result,
    )
    result = re.sub(r"(https?://\S+?)(?=[一-龠ぁ-んァ-ン])", r"\1 ", result)
    result = re.sub(r"\s+([、。！？])", r"\1", result)
    result = re.sub(r"([、。！？])\1+", r"\1", result)
    return normalize_transcript_artifacts(result)


def normalize_transcript_artifacts(text: str) -> str:
    result = text.strip()
    if not result:
        return result
    result = normalize_common_misrecognitions(result)
    result = remove_common_hallucination_fillers(result)
    if not result:
        return result
    result = re.sub(r"[ \t\u3000]+([、。！？!?.,，．])", r"\1", result)
    result = re.sub(rf"(?<=[{JAPANESE_CHARS}])[ \t\u3000]+(?=[{JAPANESE_CHARS}A-Za-z0-9])", "", result)
    result = re.sub(rf"(?<=[A-Za-z0-9])[ \t\u3000]+(?=[{JAPANESE_CHARS}])", "", result)
    return collapse_repeated_artifacts(result)


def remove_common_hallucination_fillers(text: str) -> str:
    result = text.strip()
    if not result:
        return result

    compact = re.sub(r"[\s、。！？!?.,，．]+", "", result)
    remainder = compact
    for phrase in COMMON_TRANSCRIPT_HALLUCINATIONS:
        remainder = remainder.replace(phrase, "")
    if not remainder:
        return ""

    separator = r"[\s、。！？!?.,，．]*"
    for phrase in COMMON_TRANSCRIPT_HALLUCINATIONS:
        escaped = re.escape(phrase)
        result = re.sub(rf"^(?:{escaped}{separator})+", "", result)
        result = re.sub(rf"(?:{separator}{escaped})+$", "", result)
    return result.strip(" \t\r\n、。！？!?.,，．")


def collapse_repeated_artifacts(text: str) -> str:
    result = text
    previous = None
    while previous != result:
        previous = result
        result = collapse_repeated_phrases(result)
        result = re.sub(r"(?<![A-Za-z])([A-Z]{2,10})\1(?![A-Za-z])", r"\1", result)
        result = re.sub(r"(?<![一-龠])([一-龠]{2,6})\1(?![一-龠])", r"\1", result)
        result = re.sub(r"(?<![ァ-ンー])([ァ-ンー]{3,10})\1(?![ァ-ンー])", r"\1", result)
    return result


def normalize_common_misrecognitions(text: str) -> str:
    result = text
    replacements = (
        ("高液値", "声吉"),
        ("声機値", "声吉"),
        ("ペンチマーク", "ベンチマーク"),
        ("グラッシュ", "クラッシュ"),
        ("ミスパー", "Whisper"),
        ("自処的", "自動的"),
        ("自処に", "自動的に"),
        ("実過", "実装"),
        ("ジェミにAPI", "Gemini API"),
        ("ジェミニAPI", "Gemini API"),
        ("ジェミに", "Gemini"),
        ("話しすと", "離すと"),
        ("話しす", "離す"),
        ("春シネーション", "ハルシネーション"),
        ("春市ネーション", "ハルシネーション"),
        ("春子ネーション", "ハルシネーション"),
        ("よくある春日", "よくあるハルシネーション"),
        ("また離すと録音が解除されます解除される", "また離すと録音が解除される"),
    )
    for source, target in replacements:
        result = result.replace(source, target)
    result = re.sub(r"((?:キーボード|キー|入力|マウス|マウスカーソル|カーソル|ボタン)が)向こう(?=になる|に)", r"\1無効", result)
    return result


def collapse_repeated_phrases(text: str) -> str:
    result = text
    result = re.sub(r"([一-龠ぁ-んァ-ン]{1,6}(?:に|を|が|は|で|へ|と|も|の|か|ね|よ))\1", r"\1", result)
    result = re.sub(r"(解除されます)解除される", r"\1", result)
    result = re.sub(r"(録音状態になる)また\1", r"\1また", result)
    return result


def default_instructions(*, rewrite: bool) -> str:
    if rewrite:
        return (
            "あなたは日本語音声入力の後処理器です。音声認識の誤字、明らかな同音誤変換、重複、句読点だけを直してください。"
            "意味、語尾、話者の意図、情報量を変えず、要約や補足や言い換えをしないでください。"
            "内容を増やさず、URL、英数字、固有名詞、コード片は変更しないでください。"
            "説明や引用符を付けず、修正後の本文だけを返してください。"
        )
    return (
        "あなたは日本語音声入力の句読点補正器です。語尾、文体、語彙を変更せず、句読点だけを追加してください。"
        "読点「、」は控えめにし、迷う場所には入れないでください。"
        "ただし文末、問い、感嘆、明確な文の終わりには「。」「？」「！」を正確に入れてください。"
        "短い語句ごとに句点を打たず、話し言葉の流れを保ってください。"
        "説明や引用符を付けず、本文だけを返してください。"
    )


def prompt_for_mode(text: str, *, rewrite: bool) -> str:
    if rewrite:
        return f"次の音声入力文の誤字、重複、句読点だけを軽く修正してください。意味は変えないでください。\n入力: {text}\n出力:"
    return f"次の本文に句読点だけを追加してください。読点は控えめにし、文末には句点を正確に入れてください。\n入力: {text}\n出力:"


def sanitize_model_output(text: str) -> str:
    result = text.strip()
    for prefix in ("出力:", "出力：", "修正後:", "修正後："):
        if result.startswith(prefix):
            result = result[len(prefix) :].strip()
    quote_pairs = (("「", "」"), ("『", "』"), ("“", "”"), ("‘", "’"))
    for left, right in quote_pairs:
        if result.startswith(left) and result.endswith(right):
            result = result[len(left) : -len(right)].strip()
    if len(result) >= 2 and result[0] == result[-1] and result[0] in "\"'「」":
        result = result[1:-1].strip()
    return result


def validate_punctuation_rewrite(original: str, rewritten: str) -> None:
    if not rewritten:
        raise RuntimeError("empty rewrite")
    if punctuation_signature(original) != punctuation_signature(rewritten):
        raise RuntimeError("punctuation mode changed non-punctuation text")
    if not contains_japanese(original):
        return

    signature_len = max(1, len(punctuation_signature(original)))
    original_commas = punctuation_count(original, "、，,")
    rewritten_commas = punctuation_count(rewritten, "、，,")
    added_commas = max(0, rewritten_commas - original_commas)
    if added_commas > max(2, signature_len // 18) or rewritten_commas > max(3, signature_len // 14):
        raise RuntimeError("punctuation mode added too many commas")

    short_fragments = 0
    for fragment in re.split(r"[。！？!?]", rewritten)[:-1]:
        body = re.sub(r"[\s、。，．,.！？!?]", "", fragment)
        if body and contains_japanese(body) and len(body) <= 3:
            short_fragments += 1
    if short_fragments >= 2:
        raise RuntimeError("punctuation mode created too many short sentence fragments")

    stripped = rewritten.strip()
    if signature_len >= 4 and not re.search(r"https?://\S+$", stripped):
        if not re.search(r"[。！？!?][」』）\]\)]?$", stripped):
            raise RuntimeError("punctuation mode missed sentence-final punctuation")


def punctuation_signature(text: str) -> str:
    return re.sub(r"[\s、。，．,.！？!?]", "", text)


def punctuation_count(text: str, chars: str) -> int:
    return sum(text.count(char) for char in chars)


def contains_japanese(text: str) -> bool:
    return re.search(r"[一-龠々〆ヵヶぁ-んァ-ン]", text) is not None
