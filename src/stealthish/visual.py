"""Viewport observations and native-input coordinate mapping."""
import math
import secrets
import struct

from .errors import StealthishError

GEOMETRY = """() => ({width:innerWidth,height:innerHeight,x:scrollX,y:scrollY,
    visual:visualViewport ? [visualViewport.offsetLeft,visualViewport.offsetTop,
                            visualViewport.width,visualViewport.height,visualViewport.scale] : null})"""


def number(value):
    return type(value) in {int, float} and math.isfinite(value)


class Observations:
    def __init__(self):
        self.values = {}
        self.generations = {}

    def invalidate(self, tab):
        self.values.pop(tab, None)
        self.generations[tab] = self.generations.get(tab, 0) + 1

    def forget(self, tab):
        self.values.pop(tab, None)
        self.generations.pop(tab, None)

    async def capture(self, tab, page, directory, *, full=False, clip=None):
        if type(full) is not bool or (full and clip is not None):
            raise StealthishError("INVALID_REQUEST")
        self.invalidate(tab)
        generation = self.generations[tab]
        geometry = await page.evaluate(GEOMETRY)
        rect = {"x": 0, "y": 0, "width": geometry["width"], "height": geometry["height"]}
        if clip is not None:
            if not isinstance(clip, dict) or set(clip) != set(rect) or \
                    not all(number(value) for value in clip.values()):
                raise StealthishError("INVALID_REQUEST")
            if clip["x"] < 0 or clip["y"] < 0 or clip["width"] <= 0 or clip["height"] <= 0 or \
                    clip["x"] + clip["width"] > rect["width"] or \
                    clip["y"] + clip["height"] > rect["height"]:
                raise StealthishError("INVALID_REQUEST")
            rect = clip.copy()
        options = {"full_page": full, "scale": "css", "animations": "allow", "caret": "initial",
                   "type": "png", "timeout": 10000}
        if clip is not None:
            options["clip"] = {**rect, "x": rect["x"] + geometry["x"],
                               "y": rect["y"] + geometry["y"]}
        png = await page.screenshot(**options)
        if self.generations.get(tab) != generation or await page.evaluate(GEOMETRY) != geometry:
            raise StealthishError("STALE_IMAGE")
        width, height = struct.unpack(">II", png[16:24])
        image_id = secrets.token_hex(16) if not full else None
        path = directory / (secrets.token_hex(16) + ".png")
        with path.open("xb") as output:
            path.chmod(0o600)
            output.write(png)
        image = {"path": str(path), "format": "png", "mimeType": "image/png",
                 "imageId": image_id, "width": width, "height": height,
                 "coordinateSpace": "image", "viewportRect": rect if not full else None,
                 "fullPage": full}
        if image_id:
            self.values[tab] = {"image": image, "geometry": geometry, "generation": generation}
        return image

    async def validate(self, tab, page, image_id):
        record = self.values.get(tab)
        if not isinstance(image_id, str) or not record or record["image"]["imageId"] != image_id:
            raise StealthishError("STALE_IMAGE")
        if await page.evaluate(GEOMETRY) != record["geometry"] or \
                self.generations.get(tab) != record["generation"]:
            self.invalidate(tab)
            raise StealthishError("STALE_IMAGE")
        return record["image"]

    async def point(self, tab, page, image_id, x, y):
        image = await self.validate(tab, page, image_id)
        if not number(x) or not number(y) or not 0 <= x < image["width"] or not 0 <= y < image["height"]:
            raise StealthishError("INVALID_REQUEST")
        rect = image["viewportRect"]
        return (rect["x"] + x * rect["width"] / image["width"],
                rect["y"] + y * rect["height"] / image["height"])
