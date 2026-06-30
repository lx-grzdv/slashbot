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

# Провокационное / ироничное — короткие реплики из экспорта (≤32 символа)
PROVOCATIVE = [
    "блэт", "да бля", "блин", "лол", "ахах", "ахаха", "Лол",
    "классика", "лавли", "экзактли", "lf", "++++", "неа", "Неа",
    "да.", "ну такое", "как скажете", "договор", "нуу неее",
    "не, так хуже", "все серьезно", "тюю", "ого", "хрен", "прикольно",
]
PROVOCATIVE_TEASE = ["красавчики", "мазлтов!", "граци рагаци", "секси", "вааай"]
PROVOCATIVE_COMPOUND = [
    "да бля", "ну такое", "не, так хуже", "лавли, спасибище",
    "классика, блэт", "да. но херово", "ну, интересно", "вроде, ого",
]

MAX_SHORT_LEN = 32
MAX_LONG_LEN = 120
LONG_REPLY_CHANCE = 0.28

# Длинные контекстные реплики из экспорта (33–120 символов, без @ и обещаний)
PROVOCATIVE_LONG: dict[str, list[str]] = {
    "design": [
        "бля как же жопа горит от таких макетов",
        "В этом блок чет половина логотипов шакальная",
        "ТОлько кейс прикольный, а стиль ну стиль и стиль. Подали вкусно",
        "Замени только тридэхи на секси футуристичные, эти чет зашкварные",
        "Сделай тут фон карточки менее активный, а то прям стремно выглядит",
        "ТЫ точно поменял картинки? Чет у меня все ранво шакальные",
        "бля шапки магистерские как свечи японские",
        "Странный масштаб и позиционирование",
        "вот эта конструкция странно выглядит",
        "Сань чет у Рюдигера бошка светится странно",
        "это бля Саня вместо того, чтобы сделать нормальный градиент просто в группе продублировал плашку",
        "ну и в целом то стиль разъехался, где-то супер секси тридэхи остались, а где-то просто линии на плашке.",
        "Гуд. Кажется на втором и третьем слайдах контент внутри карточек мелкий. Непонятно че там",
        "бляя парни прикиньте такие обложки сделать? Прям разъеб",
    ],
    "problem": [
        "чУприн блядь. Понаехали дизайнеры",
        "Блин. Я уж подумал опять без меня дудосят",
        "нет. я просто не понял что ты сделал)",
        "ниче непонятно, но очень интересно",
        "видимо через жопу стаивли задачу и назвали хз как",
        "ну чет не туда Саша. В текс то вникни и посмотри куда я комменты ткнул",
        "не визуал мимо, а сам подход и идея в корне не туда. Это про понимание задачи и того как вообще коммуникация работает",
        "и в ноукод сатйах снова повернул не туда",
        "хотя что блядь там комментировать???",
        "Бля, даже картинку уде не может сделать",
        "ага, заюзал. Говно какое-то выгрузил мне)",
        "план говно. а как люди с картинки будут копировать код?",
        "Да чет рябит все в мелких и не понятна история с параллельным миром",
        "Погодь, кажись не туда смотришь)",
    ],
    "video": [
        "А то бля озвучку делаем дольше чем ролик",
        "Ахах, автор задачи скинет только люлей",
        "Ахаха видимо так долго делаем, что он уже забыл про сто видос",
        "Да бля это Олег конечно напорпол в сисходниках. Там видос золотой будет, если все за ним затирать",
    ],
    "mail": [
        "Интересно, я чекал оригинал в браузере было норм. Видимо особенности меилчимпа",
        "мне только стрелки в тексте не нравятся, кажется они в переводах по бороде пойдут",
        "ит текст под заголовком ооч мелкий",
    ],
    "delivered": [
        "Очень прикольно вышло, все нравится, спасибо!",
        "Вообще дашборд пушка. Ты красавчик",
        "хихи какой прикольный первый слайд получился) мне все нравится, забираю, спасибо!",
        "Вы даже распределили от зеленого к красному в соответствии со степенью сложности, очень прикольно вышло, спасибо!!",
        "Облоги гуд. Добавь еще постик и мелкие картинки",
    ],
    "thanks": [
        "Ребята в плане концепций красавчики",
        "Господа, всем спасибо и хорошего дудосинга.",
        "Очень прикольно вышло, все нравится, спасибо!",
    ],
    "approve": [
        "да, классикаЯ так и думал если честно. Но мы рил в последний вагон",
        "Бля ну щас прям збс, чутка всратости добавить бы.",
        "Стали серьезными ребятами. Обратил внимание, как на голд переключился стиль",
    ],
    "sync": [
        "Чет я не уверен на счет черного фона.",
        "Оо, а я хз. Думаю инфа будет как обычно 20го",
        "тогда хз, просто если Маша доебется придется придумать план Б",
        "Дада. Только чет 27 вопросов ту мач",
    ],
    "generic": [
        "Ну вообще в интересное время живем",
        "Обдудосились своими дизайнами этими",
        "Воо сегодня же короткий день перед праздниками и все тусят. Минская классика - хуй где сядешь",
        "Есть такая фраза из подкаста череповецких утопленников \"Зачем делать говно, когда можно сделать не говно?\"",
        "ахаха я видимо заебал гпт так, что он мне по простому запросу сразу код херачит",
        "Ахах, Алексис, на донышке это твоя тема",
        "Ахаха, она говорила я тоже хочу золотое",
        "Бля Леха, котики это же гениально",
        "Прикольно что запрос - напиши змейку на питоне",
        "Парни, где искать такие секси карточки курсов?",
        "кста. из этих стартапов flipscards прикольня штука",
        "На Индонезийски. Выглядит прикольно",
        "У меня не было такого. Мы пили Степу спецуху",
        "Ахах как кость. Я аж пропустил вчера",
        "Ахах забыли очередь узбеков в рендер добавить",
        "Гпт красавчег. Только в хигсфилде почему то нет 16:9",
        "вроде супер простая штука и должна быть из коробки в маке давноИбо все сервисы говно полное",
        "Оо они лучше выпустят говнообновления. Курсоры де завезли, но не в ту дверь",
        "интересно, а хоть кто-то из спикеров ворощит болото? Или все до сих пор суперпродуктивные и успешный пупсики?",
        "бля вчера только меме читал, что в 16 часов просыпаются америкосы и нейронки ложатся и тупеют",
    ],
}

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
    "договор", "нуу неее", "все серьезно", "блин", "не, так хуже", "прикольно",
]

