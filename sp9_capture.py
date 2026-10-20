"""Browser capture for the local S:P9 daily digest.

The collector uses a dedicated persistent Chrome profile.  The user signs in
to Notion once with ``python sp9_digest.py setup-browser``; scheduled weekday
runs then reuse that guest session without a Notion integration or API token.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


BOARD_URL = os.getenv(
    "SP9_NOTION_URL",
    "https://app.notion.com/p/Sabio-Marketing-Plans-11541fd053ce8023873af02a304d24cd",
)
MOTION_URL = os.getenv(
    "SP9_MOTION_URL",
    "https://sabio-tasks.superpasha9000.chatgpt.site/",
)
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_PROFILE_DIR = Path(
    os.getenv("SP9_BROWSER_PROFILE", str(PROJECT_ROOT / ".sp9_browser_profile"))
).expanduser()


class BrowserCaptureError(RuntimeError):
    """Raised when the browser could not collect a trustworthy source set."""


def _playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserCaptureError(
            "Не установлен Playwright. Запусти: pip install -r requirements.txt"
        ) from exc
    return sync_playwright


def _launch_context(playwright: Any, profile_dir: Path, *, headless: bool):
    profile_dir.mkdir(parents=True, exist_ok=True)
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        channel="chrome",
        headless=headless,
        viewport={"width": 2200, "height": 1350},
        screen={"width": 2200, "height": 1350},
        args=[
            "--window-size=2200,1350",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
        ],
    )


def setup_browser(
    *, board_url: str = BOARD_URL, profile_dir: Path = DEFAULT_PROFILE_DIR
) -> None:
    """Open the dedicated Chrome profile so the user can sign in once."""
    sync_playwright = _playwright()
    with sync_playwright() as playwright:
        context = _launch_context(playwright, profile_dir, headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(board_url, wait_until="domcontentloaded", timeout=90_000)
        print("\nОткрылся отдельный профиль Chrome для ежедневной сводки.")
        print("Войди в Notion и убедись, что видна вкладка S:P9 tasks.")
        input("После этого вернись в терминал и нажми Enter: ")
        page.reload(wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(2500)
        if _looks_logged_out(page):
            context.close()
            raise BrowserCaptureError("Notion всё ещё показывает вход. Авторизация не сохранена.")
        context.close()
    print(f"Готово: гостевая сессия сохранена в {profile_dir}")


def _looks_logged_out(page: Any) -> bool:
    url = page.url.lower()
    if "/login" in url or "/signup" in url:
        return True
    try:
        text = page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        return False
    markers = ("continue with google", "продолжить с google", "log in to notion")
    return any(marker in text for marker in markers)


def _open_notion_page(page: Any, url: str) -> None:
    """Wait for the usable Notion UI rather than unrelated document loading."""
    page.goto(url, wait_until='commit', timeout=45_000)
    try:
        page.locator('.notion-page-content').wait_for(state='attached', timeout=45_000)
    except Exception:
        if _looks_logged_out(page):
            raise BrowserCaptureError('Гостевая сессия Notion не авторизована. Запусти setup-browser.')
        raise


_BOARD_INVENTORY_JS = r"""() => {
  const view=[...document.querySelectorAll('.notion-board-view')].find(e=>e.getClientRects().length && getComputedStyle(e).display!=='none');
  if (!view) return null;
  const lines=view.innerText.split('\n').map(x=>x.trim()).filter(Boolean);
  const headers=[];
  while (lines.length>=2 && /^(No Status|To Do|In Progress|Review|Completed)$/.test(lines[0]) && /^\d+\+?$/.test(lines[1])) {
    headers.push({status:lines.shift(),count:lines.shift()});
  }
  const groups=[...view.querySelectorAll('.notion-board-group')];
  return {headers,groups:groups.map(g=>[...g.querySelectorAll('.notion-collection-item[data-block-id]')].map(e=>({
    id:e.getAttribute('data-block-id'),text:e.innerText,
    title:e.innerText.split('\n').map(x=>x.trim()).find(x=>/[\p{L}\p{N}]/u.test(x)) || ''
  })))};
}"""


def _board_inventory(page: Any) -> dict[str, Any]:
    """A description inside a card cannot create another card in this census."""
    raw = page.evaluate(_BOARD_INVENTORY_JS)
    labels = {'No Status': 'no_status', 'To Do': 'to_do', 'In Progress': 'in_progress',
              'Review': 'review', 'Completed': 'completed'}
    if not isinstance(raw, dict):
        raise BrowserCaptureError('Не удалось прочитать структуру доски Notion')
    headers, groups = raw.get('headers', []), raw.get('groups', [])
    if len(headers) != 5 or len(groups) != 5 or {h.get('status') for h in headers} != labels.keys():
        raise BrowserCaptureError('Не удалось сопоставить колонки и карточки доски Notion')
    cards, counts, seen = [], {}, set()
    for header, group in zip(headers, groups):
        status = header['status']
        value = str(header['count'])
        if not re.fullmatch(r'\d+\+?', value) or (status != 'Completed' and value.endswith('+')):
            raise BrowserCaptureError('Не удалось прочитать точный счётчик активной колонки')
        counts[labels[status]] = int(value.rstrip('+'))
        for item in group:
            key = str(item.get('id', '')).replace('-', '').lower()
            if not re.fullmatch(r'[a-f0-9]{32}', key) or key in seen or not item.get('title'):
                raise BrowserCaptureError('Не удалось однозначно прочитать ID карточки доски')
            seen.add(key)
            cards.append({'id': key, 'title': item['title'], 'status': status,
                          'url': 'https://app.notion.com/p/' + key, 'text': item.get('text', '')})
        if status != 'Completed' and len(group) != counts[labels[status]]:
            raise BrowserCaptureError(f'DOM доски: {status} — прочитано {len(group)} из {counts[labels[status]]}')
    return {'version': 1, 'complete': True, 'board_counts': counts, 'cards': cards,
            'captured_at': datetime.now(MOSCOW_TZ).isoformat()}


def _click_sp9_view(page: Any) -> None:
    # Notion opens the view actions menu when the already selected tab is
    # clicked.  Avoid that: the menu otherwise stays over every screenshot.
    try:
        selected = page.locator('[role="tab"][aria-selected="true"]')
        if selected.count() and "s:p9 tasks" in selected.first.inner_text().casefold():
            return
    except Exception:
        pass

    candidates = [
        page.get_by_text("S:P9 tasks", exact=True),
        page.get_by_role("tab", name=re.compile(r"S:P9 tasks", re.I)),
    ]
    for locator in candidates:
        try:
            if locator.count() and locator.first.is_visible():
                locator.first.click(timeout=5000)
                page.wait_for_timeout(1800)
                page.keyboard.press("Escape")
                return
        except Exception:
            continue


_SCROLLER_SCRIPT = r"""
({preferText, horizontal}) => {
  const all = [document.scrollingElement, ...document.querySelectorAll('*')].filter(Boolean);
  let preferred = null;
  if (preferText) {
    const needle = preferText.toLowerCase();
    const hit = all.find(el => {
      const own = (el.innerText || '').trim().toLowerCase();
      return own && own.length < 5000 && own.includes(needle);
    });
    let node = hit;
    while (node) {
      const delta = horizontal
        ? node.scrollWidth - node.clientWidth
        : node.scrollHeight - node.clientHeight;
      if (delta > 180) { preferred = node; break; }
      node = node.parentElement;
    }
  }
  const candidates = all.filter(el => {
    const rect = el.getBoundingClientRect();
    const delta = horizontal
      ? el.scrollWidth - el.clientWidth
      : el.scrollHeight - el.clientHeight;
    return delta > 180 && rect.width > 320 && rect.height > 240;
  });
  const target = preferred || candidates.sort((a, b) => {
    const ar = a.getBoundingClientRect();
    const br = b.getBoundingClientRect();
    const as = (horizontal ? a.scrollWidth-a.clientWidth : a.scrollHeight-a.clientHeight) * ar.width;
    const bs = (horizontal ? b.scrollWidth-b.clientWidth : b.scrollHeight-b.clientHeight) * br.width;
    return bs - as;
  })[0] || document.scrollingElement;
  if (!target) return null;
  target.setAttribute('data-slashbot-scroller', horizontal ? 'x' : 'y');
  return {
    clientHeight: target.clientHeight,
    clientWidth: target.clientWidth,
    scrollHeight: target.scrollHeight,
    scrollWidth: target.scrollWidth,
    scrollTop: target.scrollTop,
    scrollLeft: target.scrollLeft
  };
}
"""


def _find_scroller(page: Any, *, prefer_text: str | None = None, horizontal: bool = False):
    return page.evaluate(
        _SCROLLER_SCRIPT,
        {"preferText": prefer_text or "", "horizontal": horizontal},
    )


def _scroll(page: Any, *, top: int | None = None, left: int | None = None) -> None:
    page.evaluate(
        """
        ({top, left}) => {
          const y = document.querySelector('[data-slashbot-scroller="y"]') || document.scrollingElement;
          const x = document.querySelector('[data-slashbot-scroller="x"]') || y;
          if (y && top !== null) y.scrollTop = top;
          if (x && left !== null) x.scrollLeft = left;
        }
        """,
        {"top": top, "left": left},
    )


def _positions(total: int, viewport: int, *, cap: int) -> list[int]:
    maximum = max(0, total - viewport)
    if maximum == 0:
        return [0]
    step = max(300, int(viewport * 0.76))
    values = list(range(0, maximum + 1, step))
    if values[-1] != maximum:
        values.append(maximum)
    if len(values) <= cap:
        return values
    # Preserve the beginning and end while sampling the middle evenly.
    return sorted({round(maximum * index / (cap - 1)) for index in range(cap)})


def _visible_anchors(page: Any) -> list[dict[str, str]]:
    try:
        return page.locator("a:visible").evaluate_all(
            """
            els => els.map(a => ({
              text: (a.innerText || a.textContent || '').trim(),
              href: a.href || ''
            })).filter(x => x.text && x.href)
            """
        )
    except Exception:
        return []


def _body_excerpt(page: Any, limit: int = 18_000) -> str:
    try:
        return page.locator("body").inner_text(timeout=5000)[:limit]
    except Exception:
        return ""


def _capture_series(
    page: Any,
    destination: Path,
    prefix: str,
    *,
    prefer_text: str | None = None,
    max_vertical: int = 8,
    include_horizontal_end: bool = False,
) -> tuple[list[Path], list[dict[str, str]], list[str]]:
    y_info = _find_scroller(page, prefer_text=prefer_text, horizontal=False) or {}
    x_info = _find_scroller(page, prefer_text=prefer_text, horizontal=True) or y_info
    y_values = _positions(
        int(y_info.get("scrollHeight", 0)),
        int(y_info.get("clientHeight", 0)),
        cap=max_vertical,
    )
    x_values = [0]
    max_x = max(0, int(x_info.get("scrollWidth", 0)) - int(x_info.get("clientWidth", 0)))
    if include_horizontal_end and max_x > 250:
        x_values.append(max_x)

    images: list[Path] = []
    anchors: list[dict[str, str]] = []
    excerpts: list[str] = []
    hashes: set[str] = set()
    counter = 0
    for left in x_values:
        for top in y_values:
            _scroll(page, top=top, left=left)
            page.wait_for_timeout(800)
            raw = page.screenshot(full_page=False, type="jpeg", quality=78)
            digest = hashlib.sha256(raw).hexdigest()
            if digest in hashes:
                continue
            hashes.add(digest)
            path = destination / f"{prefix}_{counter:02d}.jpg"
            path.write_bytes(raw)
            images.append(path)
            anchors.extend(_visible_anchors(page))
            excerpt = _body_excerpt(page)
            if excerpt:
                excerpts.append(excerpt)
            counter += 1
    return images, anchors, excerpts


def _click_updates(page: Any, *, timeout_ms: int = 30_000) -> None:
    """Open Notion's updates panel after its lazy sidebar has rendered."""
    labels = re.compile(r"^(Inbox|Workspace updates|Updates|Входящие|Обновления)$", re.I)
    deadline = time.monotonic() + timeout_ms / 1000

    while time.monotonic() < deadline:
        candidates = [
            page.get_by_role("button", name=labels),
            page.locator('[role="button"][aria-label="Inbox"]'),
            page.get_by_text(labels, exact=True),
        ]
        for locator in candidates:
            try:
                if locator.count():
                    # A direct DOM click also works when Notion temporarily
                    # marks its fixed sidebar control as outside the viewport.
                    locator.first.evaluate("element => element.click()")
                    page.wait_for_timeout(1800)
                    return
            except Exception:
                continue

        # The sidebar can start collapsed even though the persistent profile
        # normally keeps it open.  Expanding it lets the Inbox control mount.
        try:
            open_sidebar = page.get_by_role(
                "button", name=re.compile(r"^(Open sidebar|Открыть боковую панель)$", re.I)
            )
            if open_sidebar.count():
                open_sidebar.first.evaluate("element => element.click()")
        except Exception:
            pass
        page.wait_for_timeout(750)

    raise BrowserCaptureError(
        "Notion не показал Inbox / Workspace updates за 30 секунд"
    )


