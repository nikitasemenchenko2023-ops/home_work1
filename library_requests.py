import re
import requests
from bs4 import BeautifulSoup, NavigableString

BASE_URL = "http://hw1.alexbers.com"
USER_COOKIE = {"user": "4b838d3fac1efe4d30f2de1e7805bd43"}

session = requests.Session()
session.cookies.update(USER_COOKIE)



def get_context_before_table(table, max_len=300):
    """Собирает текст непосредственно перед таблицей, пока не встретит другую таблицу."""
    parts = []
    el = table.previous_sibling
    while el is not None:
        if getattr(el, "name", None) == "table":
            break
        if isinstance(el, NavigableString):
            s = str(el).strip()
            if s:
                parts.append(s)
        else:
            s = el.get_text(" ", strip=True)
            if s:
                parts.append(s)
        el = el.previous_sibling
    text = " ".join(reversed(parts))
    return text[-max_len:]


def classify_context(ctx):
    """Определяет по контексту, к чему относится таблица. Берёт ПОСЛЕДНИЙ маркер."""
    ctx = ctx.lower()
    markers = [
        ("cookie", "cookies"),
        ("заголовк", "headers"),
        ("параметр", "params"),
        ("данные формы", "data"),
        ("имя файла", "files"),
        ("содержим", "files"),
    ]
    best_pos = -1
    best_key = None
    for marker, key in markers:
        pos = ctx.rfind(marker)
        if pos > best_pos:
            best_pos = pos
            best_key = key
    return best_key


def parse_kv_table(table):
    """Парсит таблицу Ключ|Значение или Имя файла|Содержимое в dict."""
    result = {}
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) == 2:
            key = tds[0].get_text(strip=True)
            val = tds[1].get_text(strip=True)
            result[key] = val
    return result


def classify_tables(soup):
    """Возвращает dict с cookies/headers/params/data/files."""
    out = {"cookies": {}, "headers": {}, "params": {}, "data": {}, "files": {}}

    for table in soup.find_all("table"):
        ctx = get_context_before_table(table)
        key = classify_context(ctx)
        if key is None:
            continue
        kv = parse_kv_table(table)
        if kv:
            out[key].update(kv)

    return out


def extract_url(text, keyword):
    idx = text.find(keyword)
    if idx == -1:
        return None
    after = text[idx:]
    m = re.search(r"<code>(/[^<]+)</code>", after)
    if m:
        return BASE_URL + m.group(1)
    return None


def extract_link(soup):
    a = soup.find("a")
    if a and a.get("href"):
        href = a["href"]
        return BASE_URL + href if href.startswith("/") else href
    return None


def solve(response):
    response.encoding = "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")
    text = response.text
    print(text[:600])
    tables = classify_tables(soup)

    if "Отправьте GET-запрос" in text:
        url = extract_url(text, "Отправьте GET-запрос")
        print(f"[GET] {url}")
        print(f"  cookies={tables['cookies']}")
        print(f"  headers={tables['headers']}")
        print(f"  params={tables['params']}")
        return session.get(
            url,
            cookies=tables["cookies"],
            headers=tables["headers"],
            params=tables["params"],
            timeout=60
        )

    if "Отправьте POST-запрос" in text:
        url = extract_url(text, "Отправьте POST-запрос")
        print(f"[POST] {url}")
        print(f"  cookies={tables['cookies']}")
        print(f"  headers={tables['headers']}")
        print(f"  params={tables['params']}")
        print(f"  data={tables['data']}")
        return session.post(
            url,
            cookies=tables["cookies"],
            headers=tables["headers"],
            params=tables["params"],
            data=tables["data"],
            timeout=60
        )

    if "Перейдите по" in text:
        url = extract_link(soup)
        print(f"[LINK] {url}")
        print(f"  cookies={tables['cookies']}")
        print(f"  headers={tables['headers']}")
        print(f"  params={tables['params']}")
        return session.get(
            url,
            cookies=tables["cookies"],
            headers=tables["headers"],
            params=tables["params"],
            timeout=60
        )

    if "Загрузите файлы" in text:
        url = extract_url(text, "Загрузите файлы")
        files = {}
        for file_name, content in tables["files"].items():
            files[file_name] = (
                file_name,
                content.encode("utf-8"),
                "application/octet-stream",
            )
        print(f"[UPLOAD] {url}")
        print(f"  files={list(files.keys())}")
        return session.post(url, files=files, timeout=60)

    print("Неизвестный тип задания")
    return None



response = session.get(BASE_URL)
step = 0
while response is not None and step < 200:
    step += 1
    new_response = solve(response)
    if new_response is None:
        break
    response = new_response
    if "Шаг #" not in response.text and "ДЗ-1" not in response.text:
        print("Задание завершено!")
        print(response.text)
        break