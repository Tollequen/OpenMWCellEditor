"""Draws the editor's logo, web icons and app icons (python3 packaging/make_icons.py; needs Pillow)."""
import io
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "celleditor", "web")

GOLD_TOP, GOLD_BOTTOM, GOLD_EDGE = "#e2c27f", "#a9843f", "#5e4520"
PLATE_TOP, PLATE_BOTTOM = "#2b2118", "#120d09"
CX = CY = 512


def cog(small):
    """The cog's measures in a 1024 frame: a toothed ring."""
    if small:
        return dict(teeth=8, outer=392, root=326, inner=170, groove=0)
    return dict(teeth=10, outer=352, root=300, inner=168, groove=0)


def teeth_outline(c):
    """The toothed rim as a polygon."""
    pts, n = [], c["teeth"]
    step = 2 * math.pi / n
    for i in range(n):
        a = i * step - math.pi / 2
        for ang, r in ((a - step * 0.30, c["root"]), (a - step * 0.20, c["outer"]),
                       (a + step * 0.20, c["outer"]), (a + step * 0.30, c["root"])):
            pts.append((CX + r * math.cos(ang), CY + r * math.sin(ang)))
    return pts


def plate_of(small):
    return (40, 40, 944, 212) if small else (100, 100, 824, 186)      # x, y, size, corner radius


def svg(small, plate=True):
    c = cog(small)
    p = lambda pts: " ".join("%.1f,%.1f" % q for q in pts)
    circle = lambda r: "M%.1f,%.1f a%.1f,%.1f 0 1,0 %.1f,0 a%.1f,%.1f 0 1,0 %.1f,0z" % (CX - r, CY, r, r, 2 * r, r, r, -2 * r)
    box = "0 0 1024 1024" if plate else "%d %d %d %d" % (CX - c["outer"] - 8, CY - c["outer"] - 8,
                                                        2 * c["outer"] + 16, 2 * c["outer"] + 16)
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="%s">' % box,
             '<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="%s"/>'
             '<stop offset="1" stop-color="%s"/></linearGradient>' % (PLATE_TOP, PLATE_BOTTOM),
             '<linearGradient id="gold" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="%s"/>'
             '<stop offset="1" stop-color="%s"/></linearGradient></defs>' % (GOLD_TOP, GOLD_BOTTOM)]
    if plate:
        x, y, size, r = plate_of(small)
        parts.append('<rect x="%d" y="%d" width="%d" height="%d" rx="%d" fill="url(#bg)"/>' % (x, y, size, size, r))
        parts.append('<rect x="%.1f" y="%.1f" width="%d" height="%d" rx="%.1f" fill="none" stroke="#fff" '
                     'stroke-opacity=".07" stroke-width="3"/>' % (x + .5, y + .5, size - 1, size - 1, r - .5))
    edge = 10 if small else 8
    gear = "M" + p(teeth_outline(c)).replace(" ", " L") + "z " + circle(c["inner"])
    parts.append('<path d="%s" fill="url(#gold)" fill-rule="evenodd" stroke="%s" stroke-width="%d" stroke-linejoin="round"/>'
                 % (gear, GOLD_EDGE, edge))
    if c["groove"]:
        parts.append('<circle cx="%d" cy="%d" r="%d" fill="none" stroke="%s" stroke-opacity=".55" stroke-width="6"/>'
                     % (CX, CY, c["groove"], GOLD_EDGE))
    parts.append("</svg>")
    return "".join(parts)