def _dedupe_anchors(items: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        text = re.sub(r"\s+", " ", item.get("text", "")).strip()
        href = item.get("href", "").strip()
        if not text or not href or len(text) > 300:
            continue
        key = (text, href.split("?", 1)[0])
        if key in seen:
            continue
        seen.add(key)
        result.append({"text": text, "href": href})
    return result


def capture_sources(
    destination: Path,
    **kwargs: Any,
) -> dict[str, Any]:
    """Convert browser failures into errors handled by the digest retry loop."""
    _playwright()
    from playwright.sync_api import Error as PlaywrightError

    try:
        return _capture_sources(destination, **kwargs)
    except PlaywrightError as exc:
        raise BrowserCaptureError(f"Ошибка браузера при сборе источников: {exc}") from exc


def _capture_sources(
    destination: Path,
    *,
    board_url: str = BOARD_URL,
    motion_url: str = MOTION_URL,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    headless: bool = True,
) -> dict[str, Any]:
    """Capture the whole board, recent updates and the public motion board."""
    destination.mkdir(parents=True, exist_ok=True)
    sync_playwright = _playwright()
    with sync_playwright() as playwright:
        context = _launch_context(playwright, profile_dir, headless=headless)
        # A restored Chrome startup tab may close itself while extensions and
        # session restore settle.  Always work in a fresh tab owned by us.
        page = context.new_page()
        _open_notion_page(page, board_url)
        page.wait_for_timeout(5000)
        if _looks_logged_out(page):
            context.close()
            raise BrowserCaptureError(
                "Гостевая сессия Notion не авторизована. Запусти setup-browser."
            )
        # Capture the inbox before traversing the large board.  Scrolling the
        # board can make Notion report the fixed sidebar control as hidden.
        _click_updates(page)
        updates_images, updates_anchors, updates_text = _capture_series(
            page,
            destination,
            "updates",
            prefer_text="Inbox",
            max_vertical=5,
        )

        # Reload closes Inbox and restores a clean board viewport.
        _open_notion_page(page, board_url)
        page.wait_for_timeout(4000)
        _click_sp9_view(page)
        inventory = _board_inventory(page)
        board_images, board_anchors, board_text = _capture_series(
            page,
            destination,
            "board",
            max_vertical=9,
            include_horizontal_end=True,
        )

        motion_page = context.new_page()
        motion_page.goto(motion_url, wait_until="domcontentloaded", timeout=90_000)
        motion_page.wait_for_timeout(3500)
        motion_images, motion_anchors, motion_text = _capture_series(
            motion_page,
            destination,
            "motion",
            max_vertical=6,
        )
        context.close()

    if not board_images or not updates_images:
        raise BrowserCaptureError("Не удалось получить обязательные снимки Notion")

    manifest: dict[str, Any] = {
        "captured_at": datetime.now(MOSCOW_TZ).isoformat(),
        "board_url": board_url,
        "motion_url": motion_url,
        "board_inventory": inventory,
        "board_images": [str(path) for path in board_images],
        "updates_images": [str(path) for path in updates_images],
        "motion_images": [str(path) for path in motion_images],
        "anchors": _dedupe_anchors(board_anchors + updates_anchors + motion_anchors),
        "visible_text": {
            "board": board_text,
            "updates": updates_text,
            "motion": motion_text,
        },
    }
    (destination / "capture_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    target = PROJECT_ROOT / ".sp9_data" / "manual-capture" / str(int(time.time()))
    print(json.dumps(capture_sources(target, headless=False), ensure_ascii=False, indent=2))
