"""
Случайные мемные реплики на основе текущего сообщения и недавней истории чата.

С OPENAI_API_KEY в env — часть мемов генерит LLM (gpt-4o-mini по умолчанию),
иначе остаются шаблоны из фраз чата.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from collections import deque
from typing import Deque, Optional
from zoneinfo import ZoneInfo

MEME_CHANCE_GROUP = 0.035
MEME_CHANCE_PRIVATE = 0.012
MEME_COOLDOWN_SEC = 420.0
MEME_HISTORY_SIZE = 24
MEME_DAILY_HISTORY_SIZE = 220
MEME_MIN_HISTORY = 2
MEME_MIN_TEXT_LEN = 6
MEME_MAX_LEN = 180

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
MEME_LLM_MODEL = os.getenv("MEME_LLM_MODEL", "gpt-4o-mini")
MEME_LLM_CHANCE = float(os.getenv("MEME_LLM_CHANCE", "0.85"))
MEME_LLM_TIMEOUT_SEC = float(os.getenv("MEME_LLM_TIMEOUT_SEC", "12"))
MEME_LLM_HISTORY_LINES = int(os.getenv("MEME_LLM_HISTORY_LINES", "40"))
MEME_FORCE_COOLDOWN_SEC = 20.0
MEME_FORCE_FALLBACK_PROMPT = "в чате тишина, все притворяются что макет гуд, а дедлайн горит"
MOSCOW_TZ = ZoneInfo("Europe/Moscow")

SILENCE_MEME_ENABLED = os.getenv("SILENCE_MEME_ENABLED", "1").strip().lower() not in ("0", "false", "no")
SILENCE_MEME_SEC = float(os.getenv("SILENCE_MEME_HOURS", "3")) * 3600.0
SILENCE_MEME_CHECK_SEC = float(os.getenv("SILENCE_MEME_CHECK_MIN", "20")) * 60.0
SILENCE_MEME_PROMPT = (
    "в чате тишина уже три часа, все притворяются что работают, а макеты сами себя не сделают"
)

SP9_SCHEDULED_MEME_ENABLED = os.getenv("SP9_SCHEDULED_MEME_ENABLED", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)

SP9_AFTERNOON_MEME_PROMPT = (
    "после обеда в рабочем чате, все в полусне, макеты висят, синк был, а прогресса ноль"
)
SP9_EVENING_MEME_PROMPT = (
    "вечер буднего дня, пора сворачиваться, но все ещё притворяются что доделают макет"
)
SP9_EVENING_FRIDAY_MEME_PROMPT = (
    "пятница вечер, скоро дудосинг, все притворяются что успели до выходных"
)

SP9_AFTERNOON_FALLBACKS = (
    "после обеда мозг в рендере, а ты всё ещё в фигме — классика",
    "обед прошёл, макет нет, синк был — зашкварный послеобеденный шаблон",
    "полтретьего: все притворяются что гуд, а глаза на пол-экрана",
    "послеобеденный кринж: {snippet} — и это мы называем продуктивностью",
    "я в своём послеобеденном познании настолько преисполнился, что {snippet} мне уже как триллионный рендер",
    "это разговор освобождённого от дедлайна существа, идущего к кофе после «{snippet}»",
)

SP9_EVENING_FALLBACKS = (
    "вечер, пора домой, но макет всё ещё «почти гуд»",
    "ну всё, сворачиваемся — завтра снова притворимся что успеем",
    "18:00: дедлайн завтра, а сегодня уже морально в дудосинге",
    "на ночь глядя: {snippet} — звучит как план на завтра",
    "мне похуй, какая там у тебя тачка и яхта — у меня {snippet}, и я иду к реке",
    "я уже как глубокий старец узревший вечное: {snippet}. осталось только закрыть фигму",
)

SP9_EVENING_FRIDAY_FALLBACKS = (
    "пятница вечер — официально можно притвориться что всё залили",
    "ну всё, выходные: макеты сами себя не сделают, но мы попробуем не думать",
    "скоро дудосинг, а макет всё ещё «на финале» — классика пятницы",
    "пятничный финал: {snippet} — и в понедельник снова «почти гуд»",
    "пятница: преисполнился в познании настолько, что {snippet} уже не цепляет — только дудосинг и река",
    "это триумф свободы от синка и макетов: {snippet}. иду к реке, а вы там доделывайте",
)

SP9_SLOT_LLM_FOCUS = {
    "afternoon": (
        "ПОСЛЕОБЕДЕННЫЙ мем (15:00 МСК): полусон, макеты висят, прогресса ноль. "
        "Стиль можно как кринж S:P9, так и пафос «идущего к реке». "
        "Опирайся на конкретные реплики из переписки ниже; не повторяй старые шутки про sync/checkout/espresso."
    ),
    "evening": (
        "ВЕЧЕРНИЙ мем (18:00 МСК): пора сворачиваться, но все притворяются что доделают. "
        "Стиль можно как кринж S:P9, так и пафос «идущего к реке» / Дур-Дачника. "
        "Опирайся на конкретные реплики из переписки ниже; не повторяй старые шутки про sync/checkout/espresso."
    ),
    "evening_friday": (
        "ПЯТНИЧНЫЙ ВЕЧЕР (18:00 МСК): напутствие на выходные, дудосинг, макет «на финале». "
        "Особенно уместен пафос «идущего к реке»: отпустить эго, дедлайны и фигму. "
        "Опирайся на конкретные реплики из переписки ниже; не повторяй старые шутки про sync/checkout/espresso."
    ),
}

BLAND_MEME = re.compile(
    r"тишина в чате|на уровне|прям как в классике|спокойно работа|звучит как название стартапа|"
    r"буквально мы|мем дня:|удался$|без вариантов|это же гениально|на душе|"
    r"checkout пусть ночует|экспрессо на синке|ноукод же,? хули|форма коллективного отрицания",
    re.I,
)

LLM_SYSTEM_PROMPT = """\
Ты @ag_slashbot в рабочем Telegram-чате дизайн-студии S:P9. Напиши ОДНУ короткую смешную кринжовую провокационную реплику по переписке за день.

