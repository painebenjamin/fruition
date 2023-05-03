import os
import re
import subprocess

from typing import Optional, Any
from pibble.util.strings import decode
from pibble.util.log import logger

try:
    from PIL import ImageChops, Image
except ImportError:
    logger.warning(
        "Cannot import imaging libraries. Make sure to install with the [imaging] option selected if imaging functionality is required."
    )
    raise

from pibble.util.helpers import find_executable
from pibble.util.files import TempfileContext

video_extensions = [".mov", ".mp4", ".flv", ".gif", ".webm"]
audio_extensions = [
    ".aiv",
    ".aiff",
    ".au",
    ".snd",
    ".iff",
    ".mp2",
    ".ra",
    ".sf",
    ".smp",
    ".voc",
    ".wve",
    ".mod",
    ".nst",
    ".wav",
    ".mp3",
]
document_extensions = [
    ".doc",
    ".docx",
    ".dot",
    ".xls",
    ".xlsx",
    ".xlw",
    ".xlt",
    ".ppt",
    ".pptx",
    ".odf",
    ".odt",
    ".fodt",
    ".ods",
    ".fods",
    ".odp",
    ".fodp",
    ".odg",
    ".fodp",
    ".txt",
    ".csv",
]
browser_extensions = [".html", ".htm"]
image_extensions = [
    ".jpg",
    ".jpeg",
    ".bmp",
    ".eps",
    ".ico",
    ".png",
    ".tga",
    ".tiff",
    ".webp",
    ".xbm",
    ".xpm",
]
non_alpha_image_extensions = [".jpg", ".jpeg", ".bmp", ".ico"]
special_extensions = [".psd", ".pdf"]
has_protocol_regex = re.compile(r"^.+://.+$")


def CallProcess(*args: Any, **kwargs: Any) -> str:
    """
    Calls a subprocess() and then calls communicate(), effectively
    making this method a synchronous subprocess call.
    """
    logger.debug(f"Calling subprocess with args {args}, kwargs {kwargs}.")
    p = subprocess.Popen(*args, **kwargs)
    out, err = p.communicate()
    if p.returncode != 0:
        raise Exception(err)
    return str(decode(out))


def TrimImage(image: Image.Image) -> Image.Image:
    """
    Trims an image - i.e., removes empty background space around the 'content'
    of the image.

    In practice, this takes the top-left pixel and assumes this is the color of the
    background. It will then generate an image that is the same size as the input
    image, filled entirely with the background color. It then takes the difference
    of the two images, which would represent all non-background pixels. We take
    the bounding box of that resulting image chop, and slice that out of the original
    image.
    """
    background = Image.new(image.mode, image.size, image.getpixel((0, 0)))
    difference = ImageChops.difference(image, background)
    difference = ImageChops.add(difference, difference)
    bounding_box = difference.getbbox()
    if bounding_box:
        return image.crop(bounding_box)
    return image


