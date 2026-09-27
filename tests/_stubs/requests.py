"""Minimal stand-in for the `requests` package so app code can be
imported without the real dependency installed. Tests patch
`.request`/`.post` directly to control behavior and assert on the
exact call arguments made.
"""


class RequestException(Exception):
    pass


class HTTPError(RequestException):
    pass


class Response:
    def __init__(self, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.text = text if text else ("{}" if json_data is not None else "")
        self.headers = headers or {}

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise HTTPError(f"{self.status_code} error")


def request(method, url, headers=None, timeout=None, **kwargs):
    raise NotImplementedError("requests.request should be patched by the test")


def post(url, data=None, timeout=None, **kwargs):
    raise NotImplementedError("requests.post should be patched by the test")


class _Utils:
    @staticmethod
    def quote(s, *a, **kw):
        import urllib.parse
        return urllib.parse.quote(s)


utils = _Utils()