СТИЛЬ (обязательно — выбери ОДИН режим на ответ):
1) кринж S:P9: стыдно-смешно, пассивная агрессия, абсурд, как будто дедлайн уже съел уважение
2) «идущий к реке» / Дур-Дачник: псевдофилософский пафос + мат, преисполнение, триллионы планет, похуй на тачки/яхты/финалы, триумф свободы от эго; но punchline обязательно про реальный рабочий бред из чата (фигма, макет, синк, рендер, дедлайн)

- рабочий мат уместно: бля, блэт, зашквар, всратость, говно, жопа горит, херово, похуй
- искажай фразы из чата — уничижительно, но смешно; делай punchline, а не пересказ
- референсы: дудосинг, ноукод, шакальные макеты, понаехали дизайнеры, рендер, фигма, синк, река, преисполнился
- лучше одна точная шутка про 1–2 события дня, чем общий комментарий «классика»
- если историй мало — всё равно смешно выдумывай в стиле, но не залипай на одних и тех же словах

ЗАПРЕЩЕНО:
- bland корпоративный юмор («тишина в чате», «на уровне гуд», «классика ахах» без укуса)
- обрывки фраз и словесное месиво («че макетам», «типа норм макет» без смысла)
- мотивация, советы, объяснения, нравоучения
- @, ссылки, кавычки вокруг всего ответа
- повторять вчерашние мемы про sync/checkout/espresso/коммент во фрейме — бери свежий угол

ОБЯЗАТЕЛЬНО:
- анализируй сообщения сегодняшнего дня и опирайся на 1–2 конкретные реплики, ЕСЛИ они есть
- грамматически цельное предложение, чтобы было понятно без контекста чата
- можно связать два события из чата в один абсурдный вывод
- если в контексте есть список «темы дня», используй его как карту, но шути по реальным репликам ниже

Примеры тона (кринж):
- бля как же жопа горит от таких макетов
- видимо через жопу ставили задачу и назвали хз как
- ахах забыли очередь узбеков в рендер добавить

Примеры тона (идущий к реке):
- я в своём познании настолько преисполнился, что ваш синк мне как пыль на ботинке у реки
- мне похуй, какая у тебя тачка и яхта — у нас макет всратый, а я уже узревший вечное
- это триумф свободы от фигмы: иду к реке, а дедлайн пусть сам себя закроет

