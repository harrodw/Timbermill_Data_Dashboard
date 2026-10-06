"""Resize + EXIF-strip camera photos into docs/media/photos/.

Every output is rebuilt pixel-by-pixel into a fresh Image object, so no
EXIF/IPTC/XMP block from the source can survive into the published file.
Camera traps can embed GPS and device serials; this study is on private
industrial forest land, so stripping is a hard requirement.

The reptile and amphibian photographs are filed one directory per taxon under
``data/AHDriFT_Photos/``, with Wildlife Insights export filenames that carry
the image UUID. That UUID is the join key into
``data/WI_Download/images_2011183.csv``, so every published caption's species,
plot and timestamp comes from the Wildlife Insights identification rather than
from the directory name. This matters: one file filed under ``T.saurita/`` is
identified in Wildlife Insights as a common gartersnake (*Thamnophis
sirtalis*), not a ribbon snake, and the album follows the identification.

``PICKS`` names the one photograph published per taxon. The selection is
editorial -- the clearest view of the animal -- and is recorded here by
filename so a rebuild publishes the same album.

Run:  python build/make_photos.py
"""
import csv
import json
import os
import re
from PIL import Image

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "data")
PHOTO_OUT = os.path.join(REPO, "docs", "media", "photos")
WI_IMAGES = os.path.join(DATA, "WI_Download", "images_2011183.csv")
SELECTION_JSON = os.path.join(REPO, "build", "photo_selection.json")

THUMB_W, DISPLAY_W = 400, 1200
THUMB_Q, DISPLAY_Q = 78, 82

UUID_RE = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")

