import hashlib
import os
import re
import shutil

from .commands import run_reporting
from .state import DATA_DIR

# Upscayl's command-line engine, where its packages put it: the AUR package
# (upscayl-bin) links it into the PATH, the official .deb and .rpm keep it in /opt.
_PROGRAMS = ("upscayl-ncnn", "upscayl-bin", "/opt/Upscayl/resources/bin/upscayl-bin")
_MODEL_DIRS = ("/usr/share/upscayl/models", "/opt/Upscayl/resources/models")
# (model file name, name shown), best first; only the installed ones are offered.
MODELS = [
    ("upscayl-standard-4x", "Standard"),
    ("digital-art-4x", "Digital art (anime, illustration)"),
    ("upscayl-lite-4x", "Lite (fastest)"),
    ("ultrasharp-4x", "Ultrasharp"),
]
SCALES = (2, 3, 4)
# Upscayl marks the work with bare percentages on stderr, and its device banner
# and resize notes carry numbers too, so only a line that is nothing but the
# percentage counts as progress.
_TILE = re.compile(r"(\d+(?:\.\d+)?)%")
# Kept with the crops, not in ~/.cache: state.json points at them to resume.
UPSCALED_DIR = os.path.join(DATA_DIR, "upscaled")
INSTALL_HELP = (
    "Upscayl is not installed. wallframe uses its engine to upscale with AI.\n\n"
    "Arch Linux: install upscayl-bin from the AUR.\n"
    "Debian, Ubuntu, Fedora: install the .deb or .rpm from Upscayl's releases.\n"
    "The Flatpak and AppImage keep the engine inside, so wallframe cannot use them.\n\n"
    "It needs a GPU with Vulkan.")
RELEASES_URL = "https://github.com/upscayl/upscayl/releases"


class Upscaler:
    """Enlarges images with AI through Upscayl's engine."""

    def __init__(self, program, models_dir, directory=UPSCALED_DIR):
        self.program, self.models_dir, self.directory = program, models_dir, directory
        self.models = [(model, label) for model, label in MODELS
                       if os.path.exists(os.path.join(models_dir, model + ".param"))]

    def owns(self, path):
        """True for an image this upscaler made, so it is never upscaled again."""
        return os.path.dirname(os.path.abspath(path)) == os.path.abspath(self.directory)

    def upscale(self, source, model, scale, report=None):
        """Returns `source` enlarged `scale` times with `model`, made once and then reused.

        `report` gets each line of Upscayl's output as it arrives, for a progress bar.

        Raises OSError when Upscayl fails, e.g. with no Vulkan GPU.
        """
        info = os.stat(source)
        name = f"{os.path.abspath(source)}:{info.st_mtime_ns}:{info.st_size}"
        digest = hashlib.sha1(name.encode()).hexdigest()[:16]
        path = os.path.join(self.directory, f"{digest}-{model}-x{scale}.png")
        if os.path.exists(path):
            return path
        os.makedirs(self.directory, exist_ok=True)
        partial = path[:-len(".png")] + ".part.png"  # the extension picks the format
        try:
            run_reporting([self.program, "-i", source, "-o", partial, "-m", self.models_dir,
                           "-n", model, "-s", str(scale)], report)
            os.replace(partial, path)
        except OSError:
            if os.path.exists(partial):
                os.remove(partial)
            raise
        return path

    def clean(self, keep):
        """Deletes the upscaled copies not in `keep`; they are large."""
        if not os.path.isdir(self.directory):
            return
        for name in os.listdir(self.directory):
            path = os.path.join(self.directory, name)
            if path not in keep:
                os.remove(path)


def percent(line):
    """How far along an upscale is, 0 to 100, or None for a line that is not progress."""
    found = _TILE.match(line.strip())
    return float(found.group(1)) if found else None


def detect():
    """Upscayl when it is installed with at least one model, or None."""
    program = next((p for p in _PROGRAMS if shutil.which(p)), None)
    models_dir = next((d for d in _MODEL_DIRS
                       if any(os.path.exists(os.path.join(d, model + ".param"))
                              for model, _label in MODELS)), None)
    return Upscaler(program, models_dir) if program and models_dir else None
