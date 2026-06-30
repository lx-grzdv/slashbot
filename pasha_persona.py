"""
Персона Паши для @ag_slashbot.

Реакции собраны и синтезируются из экспорта S:P9 works:
- только отклики (без «оставил», «проверь», «закинь»)
- шаблоны: {оценка}, {согласие}, {оценка}, спасибо и т.д.
"""
import random
import re
from typing import Optional

BOT_USERNAME = "ag_slashbot"
BOT_MENTION = f"@{BOT_USERNAME}"

URL = re.compile(r"https?://|t\.me/|@", re.I)

# --- Блоки из частотного анализа коротких реплик Паши ---
AFFIRM_SIMPLE = ["да", "ага", "го", "угу", "неа", "ес", "есс", "давай"]
EVAL_SIMPLE = ["гуд", "норм", "каеф", "збс", "стопроц", "ура", "топ", "кул", "ого"]
COMPOUND = [
    "супер, спасибо", "гуд, спасибо", "отлично, спасибо", "ага, спасибо",
    "ну да", "да норм", "граци рагаци", "да бля",
]
AFFIRM = [
    "да", "ага", "угу", "дада", "го", "го?", "давай", "ес", "есс", "неа",
    "ну да", "оно да", "да норм",
]
EVAL = [
    "гуд", "норм", "супер", "каеф", "збс", "стопроц", "апрувед", "блэт", "лол",
    "ахах", "ахаха", "ура", "классика", "лавли", "ого", "кул", "топ", "экзактли",
    "каефы", "секси",
]
THANKS = [
    "спасибо", "спс", "супер, спасибо", "гуд, спасибо", "отлично, спасибо",
    "ага, спасибо", "спасибо бро", "спасибо ребят", "спасибо гайз",
    "граци рагаци", "мазлтов!", "спасибо большой",
]
LEAD = ["ну", "кста", "чет", "вроде", "ого", "а", "ля", "тюю", "воо"]
EMPHASIS = ["да бля", "++++", "да.", "Неа", "lf"]
SOCIAL = ["красавчики", "парни", "посоны", "салам", "ребзя"]
READY = ["готово?", "Готово?"]

# Задумчивое — без «бегу», «5 мин», «го» (это уже обещания)
THOUGHTFUL = [
    "хз", "ну", "ну да", "ну такое", "вроде", "наверн", "чет", "кажется",
    "как скажете", "lf", "да хз", "ну вот", "хм", "ого", "неа",
    "интересно", "странно", "сложно", "похоже", "ну вот хз",
]
THOUGHTFUL_LEAD = ["ну", "чет", "вроде", "кста", "а", "ого", "ля", "тюю"]
THOUGHTFUL_TAIL = ["хз", "да", "нет", "такое", "норм", "ок", "неа"]
THOUGHTFUL_COMPOUND = [
    "ну да", "ну такое", "как скажете", "вроде да", "да хз", "чет хз",
    "ну вот хз", "не уверен", "ниче непонятно", "ну такое себе",
]

# Реальные частые реплики — якоря, чтобы синтез не уезжал от стиля
ANCHORS = [
    "да", "Да", "ага", "Ага", "спс", "спасибо", "Спасибо",
    "гуд", "Гуд", "норм", "супер", "каеф", "Каеф", "збс", "стопроц", "апрувед",
    "блэт", "лол", "ахах", "мазлтов!", "ура", "неа", "дада", "Дада", "++++",
    "супер, спасибо", "гуд, спасибо", "отлично, спасибо", "граци рагаци",
    "красавчики", "классика", "лавли", "да бля", "хз", "ну", "как скажете",
]

# Запрещённые в синтезе (обещания / действия)
FORBIDDEN = re.compile(
    r"оставил|откомментил|закинул|закинь|отдал|отправил|поправил|сделаю|"
    r"проверь|чекни|дай|добавил|собери|поправь|нужно|надо|можешь|плиз|"
    r"давайте|подвинем|гляну|жду|дам|скину|кину|посмотрите|глянь|"
    r"отдадим|запил|запулил|пилить|собирать|попробуем|разбер|"
    r"бегу|5\s*мин|\bмин\b|скипнем|маякну|попозже|сейчас надо",
    re.I,
)