# ---------------------------------------------------------------------------
# What gets published. slug -> source path relative to data/.
#
# The reptile and amphibian entries are one photograph per taxon, chosen for
# how clearly the animal reads at album size. The mammal entries are the
# frames the album already carried and are NOT one-per-taxon: black bear keeps
# three, because a bear filling a bucket mouth and a sow with cubs crossing a
# thinned stand are different photographs of different things.
# ---------------------------------------------------------------------------
PICKS = {
    # ---- parallel cameras (tree-mounted, mid/large mammals) ----
    "bear_cubs": "CT_photos/bear_cubs.jpg",
    "bobcat": "CT_photos/bobcat.jpg",
    "coyote": "CT_photos/coyote.jpg",

    # ---- AHDriFT bucket cameras: mammals ----
    "bear_bucket": "AHDriFT_Photos/bear_bucket.jpg",
    "bear_paw": "AHDriFT_Photos/bear_paw.jpg",

    # ---- AHDriFT bucket cameras: reptiles ----
    "broadhead_skink":
        "AHDriFT_Photos/P.laticeps/"
        "deployment_2491397_prod_directUpload_"
        "ca59ccbc-3986-4ff5-81e6-ab24abe3aef0.jpeg",
    "common_box_turtle":
        "AHDriFT_Photos/T.carolinensis/"
        "deployment_2492053_prod_directUpload_"
        "ce5e0c2f-c743-4a28-9c55-65df3ca4f79e.jpeg",
    "common_gartersnake":
        "AHDriFT_Photos/T.saurita/"
        "deployment_2500499_prod_directUpload_"
        "ff72bf3c-32f6-451d-b8a4-b71dfdcfeb58.jpg",
    "common_kingsnake":
        "AHDriFT_Photos/L.getula/"
        "deployment_2492047_prod_directUpload_"
        "a8714185-4490-4eb7-9d6b-566f2bec519f.jpeg",
    "dekays_brownsnake":
        "AHDriFT_Photos/S.dekayi/"
        "deployment_2502930_prod_directUpload_"
        "6dd108af-bec0-4e45-9833-471b5eab3d93.jpeg",
    "eastern_racer":
        "AHDriFT_Photos/C.constrictor/"
        "deployment_2492047_prod_directUpload_"
        "987d039c-afe0-4198-bb16-4ae05dba5478.jpeg",
    "eastern_rat_snake":
        "AHDriFT_Photos/P.alleghaniensis/"
        "deployment_2492053_prod_directUpload_"
        "4f08cc35-c068-4ce3-8341-faf4faabe5a9.jpeg",
    "eastern_ribbon_snake":
        "AHDriFT_Photos/T.saurita/"
        "deployment_2505381_prod_directUpload_"
        "7b3c81f5-22b6-40b9-8225-a96dc6e5965e.jpg",
    "little_brown_skink":
        "AHDriFT_Photos/S.lateralis/"
        "deployment_2492053_prod_directUpload_"
        "928df7b4-12f4-4088-ab2a-b6f486e7888b.jpeg",
    "northern_copperhead":
        "AHDriFT_Photos/A.contortrix/"
        "deployment_2502808_prod_directUpload_"
        "ad382299-5675-4809-bb0d-9e24653ed652.jpg",
    "northern_cottonmouth":
        "AHDriFT_Photos/A.piscivorus/"
        "deployment_2491993_prod_directUpload_"
        "e8106aef-f034-40b3-89d4-afe978224ddf.jpeg",
    "plain_bellied_watersnake":
        "AHDriFT_Photos/N.erythrogaster/"
        "deployment_2492814_prod_directUpload_"
        "66e2b077-1018-4f6c-bae1-735d433570a5.jpeg",
    "plestiodon_species":
        "AHDriFT_Photos/Plestiodon.sp./"
        "deployment_2505391_prod_directUpload_"
        "d593d9c7-50a9-4926-a0c6-a1cd1b48c1e5.jpg",
    "ring_necked_snake":
        "AHDriFT_Photos/D.punctatus/"
        "deployment_2492053_prod_directUpload_"
        "9d5718d4-f15c-447d-a8a3-5c47342cf15f.jpeg",
    "timber_rattlesnake":
        "AHDriFT_Photos/C.horridas/"
        "deployment_2491397_prod_directUpload_"
        "1920fa0c-f54b-441c-ba19-221f0972e265.jpeg",
    "unidentified_snake":
        "AHDriFT_Photos/Mystery.Snakes/"
        "deployment_2502930_prod_directUpload_"
        "ca216b07-2948-4313-acbd-79928dec0c90.jpeg",
    "worm_snake":
        "AHDriFT_Photos/C.amoenus/"
        "deployment_2502821_prod_directUpload_"
        "8431db05-53c9-4164-b659-f9e6a5f1dc9f.jpeg",
    "spotted_turtle": "AHDriFT_Photos/Spotted_turtle.jpg",

    # ---- AHDriFT bucket cameras: amphibians ----
    "eastern_narrowmouth_toad":
        "AHDriFT_Photos/G.carolinensis/"
        "deployment_2502811_prod_directUpload_"
        "ceabb2fa-2f1d-441d-bb8a-69befbd27a05.jpeg",
    "salamander_species":
        "AHDriFT_Photos/Caudatans/"
        "deployment_2500817_prod_directUpload_"
        "8ba49eb0-f912-449b-8d1f-6d8a66f578b3.jpeg",
    "southern_leopard_frog":
        "AHDriFT_Photos/L.sphenocephalus/"
        "deployment_2500416_prod_directUpload_"
        "8b1edf63-a8f5-499c-b9db-e14d5344f9bd.jpg",
    "southern_toad":
        "AHDriFT_Photos/A.terestris/"
        "deployment_2505421_prod_directUpload_"
        "34fbcf72-e474-4bdb-aae0-e321108b0d8f.jpeg",
}

# Photographs with no Wildlife Insights image record to join against: the four
# originals the researcher exported by hand. Their identification is the
# researcher's own and is recorded as such, never as a Wildlife Insights ID.
MANUAL_IDS = {
    "bear_cubs": ("American Black Bear", "Ursus americanus", "Mammalia"),
    "bobcat": ("Bobcat", "Lynx rufus", "Mammalia"),
    "coyote": ("Coyote", "Canis latrans", "Mammalia"),
    "bear_bucket": ("American Black Bear", "Ursus americanus", "Mammalia"),
    "bear_paw": ("American Black Bear", "Ursus americanus", "Mammalia"),
    "spotted_turtle": ("Spotted Turtle", "Clemmys guttata", "Reptilia"),
}

