"""Build docs/data/media.json — the manifest the frontend reads.

All paths are RELATIVE to docs/ so the site works on GitHub Pages under a
subpath. Species names come only from verified sources: the Wildlife
Insights species lists in docs/data/species_*.json for photos, and the
BirdNET results CSV for audio. Nothing here is guessed.
"""
import json
import os
from datetime import datetime, timezone

REPO = "/home/will/NCSU/Claude_Science/2026_Sensor_Dashboard"
CREDIT = "W. Harrod / NC State University"

# --- photos ------------------------------------------------------------
# common/latin names cross-checked against docs/data/species_ahdrift.json
# and species_parallel.json; each caption describes what is visible.
PHOTOS = {
    "parallel_camera": [
        dict(id="bear_cubs", common_name="American Black Bear",
             latin_name="Ursus americanus",
             caption="A black bear sow and two cubs cross a thinned loblolly "
                     "pine stand in front of a tree-mounted camera."),
        dict(id="bobcat", common_name="Bobcat", latin_name="Lynx rufus",
             caption="A bobcat moves along the treeline at 05:25, caught by "
                     "the camera's infrared flash before dawn."),
        dict(id="coyote", common_name="Coyote", latin_name="Canis latrans",
             caption="A coyote pauses on a vegetated access route in early "
                     "June, facing the camera."),
    ],
    "bucket_camera": [
        # Filed under raw_data/CT_photos/, but the image is unmistakably an
        # AHDriFT bucket interior (white bucket floor, wooden ramp boards),
        # so it is mapped by SENSOR to bucket_camera rather than by folder.
        dict(id="gartersnake", common_name="Common Gartersnake",
             latin_name="Thamnophis sirtalis",
             caption="A gartersnake crosses the white floor of an AHDriFT "
                     "bucket, its pale dorsal stripes clearly visible."),
        dict(id="bear_bucket", common_name="American Black Bear",
             latin_name="Ursus americanus",
             caption="A black bear investigates the mouth of a bucket trap, "
                     "filling the camera's infrared frame."),
        dict(id="bear_paw", common_name="American Black Bear",
             latin_name="Ursus americanus",
             caption="A bear's paw and muzzle sweep across the bucket opening, "
                     "blurred by the close-focus daylight exposure."),
        dict(id="box_turtle_bucket", common_name="Eastern Box Turtle",
             latin_name="Terrapene carolina carolina",
             caption="An eastern box turtle sits on the bucket floor, the "
                     "yellow-on-dark pattern of its carapace clearly visible."),
        dict(id="broadhead_skink", common_name="Broadhead Skink",
             latin_name="Plestiodon laticeps",
             caption="A broadhead skink crosses the bucket ramp; the orange-red "
                     "head marks a male in breeding condition."),
        dict(id="possum_bucket", common_name="Virginia Opossum",
             latin_name="Didelphis virginiana",
             caption="A Virginia opossum peers into the bucket opening late at "
                     "night, lit by the camera's infrared flash."),
        dict(id="racer", common_name="Eastern Racer",
             latin_name="Coluber constrictor",
             caption="An eastern racer coils on the bucket floor in afternoon "
                     "light, tongue extended."),
        dict(id="raccoon_bucket", common_name="Northern Raccoon",
             latin_name="Procyon lotor",
             caption="A raccoon reaches a forepaw into the bucket, its face and "
                     "whiskers close to the lens."),
        dict(id="spotted_turtle", common_name="Spotted Turtle",
             latin_name="Clemmys guttata",
             caption="A spotted turtle in a bucket trap: discrete yellow spots "
                     "scattered over a black carapace. This is a state-listed "
                     "species of conservation concern."),
    ],
}

# --- audio -------------------------------------------------------------
# Each clip is named for the species it contains; that identification is the
# researcher's, made by listening, and is authoritative here. Latin name,
# taxonomic class and every detection count are read from birdnet.json, so
# nothing on the panel is typed from memory.
#
# These files carry no recorder, plot or timestamp (unlike the earlier
# SMM2-<unit>_<date>_<time> exports), so no per-clip location or date is
# claimed. The context shown is season-wide for the species.
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
        "The musical trill of a pine warbler, the second most frequently "
        "detected species in the acoustic dataset after eastern towhee.",
}

