"""Build docs/data/media.json -- the manifest the frontend reads.

All paths are RELATIVE to docs/ so the site works on GitHub Pages under a
subpath. Nothing here is guessed:

  * photo species, Latin name, class, plot and timestamp come from
    build/photo_selection.json, which make_photos.py writes by joining each
    image UUID against the Wildlife Insights image export;
  * audio species are the researcher's own identifications, with Latin names
    and detection counts read from docs/data/birdnet.json;
  * each photo's detection count is looked up in the published species
    summaries, which is what lets the album state honestly when a taxon was
    photographed but does not appear in the motion-capture dataset.

Only the captions are written by hand, and each describes what is visible in
its own frame.

Run:  python build/make_media_json.py   (after make_photos.py)
"""
import json
import os
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(REPO, "docs")
DATA_OUT = os.path.join(DOCS, "data")
SELECTION = os.path.join(REPO, "build", "photo_selection.json")
CREDIT = "W. Harrod / NC State University"

# ---------------------------------------------------------------------------
# Captions: one per published photograph, describing that frame.
# ---------------------------------------------------------------------------
CAPTIONS = {
    # ---- parallel cameras ----
    "bear_cubs": "A black bear sow and two cubs cross a thinned loblolly pine "
                 "stand in front of a tree-mounted camera.",
    "bobcat": "A bobcat moves along the treeline before dawn, caught by the "
              "camera's infrared flash.",
    "coyote": "A coyote pauses on a vegetated access route in early June, "
              "facing the camera.",

    # ---- bucket cameras: mammals ----
    "bear_bucket": "A black bear investigates the mouth of a bucket trap, "
                   "filling the camera's infrared frame.",
    "bear_paw": "A bear's paw and muzzle sweep across the bucket opening, "
                "blurred by the close-focus daylight exposure.",

    # ---- bucket cameras: reptiles ----
    "broadhead_skink": "A broadhead skink at the lip of a bucket, backlit by "
                       "strong afternoon sun.",
    "common_box_turtle": "An eastern box turtle on the bucket floor with its "
                         "head raised, the yellow-on-dark carapace pattern "
                         "clearly visible.",
    "common_gartersnake": "A gartersnake crossing the pale floor of a bucket, "
                          "its light dorsal stripes running the length of the "
                          "body. Filed by the researcher under the ribbonsnake "
                          "folder; the Wildlife Insights identification is "
                          "Thamnophis sirtalis and the album follows it.",
    "common_kingsnake": "A kingsnake pressed against the curve of the bucket "
                        "wall, the pale chain-link banding of the species "
                        "visible along its flank.",
    "dekays_brownsnake": "A DeKay's brownsnake at the mouth of a bucket, "
                         "picked out against the leaf litter. The only "
                         "brownsnake photographed in the arrays.",
    "eastern_racer": "An eastern racer stretched across the bucket floor in "
                     "daylight, uniform dark dorsum and smooth scales filling "
                     "the frame.",
    "eastern_rat_snake": "An eastern ratsnake doubled back on itself on the "
                         "bucket floor in mid-afternoon.",
    "eastern_ribbon_snake": "An eastern ribbonsnake descending the bucket "
                            "wall, the bright lateral stripe of the species "
                            "clearly visible.",
    "little_brown_skink": "A little brown skink at the rim of a bucket. The "
                          "coppery dorsum and dark lateral stripe are only "
                          "just resolvable at this distance, which is typical "
                          "of the genus in bucket frames.",
    "northern_copperhead": "A copperhead crossing the bucket floor with the "
                           "hourglass crossbands of the species clearly "
                           "visible. The only copperhead photographed in the "
                           "arrays.",
    "northern_cottonmouth": "A cottonmouth coiled on the litter at the bucket "
                            "mouth, heavy-bodied and dark-banded.",
    "plain_bellied_watersnake": "A plain-bellied watersnake looped over the "
                                "wooden ramp boards of a bucket.",
    "plestiodon_species": "A Plestiodon skink on the bucket floor beside "
                          "fallen leaves. Females and juveniles in this genus "
                          "cannot be separated reliably in a bucket "
                          "photograph, so these records stop at genus.",
    "ring_necked_snake": "A ring-necked snake along the inner wall of a "
                         "bucket in late morning.",
    "spotted_turtle": "A spotted turtle in a bucket trap: discrete yellow "
                      "spots scattered over a black carapace. A state-listed "
                      "species of conservation concern.",
    "timber_rattlesnake": "A timber rattlesnake at the mouth of a bucket in "
                          "strong afternoon light.",
    "unidentified_snake": "A snake entering a bucket at night, recorded only "
                          "as a tail and flank. One of the frames that could "
                          "not be taken past Squamata.",
    "worm_snake": "An eastern wormsnake looped against the bucket wall. A "
                  "fossorial species small enough to be missed easily in a "
                  "bucket frame.",

    # ---- bucket cameras: amphibians ----
    "eastern_narrowmouth_toad": "An eastern narrow-mouthed toad on the bucket "
                                "floor at night, the squat pointed-snout "
                                "profile of the species visible under "
                                "infrared.",
    "salamander_species": "A salamander on the ramp boards of a bucket at "
                          "night. Caudate records from these frames were not "
                          "resolved past order.",
    "southern_leopard_frog": "A southern leopard frog on the bucket floor, "
                             "the dark dorsal spotting of the species visible "
                             "in daylight.",
    "southern_toad": "A southern toad centred on the bucket floor at night, "
                     "its warty dorsum picked out by the infrared flash.",
}

