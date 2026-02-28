# Отправка проекта на GitHub

Репозиторий уже инициализирован, первый коммит сделан. Осталось создать репозиторий на GitHub и выполнить push.

## Шаги

### 1. Создай репозиторий на GitHub

1. Зайди на [github.com](https://github.com) и войди в аккаунт.
2. Нажми **"+"** → **"New repository"**.
3. Укажи:
   - **Repository name:** `slashbot` (или любое имя).
   - **Visibility:** Private или Public.
   - **НЕ** ставь галочки "Add a README" / "Add .gitignore" — у тебя уже есть файлы.
4. Нажми **"Create repository"**.

### 2. Привяжи remote и сделай push

В терминале в папке проекта выполни (подставь свой **username** вместо `YOUR_USERNAME`):

```bash
cd "/Users/alexeygruzdev/Documents/Проекты/slashbot"

git remote add origin https://github.com/YOUR_USERNAME/slashbot.git
git branch -M main
git push -u origin main
```

Если используешь SSH:

```bash
git remote add origin git@github.com:YOUR_USERNAME/slashbot.git
git branch -M main
git push -u origin main
```

При первом push может потребоваться авторизация (логин/пароль или токен; при 2FA — Personal Access Token вместо пароля).

---

**Важно:** В репозиторий не попали `config.py` (токен бота), `bot_users.json`, `bot_settings.json`, `scheduled_messages.json` — они в `.gitignore`. На другом компьютере после клона нужно создать `config.py` из `config.example.py` и подставить токен.
