class Image:
    def __init__(self, mode, size):
        self.mode = mode
        self.size = size


def new(mode, size, color=None):
    return Image(mode, size)