AUDIO_NOTE = (
    "Spectrograms show a 5-second excerpt at 24 kHz mono (0-12 kHz displayed, "
    "the full recorded band). The species on each clip was identified by ear "
    "by the researcher. Detection counts beside it are season-wide, "
    "unvalidated BirdNET totals for that species across the whole dataset -- "
    "they describe how often the classifier flagged the species, not this "
    "clip. These files carry no recorder or timestamp, so no plot or date is "
    "attributed to an individual clip."
)


def load_species_rows():
    """clip_id -> BirdNET summary row, for the clips actually present.

    The species mapping lives in make_spectrograms.py so the figure and the
    manifest can never disagree about which clip is which species.
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import make_spectrograms as ms
    clips, problems = ms.discover_clips()
    rows = {}
    for meta in clips.values():
        rows[meta["clip_id"]] = dict(
            species=meta["species"],
            latin_name=meta["latin_name"],
            **{"class": meta["taxon_class"]},
            n_detections=meta["n_detections"],
            n_plots=meta["n_plots"],
            by_plot_type=meta["by_plot_type"],
        )
    # Validation targets come straight from the published summary.
    with open(os.path.join(REPO, "docs", "data", "birdnet.json")) as fh:
        targets = {s["species"]: s.get("validation_target")
                   for s in json.load(fh)["species"]}
    for r in rows.values():
        r["validation_target"] = targets.get(r["species"])
    return rows, problems


def build(species_rows):
    views = {}

    for view_id, items in PHOTOS.items():
        out = []
        for it in items:
            out.append(dict(
                id=it["id"],
                thumb=f"media/photos/{it['id']}_thumb.jpg",
                display=f"media/photos/{it['id']}_display.jpg",
                caption=it["caption"],
                common_name=it["common_name"],
                latin_name=it["latin_name"],
                sensor_type="Camera Trap" if view_id == "parallel_camera"
                            else "AHDriFT",
                credit=CREDIT,
            ))
        views[view_id] = dict(kind="photo", items=out)

    audio_items = []
    for clip_id, row in sorted(species_rows.items()):
        by_pt = row.get("by_plot_type") or {}
        top_pt = max(by_pt.items(), key=lambda kv: kv[1])[0] if by_pt else None
        audio_items.append(dict(
            id=clip_id,
            spectrogram=f"media/spectrograms/{clip_id}.png",
            audio=f"media/audio/{clip_id}.m4a",
            caption=AUDIO_CAPTIONS.get(clip_id, ""),
            common_name=row["species"],
            latin_name=row.get("latin_name"),
            taxon_class=row.get("class"),
            sensor_type="ARU",
            credit=CREDIT,
            duration_sec=5.0,
            sample_rate_hz=24000,
            # Season-wide, explicitly not clip-level.
            species_context=dict(
                n_detections=row.get("n_detections"),
                n_plots=row.get("n_plots"),
                by_plot_type=by_pt,
                most_detected_plot_type=top_pt,
                validation_target=row.get("validation_target"),
                note="Unvalidated BirdNET detections for this species across "
                     "the whole 2026 season, not for this clip.",
            ),
        ))
    views["bird_frog_audio"] = dict(kind="audio", note=AUDIO_NOTE,
                                    items=audio_items)
    return dict(
        generated_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        credit=CREDIT,
        views=views,
    )


def main():
    rows, problems = load_species_rows()
    for p in problems:
        print(f"  SKIP {p}")
    if not rows:
        raise SystemExit("No audio clips resolved -- media.json not written.")

    payload = build(rows)
    out = os.path.join(REPO, "docs", "data", "media.json")
    with open(out, "w") as fh:
        json.dump(payload, fh, separators=(",", ":"), allow_nan=False)

    # Every referenced asset must exist, or the gallery renders broken tiles.
    docs = os.path.join(REPO, "docs")
    missing = []
    for view in payload["views"].values():
        for item in view["items"]:
            for key in ("thumb", "display", "spectrogram", "audio"):
                rel = item.get(key)
                if rel and not os.path.exists(os.path.join(docs, rel)):
                    missing.append(rel)
    if missing:
        raise SystemExit("Referenced media missing:\n  " +
                         "\n  ".join(missing))

    counts = ", ".join(f"{k} {len(v['items'])}"
                       for k, v in payload["views"].items())
    print(f"  wrote docs/data/media.json ({counts}); "
          f"all referenced assets present")


if __name__ == "__main__":
    main()