METADATA_KEYS = ("exif", "icc_profile", "photoshop", "adobe", "xmp",
                 "comment", "dpi", "iptc", "adobe_transform")

# Wildlife Insights labels that read badly as a gallery caption. The stored
# identification is unchanged; only the displayed wording is.
DISPLAY_NAMES = {
    "Lizards and Snakes": "Unidentified snake",
    "Salamander species": "Salamander",
    "ring-necked snake": "Ring-necked Snake",
    "Plestiodon Species": "Plestiodon skink",
}


# ---------------------------------------------------------------------------
# Wildlife Insights join
# ---------------------------------------------------------------------------
def load_wi_images(uuids):
    """image_id -> identification, for the UUIDs we actually publish."""
    want = set(uuids)
    out = {}
    with open(WI_IMAGES, newline="") as fh:
        for row in csv.DictReader(fh):
            if row["image_id"] in want:
                genus = (row.get("genus") or "").strip()
                species = (row.get("species") or "").strip()
                # A row identified only to genus gets "Genus sp.", not a bare
                # genus that reads as a binomial with the epithet missing.
                if genus and species:
                    latin = f"{genus} {species}"
                elif genus:
                    latin = f"{genus} sp."
                else:
                    latin = None
                out[row["image_id"]] = dict(
                    common_name=(row.get("common_name") or "").strip() or None,
                    latin_name=latin,
                    taxon_class=(row.get("class") or "").strip() or None,
                    order=(row.get("order") or "").strip() or None,
                    deployment_id=(row.get("deployment_id") or "").strip(),
                    timestamp=(row.get("timestamp") or "").strip() or None,
                )
    return out


def plot_of(deployment_id):
    m = re.match(r"([A-Za-z]{2}\d+)", str(deployment_id))
    return m.group(1).upper() if m else None


def schedule_of(deployment_id):
    """AHDriFT cameras log a motion-capture and a time-lapse schedule."""
    d = str(deployment_id).upper()
    if d.endswith("_MC"):
        return "motion capture"
    if d.endswith("_TL"):
        return "time lapse"
    return None


# ---------------------------------------------------------------------------
# Image processing
# ---------------------------------------------------------------------------
def _clean_copy(im):
    """Return a new RGB image carrying pixels only - no info dict."""
    out = Image.new("RGB", im.size)
    out.putdata(list(im.convert("RGB").getdata()))
    return out


def process(slug, rel_path, outdir=PHOTO_OUT):
    src = os.path.join(DATA, rel_path)
    with Image.open(src) as raw:
        had_exif = bool(raw.getexif()) or "exif" in raw.info
        src_size = raw.size
        clean = _clean_copy(raw)

    os.makedirs(outdir, exist_ok=True)
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
    return dict(slug=slug, src=rel_path, src_size=src_size,
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


def discover_all():
    """Every candidate photograph on disk, so coverage can be reported."""
    found = []
    for root in ("AHDriFT_Photos", "CT_photos"):
        base = os.path.join(DATA, root)
        for dirpath, _dirs, files in os.walk(base):
            for f in sorted(files):
                if not f.lower().endswith((".jpg", ".jpeg", ".png")):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, f), DATA)
                m = UUID_RE.search(f)
                found.append(dict(rel=rel, uuid=m.group(1) if m else None))
    return found


