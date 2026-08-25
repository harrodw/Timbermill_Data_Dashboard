"""Resize + EXIF-strip camera photos into docs/media/photos/.

Every output is rebuilt pixel-by-pixel into a fresh Image object, so no
EXIF/IPTC/XMP block from the source can survive into the published file.
Camera traps can embed GPS and device serials; this study is on private
industrial forest land, so stripping is a hard requirement.
"""
import os
from PIL import Image

REPO = "/home/will/NCSU/Claude_Science/2026_Sensor_Dashboard"
PHOTO_OUT = os.path.join(REPO, "docs", "media", "photos")

THUMB_W, DISPLAY_W = 400, 1200
THUMB_Q, DISPLAY_Q = 78, 82

# slug -> (source subdir, source filename)
SOURCES = {
    # parallel cameras (tree-mounted, mid/large mammals)
    "bear_cubs":         ("CT_photos", "bear_cubs.jpg"),
    "bobcat":            ("CT_photos", "bobcat.jpg"),
    "coyote":            ("CT_photos", "coyote.jpg"),
    "gartersnake":       ("CT_photos", "gartersnake.jpg"),
    # AHDriFT bucket traps (reptiles, amphibians, small mammals)
    "bear_bucket":       ("AHDriFT_Photos", "bear_bucket.jpg"),
    "bear_paw":          ("AHDriFT_Photos", "bear_paw.jpg"),
    "box_turtle_bucket": ("AHDriFT_Photos", "box_turtle_bucket.jpg"),
    "broadhead_skink":   ("AHDriFT_Photos", "broadhead_skink.jpg"),
    "possum_bucket":     ("AHDriFT_Photos", "possum_bucket.jpg"),
    "racer":             ("AHDriFT_Photos", "racer.jpg"),
    "raccoon_bucket":    ("AHDriFT_Photos", "racoon_bucket.jpg"),  # slug spelling fixed
    "spotted_turtle":    ("AHDriFT_Photos", "Spottie!.jpg"),   # punctuation removed
}

METADATA_KEYS = ("exif", "icc_profile", "photoshop", "adobe", "xmp",
                 "comment", "dpi", "iptc", "adobe_transform")


def _clean_copy(im):
    """Return a new RGB image carrying pixels only - no info dict."""
    out = Image.new("RGB", im.size)
    out.putdata(list(im.convert("RGB").getdata()))
    return out


def process(slug, subdir, fname, outdir=PHOTO_OUT):
    src = os.path.join(REPO, "raw_data", subdir, fname)
    with Image.open(src) as raw:
        had_exif = bool(raw.getexif()) or "exif" in raw.info
        src_size = raw.size
        clean = _clean_copy(raw)

    written = {}
    for kind, width, q in (("thumb", THUMB_W, THUMB_Q),
                           ("display", DISPLAY_W, DISPLAY_Q)):
        w = min(width, clean.size[0])
        h = round(clean.size[1] * w / clean.size[0])
        im = clean.resize((w, h), Image.LANCZOS)
        path = os.path.join(outdir, f"{slug}_{kind}.jpg")
        # no exif= kwarg -> Pillow writes none; optimize strips the rest
        im.save(path, "JPEG", quality=q, optimize=True, progressive=True)
        written[kind] = dict(path=path, size=(w, h),
                             kb=round(os.path.getsize(path) / 1024, 1))
    return dict(slug=slug, src=fname, src_size=src_size,
                src_had_exif=had_exif, **written)


def verify(path):
    """Re-read an output and report any residual metadata."""
    with Image.open(path) as im:
        exif = im.getexif()
        residual = {k: v for k, v in im.info.items() if k in METADATA_KEYS}
        return dict(path=os.path.basename(path),
                    n_exif_tags=len(exif),
                    gps=bool(exif.get_ifd(0x8825)) if exif else False,
                    residual_keys=sorted(residual),
                    clean=(len(exif) == 0 and not residual))
