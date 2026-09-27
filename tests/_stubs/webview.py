"""Minimal stand-in for `pywebview` -- import-safety only. main.py's
run() is an entry point that blocks on a real GUI event loop and isn't
exercised by the unit tests; this just lets the module be imported (and
its non-run() top-level code checked) without the real dependency."""


class _EventSlot:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, fn):
        self.handlers.append(fn)
        return self


class _Events:
    def __init__(self):
        self.closing = _EventSlot()
        self.shown = _EventSlot()


class Window:
    def __init__(self, *a, **kw):
        self.events = _Events()

    def show(self):
        pass

    def hide(self):
        pass

    def destroy(self):
        pass


def create_window(*a, **kw):
    return Window()


def start(*a, **kw):
    pass
