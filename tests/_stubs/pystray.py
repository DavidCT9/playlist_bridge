"""Minimal stand-in for `pystray` -- import-safety only."""


class MenuItem:
    def __init__(self, text, action, default=False, checked=None):
        self.text = text
        self.action = action
        self.default = default
        self.checked = checked


class Menu:
    def __init__(self, *items):
        self.items = items


class Icon:
    def __init__(self, name, icon=None, title=None, menu=None):
        self.name = name
        self.icon = icon
        self.title = title
        self.menu = menu

    def run(self):
        pass

    def run_detached(self):
        pass

    def stop(self):
        pass