# Якоря для «сдали работу» — без провокации и «го?»
DELIVERED_ANCHORS = [
    "да", "Да", "ага", "Ага", "спс", "спасибо", "Спасибо",
    "гуд", "Гуд", "норм", "супер", "каеф", "збс", "стопроц", "апрувед",
    "супер, спасибо", "гуд, спасибо", "отлично, спасибо", "ага, спасибо",
    "ура", "дада", "Дада",
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
    "delivered": {"thanks": 4, "affirm": 2.5, "eval": 2, "anchor": 2, "provocative": 0.3},
    "mail": {"thanks": 2.5, "affirm": 2, "eval": 1.5, "anchor": 2, "provocative": 0.3},
    "design": {"affirm": 2.5, "thanks": 2, "eval": 1.5, "anchor": 2, "provocative": 0.5},
    "video": {"eval": 2.5, "provocative": 3, "emphasis": 2, "affirm": 1, "anchor": 1},
    "task": {"affirm": 2.5, "thanks": 2, "anchor": 2, "provocative": 0.5},
    "approve": {"eval": 2.5, "provocative": 2, "anchor": 2},
    "sync": {"thoughtful": 5, "lead": 2, "anchor": 0.5},
    "translate": {"affirm": 2.5, "thanks": 2, "anchor": 1.5, "provocative": 0.5},
    "greeting": {"social": 4, "affirm": 2, "anchor": 1, "provocative": 1},
    "thanks": {"thanks": 2, "social": 2, "provocative": 1.5, "eval": 2, "anchor": 2},
    "problem": {"provocative": 4, "emphasis": 3, "eval": 2, "anchor": 1},
    "go": {"thoughtful": 4, "lead": 2, "anchor": 0.5},
    "generic": {"anchor": 2, "affirm": 1.5, "eval": 1.5, "thanks": 1, "provocative": 1.5},
}