# Контекст → веса блоков для синтеза
CONTEXT_WEIGHTS: dict[str, dict[str, float]] = {
    "delivered": {"thanks": 3, "eval": 2, "affirm": 2, "anchor": 2},
    "mail": {"thanks": 2, "affirm": 2, "eval": 1.5, "anchor": 2},
    "design": {"affirm": 2.5, "thanks": 2, "eval": 1.5, "anchor": 2},
    "video": {"eval": 3, "emphasis": 2, "affirm": 1, "anchor": 1.5},
    "task": {"affirm": 2.5, "thanks": 2, "anchor": 2},
    "approve": {"eval": 3, "anchor": 2},
    "sync": {"thoughtful": 5, "lead": 2, "anchor": 0.5},
    "translate": {"affirm": 2.5, "thanks": 2, "anchor": 1.5},
    "greeting": {"social": 4, "affirm": 2, "anchor": 1},
    "thanks": {"thanks": 2, "social": 2, "eval": 2, "anchor": 2},
    "problem": {"emphasis": 3, "eval": 2, "anchor": 1},
    "go": {"thoughtful": 4, "lead": 2, "anchor": 0.5},
    "generic": {"anchor": 2, "affirm": 1.5, "eval": 1.5, "thanks": 1},
}

TRIGGER_CONTEXT: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(готов[аоы]?|сделал[аи]?|залил|закинул|отдал|загрузил|обновил|поправил|отправил)\b", re.I), "delivered"),
    (re.compile(r"письм|email|промо|рассыл", re.I), "mail"),
    (re.compile(r"макет|фигм|figma|верст|баннер|ленд|обложк|квиз", re.I), "design"),
    (re.compile(r"видео|рилс|ролик|монтаж|ftmo", re.I), "video"),
    (re.compile(r"задач|notion|ноушн|тикет", re.I), "task"),
    (re.compile(r"апрув|approve|ревью|review", re.I), "approve"),
    (re.compile(r"синк|созвон|мит\b|meet|whereby|колл", re.I), "sync"),
    (re.compile(r"перевод|локал", re.I), "translate"),
    (re.compile(r"привет|салам|здаров|добр(ое|ый)\s+(утро|день|вечер)", re.I), "greeting"),
    (re.compile(r"спасибо|спс\b|благодар", re.I), "thanks"),
    (re.compile(r"ошиб|баг|не работ|сломал|проблем|не могу", re.I), "problem"),
    (re.compile(r"\bго\??\b", re.I), "go"),
    (re.compile(r"заход", re.I), "sync"),
    (re.compile(r"\b(гуд|норм|окей|ок)\b", re.I), "approve"),
]

BACKGROUND_TRIGGER = re.compile(
    r"\b(готов[аоы]?|сделал[аи]?|залил|закинул|отдал|загрузил|обновил|поправил)\b|"
    r"заход|письм|email|промо|макет|figma|фигм|баннер|ленд|видео|рилс|"
    r"апрув|ревью|синк|созвон|whereby",
    re.I,
)


def _maybe_cap(word: str) -> str:
    """Паша часто пишет «Да», «Ага», «Спасибо» с заглавной."""
    if random.random() < 0.45 and word.islower() and word.isalpha():
        return word[0].upper() + word[1:]
    return word


def _pick(pool: list[str], cap: bool = False) -> str:
    w = random.choice(pool)
    return _maybe_cap(w) if cap else w


def _pick_simple(kind: str) -> str:
    pools = {"affirm": AFFIRM_SIMPLE, "eval": EVAL_SIMPLE, "lead": LEAD}
    return _maybe_cap(random.choice(pools[kind]))


def _block_for(kind: str) -> str:
    pools = {
        "affirm": AFFIRM,
        "eval": EVAL,
        "thanks": THANKS,
        "lead": LEAD,
        "emphasis": EMPHASIS,
        "social": SOCIAL,
        "ready": READY,
        "anchor": ANCHORS,
        "thoughtful": THOUGHTFUL,
    }
    pool = pools[kind]
    item = random.choice(pool)
    # одиночные слова — иногда с заглавной
    if " " not in item and "," not in item and len(item) < 12:
        return _maybe_cap(item)
    return item


def _weighted_kind(context: str) -> str:
    weights = CONTEXT_WEIGHTS.get(context, CONTEXT_WEIGHTS["generic"])
    kinds = list(weights.keys())
    w = [weights[k] for k in kinds]
    return random.choices(kinds, weights=w, k=1)[0]


def _synthesize_thoughtful() -> str:
    """Задумчивая реакция — для синка, захода, «го»."""
    templates = [
        lambda: random.choice(THOUGHTFUL),
        lambda: random.choice(THOUGHTFUL_COMPOUND),
        lambda: f"{random.choice(THOUGHTFUL_LEAD)} {random.choice(THOUGHTFUL_TAIL)}",
        lambda: f"вроде {random.choice(THOUGHTFUL_TAIL)}",
        lambda: f"чет {random.choice(['хз', 'ну', 'такое', 'странно'])}",
        lambda: f"ну, {random.choice(['хз', 'такое', 'интересно', 'сложно'])}",
        lambda: _maybe_cap(random.choice(["хз", "ну", "ого", "lf"])),
    ]
    return random.choice(templates)()


