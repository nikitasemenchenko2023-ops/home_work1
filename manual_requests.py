import re
import socket
import ssl
import uuid
from urllib.parse import urlparse, urlencode
from bs4 import BeautifulSoup, NavigableString

BASE_URL = "http://hw1.alexbers.com"
USER_COOKIE = {"user": "4b838d3fac1efe4d30f2de1e7805bd43"}


class RawHTTP:
    def __init__(self, cookies=None, timeout=60):
        self.cookies = dict(cookies or {})
        self.timeout = timeout

    def _open(self, host, port, use_ssl):
        raw = socket.create_connection((host, port), timeout=self.timeout)
        if use_ssl:
            ctx = ssl.create_default_context()
            return ctx.wrap_socket(raw, server_hostname=host)
        return raw

    def _cookie_header(self):
        if not self.cookies:
            return None
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())

    def _update_cookies(self, headers):
        for sc in headers.get("set-cookie", []):
            pair = sc.split(";", 1)[0]
            if "=" in pair:
                k, v = pair.split("=", 1)
                self.cookies[k.strip()] = v.strip()

    def _read_response(self, s):
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        head_b, _, body = data.partition(b"\r\n\r\n")
        head_text = head_b.decode("iso-8859-1", errors="replace")
        lines = head_text.split("\r\n")
        status = int(lines[0].split()[1])
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers.setdefault(k.strip().lower(), []).append(v.strip())
        return status, headers, body

    def _request(self, method, url, headers=None, body=b"", allow_redirects=True):
        u = urlparse(url)
        host = u.hostname
        port = u.port or (443 if u.scheme == "https" else 80)
        use_ssl = (u.scheme == "https")
        path = u.path or "/"
        if u.query:
            path += "?" + u.query

        headers = dict(headers or {})
        headers.setdefault("Host", host)
        headers.setdefault("User-Agent", "raw-client/1.0")
        headers.setdefault("Accept", "*/*")
        headers.setdefault("Connection", "close")
        if self.cookies:
            headers["Cookie"] = self._cookie_header()
        if body:
            headers["Content-Length"] = str(len(body))

        head = f"{method} {path} HTTP/1.1\r\n"
        head += "".join(f"{k}: {v}\r\n" for k, v in headers.items())
        head += "\r\n"
        raw = head.encode("iso-8859-1") + body

        s = self._open(host, port, use_ssl)
        s.sendall(raw)
        status, resp_headers, resp_body = self._read_response(s)
        s.close()
        self._update_cookies(resp_headers)

        if allow_redirects and status in (301, 302, 303, 307, 308):
            loc = resp_headers.get("location", [None])[0]
            if loc:
                if loc.startswith("/"):
                    loc = f"{u.scheme}://{host}{loc}"
                elif not loc.startswith("http"):
                    loc = f"{u.scheme}://{host}/{loc}"
                new_method = "GET" if status == 303 else method
                return self._request(new_method, loc, allow_redirects=True)

        return status, resp_headers, resp_body

    def get(self, url, params=None, cookies=None, headers=None):
        saved = None
        if cookies:
            saved = dict(self.cookies)
            self.cookies.update(cookies)
        if params:
            sep = "&" if "?" in url else "?"
            url += sep + urlencode(params, doseq=True)
        try:
            return self._request("GET", url, headers=headers)
        finally:
            if saved is not None:
                self.cookies = saved

    def post_form(self, url, data=None, params=None, cookies=None, headers=None):
        saved = None
        if cookies:
            saved = dict(self.cookies)
            self.cookies.update(cookies)
        if params:
            sep = "&" if "?" in url else "?"
            url += sep + urlencode(params, doseq=True)
        body = urlencode(data or {}, doseq=True).encode("ascii")
        h = dict(headers or {})
        h["Content-Type"] = "application/x-www-form-urlencoded"
        try:
            return self._request("POST", url, headers=h, body=body)
        finally:
            if saved is not None:
                self.cookies = saved

    def post_files(self, url, files: dict, fields: dict = None,
                   cookies=None, headers=None):
        saved = None
        if cookies:
            saved = dict(self.cookies)
            self.cookies.update(cookies)

        boundary = uuid.uuid4().hex
        parts = []
        for k, v in (fields or {}).items():
            parts.append(f"--{boundary}\r\n")
            parts.append(f'Content-Disposition: form-data; name="{k}"\r\n\r\n')
            parts.append(f"{v}\r\n")
        for fname, content in files.items():
            parts.append(f"--{boundary}\r\n")
            parts.append(
                f'Content-Disposition: form-data; name="{fname}"; '
                f'filename="{fname}"\r\n'
            )
            parts.append("Content-Type: application/octet-stream\r\n\r\n")
            if isinstance(content, str):
                content = content.encode("utf-8")
            parts.append(content)
            parts.append("\r\n")
        parts.append(f"--{boundary}--\r\n")
        body = b"".join(
            p if isinstance(p, bytes) else p.encode("utf-8") for p in parts
        )

        h = dict(headers or {})
        h["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        try:
            return self._request("POST", url, headers=h, body=body)
        finally:
            if saved is not None:
                self.cookies = saved


class Resp:
    def __init__(self, status, headers, body):
        self.status_code = status
        self.headers = headers
        self.content = body
        self.text = body.decode("utf-8", errors="replace")



def get_context_before_table(table, max_len=300):
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
    result = {}
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) == 2:
            key = tds[0].get_text(strip=True)
            val = tds[1].get_text(strip=True)
            result[key] = val
    return result


def classify_tables(soup):
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



client = RawHTTP(cookies=USER_COOKIE)


def solve(response):
    text = response.text
    soup = BeautifulSoup(text, "html.parser")
    print(text[:600])
    tables = classify_tables(soup)

    if "Отправьте GET-запрос" in text:
        url = extract_url(text, "Отправьте GET-запрос")
        print(f"[GET] {url}")
        print(f"  cookies={tables['cookies']}")
        print(f"  headers={tables['headers']}")
        print(f"  params={tables['params']}")
        status, headers, body = client.get(
            url,
            params=tables["params"],
            cookies=tables["cookies"],
            headers=tables["headers"],
        )
        return Resp(status, headers, body)

    if "Отправьте POST-запрос" in text:
        url = extract_url(text, "Отправьте POST-запрос")
        print(f"[POST] {url}")
        print(f"  cookies={tables['cookies']}")
        print(f"  headers={tables['headers']}")
        print(f"  params={tables['params']}")
        print(f"  data={tables['data']}")
        status, headers, body = client.post_form(
            url,
            data=tables["data"],
            params=tables["params"],
            cookies=tables["cookies"],
            headers=tables["headers"],
        )
        return Resp(status, headers, body)

    if "Перейдите по" in text:
        url = extract_link(soup)
        print(f"[LINK] {url}")
        status, headers, body = client.get(
            url,
            params=tables["params"],
            cookies=tables["cookies"],
            headers=tables["headers"],
        )
        return Resp(status, headers, body)

    if "Загрузите файлы" in text:
        url = extract_url(text, "Загрузите файлы")
        files = {}
        for fname, content in tables["files"].items():
            files[fname] = content.encode("utf-8")
        print(f"[UPLOAD] {url}")
        print(f"  files={list(files.keys())}")
        status, headers, body = client.post_files(url, files=files)
        return Resp(status, headers, body)

    print("Неизвестный тип задания")
    return None



status, headers, body = client.get(BASE_URL)
response = Resp(status, headers, body)

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