PHOTO_NOTE = (
    "One photograph per reptile and amphibian taxon, chosen for how clearly "
    "the animal reads, alongside the mammal frames the album already carried "
    "-- black bear appears more than once because the bucket and the "
    "tree-mounted cameras show it very differently. "
    "Species, plot and time come from the Wildlife Insights identification "
    "of that exact image, joined on the image UUID -- not from the folder it "
    "was filed in. Images are resized and rebuilt pixel-by-pixel so no EXIF, "
    "GPS or device serial survives. They are illustrative, not a sample for "
    "analysis."
)

# --- audio -------------------------------------------------------------
AUDIO_CAPTIONS = {
    "brimleys_chorus_frog":
        "The short rasping call of Brimley's chorus frog, one of the first "
        "species calling in the emergent wetlands that formed under the "
        "turbines in early spring.",
    "field_sparrow":
        "The accelerating trill of a field sparrow, a shrubland species "
        "expected to benefit from the herbaceous openings around turbines.",
    "hooded_warbler":
        "The ringing song of a hooded warbler, an interior-forest species of "
        "the shaded understory beneath closed canopy.",
    "pickerel_frog":
        "The low snore of a pickerel frog, the most frequently detected "
        "amphibian of the season.",
    "pine_warbler":
        "The musical trill of a pine warbler, among the most frequently "
        "detected species in the acoustic dataset.",
}

AUDIO_NOTE = (
    "Spectrograms show a 5-second excerpt at 24 kHz mono (0-12 kHz "
    "displayed, the full recorded band). The species on each clip was "
    "identified by ear by the researcher. Counts beside it are season-wide "
    "totals for that species -- filtered to the species' validated cutoff "
    "where one exists, raw where it does not -- and describe how often the "
    "classifier flagged the species, not this clip. These files carry no "
    "recorder or timestamp, so no plot or date is attributed to a clip."
)


def load_json(name):
    with open(os.path.join(DATA_OUT, name)) as fh:
        return json.load(fh)


def detection_index():
    """Common name -> (view, n_detections) from the published summaries."""
    out = {}
    for view, fname, key in (("bucket_camera", "species_ahdrift.json",
                              "n_detections"),
                             ("parallel_camera", "species_parallel.json",
                              "n_sequences")):
        try:
            src = load_json(fname)
        except FileNotFoundError:
            continue
        for s in src["species"]:
            out.setdefault(s["common_name"], {})[view] = int(s[key])
    return out


def build_photos(selection, det_index):
    views = {"bucket_camera": [], "parallel_camera": []}
    missing_caption = []
    for slug, p in sorted(selection["photos"].items(),
                          key=lambda kv: (kv[1]["taxon_class"] or "zz",
                                          kv[1]["display_name"] or "")):
        view = ("bucket_camera" if p["sensor_type"] == "AHDriFT"
                else "parallel_camera")
        caption = CAPTIONS.get(slug)
        if not caption:
            missing_caption.append(slug)
            caption = ""

        n_det = det_index.get(p["common_name"], {}).get(view)
        context = None
        if n_det is not None:
            unit = ("detection events" if view == "bucket_camera"
                    else "sequences")
            context = (f"{n_det:,} {unit} of this taxon in the 2026 season.")
        elif view == "bucket_camera":
            # Photographed, but absent from the cleaned motion-capture table.
            # Usually because the frame came from the time-lapse schedule,
            # which that table does not cover -- worth saying, not hiding.
            why = (" The frame came from the time-lapse schedule, which the "
                   "motion-capture dataset does not cover."
                   if p.get("schedule") == "time lapse" else "")
            context = ("This taxon does not appear in the cleaned "
                       "motion-capture detection table." + why)

        views[view].append(dict(
            id=slug,
            thumb=p["thumb"],
            display=p["display"],
            caption=caption,
            # common_name is the identification as recorded; display_name is
            # how it is worded in the gallery. Keeping both separate means a
            # cosmetic relabel never breaks a join against the species
            # summaries (the album-coverage check in build_summaries.py does
            # exactly that join).
            common_name=p["common_name"],
            display_name=p["display_name"],
            latin_name=p["latin_name"],
            taxon_class=p["taxon_class"],
            sensor_type=p["sensor_type"],
            plot=p.get("plot"),
            schedule=p.get("schedule"),
            recorded_local=p.get("timestamp"),
            id_source=p["id_source"],
            n_detections_season=n_det,
            context=context,
            credit=CREDIT,
        ))
    return views, missing_caption