def resolve_picks(all_found):
    """Map each pick to the path that is actually on disk.

    Several taxon directories carry a trailing space in their name
    (``A.terestris/``), which is invisible in a listing and easy to lose in a
    copied path. Filenames are UUID-based and unique across the tree, so a
    pick is resolved by basename when its literal path does not exist, and
    the real path is what gets recorded.
    """
    by_base = {}
    for f in all_found:
        by_base.setdefault(os.path.basename(f["rel"]), []).append(f["rel"])

    resolved, problems = {}, []
    for slug, rel in PICKS.items():
        if os.path.exists(os.path.join(DATA, rel)):
            resolved[slug] = rel
            continue
        hits = by_base.get(os.path.basename(rel), [])
        if len(hits) == 1:
            resolved[slug] = hits[0]
        elif not hits:
            problems.append(f"{slug}: not found -- {rel}")
        else:
            problems.append(f"{slug}: {len(hits)} files share that name -- "
                            + ", ".join(hits))
    if problems:
        raise SystemExit("Selected photographs could not be resolved:\n  " +
                         "\n  ".join(problems))
    return resolved


def main():
    all_found = discover_all()
    picks = resolve_picks(all_found)
    uuids = [UUID_RE.search(p).group(1) for p in picks.values()
             if UUID_RE.search(p)]
    wi = load_wi_images(uuids)

    records = {}
    unclean = []
    for slug, rel in sorted(picks.items()):
        info = process(slug, rel)
        for kind in ("thumb", "display"):
            v = verify(info[kind]["path"])
            if not v["clean"]:
                unclean.append(v)

        m = UUID_RE.search(rel)
        ident, source = None, None
        if m and m.group(1) in wi:
            ident = dict(wi[m.group(1)])
            source = "wildlife_insights"
        elif slug in MANUAL_IDS:
            cn, ln, kl = MANUAL_IDS[slug]
            ident = dict(common_name=cn, latin_name=ln, taxon_class=kl,
                         order=None, deployment_id=None, timestamp=None)
            source = "researcher"
        else:
            print(f"  SKIP {slug}: no Wildlife Insights record and no "
                  f"researcher identification")
            continue

        records[slug] = dict(
            slug=slug,
            source_file=rel,
            id_source=source,
            display_name=DISPLAY_NAMES.get(ident["common_name"],
                                           ident["common_name"]),
            thumb=f"media/photos/{slug}_thumb.jpg",
            display=f"media/photos/{slug}_display.jpg",
            display_size=info["display"]["size"],
            sensor_type=("AHDriFT" if rel.startswith("AHDriFT_Photos")
                         else "Camera Trap"),
            plot=plot_of(ident["deployment_id"]) if ident["deployment_id"]
            else None,
            schedule=(schedule_of(ident["deployment_id"])
                      if ident["deployment_id"] else None),
            **ident,
        )

    payload = dict(
        n_photos_on_disk=len(all_found),
        n_photos_published=len(records),
        n_with_wi_identification=sum(1 for r in records.values()
                                     if r["id_source"] == "wildlife_insights"),
        note=("One photograph is published per taxon. Species, plot and "
              "timestamp come from the Wildlife Insights image record joined "
              "on the image UUID in the filename, except for the six "
              "hand-exported originals, whose identification is the "
              "researcher's own and is labelled as such."),
        photos=records,
    )
    with open(SELECTION_JSON, "w") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True)

    # Files left behind by an earlier album. Reported, never deleted: these
    # live under docs/ and removing them is the operator's call.
    expected = {f"{s}_{k}.jpg" for s in records for k in ("thumb", "display")}
    stale = sorted(f for f in os.listdir(PHOTO_OUT)
                   if f.endswith(".jpg") and f not in expected)
    payload_stale = stale

    if unclean:
        raise SystemExit("Residual metadata survived in:\n  " +
                         "\n  ".join(str(u) for u in unclean))
    if payload_stale:
        print(f"  NOTE {len(payload_stale)} file(s) in docs/media/photos/ are "
              f"not part of the current album and can be removed: "
              f"{', '.join(payload_stale)}")
    print(f"  {len(records)} photographs published from {len(all_found)} on "
          f"disk; {payload['n_with_wi_identification']} carry a Wildlife "
          f"Insights identification; all outputs EXIF-clean")
    print(f"  wrote build/photo_selection.json")


if __name__ == "__main__":
    main()
