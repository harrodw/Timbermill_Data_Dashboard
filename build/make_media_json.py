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
# The clip filenames (…_001_C<NN>.wav) do not appear anywhere in
# preliminary_BirdNET_Results.csv — that table's File column names the
# full ~60-minute parent recording. No tested reading of the C<NN> suffix
# picks out a single detection, so NO species is attributed to a clip.
# `detections` is therefore empty by design, and `recording_context`
# carries what IS verifiable: the parent recording's detection totals.
AUDIO = [
    dict(id="TO02_20260311_0701", plot="TO02", plot_type="Turbine Opening",
         recorded_local="2026-03-11 07:01:02", recorder="SMM2-02",
         parent_recording="SMM2-02_20260311_070102.wav",
         caption="Dawn chorus at a turbine opening, 11 March, 07:01. A 5-second "
                 "excerpt from an hour-long recording in which BirdNET flagged "
                 "504 detections across 20 species. No species can be tied to "
                 "this excerpt specifically."),
    dict(id="RE07_20260418_0608_a", plot="RE07", plot_type="Reference Edge",
         recorded_local="2026-04-18 06:08:02", recorder="SMM2-23",
         parent_recording="SMM2-23_20260418_060802.wav",
         caption="Dawn chorus at a forest/agriculture reference edge, 18 April, "
                 "06:08. A 5-second excerpt from an hour-long recording in which "
                 "BirdNET flagged 315 detections across 20 species. No species "
                 "can be tied to this excerpt specifically."),
    dict(id="RE07_20260418_0608_b", plot="RE07", plot_type="Reference Edge",
         recorded_local="2026-04-18 06:08:02", recorder="SMM2-23",
         parent_recording="SMM2-23_20260418_060802.wav",
         caption="A second 5-second excerpt from the same reference-edge dawn "
                 "recording on 18 April, 06:08. No species can be tied to this "
                 "excerpt specifically."),
]

AUDIO_NOTE = (
    "Spectrograms show a 5-second excerpt at 24 kHz mono (0-12 kHz displayed, "
    "the full recorded band). Species are not attributed to individual clips: "
    "the excerpt filenames do not appear in the BirdNET results, whose File "
    "column refers to the full hour-long parent recording. `recording_context` "
    "reports unvalidated BirdNET detections for that parent recording, not for "
    "the excerpt."
)


def build(rec_ctx):
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
    for it in AUDIO:
        ctx = rec_ctx[it["parent_recording"]]
        audio_items.append(dict(
            id=it["id"],
            spectrogram=f"media/spectrograms/{it['id']}.png",
            audio=f"media/audio/{it['id']}.m4a",
            caption=it["caption"],
            plot=it["plot"],
            plot_type=it["plot_type"],
            recorded_local=it["recorded_local"],
            detections=[],
            sensor_type="ARU",
            credit=CREDIT,
            duration_sec=5.0,
            sample_rate_hz=24000,
            recording_context=dict(
                parent_recording=it["parent_recording"],
                n_detections=ctx["n_detections"],
                n_species=ctx["n_species"],
                top_species=ctx["top"],
                note="Unvalidated BirdNET detections for the full parent "
                     "recording, not for this excerpt.",
            ),
        ))
    views["bird_frog_audio"] = dict(kind="audio", note=AUDIO_NOTE,
                                    items=audio_items)
    return dict(
        generated_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        credit=CREDIT,
        views=views,
    )