def build_audio():
    """Audio items, with species context read from birdnet.json."""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import make_spectrograms as ms
    clips, problems = ms.discover_clips()

    items = []
    for meta in sorted(clips.values(), key=lambda m: m["clip_id"]):
        by_pt = meta.get("by_plot_type") or {}
        top_pt = max(by_pt.items(), key=lambda kv: kv[1])[0] if by_pt else None
        filtered = meta.get("threshold") is not None
        items.append(dict(
            id=meta["clip_id"],
            spectrogram=f"media/spectrograms/{meta['clip_id']}.png",
            audio=f"media/audio/{meta['clip_id']}.m4a",
            caption=AUDIO_CAPTIONS.get(meta["clip_id"], ""),
            common_name=meta["species"],
            latin_name=meta.get("latin_name"),
            taxon_class=meta.get("taxon_class"),
            sensor_type="ARU",
            credit=CREDIT,
            duration_sec=5.0,
            sample_rate_hz=24000,
            species_context=dict(
                n_detections=meta.get("n_detections"),
                n_detections_raw=meta.get("n_detections_raw"),
                n_plots=meta.get("n_plots"),
                by_plot_type=by_pt,
                most_detected_plot_type=top_pt,
                threshold=meta.get("threshold"),
                filtered=filtered,
                n_clips_listened=(meta.get("validation") or {})
                .get("n_listened"),
                note=(
                    f"Detections at or above this species' validated cutoff "
                    f"of {meta['threshold']:g}, across the whole 2026 season "
                    f"-- not for this clip."
                    if filtered else
                    "Unvalidated BirdNET detections for this species across "
                    "the whole 2026 season, not for this clip. No confidence "
                    "cutoff has been established for it yet."
                ),
            ),
        ))
    return items, problems


def main():
    with open(SELECTION) as fh:
        selection = json.load(fh)
    det_index = detection_index()
    views, missing_caption = build_photos(selection, det_index)
    for slug in missing_caption:
        print(f"  WARNING no caption written for {slug}")

    audio_items, problems = build_audio()
    for p in problems:
        print(f"  SKIP {p}")
    if not audio_items:
        raise SystemExit("No audio clips resolved -- media.json not written.")

    payload = dict(
        generated_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        credit=CREDIT,
        views={
            "bucket_camera": dict(kind="photo", note=PHOTO_NOTE,
                                  items=views["bucket_camera"]),
            "parallel_camera": dict(kind="photo", note=PHOTO_NOTE,
                                    items=views["parallel_camera"]),
            "bird_frog_audio": dict(kind="audio", note=AUDIO_NOTE,
                                    items=audio_items),
        },
        photo_selection=dict(
            n_on_disk=selection["n_photos_on_disk"],
            n_published=selection["n_photos_published"],
            n_wi_identified=selection["n_with_wi_identification"],
            note=selection["note"],
        ),
    )

    out = os.path.join(DATA_OUT, "media.json")
    with open(out, "w") as fh:
        json.dump(payload, fh, separators=(",", ":"), allow_nan=False)

    # Every referenced asset must exist, or the gallery renders broken tiles.
    missing = []
    for view in payload["views"].values():
        for item in view["items"]:
            for key in ("thumb", "display", "spectrogram", "audio"):
                rel = item.get(key)
                if rel and not os.path.exists(os.path.join(DOCS, rel)):
                    missing.append(rel)
    if missing:
        raise SystemExit("Referenced media missing:\n  " + "\n  ".join(missing))

    counts = ", ".join(f"{k} {len(v['items'])}"
                       for k, v in payload["views"].items())
    print(f"  wrote docs/data/media.json ({counts}); "
          f"all referenced assets present")


if __name__ == "__main__":
    main()
