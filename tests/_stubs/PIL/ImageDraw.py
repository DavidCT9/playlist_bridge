class _Draw:
    def __init__(self, image):
        self.image = image

    def ellipse(self, box, fill=None):
        pass


def Draw(image):
    return _Draw(image)