def _synthesize_one(context: str = "generic") -> str:
    """Собрать одну реакцию из блоков в стиле Паши."""
    if context in ("sync", "go"):
        return _synthesize_thoughtful()

    roll = random.random()

    # 35% — готовая якорная фраза из данных
    if roll < 0.35:
        return random.choice(ANCHORS)

    # шаблоны синтеза
    templates = [
        lambda: _block_for(_weighted_kind(context)),
        lambda: random.choice(COMPOUND),
        lambda: f"{_pick_simple('lead')}, {_pick_simple('eval')}",
        lambda: f"{_pick_simple('lead')} {_pick_simple('affirm')}",
        lambda: f"{_pick_simple('affirm')} {_pick_simple('eval')}",
        lambda: _block_for("thanks"),
        lambda: _pick_simple("eval") + "!",
        lambda: _block_for("emphasis"),
        lambda: _block_for("social"),
    ]

    # контекстные шаблоны
    if context == "greeting":
        templates.extend([
            lambda: random.choice(["салам", "го?", "парни", "ага", "го"]),
        ])
    elif context == "thanks":
        templates.extend([
            lambda: random.choice(["граци рагаци", "красавчики", "мазлтов!", "супер, спасибо", "лавли"]),
        ])
    elif context == "problem":
        templates.extend([
            lambda: random.choice(["да бля", "блэт", "лол", "ого", "ну да"]),
        ])
    elif context in ("delivered", "mail", "design", "task"):
        templates.extend([
            lambda: random.choice(["Спасибо", "спасибо", "да", "Да", "Ага", "гуд", "супер", "спс"]),
            lambda: random.choice(["супер, спасибо", "гуд, спасибо", "отлично, спасибо"]),
        ])
    elif context == "approve":
        templates.extend([
            lambda: random.choice(["стопроц", "апрувед", "гуд", "супер", "каеф", "збс"]),
        ])
    elif context == "video":
        templates.extend([
            lambda: random.choice(["блэт", "каеф", "ого", "лол", "ахах", "гуд"]),
        ])

    result = random.choice(templates)()
    result = re.sub(r"\s+", " ", result).strip()
    return result


def _detect_context(text: Optional[str]) -> str:
    if not text:
        return "generic"
    for pattern, ctx in TRIGGER_CONTEXT:
        if pattern.search(text):
            return ctx
    return "generic"


def synthesize_reaction(text: Optional[str] = None, n_candidates: int = 5) -> str:
    """
    Синтезировать реакцию в стиле Паши.
    Генерирует несколько вариантов и выбирает валидный.
    """
    context = _detect_context(text)
    for _ in range(n_candidates * 2):
        candidate = _synthesize_one(context)
        if len(candidate) > 32:
            continue
        if FORBIDDEN.search(candidate):
            continue
        if URL.search(candidate):
            continue
        return candidate
    return random.choice(ANCHORS)


def generate_pasha_response(text: Optional[str] = None, command: Optional[str] = None) -> str:
    if command:
        cmd = command.lower().split()[0]
        if cmd in ("pasha", "паша", "салам", "апрув", "макет", "гуд"):
            return synthesize_reaction(text)
        if cmd in ("синк", "sync", "го"):
            return synthesize_reaction("синк")
        return synthesize_reaction()

    return synthesize_reaction(text)


def pasha_reply_to_message(message_text: str) -> Optional[str]:
    text = message_text.strip()
    lower = text.lower()

    if BOT_MENTION.lower() in lower or re.search(r"@ag_slashbot|@\w*slashbot", lower, re.I):
        return synthesize_reaction(strip_bot_mention(text) or text)

    if BACKGROUND_TRIGGER.search(text):
        return synthesize_reaction(text)

    return None


def strip_bot_mention(text: str) -> str:
    return re.sub(rf"@?{re.escape(BOT_USERNAME)}\b", "", text, flags=re.I).strip()


def sample_synthetic(count: int = 20, context: Optional[str] = None) -> list[str]:
    """Для отладки: набор синтетических реакций."""
    ctx = context or "generic"
    if context is None:
        return [synthesize_reaction() for _ in range(count)]
    fake_text = {
        "delivered": "залил макет",
        "mail": "письмо готово",
        "design": "фигма макет",
        "video": "рилс готов",
        "sync": "синк в 12",
        "greeting": "привет",
        "problem": "баг в верстке",
    }.get(ctx, "")
    return [synthesize_reaction(fake_text or None) for _ in range(count)]