TRIGGER_CONTEXT: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(готов[аоы]?|сделал[аи]?|залил|закинул|отдал|загрузил|обновил|поправил|отправил)\b", re.I), "delivered"),
    (re.compile(r"письм|email|промо|рассыл", re.I), "mail"),
    (re.compile(r"ошиб|баг|не работ|сломал|проблем|не могу", re.I), "problem"),
    (re.compile(r"макет|фигм|figma|верст|баннер|ленд|обложк|квиз", re.I), "design"),
    (re.compile(r"видео|рилс|ролик|монтаж|ftmo", re.I), "video"),
    (re.compile(r"задач|notion|ноушн|тикет", re.I), "task"),
    (re.compile(r"апрув|approve|ревью|review", re.I), "approve"),
    (re.compile(r"синк|созвон|мит\b|meet|whereby|колл", re.I), "sync"),
    (re.compile(r"перевод|локал", re.I), "translate"),
    (re.compile(r"привет|салам|здаров|добр(ое|ый)\s+(утро|день|вечер)", re.I), "greeting"),
    (re.compile(r"спасибо|спс\b|благодар", re.I), "thanks"),
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
        "provocative": PROVOCATIVE + PROVOCATIVE_TEASE,
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

    if context in ("delivered", "mail", "design", "task"):
        templates = [
            lambda: random.choice(["Спасибо", "спасибо", "да", "Да", "Ага", "гуд", "супер", "спс"]),
            lambda: random.choice(["супер, спасибо", "гуд, спасибо", "отлично, спасибо", "ага, спасибо"]),
            lambda: _block_for("thanks"),
            lambda: _block_for("affirm"),
            lambda: _block_for("eval"),
            lambda: random.choice(DELIVERED_ANCHORS),
        ]
        return random.choice(templates)()

    if context == "problem":
        templates = [
            lambda: random.choice(["да бля", "блэт", "лол", "ого", "блин", "да.", "lf", "ахах"]),
            lambda: random.choice(["не, так хуже", "все серьезно", "нуу неее", "договор", "ну такое"]),
            lambda: random.choice(PROVOCATIVE_COMPOUND),
            lambda: f"ну, {_block_for('provocative')}",
            lambda: _block_for("provocative"),
            lambda: _block_for("emphasis"),
        ]
        return random.choice(templates)()

    roll = random.random()

    # 35% — готовая якорная фраза из данных
    if roll < 0.35:
        return random.choice(ANCHORS)

    # шаблоны синтеза
    templates = [
        lambda: _block_for(_weighted_kind(context)),
        lambda: random.choice(COMPOUND),
        lambda: random.choice(PROVOCATIVE_COMPOUND),
        lambda: f"{_block_for('provocative')}, {_pick_simple('eval')}",
        lambda: f"ну, {_block_for('provocative')}",
        lambda: f"{_pick_simple('lead')}, {_pick_simple('eval')}",
        lambda: f"{_pick_simple('lead')} {_pick_simple('affirm')}",
        lambda: f"{_pick_simple('affirm')} {_pick_simple('eval')}",
        lambda: _block_for("thanks"),
        lambda: _pick_simple("eval") + "!",
        lambda: _block_for("emphasis"),
        lambda: _block_for("social"),
        lambda: _block_for("provocative"),
    ]

    # контекстные шаблоны
    if context == "greeting":
        templates.extend([
            lambda: random.choice(["салам", "го?", "парни", "ага", "го"]),
        ])
    elif context == "thanks":
        templates.extend([
            lambda: random.choice(["граци рагаци", "красавчики", "мазлтов!", "супер, спасибо", "лавли"]),
            lambda: random.choice(PROVOCATIVE_TEASE),
        ])
    elif context == "approve":
        templates.extend([
            lambda: random.choice(["стопроц", "апрувед", "гуд", "супер", "каеф", "збс", "классика", "экзактли"]),
        ])
    elif context == "video":
        templates.extend([
            lambda: random.choice(["блэт", "каеф", "ого", "лол", "ахах", "гуд", "классика", "лавли"]),
        ])

    result = random.choice(templates)()
    result = re.sub(r"\s+", " ", result).strip()
    return result



def _is_valid_reply(candidate: str, max_len: int) -> bool:
    if len(candidate) > max_len:
        return False
    if FORBIDDEN.search(candidate):
        return False
    if URL.search(candidate):
        return False
    return True


def _long_pool_for(context: str) -> list[str]:
    own = list(PROVOCATIVE_LONG.get(context, []))
    if context in ("delivered", "mail", "task", "thanks"):
        return own
    if own:
        return own + PROVOCATIVE_LONG.get("generic", [])
    return list(PROVOCATIVE_LONG.get("generic", []))


def _long_reply_chance(context: str) -> float:
    if context in ("problem", "design"):
        return 0.38
    if context in ("video", "generic"):
        return 0.32
    if context in ("delivered", "mail", "task", "thanks"):
        return 0.18
    if context in ("sync", "go"):
        return 0.12
    return LONG_REPLY_CHANCE


def _pick_long_reaction(context: str) -> Optional[str]:
    pool = _long_pool_for(context)
    if not pool:
        return None
    return random.choice(pool)

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
    if random.random() < _long_reply_chance(context):
        for _ in range(n_candidates * 3):
            candidate = _pick_long_reaction(context)
            if candidate and _is_valid_reply(candidate, MAX_LONG_LEN):
                return candidate

    for _ in range(n_candidates * 2):
        candidate = _synthesize_one(context)
        if _is_valid_reply(candidate, MAX_SHORT_LEN):
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