До 180 символов. Только текст реплики."""

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
    "ну да, {snippet} — отличный способ сказать клиенту «мы всё контролируем»",
    "S:P9 сегодня: {snippet}. Осталось только назвать это концепцией",
    "после «{snippet}» фигма сама должна попросить больничный",
    "я в своём познании настолько преисполнился, что «{snippet}» мне уже как пыль на дороге к реке",
    "мне похуй на твои статусы и апрувы — «{snippet}», а я уже узревший вечное",
    "это триумф свободы от дедлайна: после «{snippet}» только река и дудосинг",
]

MASHUP_TEMPLATES = [
    "сначала {a}, потом {b} — ну всё, дудосинг",
    "бля: {a}. и тут же {b}. классика",
    "в чате {a}, а параллельно {b} — зашквар, но гуд",
    "{a}? ок. но потом {b} — и я уже не уверен в реальности",
    "день начался с «{a}», докатился до «{b}» — прекрасный ноукодный ад",
    "{a}, потом {b}; короче макет сам понял, что его всрали",
    "преисполнился: сначала «{a}», потом «{b}» — иду к реке, вам тут разгребать",
    "мне похуй на «{a}» и «{b}»: это уже разговор существа, свободного от фигмы",
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
_chat_daily_history: dict[int, Deque[dict[str, object]]] = {}
_last_meme_reply: dict[int, float] = {}
_last_force_meme: dict[tuple[int, int], float] = {}
_last_chat_activity: dict[int, float] = {}
_silence_nudged_activity: dict[int, float] = {}
_chat_types: dict[int, str] = {}

_DATA_DIR = os.environ.get("SLASHBOT_DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
MEME_STATE_FILE = os.path.join(_DATA_DIR, "meme_state.json")
_last_state_save = 0.0
_state_dirty = False
STATE_SAVE_INTERVAL_SEC = 30.0
MEME_STATE_VERSION = 2


def _normalize_openai_base_url() -> str:
    base = OPENAI_BASE_URL.rstrip("/")
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    return base.rstrip("/")


def _openai_completions_url() -> str:
    return f"{_normalize_openai_base_url()}/chat/completions"


def _llm_uses_max_completion_tokens(model: str) -> bool:
    lowered = model.lower()
    return lowered.startswith(("o1", "o3", "o4", "gpt-5"))


def _build_llm_payload(
    messages: list[dict[str, str]],
    *,
    temperature: float,
    include_temperature: bool = True,
) -> dict:
    payload: dict = {
        "model": MEME_LLM_MODEL,
        "messages": messages,
    }
    if include_temperature:
        payload["temperature"] = temperature
    token_key = "max_completion_tokens" if _llm_uses_max_completion_tokens(MEME_LLM_MODEL) else "max_tokens"
    payload[token_key] = 120
    return payload


def _mark_state_dirty() -> None:
    global _state_dirty
    _state_dirty = True


def _today_key() -> str:
    return dt.datetime.now(MOSCOW_TZ).date().isoformat()


def _day_key(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, MOSCOW_TZ).date().isoformat()


def _normalize_daily_record(item: object, fallback_ts: Optional[float] = None) -> Optional[dict[str, object]]:
    if isinstance(item, str):
        text = _normalize(item)
        ts = time.time() if fallback_ts is None else fallback_ts
    elif isinstance(item, dict):
        text = _normalize(str(item.get("text", "")))
        raw_ts = item.get("ts", fallback_ts if fallback_ts is not None else time.time())
        try:
            ts = float(raw_ts)
        except (TypeError, ValueError):
            ts = time.time()
    else:
        return None

    if len(text) < 3:
        return None
    return {"ts": ts, "day": _day_key(ts), "text": text}


def _prune_daily_history(chat_id: int) -> None:
    history = _chat_daily_history.get(chat_id)
    if not history:
        return

    today = _today_key()
    todays_records = [item for item in history if item.get("day") == today]
    _chat_daily_history[chat_id] = deque(todays_records[-MEME_DAILY_HISTORY_SIZE:], maxlen=MEME_DAILY_HISTORY_SIZE)


def _today_history(chat_id: int) -> list[str]:
    _prune_daily_history(chat_id)
    return [
        str(item.get("text", ""))
        for item in _chat_daily_history.get(chat_id, [])
        if item.get("day") == _today_key() and item.get("text")
    ]


def load_meme_state() -> None:
    """Восстанавливает историю чатов и активность с диска."""
    global _chat_history, _chat_daily_history, _last_chat_activity, _chat_types, _silence_nudged_activity

    if not os.path.exists(MEME_STATE_FILE):
        print(f"💾 История чатов: файл не найден ({MEME_STATE_FILE})")
        return

    try:
        with open(MEME_STATE_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"⚠️ Не удалось загрузить meme_state.json: {exc}")
        return

    histories = data.get("chat_history", {})
    for raw_chat_id, messages in histories.items():
        chat_id = int(raw_chat_id)
        if not isinstance(messages, list):
            continue
        _chat_history[chat_id] = deque(
            (str(item) for item in messages[-MEME_HISTORY_SIZE:]),
            maxlen=MEME_HISTORY_SIZE,
        )

    daily_histories = data.get("daily_history", {})
    for raw_chat_id, messages in daily_histories.items():
        chat_id = int(raw_chat_id)
        if not isinstance(messages, list):
            continue
        normalized = []
        for item in messages[-MEME_DAILY_HISTORY_SIZE:]:
            record = _normalize_daily_record(item)
            if record:
                normalized.append(record)
        _chat_daily_history[chat_id] = deque(normalized, maxlen=MEME_DAILY_HISTORY_SIZE)
        _prune_daily_history(chat_id)

    # Мягкая миграция старого состояния: последние реплики считаем сегодняшним контекстом,
    # чтобы после деплоя плановый мем не ослеп до новых сообщений.
    now = time.time()
    for chat_id, history in _chat_history.items():
        if chat_id in _chat_daily_history and _chat_daily_history[chat_id]:
            continue
        records = []
        for text in list(history)[-MEME_DAILY_HISTORY_SIZE:]:
            record = _normalize_daily_record(text, fallback_ts=now)
            if record:
                records.append(record)
        if records:
            _chat_daily_history[chat_id] = deque(records, maxlen=MEME_DAILY_HISTORY_SIZE)

    for raw_chat_id, ts in data.get("last_activity", {}).items():
        _last_chat_activity[int(raw_chat_id)] = float(ts)

    for raw_chat_id, chat_type in data.get("chat_types", {}).items():
        _chat_types[int(raw_chat_id)] = str(chat_type)

    for raw_chat_id, ts in data.get("silence_nudged", {}).items():
        _silence_nudged_activity[int(raw_chat_id)] = float(ts)

    print(
        f"💾 История чатов загружена: {len(_chat_history)} чат(ов), "
        f"файл {MEME_STATE_FILE}"
    )


def save_meme_state(force: bool = False) -> None:
    """Сохраняет историю и активность на диск (debounce 30 сек)."""
    global _last_state_save, _state_dirty

    now = time.time()
    if not force and (not _state_dirty or now - _last_state_save < STATE_SAVE_INTERVAL_SEC):
        return

    for chat_id in list(_chat_daily_history):
        _prune_daily_history(chat_id)

    payload = {
        "version": MEME_STATE_VERSION,
        "chat_history": {
            str(chat_id): list(history)
            for chat_id, history in _chat_history.items()
            if history
        },
        "daily_history": {
            str(chat_id): list(history)
            for chat_id, history in _chat_daily_history.items()
            if history
        },
        "last_activity": {str(chat_id): ts for chat_id, ts in _last_chat_activity.items()},
        "chat_types": {str(chat_id): chat_type for chat_id, chat_type in _chat_types.items()},
        "silence_nudged": {str(chat_id): ts for chat_id, ts in _silence_nudged_activity.items()},
    }

    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
        tmp_path = f"{MEME_STATE_FILE}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_path, MEME_STATE_FILE)
        _last_state_save = now
        _state_dirty = False
    except OSError as exc:
        print(f"⚠️ Не удалось сохранить meme_state.json: {exc}")


def probe_llm_api() -> tuple[bool, str]:
    """Проверка OPENAI_API_KEY и модели при старте."""
    if not OPENAI_API_KEY:
        return False, "OPENAI_API_KEY не задан — мемы только из шаблонов"

    messages = [
        {"role": "system", "content": "Ответь одним словом: ок"},
        {"role": "user", "content": "ping"},
    ]
    for include_temperature in (True, False):
        payload = _build_llm_payload(messages, temperature=0.2, include_temperature=include_temperature)
        request = urllib.request.Request(
            _openai_completions_url(),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=min(MEME_LLM_TIMEOUT_SEC, 8.0)) as response:
                body = json.loads(response.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            return True, f"{MEME_LLM_MODEL} @ {_normalize_openai_base_url()} — ok ({content.strip()[:20]})"
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
            except OSError:
                pass
            if include_temperature and exc.code == 400 and "temperature" in detail.lower():
                continue
            hint = ""
            if exc.code == 401:
                hint = " — проверь OPENAI_API_KEY"
            elif exc.code == 404:
                hint = " — проверь MEME_LLM_MODEL и OPENAI_BASE_URL"
            return False, f"HTTP {exc.code}: {detail or exc.reason}{hint}"
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError) as exc:
            return False, str(exc)

    return False, "не удалось проверить LLM"


def _normalize(text: str) -> str:
    text = URL.sub("", text)
    text = MENTION.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _words(text: str) -> list[str]:
    return [w for w in WORD.findall(text) if len(w) > 1]


def _meaningful_words(text: str) -> list[str]:
    return [w for w in _words(text) if w.lower() not in STOP_WORDS]


def _top_terms(texts: list[str], limit: int = 10) -> list[str]:
    counts: dict[str, int] = {}
    for text in texts:
        for word in _meaningful_words(text):
            lowered = word.lower()
            if len(lowered) < 4:
                continue
            counts[lowered] = counts.get(lowered, 0) + 1
    return [
        word
        for word, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


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
    *,
    focus: Optional[str] = None,
) -> str:
    lines: list[str] = []
    if focus:
        lines.append(focus)
    if recent_texts:
        if len(recent_texts) > 12:
            topics = _top_terms(recent_texts)
            if topics:
                lines.append(f"Темы дня: {', '.join(topics)}")
        label = "Сегодняшняя переписка в чате S:P9 works:" if focus else "Недавняя переписка в чате S:P9 works:"
        lines.append(label)
        for text in recent_texts[-MEME_LLM_HISTORY_LINES:]:
            lines.append(f"- {_normalize(text)}")
    elif focus:
        lines.append("Сегодня мало сообщений — всё равно кринж про рабочий день S:P9.")
    if current_text and not focus:
        lines.append(f"Сейчас в чате: {_normalize(current_text)}")
    if reply_to_text:
        lines.append(f"Ответ на сообщение: {_normalize(reply_to_text)}")
    return "\n".join(lines)


def _generate_meme_with_llm(
    current_text: str,
    recent_texts: list[str],
    reply_to_text: Optional[str] = None,
    *,
    attempts: int = 1,
    focus: Optional[str] = None,
) -> Optional[str]:
    if not OPENAI_API_KEY:
        return None

    context = _llm_context_block(
        current_text,
        recent_texts,
        reply_to_text=reply_to_text,
        focus=focus,
    )
    temperature = 1.28 if attempts > 1 else 1.18
    messages = [
        {"role": "system", "content": LLM_SYSTEM_PROMPT},
        {"role": "user", "content": context},
    ]

    for include_temperature in (True, False):
        payload = _build_llm_payload(
            messages,
            temperature=temperature,
            include_temperature=include_temperature,
        )
        request = urllib.request.Request(
            _openai_completions_url(),
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
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
            except OSError:
                pass
            if include_temperature and exc.code == 400 and "temperature" in detail.lower():
                continue
            print(f"⚠️ LLM meme failed: HTTP {exc.code} {exc.reason}" + (f" — {detail}" if detail else ""))
            return None
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError) as exc:
            print(f"⚠️ LLM meme failed: {exc}")
            return None

    return None


def _generate_meme_with_llm_retries(
    current_text: str,
    recent_texts: list[str],
    reply_to_text: Optional[str] = None,
    *,
    max_attempts: int = 3,
    focus: Optional[str] = None,
) -> Optional[str]:
    for attempt in range(1, max_attempts + 1):
        meme = _generate_meme_with_llm(
            current_text,
            recent_texts,
            reply_to_text=reply_to_text,
            attempts=attempt,
            focus=focus,
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
    daily_history = _chat_daily_history.setdefault(chat_id, deque(maxlen=MEME_DAILY_HISTORY_SIZE))
    now = time.time()
    if not daily_history or daily_history[-1].get("text") != cleaned:
        daily_history.append({"ts": now, "day": _day_key(now), "text": cleaned})
        _prune_daily_history(chat_id)
    _mark_state_dirty()
    save_meme_state()


def touch_chat_activity(chat_id: int, chat_type: str = "group") -> None:
    """Отмечает активность людей в чате (для мема после тишины)."""
    _last_chat_activity[chat_id] = time.time()
    _chat_types[chat_id] = chat_type
    _mark_state_dirty()
    save_meme_state()


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
    now = time.time()
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
    _mark_state_dirty()
    save_meme_state(force=True)


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


def _scheduled_meme_config(slot: str) -> tuple[str, tuple[str, ...]]:
    if slot == "afternoon":
        return SP9_AFTERNOON_MEME_PROMPT, SP9_AFTERNOON_FALLBACKS
    if slot == "evening_friday":
        return SP9_EVENING_FRIDAY_MEME_PROMPT, SP9_EVENING_FRIDAY_FALLBACKS
    return SP9_EVENING_MEME_PROMPT, SP9_EVENING_FALLBACKS


def _pick_scheduled_fallback(fallbacks: tuple[str, ...], history: list[str]) -> str:
    phrases = _collect_phrases(history) if history else []
    snippet = random.choice(phrases) if phrases else "макет почти гуд"
    for template in random.sample(list(fallbacks), len(fallbacks)):
        try:
            candidate = template.format(snippet=snippet) if "{snippet}" in template else template
        except (KeyError, IndexError):
            candidate = template
        if _is_valid_meme(candidate):
            return candidate
    template = random.choice(fallbacks)
    try:
        return template.format(snippet=snippet) if "{snippet}" in template else template
    except (KeyError, IndexError):
        return template


async def generate_sp9_scheduled_meme(chat_id: int, slot: str) -> Optional[str]:
    """Плановый мем для S:P9 works: afternoon | evening | evening_friday."""
    _, fallbacks = _scheduled_meme_config(slot)
    history = _today_history(chat_id) or list(_chat_history.get(chat_id, []))
    focus = SP9_SLOT_LLM_FOCUS.get(slot, SP9_SLOT_LLM_FOCUS["evening"])

    meme = await asyncio.to_thread(
        _generate_scheduled_sp9_meme,
        history,
        focus,
        fallbacks,
    )
    return meme


def _generate_scheduled_sp9_meme(
    history: list[str],
    focus: str,
    fallbacks: tuple[str, ...],
) -> Optional[str]:
    if OPENAI_API_KEY:
        meme = _generate_meme_with_llm_retries(
            "",
            history,
            max_attempts=3,
            focus=focus,
        )
        if meme:
            print(f"🧠 LLM scheduled meme: {meme}")
            return meme
        print("⚠️ LLM scheduled meme empty, fallback to phrases")

    sources = list(history) if history else [focus]
    built = _build_meme(sources)
    if built:
        return built
    return _pick_scheduled_fallback(fallbacks, history)


def mark_meme_sent(chat_id: int) -> None:
    _mark_meme_reply(chat_id)


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
    day_history = _today_history(chat_id)
    context_history = day_history or history
    recent = context_history[:-1] if context_history else []
    current = _resolve_force_prompt(prompt_text, context_history)

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

    day_history = _today_history(chat_id)
    context_history = day_history if len(day_history) >= MEME_MIN_HISTORY else history
    recent = [t for t in context_history if t != _normalize(message_text)]
    meme = await asyncio.to_thread(
        _generate_meme,
        message_text,
        recent,
        reply_to_text,
    )
    if meme:
        _mark_meme_reply(chat_id)
    return meme
