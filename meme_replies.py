"""
Случайные мемные реплики на основе текущего сообщения и недавней истории чата.
"""
from __future__ import annotations

import random
import re
import time
from collections import deque
from typing import Deque, Optional

MEME_CHANCE_GROUP = 0.035
MEME_CHANCE_PRIVATE = 0.012
MEME_COOLDOWN_SEC = 420.0
MEME_HISTORY_SIZE = 24
MEME_MIN_HISTORY = 2
MEME_MIN_TEXT_LEN = 6
MEME_MAX_LEN = 140

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

        result = re.sub(r"\s+", " ", result).strip()
        if len(result) < 8 or len(result) > MEME_MAX_LEN:
            continue
        if URL.search(result):
            continue
        return result
    return None


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


def maybe_meme_reply(
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
    sources = _source_pool(message_text, recent, reply_to_text=reply_to_text)
    meme = _build_meme(sources)
    if meme:
        _mark_meme_reply(chat_id)
    return meme
