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
MEME_FORCE_FALLBACK_PROMPT = "в чате тишина, все притворяются что макет гуд, а дедлайн горит"

SILENCE_MEME_ENABLED = os.getenv("SILENCE_MEME_ENABLED", "1").strip().lower() not in ("0", "false", "no")
SILENCE_MEME_SEC = float(os.getenv("SILENCE_MEME_HOURS", "3")) * 3600.0
SILENCE_MEME_CHECK_SEC = float(os.getenv("SILENCE_MEME_CHECK_MIN", "20")) * 60.0
SILENCE_MEME_PROMPT = (
    "в чате тишина уже три часа, все притворяются что работают, а макеты сами себя не сделают"
)

BLAND_MEME = re.compile(
    r"тишина в чате|на уровне|прям как в классике|спокойно работа|звучит как название стартапа|"
    r"буквально мы|мем дня:|удался$|без вариантов|это же гениально|на душе",
    re.I,
)

LLM_SYSTEM_PROMPT = """\
Ты @ag_slashbot в рабочем Telegram-чате дизайн-студии S:P9. Напиши ОДНУ короткую кринжовую провокационную реплику по переписке.

СТИЛЬ (обязательно):
- кринж, стыдно-смешно, пассивная агрессия, абсурд, неудобный юмор
- рабочий мат уместно: бля, блэт, зашквар, всратость, говно, жопа горит, херово
- искажай фразы из чата — уничижительно, но смешно
- референсы: дудосинг, ноукод, шакальные макеты, понаехали дизайнеры, рендер, фигма, синк

ЗАПРЕЩЕНО:
- bland корпоративный юмор («тишина в чате», «на уровне гуд», «классика ахах» без укуса)
- обрывки фраз и словесное месиво («че макетам», «типа норм макет» без смысла)
- мотивация, советы, объяснения, нравоучения
- @, ссылки, кавычки вокруг всего ответа

ОБЯЗАТЕЛЬНО:
- опирайся на 1–2 конкретные реплики из переписки (экспрессо, синк, промо, checkout, коммент во фрейме…)
- грамматически цельное предложение, чтобы было понятно без контекста чата
- можно связать два события из чата в один абсурдный вывод

Примеры тона:
- бля как же жопа горит от таких макетов
- видимо через жопу ставили задачу и назвали хз как
- ахах забыли очередь узбеков в рендер добавить
- чУприн блядь. Понаехали дизайнеры
- ну и в целом стиль разъехался, где-то секси тридэхи, где-то линии на плашке

До 140 символов. Только текст реплики."""

MEME_TEMPLATES = [
    "бля {snippet} — и это мы называем пятницей",
    "POV: в чате {snippet}, а дедлайн всё ещё вчера",
    "когда {snippet}, я уже на этапе принятия",
    "ахах {snippet}... ну всратость зашкаливает",
    "после «{snippet}» хочется в ноукод уйти",
    "главный кринж сегодня: {snippet}",
    "да бля, {snippet} — классика S:P9",
    "план говно: {snippet}",
    "я: терплю\nчат: {snippet}",
    "если {snippet} — значит мы обдудосились",
    "блэт {snippet} — звучит как оправдание перед клиентом",
    "честно, {snippet} — это уже не баг, а стиль жизни",
]

MASHUP_TEMPLATES = [
    "сначала {a}, потом {b} — ну всё, дудосинг",
    "бля: {a}. и тут же {b}. классика",
    "в чате {a}, а параллельно {b} — зашквар, но гуд",
    "{a}? ок. но потом {b} — и я уже не уверен в реальности",
]

DANGLING_WORDS = frozenset({
    "че", "по", "в", "во", "на", "к", "ко", "о", "с", "со", "у", "за", "из", "и", "а", "но",
    "что", "как", "там", "тут", "это", "то", "ли", "же", "бы",
})

BROKEN_FRAGMENT = re.compile(
    r"\bче \w+ам\b|\bпо \w+ам\b|\bк \w+ам\b|"
    r"\bкста \w+ам\b|\bтипа \w+ам\b",
    re.I,
)

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

_chat_history: dict[int, Deque[str]] = {}
_last_meme_reply: dict[int, float] = {}
_last_force_meme: dict[tuple[int, int], float] = {}
_last_chat_activity: dict[int, float] = {}
_silence_nudged_activity: dict[int, float] = {}
_chat_types: dict[int, str] = {}


def _normalize(text: str) -> str:
    text = URL.sub("", text)
    text = MENTION.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _words(text: str) -> list[str]:
    return [w for w in WORD.findall(text) if len(w) > 1]


def _meaningful_words(text: str) -> list[str]:
    return [w for w in _words(text) if w.lower() not in STOP_WORDS]


def _is_coherent_snippet(snippet: str) -> bool:
    text = snippet.strip()
    if len(text) < 10:
        return False
    words = text.split()
    if len(words) < 4 and len(text) < 28:
        return False
    if words[0].lower() in DANGLING_WORDS or words[-1].lower().rstrip(".,!?") in DANGLING_WORDS:
        return False
    if len(_meaningful_words(text)) < 3:
        return False
    if BROKEN_FRAGMENT.search(text):
        return False
    if re.search(r"\.\s+[А-ЯA-ZЁ]\w*$", text):
        return False
    return True