def png(size, small, plate=True):
    """The picture at size x size pixels, drawn 4x larger and scaled down."""
    from PIL import Image, ImageDraw
    c = cog(small)
    S = 4 * size / 1024.0
    big = 4 * size
    P = lambda pts: [(x * S, y * S) for x, y in pts]
    hexc = lambda h, a=255: tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)) + (a,)

    def gradient(y0, y1, c0, c1):
        g = Image.new("RGBA", (big, big))
        d = ImageDraw.Draw(g)
        a, b = hexc(c0), hexc(c1)
        for yy in range(big):
            t = min(1, max(0, (yy - y0 * S) / max(1, (y1 - y0) * S)))
            d.line([(0, yy), (big, yy)], fill=tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(4)))
        return g

    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    if plate:
        x, y, w, r = plate_of(small)
        mask = Image.new("L", (big, big), 0)
        ImageDraw.Draw(mask).rounded_rectangle([x * S, y * S, (x + w) * S, (y + w) * S], r * S, fill=255)
        img.paste(gradient(y, y + w, PLATE_TOP, PLATE_BOTTOM), (0, 0), mask)
        ImageDraw.Draw(img).rounded_rectangle([x * S, y * S, (x + w) * S, (y + w) * S], r * S,
                                              outline=(255, 255, 255, 18), width=max(1, int(3 * S)))
    shape = Image.new("L", (big, big), 0)
    d = ImageDraw.Draw(shape)
    d.polygon(P(teeth_outline(c)), fill=255)
    ri = c["inner"] * S
    d.ellipse([CX * S - ri, CY * S - ri, CX * S + ri, CY * S + ri], fill=0)
    from PIL import ImageFilter
    edge = max(1, int((10 if small else 8) * S / 2)) * 2 + 1
    grown = shape.filter(ImageFilter.MaxFilter(edge))
    img.paste(Image.new("RGBA", (big, big), hexc(GOLD_EDGE)), (0, 0), grown)
    img.paste(gradient(CY - c["outer"], CY + c["outer"], GOLD_TOP, GOLD_BOTTOM), (0, 0), shape)
    dd = ImageDraw.Draw(img)
    if c["groove"]:
        rg = c["groove"] * S
        dd.ellipse([CX * S - rg, CY * S - rg, CX * S + rg, CY * S + rg], outline=hexc(GOLD_EDGE, 140), width=int(6 * S))
    if not plate:
        m = (CX - c["outer"] - 8) * S
        img = img.crop((int(m), int(m), int(big - m), int(big - m)))
    return img.resize((size, size), Image.LANCZOS)


def ico(path, images):
    """A Windows .ico with PNG images inside."""
    blobs = []
    for im in images:
        b = io.BytesIO()
        im.save(b, "PNG")
        blobs.append((im.size[0], b.getvalue()))
    offset = 6 + 16 * len(blobs)
    entries, data = b"", b""
    for size, blob in blobs:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(blob), offset + len(data))
        data += blob
    with open(path, "wb") as f:
        f.write(struct.pack("<HHH", 0, 1, len(blobs)) + entries + data)


def main():
    for name, small, plate in (("icon.svg", False, True), ("icon-small.svg", True, True), ("logo.svg", True, False)):
        with open(os.path.join(WEB, name), "w") as f:
            f.write(svg(small, plate))
    try:
        import PIL  # noqa: F401
    except ImportError:
        sys.exit("Wrote the SVGs. The PNGs and app icons need Pillow: pip install pillow")
    small = lambda n: n <= 64
    png(32, True).save(os.path.join(WEB, "favicon.png"))
    png(180, False).save(os.path.join(WEB, "apple-touch-icon.png"))
    for n in (192, 512):
        png(n, False).save(os.path.join(WEB, "icon-%d.png" % n))
    ico(os.path.join(ROOT, "packaging", "icon.ico"), [png(n, small(n)) for n in (16, 24, 32, 48, 64, 128, 256)])
    if shutil.which("iconutil"):
        d = tempfile.mkdtemp()
        iconset = os.path.join(d, "icon.iconset")
        os.mkdir(iconset)
        for n in (16, 32, 128, 256, 512):
            png(n, small(n)).save(os.path.join(iconset, "icon_%dx%d.png" % (n, n)))
            png(2 * n, small(2 * n)).save(os.path.join(iconset, "icon_%dx%d@2x.png" % (n, n)))
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", os.path.join(ROOT, "packaging", "icon.icns")], check=True)
        shutil.rmtree(d)
    else:
        print("iconutil not found (not macOS): icon.icns not made")
    print("Icons written.")


if __name__ == "__main__":
    main()
