"""
Случайные мемные реплики на основе текущего сообщения и недавней истории чата.

С OPENAI_API_KEY в env — часть мемов генерит LLM (gpt-4o-mini по умолчанию),
иначе остаются шаблоны из фраз чата.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from collections import deque
from typing import Deque, Optional

MEME_CHANCE_GROUP = 0.035
MEME_CHANCE_PRIVATE = 0.012
MEME_COOLDOWN_SEC = 420.0
MEME_HISTORY_SIZE = 24
MEME_MIN_HISTORY = 2
MEME_MIN_TEXT_LEN = 6
MEME_MAX_LEN = 140

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
MEME_LLM_MODEL = os.getenv("MEME_LLM_MODEL", "gpt-4o-mini")
MEME_LLM_CHANCE = float(os.getenv("MEME_LLM_CHANCE", "0.85"))
MEME_LLM_TIMEOUT_SEC = float(os.getenv("MEME_LLM_TIMEOUT_SEC", "12"))
MEME_LLM_HISTORY_LINES = 8
MEME_FORCE_COOLDOWN_SEC = 20.0
MEME_FORCE_FALLBACK_PROMPT = "тишина в рабочем чате, все ждут макет"

URL = re.compile(r"https?://|t\.me/", re.I)
MENTION = re.compile(r"@\w+", re.I)
WORD = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9][a-zA-Zа-яА-ЯёЁ0-9\-_]*", re.UNICODE)

STOP_WORDS = frozenset({
    "и", "в", "во", "на", "по", "к", "ко", "с", "со", "у", "о", "об", "от", "до", "за", "из",
    "что", "это", "как", "так", "а", "но", "да", "нет", "ну", "же", "ли", "бы", "то", "типа",
    "вот", "тут", "там", "ещё", "еще", "уже", "ещё", "мне", "меня", "мой", "моя", "мои", "тебя",
    "ты", "он", "она", "они", "мы", "вы", "я", "все", "всё", "всего", "просто", "очень", "прям",
    "the", "is", "are", "to", "a", "an", "and", "or", "in", "on", "at", "for", "of", "it",
})

MEME_TEMPLATES = [
    "POV: {snippet}",
    "когда {snippet}, а на душе {word}",
    "ахах «{snippet}» — классика",
    "{word}? в 2026? да ладно",
    "бля только что прочитал «{snippet}» и чуть не залил",
    "типа {snippet}... ну ок",
    "честно, {word} — это уже мем",
    "«{snippet}» — паша бы сказал гуд",
    "ну {word} конечно, без вариантов",
    "ахаха {snippet}... ладно, забрал",
    "именно так я и представлял {word}",
    "«{snippet}» — звучит как название стартапа",
    "если {word} — то да",
    "кста, {snippet} — это же буквально мы",
    "не знаю как у вас, а у меня после «{snippet}» только {word}",
    "в чате снова {word}, обожаю этот сериал",
    "когда в переписке {snippet} — значит день удался",
    "ахах {word} detected",
    "ну типа: {snippet}",
    "перечитал «{snippet}» три раза, всё равно смешно",
    "это не баг, это {word}",
    "главный лор чата на сегодня: {snippet}",
    "мем дня: {word}",
    "я: спокойно работаю\nчат: {snippet}",
]

_chat_history: dict[int, Deque[str]] = {}
_last_meme_reply: dict[int, float] = {}
_last_force_meme: dict[tuple[int, int], float] = {}


def _normalize(text: str) -> str:
    text = URL.sub("", text)
    text = MENTION.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _words(text: str) -> list[str]:
    return [w for w in WORD.findall(text) if len(w) > 1]


def _meaningful_words(text: str) -> list[str]:
    return [w for w in _words(text) if w.lower() not in STOP_WORDS]


def _pick_snippet(text: str, min_words: int = 2, max_words: int = 4) -> Optional[str]:
    words = _meaningful_words(text)
    if len(words) < min_words:
        return None
    size = random.randint(min_words, min(max_words, len(words)))
    if len(words) == size:
        start = 0
    else:
        start = random.randint(0, len(words) - size)
    snippet = " ".join(words[start:start + size])
    if len(snippet) < 4:
        return None
    return snippet[:72]


def _pick_word(text: str) -> Optional[str]:
    words = _meaningful_words(text)
    if not words:
        return None
    word = random.choice(words)
    return word[:24]


def _source_pool(
    current_text: str,
    recent_texts: list[str],
    reply_to_text: Optional[str] = None,
) -> list[str]:
    pool: list[str] = []
    if reply_to_text:
        cleaned = _normalize(reply_to_text)
        if len(cleaned) >= MEME_MIN_TEXT_LEN:
            pool.append(cleaned)
    cleaned_current = _normalize(current_text)
    if len(cleaned_current) >= MEME_MIN_TEXT_LEN:
        pool.append(cleaned_current)
    for text in reversed(recent_texts):
        cleaned = _normalize(text)
        if len(cleaned) >= MEME_MIN_TEXT_LEN:
            pool.append(cleaned)
    return pool


def _is_valid_meme(candidate: str) -> bool:
    text = re.sub(r"\s+", " ", candidate).strip()
    if len(text) < 8 or len(text) > MEME_MAX_LEN:
        return False
    if URL.search(text):
        return False
    if MENTION.search(text):
        return False
    if text.startswith(("{", "[", "```")):
        return False
    return True


def _sanitize_llm_reply(raw: str) -> Optional[str]:
    text = raw.strip()
    if not text:
        return None
    text = re.sub(r"^['\"«»]+|['\"«»]+$", "", text)
    text = text.split("\n", 1)[0].strip()
    text = re.sub(r"^(бот|ответ|реплика)\s*:\s*", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    if _is_valid_meme(text):
        return text
    return None


def _llm_context_block(
    current_text: str,
    recent_texts: list[str],
    reply_to_text: Optional[str] = None,
) -> str:
    lines: list[str] = [f"Сейчас в чате: {_normalize(current_text)}"]
    if reply_to_text:
        lines.append(f"Ответ на сообщение: {_normalize(reply_to_text)}")
    if recent_texts:
        lines.append("Недавно в чате:")
        for text in recent_texts[-MEME_LLM_HISTORY_LINES:]:
            lines.append(f"- {_normalize(text)}")
    return "\n".join(lines)


def _generate_meme_with_llm(
    current_text: str,
    recent_texts: list[str],
    reply_to_text: Optional[str] = None,
) -> Optional[str]:
    if not OPENAI_API_KEY:
        return None

    context = _llm_context_block(current_text, recent_texts, reply_to_text=reply_to_text)
    payload = {
        "model": MEME_LLM_MODEL,
        "temperature": 1.05,
        "max_tokens": 90,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты @ag_slashbot в рабочем Telegram-чате дизайн-студии. "
                    "Придумай одну короткую мемную смешную реплику по переписке. "
                    "Стиль: ирония, рабочий сленг, иногда «бля», «ахах», «классика», «гуд», «хз». "
                    "Можно POV, отсылки к фразам из чата, абсурд. "
                    "До 140 символов, без кавычек вокруг всего ответа, без @, без ссылок, "
                    "без советов и без объяснений. Только текст реплики."
                ),
            },
            {"role": "user", "content": context},
        ],
    }

    request = urllib.request.Request(
        f"{OPENAI_BASE_URL}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=MEME_LLM_TIMEOUT_SEC) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        return _sanitize_llm_reply(content)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, KeyError, IndexError, json.JSONDecodeError) as exc:
        print(f"⚠️ LLM meme failed: {exc}")
        return None


def _build_meme(source_texts: list[str]) -> Optional[str]:
    if not source_texts:
        return None

    for _ in range(12):
        primary = random.choice(source_texts)
        secondary = random.choice(source_texts)
        snippet = _pick_snippet(primary) or _pick_snippet(secondary)
        word = _pick_word(primary) or _pick_word(secondary)
        if not snippet and not word:
            continue
        snippet = snippet or word or ""
        word = word or snippet.split()[0]

        template = random.choice(MEME_TEMPLATES)
        try:
            result = template.format(snippet=snippet, word=word)
        except (KeyError, IndexError):
            continue

        if _is_valid_meme(result):
            return result
    return None


def _generate_meme(
    current_text: str,
    recent_texts: list[str],
    reply_to_text: Optional[str] = None,
    *,
    prefer_llm: bool = False,
) -> Optional[str]:
    sources = _source_pool(current_text, recent_texts, reply_to_text=reply_to_text)
    if not sources:
        return None

    use_llm = OPENAI_API_KEY and (prefer_llm or random.random() < MEME_LLM_CHANCE)
    if use_llm:
        meme = _generate_meme_with_llm(current_text, recent_texts, reply_to_text=reply_to_text)
        if meme:
            print(f"🧠 LLM meme: {meme}")
            return meme

    return _build_meme(sources)


def record_chat_message(chat_id: int, text: str) -> None:
    cleaned = _normalize(text)
    if len(cleaned) < 3:
        return
    history = _chat_history.setdefault(chat_id, deque(maxlen=MEME_HISTORY_SIZE))
    if history and history[-1] == cleaned:
        return
    history.append(cleaned)


def _meme_on_cooldown(chat_id: int) -> bool:
    last = _last_meme_reply.get(chat_id)
    if last is None:
        return False
    return time.monotonic() - last < MEME_COOLDOWN_SEC


def _mark_meme_reply(chat_id: int) -> None:
    _last_meme_reply[chat_id] = time.monotonic()


def _force_meme_on_cooldown(chat_id: int, user_id: int) -> bool:
    last = _last_force_meme.get((chat_id, user_id))
    if last is None:
        return False
    return time.monotonic() - last < MEME_FORCE_COOLDOWN_SEC


def _mark_force_meme(chat_id: int, user_id: int) -> None:
    _last_force_meme[(chat_id, user_id)] = time.monotonic()
    _mark_meme_reply(chat_id)


def _resolve_force_prompt(
    prompt_text: Optional[str],
    recent_texts: list[str],
) -> str:
    if prompt_text and len(_normalize(prompt_text)) >= MEME_MIN_TEXT_LEN:
        return _normalize(prompt_text)
    if recent_texts:
        return recent_texts[-1]
    return MEME_FORCE_FALLBACK_PROMPT


async def force_meme_reply(
    chat_id: int,
    user_id: int,
    *,
    prompt_text: Optional[str] = None,
    reply_to_text: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """
    Принудительный мем по команде.
    Возвращает (текст мема, сообщение об ошибке).
    """
    if _force_meme_on_cooldown(chat_id, user_id):
        wait = int(MEME_FORCE_COOLDOWN_SEC)
        return None, f"подожди {wait} сек перед следующим /meme"

    history = list(_chat_history.get(chat_id, []))
    recent = history[:-1] if history else []
    current = _resolve_force_prompt(prompt_text, history)

    meme = await asyncio.to_thread(
        _generate_meme,
        current,
        recent,
        reply_to_text,
        prefer_llm=True,
    )
    if meme:
        _mark_force_meme(chat_id, user_id)
        return meme, None

    return None, "не смог сгенерить мем — попробуй /meme про макет или ответь реплаем на сообщение"


async def maybe_meme_reply(
    chat_id: int,
    message_text: str,
    *,
    chat_type: str = "group",
    reply_to_text: Optional[str] = None,
) -> Optional[str]:
    """
    С небольшой вероятностью вернуть мемную реплику по контексту чата.
    """
    if len(_normalize(message_text)) < MEME_MIN_TEXT_LEN:
        return None

    history = list(_chat_history.get(chat_id, []))
    if len(history) < MEME_MIN_HISTORY and not reply_to_text:
        return None

    if _meme_on_cooldown(chat_id):
        return None

    chance = MEME_CHANCE_GROUP if chat_type in ("group", "supergroup") else MEME_CHANCE_PRIVATE
    if random.random() >= chance:
        return None

    recent = [t for t in history if t != _normalize(message_text)]
    meme = await asyncio.to_thread(
        _generate_meme,
        message_text,
        recent,
        reply_to_text,
    )
    if meme:
        _mark_meme_reply(chat_id)
    return meme