def _phrase_candidates(text: str) -> list[str]:
    cleaned = _normalize(text)
    if not cleaned or cleaned.startswith("/"):
        return []

    candidates: list[str] = []
    if 10 <= len(cleaned) <= 90 and _is_coherent_snippet(cleaned):
        candidates.append(cleaned)

    for sentence in re.split(r"[.!?]\s+", cleaned):
        sentence = sentence.strip()
        if 10 <= len(sentence) <= 90 and _is_coherent_snippet(sentence):
            candidates.append(sentence)

    if len(cleaned) <= 90:
        for part in re.split(r"[,;—–-]\s*", cleaned):
            part = part.strip()
            if 10 <= len(part) <= 90 and _is_coherent_snippet(part):
                candidates.append(part)

    return list(dict.fromkeys(candidates))


def _pick_snippet(text: str) -> Optional[str]:
    phrases = _phrase_candidates(text)
    if not phrases:
        return None
    return random.choice(phrases)


def _pick_word(text: str) -> Optional[str]:
    words = [w for w in _meaningful_words(text) if len(w) >= 4]
    if not words:
        return None
    return random.choice(words)[:24]


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
    if BLAND_MEME.search(text):
        return False
    if BROKEN_FRAGMENT.search(text):
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
    *,
    attempts: int = 1,
) -> Optional[str]:
    if not OPENAI_API_KEY:
        return None

    context = _llm_context_block(current_text, recent_texts, reply_to_text=reply_to_text)
    temperature = 1.28 if attempts > 1 else 1.18

    payload = {
        "model": MEME_LLM_MODEL,
        "temperature": temperature,
        "max_tokens": 90,
        "messages": [
            {"role": "system", "content": LLM_SYSTEM_PROMPT},
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


def _generate_meme_with_llm_retries(
    current_text: str,
    recent_texts: list[str],
    reply_to_text: Optional[str] = None,
    *,
    max_attempts: int = 3,
) -> Optional[str]:
    for attempt in range(1, max_attempts + 1):
        meme = _generate_meme_with_llm(
            current_text,
            recent_texts,
            reply_to_text=reply_to_text,
            attempts=attempt,
        )
        if meme:
            return meme
    return None


def _collect_phrases(source_texts: list[str]) -> list[str]:
    phrases: list[str] = []
    for text in source_texts:
        phrases.extend(_phrase_candidates(text))
    # длинные уникальные фразы важнее
    unique = list(dict.fromkeys(phrases))
    return [p for p in unique if _is_coherent_snippet(p)]


def _build_meme(source_texts: list[str]) -> Optional[str]:
    if not source_texts:
        return None

    phrases = _collect_phrases(source_texts)
    if not phrases:
        return None

    for _ in range(16):
        if len(phrases) >= 2 and random.random() < 0.35:
            a, b = random.sample(phrases, 2)
            template = random.choice(MASHUP_TEMPLATES)
            try:
                result = template.format(a=a, b=b)
            except (KeyError, IndexError):
                continue
            if _is_valid_meme(result):
                return result

        snippet = random.choice(phrases)
        template = random.choice(MEME_TEMPLATES)
        try:
            result = template.format(snippet=snippet)
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
        llm_attempts = 3 if prefer_llm else 2
        meme = _generate_meme_with_llm_retries(
            current_text,
            recent_texts,
            reply_to_text=reply_to_text,
            max_attempts=llm_attempts,
        )
        if meme:
            print(f"🧠 LLM meme: {meme}")
            return meme
        if prefer_llm:
            print("⚠️ LLM meme empty, fallback to phrases")

    return _build_meme(sources)


def record_chat_message(chat_id: int, text: str) -> None:
    cleaned = _normalize(text)
    if len(cleaned) < 3:
        return
    history = _chat_history.setdefault(chat_id, deque(maxlen=MEME_HISTORY_SIZE))
    if history and history[-1] == cleaned:
        return
    history.append(cleaned)


def touch_chat_activity(chat_id: int, chat_type: str = "group") -> None:
    """Отмечает активность людей в чате (для мема после тишины)."""
    _last_chat_activity[chat_id] = time.monotonic()
    _chat_types[chat_id] = chat_type


def _is_group_chat(chat_id: int) -> bool:
    return _chat_types.get(chat_id) in ("group", "supergroup")


def should_send_silence_meme(chat_id: int) -> bool:
    if not SILENCE_MEME_ENABLED:
        return False
    if not _is_group_chat(chat_id):
        return False
    last_activity = _last_chat_activity.get(chat_id)
    if last_activity is None:
        return False
    now = time.monotonic()
    if now - last_activity < SILENCE_MEME_SEC:
        return False
    if _silence_nudged_activity.get(chat_id) == last_activity:
        return False
    return True


def mark_silence_meme_sent(chat_id: int) -> None:
    last_activity = _last_chat_activity.get(chat_id)
    if last_activity is not None:
        _silence_nudged_activity[chat_id] = last_activity
    _mark_meme_reply(chat_id)


def silence_meme_candidates() -> list[int]:
    return [chat_id for chat_id in _last_chat_activity if should_send_silence_meme(chat_id)]


async def generate_silence_meme(chat_id: int) -> Optional[str]:
    history = list(_chat_history.get(chat_id, []))
    meme = await asyncio.to_thread(
        _generate_meme,
        SILENCE_MEME_PROMPT,
        history,
        prefer_llm=True,
    )
    return meme


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