class ThumbnailBuilder:
    """
    This class, once instantiated at runtime, will find all the necessary binaries for
    various file types. You can then use the builder to take any file and make
    an image of that input.

    :param filename str: The filename to build an image from. Supports audio, video,
        common productivity document formats, web formats, and image formats. Also
        supports photoshop uses PSDFile.
    """

    EXECUTABLES = ["ffmpeg", "libreoffice", "chromedriver"]

    ffmpeg: Optional[str]
    libreoffice: Optional[str]
    chromedriver: Optional[str]

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.ffmpeg = None
        self.libreoffice = None
        self.chromedriver = None
        self._find_executables("ffmpeg", "libreoffice", "chromedriver")

    def build(
        self, output: str, width: int, height: int, trim: Optional[bool] = False
    ) -> Image.Image:
        """
        The primary entry point, will make sure that executables are found when
        needed, and will return the image.
        """
        basename, ext = os.path.splitext(self.filename)
        if ext in video_extensions:
            if not self.ffmpeg:
                raise ImportError("Cannot process video - ffmpeg not found on path.")
            result = self._build_video(output, width, height)
        elif ext in audio_extensions:
            if not self.ffmpeg:
                raise ImportError("Cannot process audio - ffmpeg not found on path.")
            result = self._build_audio(output, width, height)
        elif ext in document_extensions:
            if not self.libreoffice:
                raise ImportError(
                    "Cannot process office documents - libreoffice not found on path."
                )
            elif not self.chromedriver:
                raise ImportError(
                    "Cannot process office documents - chromedriver not found on path."
                )
            result = self._build_document(output, width, height)
        elif ext in browser_extensions:
            if not self.chromedriver:
                raise ImportError(
                    "Cannot process browser documents - chromedriver not found on path."
                )
            result = self._build_browser(output, width, height)
        elif ext in image_extensions:
            result = self._build_image(output, width, height)
        elif ext in special_extensions:
            if ext == ".psd":
                result = self._build_psd(output, width, height)
            elif ext == ".pdf":
                result = self._build_pdf(output, width, height)
        else:
            raise ValueError("Unknown file extension '{0}'.".format(ext))
        if result and trim:
            if ext in video_extensions:
                logger.warning("Cannot trim video thumbnails.")
            else:
                logger.debug("Trimming image.")
                TrimImage(result).save(output)
        return result

    def _find_executables(self, *executables: str) -> None:
        """
        Looks for the sub-executables necessary for some thumbnail generation.
        """
        for executable in executables:
            try:
                setattr(self, executable, find_executable(executable))
            except ImportError:
                setattr(self, executable, None)

    def _build_video(self, output: str, width: int, height: int) -> Image.Image:
        logger.debug(f"Building video thumbnail from {self.filename} to {output}")
        CallProcess(
            [
                self.ffmpeg,
                "-i",
                self.filename,
                "-r",
                "1",
                "-vf",
                f"setpts=PTS/1, scale={width}:-1",
                "-an",
                "-crf",
                "30",
                output,
            ]
        )
        return Image.open(output)

    def _build_audio(self, output: str, width: int, height: int) -> Image.Image:
        logger.debug(f"Building audio thumbnail from {self.filename} to {output}")
        CallProcess(
            [
                self.ffmpeg,
                "-i",
                self.filename,
                f"showwavespic=s={width}x{height}",
                output,
            ]
        )
        return Image.open(output)

    def _build_document(self, output: str, width: int, height: int) -> Image.Image:
        logger.debug(f"Building document thumbnail from {self.filename} to {output}")
        tempfiles = TempfileContext()
        with tempfiles as generator:
            CallProcess(
                [
                    self.libreoffice,
                    "--headless",
                    "--invisible",
                    "--convert-to",
                    "pdf",
                    self.filename,
                    "--outdir",
                    tempfiles.directory,
                ]
            )
            output_file = "{0}.pdf".format(
                os.path.splitext(os.path.basename(self.filename))[0]
            )
            return ThumbnailBuilder(
                os.path.join(tempfiles.directory, output_file)
            ).build(output, width, height)

    def _build_browser(self, output: str, width: int, height: int) -> Image.Image:
        from pibble.web.scraper import WebScraper

        logger.debug(f"Building browser thumbnail from {self.filename} to {output}")
        tempfiles = TempfileContext()
        with tempfiles as generator:
            screenshot = tempfiles.touch("screenshot.png")
            with WebScraper(1920, 1080) as scraper:
                if not has_protocol_regex.match(self.filename):
                    path = "file://{0}".format(os.path.abspath(self.filename))
                else:
                    path = self.filename
                scraper.get(path)
                scraper.save_screenshot(screenshot)
                return ThumbnailBuilder(screenshot).build(output, width, height)

    def _build_pdf(self, output: str, width: int, height: int) -> Image.Image:
        logger.debug(f"Building PDF thumbnail from {self.filename} to {output}")
        from pdf2image import convert_from_path

        tempfiles = TempfileContext()
        with tempfiles as generator:
            images_from_path = convert_from_path(
                self.filename, output_folder=tempfiles.directory
            )
            page_1 = images_from_path[0]
            page_1.thumbnail((width, height))
            page_1.save(output)
        return page_1

    def _build_psd(self, output: str, width: int, height: int) -> Image.Image:
        from psd_tools import PSDImage

        logger.debug(f"Building PSD thumbnail from {self.filename} to {output}")
        psd = PSDImage.open(self.filename)
        image = psd.composite()
        image.thumbnail((width, height))
        image.save(output)
        return image

    def _build_image(self, output: str, width: int, height: int) -> Image.Image:
        logger.debug(f"Building image thumbnail from {self.filename} to {output}")
        basename, ext = os.path.splitext(output)

        image = Image.open(self.filename)
        image.thumbnail((width, height))

        if ext in non_alpha_image_extensions and (
            image.mode in ("RGBA", "LA")
            or (image.mode == "P" and "transparency" in image.info)
        ):
            background = Image.new("RGBA", image.size, (255, 255, 255))
            alpha_composite = Image.alpha_composite(background, image)
            alpha_composite.convert("RGB").save(output)
            return alpha_composite
        else:
            image.save(output)
            return image
