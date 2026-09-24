from . import render
from .framing import Framing

PREVIEW_MAX = 2048  # longest side of the preview copy; the crop uses the original


class Monitor:
    """One monitor being edited: its size, the image and how it is framed."""

    def __init__(self, output, store, model=""):
        self.name, self.width, self.height = output.name, output.width, output.height
        self.model, self.store = model, store
        self.image, saved = store.resume(self.name, output.image)
        self.framing = Framing(self.width, self.height, *render.image_size(self.image))
        if saved:
            self.framing.restore(saved)
        self.thumb = render.thumbnail(self.image, PREVIEW_MAX)
        self.applied = self.framing.key()  # what the monitor shows right now

    @property
    def touched(self):
        """True when the framing differs from what the monitor shows."""
        return self.framing.key() != self.applied

    @property
    def portrait(self):
        return self.height > self.width

    def edit(self, action):
        """Runs "mirror", "flip", "rotate" or "reset" on the framing."""
        {"mirror": lambda: self.framing.mirror(horizontal=True),
         "flip": lambda: self.framing.mirror(horizontal=False),
         "rotate": self.framing.rotate,
         "reset": self.framing.reset}[action]()

    def preview(self):
        """The thumbnail with the current mirror and rotation."""
        return render.transform(self.thumb, self.framing)

    def apply(self, daemon):
        """Crops the original image, saves the state and shows the crop on the monitor."""
        path = self.store.new_crop_path(self.name)
        render.crop(self.image, self.framing, path)
        self.store.remember(self.name, path, self.image, self.framing)
        daemon.set_image(self.name, path)
        self.applied = self.framing.key()
