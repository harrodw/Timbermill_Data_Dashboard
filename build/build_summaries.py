#!/usr/bin/env python3
"""
Timbermill Wind & Wildlife -- dashboard summary pipeline.

Reads the raw, preliminary sensor data in ``data/`` and writes ONLY aggregated
summaries into ``docs/data/``. No individual detection record, no raw media,
and no full-precision coordinate ever reaches ``docs/``.

Run from the repository root:

    python build/build_summaries.py

Data sources, and which view each one backs:

    data/Clean_AHDriFT_Data/ahdrift_data_cleaned.csv
        bucket_camera. One row per motion-capture detection event, plus one
        "No Detections" row per surveyed plot-day, which is what makes real
        survey effort (and therefore detection rate and naive occupancy)
        computable for the AHDriFT arrays. This file -- not the Wildlife
        Insights export -- is authoritative for the bucket cameras.
    data/WI_Download/
        parallel_camera only. sequences.csv filtered to the CT deployments.
    data/Bird_Frog_Audio_Summaries/preliminary_BirdNET_Results.csv
        bird_frog_audio. 3.6 M raw classifier detections.
    data/Bird_Frog_Audio_Summaries/BirdNet_Thresholds.csv
        Per-species confidence cutoffs from listening to 150 clips per
        species. Species are split into validation groups from this file and
        the validated ones are filtered to their own cutoff.

Outputs (all JSON, all safe to publish):

    docs/data/manifest.json         build metadata, view registry, headline totals
    docs/data/locations.json        jittered coordinates + per-point species tallies
    docs/data/effort.json           survey effort by view
    docs/data/species_ahdrift.json  AHDriFT species, activity, rate vs occupancy
    docs/data/species_parallel.json parallel-camera equivalents
    docs/data/birdnet.json          BirdNET species by validation group + activity
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path

import pandas as pd

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data"
WI_DIR = RAW / "WI_Download"
AH_CSV = RAW / "Clean_AHDriFT_Data" / "ahdrift_data_cleaned.csv"
TH_CSV = RAW / "Bird_Frog_Audio_Summaries" / "BirdNet_Thresholds.csv"
BN_CSV = RAW / "Bird_Frog_Audio_Summaries" / "preliminary_BirdNET_Results.csv"
LOC_CSV = RAW / "Locations" / "cam_trap_locations_info.csv"
OUT = ROOT / "docs" / "data"

# --------------------------------------------------------------------------
# Privacy controls
# --------------------------------------------------------------------------
# Published coordinates are rounded to COORD_DECIMALS and then displaced by a
# deterministic per-point offset. Deterministic means the same point lands in
# the same place on every rebuild (so the map is stable) while never revealing
# the true location. Full-precision coordinates stay in data/, git-ignored.
COORD_DECIMALS = 3
JITTER_MIN_M = 40.0
JITTER_MAX_M = 110.0

# --------------------------------------------------------------------------
# Activity-pattern binning
# --------------------------------------------------------------------------
# Time-of-day histograms are published as counts in half-hour bins; the
# frontend smooths them into the activity curves. Half-hour bins are fine
# enough to resolve a dawn peak and coarse enough that a single species with a
# few hundred detections still gives a readable curve.
ACT_BINS = 48
ACT_BIN_SECONDS = 86400 // ACT_BINS

# A half-hour counts as sampled when its recording effort reaches this
# fraction of the busiest half-hour. Placed in the empirical gap between the
# scheduled night bins and the off-schedule daytime plateau: see the comment
# in build_birdnet() where the mask is computed.
ACT_MIN_EFFORT_FRACTION = 0.03

# Minimum recording-hours a half-hour bin must carry before an acoustic
# activity curve is drawn through it. Used instead of a share of the busiest
# bin because it does not move between anchors: anchoring on sunset spreads
# the dawn chorus over the ~3.2 h that night length varies across the season,
# which lowers the peak without changing what was recorded. The choice is not
# knife-edge -- any floor from 15 to 25 h gives the same window to within one
# bin under all three anchors -- and at 20 h each anchor keeps ~94% of all
# recorded time.
ACT_MIN_BIN_HOURS = 20.0

# ---------------------------------------------------------------- solar time
# Activity can be binned against the clock or against a solar event. The study
# area is one block of Chowan County, North Carolina; across the 50 plots the
# spread in sunrise is a couple of seconds, so a single site position is used
# for every plot rather than a per-plot computation that would imply a
# precision the half-hour binning cannot carry.
SITE_LAT = 36.13
SITE_LON = -76.55
SITE_TZ = -4.0                      # local standard offset used all season
SOLAR_ZENITH = 90.833               # sun centre, refraction-corrected

# Solar-anchored bins are rotated so that bin ACT_BINS//2 is the event itself.
# Hours relative to the event are therefore (bin - ACT_BINS//2) * 0.5, which
# runs -12 .. +11.5 and needs no wrapping to read.
ACT_ANCHOR_BIN = ACT_BINS // 2
ACT_ANCHORS = ("clock", "sunrise", "sunset")
ANCHOR_LABELS = {
    "clock": "Clock time",
    "sunrise": "Hours from sunrise",
    "sunset": "Hours from sunset",
}
ANCHOR_NOTE = (
    "Detection times can be binned against the clock or against a solar "
    "event. Clock time asks when in the day an animal was active; a solar "
    "anchor asks where in the night or day it was active relative to the "
    "light, which is what most activity is actually keyed to and what makes "
    "March comparable with August. The anchors are not interchangeable: "
    "anchoring on one end of the night sharpens that end and blurs the "
    "other by however much night length changed over the season, so pick "
    "the anchor nearest the behaviour being read."
)

# ARU recordings come in two lengths; the schedule runs 5-minute files through
# most of the night and a 60-minute file over the dawn chorus. Detections are
# timestamped within their file, so a file's length is inferred from the
# largest detection offset it contains: the two populations are cleanly
# separated (no file in the whole dataset has a maximum offset between 300 and
# 310 s). The residual error is a 60-minute file whose only detections fall in
# its first five minutes, which would be scored as a 5-minute file and
# slightly under-count effort in that bin.
ARU_SHORT_SECONDS = 300
ARU_LONG_SECONDS = 3600
ARU_DURATION_SPLIT = 310

# --------------------------------------------------------------------------
# BirdNET validation design
# --------------------------------------------------------------------------
# Clips reviewed per species when working through the queue, and the
# true-positive probability the cutoff is read off at. Both are reported on the
# dashboard rather than described in prose, so they live here as constants and
# are not retyped into any note.
VALIDATION_N_PER_SPECIES = 150
VALIDATION_TARGET_P = 0.95

# Non-wildlife / non-identification labels excluded from species tallies.
NON_SPECIES_LABELS = {
    "no cv result", "blank", "vehicle", "animal", "unknown", "",
    "human", "homo sapiens", "camera trapper", "setup/pickup",
    "official vehicle", "no detections",
}
# Labels that are real detections but not resolved to a useful taxon. These
# are counted separately so nothing silently vanishes, and kept out of the
# species chart -- except in the AHDriFT file, where the researcher's cleaned
# species list is taken as final and its genus-level labels ("Plestiodon
# Species") are real analysis units.
COARSE_LABELS = {
    "mammal", "bird", "insect", "spider", "rodent", "reptile", "amphibian",
    "snake", "lizard", "turtle", "frog", "toad", "frogs", "toads", "bat",
    "bats", "arachnid", "arachnids", "millipede", "centipede", "snail",
    "slug", "small mammal", "large mammal", "butterflies and moths",
    "bumblebees", "dragonflies and damselflies",
}
# Wildlife Insights also emits rank-named labels ("Passeriformes Order",
# "Cathartidae Family"). Those are above genus and cannot anchor a species
# row, so they are excluded by rank suffix rather than by enumeration -- a new
# family label in a future export is then handled without a code change.
# Genus-level "<Genus> Species" labels are NOT excluded: they are the same
# kind of unit as the cleaned AHDriFT list's "Plestiodon Species" and are
# real analysis units.
COARSE_RANK_SUFFIXES = (" order", " family", " suborder", " superfamily",
                        " subfamily", " tribe", " class", " phylum")

PLOT_TYPES = {
    "TO": "Turbine Opening",
    "TE": "Turbine Edge",
    "IF": "Interior Forest",
    "RE": "Reference Edge",
}
PLOT_TYPE_ORDER = ["Turbine Opening", "Turbine Edge", "Interior Forest",
                   "Reference Edge"]

# Taxonomic classes, in the order the class filter should offer them.
CLASS_ORDER = ["Mammalia", "Aves", "Reptilia", "Amphibia", "Insecta",
               "Arachnida"]

CLASS_LABELS = {
    "Mammalia": "Mammals",
    "Aves": "Birds",
    "Reptilia": "Reptiles",
    "Amphibia": "Amphibians",
    "Insecta": "Insects",
    "Arachnida": "Arachnids",
}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def log(msg: str) -> None:
    print(f"  {msg}", flush=True)


def norm_key(s) -> str:
    """Normalize a placename for joining: TO11-AD01 / TO11_AD01 -> TO11AD01."""
    return re.sub(r"[^A-Z0-9]", "", str(s).upper())


def plot_code(name) -> str | None:
    """Leading plot code from a placename or deployment id, e.g. 'TE03'."""
    m = re.match(r"([A-Za-z]{2})\s*0*(\d+)", str(name).strip())
    if not m:
        return None
    code = m.group(1).upper()
    if code not in PLOT_TYPES:
        return None
    return f"{code}{int(m.group(2)):02d}"


def plot_type_of(name) -> str | None:
    code = plot_code(name)
    return PLOT_TYPES.get(code[:2]) if code else None


def sensor_type_of(name) -> str | None:
    """AHDriFT (bucket) vs parallel camera, from the AD##/CT## suffix."""
    u = str(name).upper()
    if re.search(r"\bAD\d+|[_-]AD\d+", u):
        return "AHDriFT"
    if re.search(r"\bCT\d+|[_-]CT\d+", u):
        return "Camera Trap"
    return None


def canon_plot_type(s) -> str | None:
    """Normalize plot-type spellings, incl. the 'Interor Forest' typo."""
    if s is None or (isinstance(s, float) and math.isnan(s)):
        return None
    t = re.sub(r"\s+", " ", str(s).strip().lower())
    if t.startswith("inter"):
        return "Interior Forest"
    if t.startswith("ref"):
        return "Reference Edge"
    if "opening" in t:
        return "Turbine Opening"
    if "edge" in t:
        return "Turbine Edge"
    return str(s).strip()


def class_rank(k) -> int:
    try:
        return CLASS_ORDER.index(str(k))
    except ValueError:
        return len(CLASS_ORDER)


def jitter(point_id: str, lat: float, lon: float) -> tuple[float, float]:
    """Deterministic, stable coordinate obfuscation.

    The true position is displaced along a pseudo-random bearing and then
    rounded. Keying the offset on the point id makes it identical on every
    rebuild, so the map does not shuffle between builds, while the enforced
    minimum radius guarantees no published marker sits on a real sensor.
    Rounding can pull a point back toward its true position, so the
    displacement is re-measured after rounding and the draw repeated with a
    wider radius until the floor actually holds.
    """
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = m_per_deg_lat * max(math.cos(math.radians(lat)), 0.1)

    for attempt in range(64):
        h = hashlib.sha256(f"timbermill/{point_id}/{attempt}".encode()).digest()
        bearing = int.from_bytes(h[0:4], "big") / 2**32 * 2 * math.pi
        frac = int.from_bytes(h[4:8], "big") / 2**32
        lo_m = JITTER_MIN_M + attempt * 5.0
        radius = math.sqrt(lo_m**2 + frac * max(JITTER_MAX_M**2 - lo_m**2, 0.0))

        jlat = round(lat + radius * math.cos(bearing) / m_per_deg_lat,
                     COORD_DECIMALS)
        jlon = round(lon + radius * math.sin(bearing) / m_per_deg_lon,
                     COORD_DECIMALS)
        moved = math.hypot((jlat - lat) * m_per_deg_lat,
                           (jlon - lon) * m_per_deg_lon)
        if moved >= JITTER_MIN_M:
            return jlat, jlon
    return jlat, jlon


def is_species_label(name) -> bool:
    if name is None or (isinstance(name, float) and math.isnan(name)):
        return False
    t = str(name).strip().lower()
    if not t or t in NON_SPECIES_LABELS or t in COARSE_LABELS:
        return False
    return not t.endswith(COARSE_RANK_SUFFIXES)


def count_lines(path: Path) -> int:
    """Fast line count for very large CSVs (header excluded)."""
    try:
        out = subprocess.run(["wc", "-l", str(path)], capture_output=True,
                             text=True, check=True)
        return max(int(out.stdout.split()[0]) - 1, 0)
    except Exception:
        with path.open("rb") as fh:
            return max(sum(1 for _ in fh) - 1, 0)


def act_bin(hour, minute=0, second=0) -> int | None:
    """Clock time -> half-hour bin index, or None when the time is missing."""
    try:
        h = int(hour)
    except (TypeError, ValueError):
        return None
    if h < 0:
        return None
    secs = (h * 3600 + int(minute or 0) * 60 + int(second or 0)) % 86400
    return int(secs // ACT_BIN_SECONDS)


@lru_cache(maxsize=None)
def solar_hours(iso_date: str):
    """(sunrise, sunset) for one date at the study site, in local decimal hours.

    NOAA's standard sunrise equation. Returns (None, None) for a date that
    cannot be parsed, so a missing date drops the detection from the
    solar-anchored bins rather than putting it at an invented time.
    """
    try:
        d = date.fromisoformat(str(iso_date)[:10])
    except (TypeError, ValueError):
        return (None, None)

    out = []
    for rising in (True, False):
        n = d.timetuple().tm_yday
        lng_hour = SITE_LON / 15.0
        t = n + ((6 if rising else 18) - lng_hour) / 24.0
        mean_anom = (0.9856 * t) - 3.289
        true_long = (mean_anom
                     + 1.916 * math.sin(math.radians(mean_anom))
                     + 0.020 * math.sin(math.radians(2 * mean_anom))
                     + 282.634) % 360
        right_asc = math.degrees(
            math.atan(0.91764 * math.tan(math.radians(true_long)))) % 360
        right_asc += ((math.floor(true_long / 90) * 90)
                      - (math.floor(right_asc / 90) * 90))
        right_asc /= 15.0
        sin_dec = 0.39782 * math.sin(math.radians(true_long))
        cos_dec = math.cos(math.asin(sin_dec))
        cos_h = ((math.cos(math.radians(SOLAR_ZENITH))
                  - sin_dec * math.sin(math.radians(SITE_LAT)))
                 / (cos_dec * math.cos(math.radians(SITE_LAT))))
        if abs(cos_h) > 1:               # no rise or set at this latitude/date
            out.append(None)
            continue
        hour_angle = (360 - math.degrees(math.acos(cos_h))) if rising \
            else math.degrees(math.acos(cos_h))
        hour_angle /= 15.0
        out.append((hour_angle + right_asc - (0.06571 * t) - 6.622
                    - lng_hour + SITE_TZ) % 24)
    return (out[0], out[1])


def anchor_bin(anchor: str, iso_date, secs) -> int | None:
    """Seconds-past-local-midnight -> bin index for one anchor.

    Solar bins are rotated so bin ACT_ANCHOR_BIN is the event. Taking the
    offset modulo 24 h means a detection either side of midnight is measured
    against the nearest occurrence of the event; the day-to-day drift in
    sunrise is about a minute, far inside one half-hour bin.
    """
    if secs is None:
        return None
    s = int(secs) % 86400
    if anchor == "clock":
        return s // ACT_BIN_SECONDS
    sunrise, sunset = solar_hours(iso_date)
    ref = sunrise if anchor == "sunrise" else sunset
    if ref is None:
        return None
    rel = (s - ref * 3600.0) % 86400
    return (int(rel // ACT_BIN_SECONDS) + ACT_ANCHOR_BIN) % ACT_BINS


def anchor_offset_seconds(anchor: str, iso_date, secs) -> float | None:
    """Rotated seconds-into-the-cycle, for spreading a recording over bins."""
    if secs is None:
        return None
    s = int(secs) % 86400
    if anchor == "clock":
        return float(s)
    sunrise, sunset = solar_hours(iso_date)
    ref = sunrise if anchor == "sunrise" else sunset
    if ref is None:
        return None
    rel = (s - ref * 3600.0) % 86400
    return (rel + ACT_ANCHOR_BIN * ACT_BIN_SECONDS) % 86400


def bin_label(anchor: str, b: int) -> str:
    """Human label for a bin edge, in that anchor's own units."""
    if anchor == "clock":
        return (f"{int(b * ACT_BIN_SECONDS // 3600):02d}:"
                f"{int(b * ACT_BIN_SECONDS % 3600 // 60):02d}")
    h = (b - ACT_ANCHOR_BIN) * (ACT_BIN_SECONDS / 3600.0)
    if abs(h) < 1e-9:
        return anchor
    return f"{h:+.1f} h".replace(".0 h", " h")


def empty_bins() -> list[int]:
    return [0] * ACT_BINS


def empty_anchor_bins() -> dict:
    return {a: [0] * ACT_BINS for a in ACT_ANCHORS}


def pack_activity(d: dict) -> dict:
    """Drop all-zero plot-type rows so the published arrays stay small."""
    return {k: v for k, v in d.items() if any(v)}


def pack_anchored_activity(d: dict) -> dict:
    """{anchor: {plot_type: bins}} with empty rows and empty anchors dropped."""
    out = {}
    for anchor in ACT_ANCHORS:
        packed = pack_activity(d.get(anchor, {}))
        if packed:
            out[anchor] = packed
    return out


def accumulate_activity(plot_types, hours, minutes, seconds, days) -> dict:
    """Bin one species' detection times against every anchor at once.

    Returns {anchor: {plot_type: [counts per bin]}}. A detection with no
    usable time, no plot type, or (for the solar anchors) no usable date is
    skipped for that anchor rather than placed at an assumed time.
    """
    act = {a: defaultdict(empty_bins) for a in ACT_ANCHORS}
    for pt, h, m, s, day in zip(plot_types, hours, minutes, seconds, days):
        if not pt or pd.isna(pt) or pd.isna(h):
            continue
        try:
            secs = (int(h) * 3600
                    + int(0 if pd.isna(m) else m) * 60
                    + int(0 if pd.isna(s) else s))
        except (TypeError, ValueError):
            continue
        for anchor in ACT_ANCHORS:
            b = anchor_bin(anchor, day, secs)
            if b is not None:
                act[anchor][str(pt)][b] += 1
    return act


def window_extent(anchor: str, win: dict) -> dict:
    """Published extent of a sampled window, in that anchor's own units.

    For a solar anchor the window is reported in hours relative to the event.
    A night window crosses the +/-12 h wrap, which would otherwise be written
    as "+10 h to +1.5 h" -- true modulo 24, but unreadable. The representation
    is chosen so the window CONTAINS the anchor, which turns that case into
    "-14 h to +1.5 h": the night running up to the following sunrise. The
    anchor is the one instant the window is guaranteed to span (the recorders
    ran through both sunset and sunrise every night), so it is the stable
    choice; picking the branch by which end is larger is not, because a
    window straddling sunset already ends past +12 h legitimately.
    """
    first, last = win["first_bin"], win["last_bin"]
    out = {
        "start_bin": first,
        "end_bin": last,
        "n_bins": win["n_bins"],
        "hours": win["hours"],
        "pct_effort_covered": win["pct_effort_covered"],
    }
    if first is None or last is None:
        out["start_label"] = out["end_label"] = None
        return out
    if anchor == "clock":
        out["start_label"] = bin_label("clock", first)
        out["end_label"] = bin_label("clock", (last + 1) % ACT_BINS)
        return out

    half = ACT_BIN_SECONDS / 3600.0
    start_rel = (first - ACT_ANCHOR_BIN) * half
    end_rel = start_rel + win["n_bins"] * half
    shift = 0.0
    if start_rel > 0.0:                     # window sits wholly after the event
        shift = -24.0
    elif end_rel < 0.0:                     # wholly before it
        shift = 24.0
    start_rel += shift
    end_rel += shift
    out["rel_shift_h"] = shift
    out["start_rel_h"] = round(start_rel, 2)
    out["end_rel_h"] = round(end_rel, 2)
    out["start_label"] = f"{start_rel:+.1f} h".replace(".0 h", " h")
    out["end_label"] = f"{end_rel:+.1f} h".replace(".0 h", " h")
    return out


def uniform_anchor_meta() -> dict:
    """Anchor metadata for a sensor that ran continuously.

    A camera watching around the clock contributes equally to every bin under
    any anchor, so all 48 bins are sampled and the curve stays circular. Only
    the x-axis meaning changes between anchors.
    """
    return {
        a: {
            "label": ANCHOR_LABELS[a],
            "sampled": [1] * ACT_BINS,
            "n_bins": ACT_BINS,
            "hours": round(ACT_BINS * ACT_BIN_SECONDS / 3600.0, 2),
            "pct_effort_covered": 100.0,
            "anchor_bin": None if a == "clock" else ACT_ANCHOR_BIN,
        }
        for a in ACT_ANCHORS
    }


def derive_window(bin_total, min_fraction=None, min_absolute=None):
    """Which bins the schedule sampled, and the extent of that run.

    Two ways to call it, for two different jobs:

    `min_fraction` marks a bin sampled at that share of the busiest bin. This
    is used on the CLOCK profile of all recordings, where the three effort
    regimes separate cleanly and the question is which recordings were on
    schedule at all.

    `min_absolute` marks a bin sampled when it carries that much effort
    outright. This is used for the drawn window, because it is anchor
    invariant: anchoring on sunset smears the dawn chorus over the hours that
    night length varies, which lowers the peak and would move a
    fraction-of-peak cut even though the recordings did not change.

    The extent is read as the complement of the LONGEST unsampled run, so a
    window that straddles the start of the cycle comes back as one contiguous
    span rather than two.
    """
    if (min_fraction is None) == (min_absolute is None):
        raise ValueError("pass exactly one of min_fraction / min_absolute")
    peak = max(bin_total) if bin_total else 0.0
    if min_absolute is not None:
        sampled = [1 if v >= min_absolute else 0 for v in bin_total]
    else:
        sampled = [1 if (peak and v >= min_fraction * peak) else 0
                   for v in bin_total]
    first_bin = last_bin = None
    if any(sampled):
        gaps, run = [], []
        for b in range(ACT_BINS * 2):
            i = b % ACT_BINS
            if not sampled[i]:
                run.append(i)
            elif run:
                gaps.append(run)
                run = []
        longest = max(gaps, key=len) if gaps else []
        if longest:
            first_bin = (longest[-1] + 1) % ACT_BINS
            last_bin = (longest[0] - 1) % ACT_BINS
        else:
            first_bin, last_bin = 0, ACT_BINS - 1
    n_bins = sum(sampled)
    pct = (100.0 * sum(v for b, v in enumerate(bin_total) if sampled[b])
           / sum(bin_total)) if sum(bin_total) else 0.0
    return {
        "sampled": sampled,
        "peak": peak,
        "first_bin": first_bin,
        "last_bin": last_bin,
        "n_bins": n_bins,
        "hours": round(n_bins * ACT_BIN_SECONDS / 3600.0, 2),
        "pct_effort_covered": round(pct, 2),
    }


def latin_from_pairs(pairs) -> str | None:
    """Latin name for a common-name group, from its (genus, species) pairs.

    A cleaned species list contains genus-level units ("Plestiodon Species")
    and one lumped pair ("Peromyscus or Ochrotomys Species"). Those get a
    genus-level name or none at all rather than an invented binomial.

    A binomial is published only when EVERY row of the group carries the same
    one. A group whose rows are a mix of bare genus and one named epithet --
    "Plestiodon Species", where some individuals were resolved to laticeps and
    others were not -- is a genus-level unit, and naming it for the epithet
    that happens to appear would assert an identification the researcher
    deliberately declined to make.
    """
    genera = sorted({g for g, _ in pairs if g})
    full = sorted({f"{g} {s}" for g, s in pairs if g and s})
    if len(full) == 1 and all(s for _, s in pairs) and len(genera) == 1:
        return full[0]
    if len(genera) == 1:
        return f"{genera[0]} sp."
    if genera:
        return " / ".join(f"{g} sp." for g in genera)
    return None


def write_json(name: str, payload) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    with p.open("w") as fh:
        json.dump(payload, fh, separators=(",", ":"), sort_keys=False,
                  allow_nan=False)
    log(f"wrote {p.relative_to(ROOT)}  ({p.stat().st_size/1024:.1f} KB)")


# --------------------------------------------------------------------------
# 1. AHDriFT bucket cameras -- from the researcher's cleaned detection table
# --------------------------------------------------------------------------
def build_ahdrift() -> dict:
    """Species, activity, effort and rate-vs-occupancy for the bucket cameras.

    The cleaned table carries one row per motion-capture detection event and
    one "No Detections" row per surveyed plot-day, so the plot-day set IS the
    survey effort: every plot-day in the file was reviewed, and the ones that
    produced nothing are explicitly recorded rather than inferred from gaps.
    That is what makes an honest detection rate and naive occupancy possible
    here, which the Wildlife Insights export alone does not support.

    Detection events are the unit throughout. ``n.Seq`` and ``Max.Group.Size``
    are zero in every row of the current export, so neither is used; counting
    rows is the only defensible unit and the published note says so.
    """
    df = pd.read_csv(AH_CSV)
    n_rows_raw = len(df)

    df["plot"] = df["Plot.ID"].astype(str).str.strip()
    df["plot_type"] = df["plot"].map(plot_type_of)
    df["Class"] = df["Class"].astype(str).str.strip()
    df["common_name"] = df["Common.Name"].astype(str).str.strip()
    df["huts"] = pd.to_numeric(df["Huts.Active"], errors="coerce").fillna(0)

    blank = df["common_name"].str.lower() == "no detections"
    det = df.loc[~blank].copy()
    n_seq_col_unused = bool((pd.to_numeric(df["n.Seq"], errors="coerce")
                             .fillna(0) == 0).all())

    # ---- effort: one record per plot, from the plot-day rows ---------------
    # Huts.Active is constant within a plot-day in the current export, so the
    # first value per plot-day is the whole story.
    pday = (df.groupby(["plot", "Date"])
              .agg(huts=("huts", "max"), plot_type=("plot_type", "first"))
              .reset_index())
    effort_rows = []
    for plot, g in pday.groupby("plot"):
        effort_rows.append({
            "view": "bucket_camera",
            "deployment_id": plot,
            "plot": plot,
            "plot_type": g["plot_type"].iloc[0],
            "sensor_type": "AHDriFT",
            "start": str(g["Date"].min()),
            "end": str(g["Date"].max()),
            "days": int(len(g)),
            "hut_days": int(g["huts"].sum()),
            "functioning": None,
        })
    effort_rows.sort(key=lambda r: r["plot"])
    total_array_days = sum(r["days"] for r in effort_rows)
    total_hut_days = sum(r["hut_days"] for r in effort_rows)
    sites = sorted({r["plot"] for r in effort_rows})
    n_sites = len(sites)

    # ---- timestamps -------------------------------------------------------
    # Time.Start is written with a trailing Z but holds camera-local clock
    # time, so it is read with no UTC conversion. Checked at record level
    # rather than by eye: joining each cleaned detection to the Wildlife
    # Insights AHDriFT sequences on (plot, instant) matches all 1,707 with no
    # offset, while a +/-4 h shift matches 1 of 1,707. Treating the Z as real
    # would move every curve four hours and turn a nocturnal small-mammal
    # peak into an afternoon one.
    ts = pd.to_datetime(det["Time.Start"], format="ISO8601", errors="coerce",
                        utc=True)
    det["hour"] = ts.dt.hour
    det["minute"] = ts.dt.minute
    det["second"] = ts.dt.second
    det["day"] = ts.dt.strftime("%Y-%m-%d")
    n_no_time = int(ts.isna().sum())

    # ---- per-species rows -------------------------------------------------
    species = []
    point_counts = defaultdict(Counter)   # plot -> species -> n

    for name, g in det.groupby("common_name"):
        klass = next((c for c in g["Class"] if c and c != "nan"), None)
        pairs = [(str(a).strip() if pd.notna(a) else None,
                  str(b).strip() if pd.notna(b) else None)
                 for a, b in zip(g["Genus"], g["Species"])]
        pairs = [(a if a not in (None, "nan", "NA") else None,
                  b if b not in (None, "nan", "NA") else None)
                 for a, b in pairs]

        by_plot_type = Counter(g["plot_type"].dropna())
        by_plot = Counter(g["plot"])
        for p, n in by_plot.items():
            point_counts[p][name] += int(n)

        act = accumulate_activity(g["plot_type"], g["hour"], g["minute"],
                                  g["second"], g["day"])

        n_det = int(len(g))
        n_sites_det = int(g["plot"].nunique())
        species.append({
            "common_name": str(name),
            "latin_name": latin_from_pairs(pairs),
            "class": klass,
            "order": None,
            "n_detections": n_det,
            "n_plots": n_sites_det,
            "by_plot_type": {k: int(v) for k, v in by_plot_type.items()},
            "by_plot": {k: int(v) for k, v in sorted(by_plot.items())},
            "naive_occupancy_pct": (round(100 * n_sites_det / n_sites, 1)
                                    if n_sites else None),
            "n_sites_detected": n_sites_det,
            "detection_rate_per_100": (round(100 * n_det / total_hut_days, 3)
                                       if total_hut_days else None),
            "activity": pack_anchored_activity(act),
            "n_activity_binned": int(sum(sum(v) for v
                                         in act["clock"].values())),
        })
    species.sort(key=lambda r: -r["n_detections"])

    by_class = []
    for k in sorted({s["class"] for s in species if s["class"]},
                    key=class_rank):
        rows = [s for s in species if s["class"] == k]
        by_class.append({
            "class": k,
            "label": CLASS_LABELS.get(k, k),
            "n_species": len(rows),
            "n_detections": sum(r["n_detections"] for r in rows),
        })

    payload = {
        "source": "data/Clean_AHDriFT_Data/ahdrift_data_cleaned.csv",
        "unit": "detection events",
        "note": (
            "One detection event is one motion-capture sequence of one taxon "
            "at one AHDriFT array, identified by the researcher. Every "
            "motion-capture image in the 2026 season has been reviewed, and "
            "plot-days that produced no detection are recorded explicitly, "
            "so these counts are complete for the species on the cleaned "
            "list rather than a work-in-progress tally."
        ),
        "counting_note": (
            "Events are counted as rows. The cleaned export carries 0 in "
            "both n.Seq and Max.Group.Size for every row, so neither a "
            "sequence count nor a group size is used anywhere on this "
            "dashboard."
            if n_seq_col_unused else
            "Events are counted as rows of the cleaned export."
        ),
        "n_species": len(species),
        "n_identified_sequences": int(len(det)),
        "n_detections": int(len(det)),
        "n_coarse_sequences": 0,
        "coarse_note": (
            "The cleaned list is the researcher's final species set for the "
            "bucket cameras, so nothing is filtered out here. Three of its "
            "entries are deliberately genus- or group-level "
            "(\"Plestiodon Species\", \"Tree Frog Species\", \"Peromyscus or "
            "Ochrotomys Species\") because those animals cannot be separated "
            "reliably in a bucket photograph."
        ),
        "n_rows_raw": n_rows_raw,
        "n_blank_plot_days": int(blank.sum()),
        "n_plot_days": int(len(pday)),
        "n_plot_days_with_detections": int(det.groupby(["plot", "Date"])
                                           .ngroups),
        "n_events_without_time": n_no_time,
        "date_range": {"first": str(df["Date"].min()),
                       "last": str(df["Date"].max())},
        "by_class": by_class,
        "effort_unit": "hut-days",
        "by_plot_type": [
            {"plot_type": pt,
             "n_detections": int((det["plot_type"] == pt).sum()),
             "n_species": int(det.loc[det["plot_type"] == pt,
                                      "common_name"].nunique()),
             "n_plots": int(pday.loc[pday["plot_type"] == pt, "plot"]
                            .nunique()),
             "hut_days": int(sum(r["hut_days"] for r in effort_rows
                                 if r["plot_type"] == pt)),
             "effort": int(sum(r["hut_days"] for r in effort_rows
                               if r["plot_type"] == pt))}
            for pt in PLOT_TYPE_ORDER
        ],
        "species": species,
        "rate": {
            "unit": "detection events per 100 hut-days",
            "denominator": total_hut_days,
            "denominator_unit": "hut-days",
            "note": (
                "An AHDriFT array is one or two camera huts at a plot; "
                f"{total_hut_days:,} hut-days were surveyed over "
                f"{total_array_days:,} array-days at {n_sites} plots. "
                "Detection rate divides a species' events by that total, so "
                "plots that ran one hut instead of two are not credited with "
                "twice the opportunity. Naive occupancy is the percentage of "
                f"the {n_sites} plots where the species was detected at least "
                "once -- an observed proportion, uncorrected for imperfect "
                "detection, so it is a floor on true occupancy, not an "
                "estimate of it."
            ),
            "n_sites": n_sites,
            "site_unit": "plot",
            "total_array_days": total_array_days,
            "total_hut_days": total_hut_days,
        },
        "activity": {
            "bins": ACT_BINS,
            "bin_seconds": ACT_BIN_SECONDS,
            "effort_mode": "uniform",
            "anchors": uniform_anchor_meta(),
            "anchor_note": ANCHOR_NOTE,
            "note": (
                "Bucket cameras run continuously, so detection times need no "
                "effort correction: every half-hour of the day was watched "
                "equally. Curves are kernel-smoothed half-hour histograms of "
                "local clock time, scaled so each one integrates to 1 over "
                "the 24-hour cycle, which is what makes plot types with very "
                "different detection totals comparable in shape."
            ),
            "timestamp_note": (
                f"Time.Start in the cleaned export is written with a trailing "
                f"Z but holds camera-local clock time, not UTC. Read with no "
                f"conversion, all {len(det):,} detection events match a "
                f"Wildlife Insights sequence at the same plot and the same "
                f"instant; applying a 4-hour UTC-to-local shift in either "
                f"direction matches 1 of {len(det):,}. The curves are "
                f"therefore on the clock the cameras recorded."
            ),
        },
    }
    return payload, effort_rows, dict(point_counts)


# --------------------------------------------------------------------------
# 2. Parallel camera traps -- Wildlife Insights sequences, CT deployments only
# --------------------------------------------------------------------------
def build_camera_traps(loc: pd.DataFrame) -> tuple[dict, list, dict, dict]:
    """Species, activity, effort and rate-vs-occupancy for the parallel cameras.

    The Wildlife Insights export is now used for the camera traps ONLY. Its
    AHDriFT rows are superseded by the cleaned bucket-camera table, which
    carries the researcher's final identifications and the blank plot-days
    that the export does not record.
    """
    cols = ["deployment_id", "sequence_id", "is_blank", "identified_by",
            "class", "order", "family", "genus", "species", "common_name",
            "group_size", "start_time"]
    seq = pd.read_csv(WI_DIR / "sequences.csv", usecols=cols, low_memory=False)
    n_seq_total = len(seq)
    seq["sensor_type"] = seq["deployment_id"].map(sensor_type_of)
    n_ahdrift_rows = int((seq["sensor_type"] == "AHDriFT").sum())

    dep = pd.read_csv(WI_DIR / "deployments.csv", low_memory=False)
    dep["sensor_type"] = dep["placename"].map(sensor_type_of)
    dep["plot"] = dep["placename"].map(plot_code)
    dep["plot_type"] = dep["placename"].map(plot_type_of)
    dep["key"] = dep["placename"].map(norm_key)
    lut = dict(zip(loc["key"], loc["plot_type"]))
    dep["plot_type"] = dep["plot_type"].fillna(dep["key"].map(lut))
    dep["start"] = pd.to_datetime(dep["start_date"], errors="coerce")
    dep["end"] = pd.to_datetime(dep["end_date"], errors="coerce")
    dep["days"] = (dep["end"] - dep["start"]).dt.total_seconds() / 86400.0

    ct_dep = dep.loc[dep["sensor_type"] == "Camera Trap"].copy()
    n_dep_raw = len(ct_dep)
    bad = ct_dep["days"].isna() | (ct_dep["days"] <= 0) | ct_dep["plot_type"].isna()
    ct_dep = ct_dep.loc[~bad].copy()

    effort_rows = [{
        "view": "parallel_camera",
        "deployment_id": str(r.deployment_id),
        "plot": r.plot,
        "point": str(r.placename),
        "point_key": r.key,
        "plot_type": r.plot_type,
        "sensor_type": "Camera Trap",
        "start": r.start.strftime("%Y-%m-%d"),
        "end": r.end.strftime("%Y-%m-%d"),
        "days": round(float(r.days), 1),
        "functioning": (str(r.camera_functioning)
                        if pd.notna(r.camera_functioning) else None),
    } for r in ct_dep.itertuples()]
    effort_rows.sort(key=lambda r: (r["plot_type"] or "", -r["days"]))

    # Sites for naive occupancy are camera POINTS, not plots: a plot carries
    # three to six parallel cameras and each is an independent station.
    site_days = defaultdict(float)
    site_meta = {}
    for r in effort_rows:
        site_days[r["point_key"]] += r["days"]
        site_meta.setdefault(r["point_key"],
                             {"point": r["point"], "plot": r["plot"],
                              "plot_type": r["plot_type"]})
    n_sites = len(site_days)
    total_camera_days = sum(site_days.values())

    # ---- identifications --------------------------------------------------
    ident = seq["identified_by"].fillna("")
    seq["human_reviewed"] = (ident != "") & (ident != "Computer vision")
    reviewers = {x for x in ident if x and x != "Computer vision"}
    n_reviewed = int(seq["human_reviewed"].sum())

    ct = seq.loc[(seq["sensor_type"] == "Camera Trap")
                 & seq["human_reviewed"]].copy()
    dep_point = dict(zip(dep["deployment_id"], dep["placename"]))
    ct["point"] = ct["deployment_id"].map(dep_point)
    ct["point_key"] = ct["point"].map(norm_key)
    ct["plot"] = ct["deployment_id"].map(plot_code)
    ct["plot_type"] = ct["deployment_id"].map(plot_type_of)
    ct["latin"] = (ct["genus"].fillna("").astype(str).str.strip() + " " +
                   ct["species"].fillna("").astype(str).str.strip()).str.strip()
    cts = pd.to_datetime(ct["start_time"], errors="coerce")
    ct["hour"] = cts.dt.hour
    ct["minute"] = cts.dt.minute
    ct["second"] = cts.dt.second
    ct["day"] = cts.dt.strftime("%Y-%m-%d")

    keep = ct["common_name"].map(is_species_label)
    sp = ct.loc[keep].copy()
    coarse = ct.loc[~keep & ct["common_name"].notna()]

    species = []
    point_counts = defaultdict(Counter)
    for name, g in sp.groupby("common_name"):
        klass = next((x for x in g["class"].dropna() if x), None)
        by_plot_type = Counter(g["plot_type"].dropna())
        by_point = Counter(g["point_key"].dropna())
        for p, n in by_point.items():
            point_counts[p][name] += int(n)

        act = accumulate_activity(g["plot_type"], g["hour"], g["minute"],
                                  g["second"], g["day"])

        n_det = int(len(g))
        det_sites = {k for k in by_point if k in site_days}
        species.append({
            "common_name": str(name),
            "latin_name": next((x for x in g["latin"] if x), None),
            "class": str(klass) if klass else None,
            "order": (str(g["order"].dropna().iloc[0])
                      if g["order"].notna().any() else None),
            "n_sequences": n_det,
            "n_detections": n_det,
            "n_plots": int(g["plot"].nunique()),
            "by_plot_type": {k: int(v) for k, v in by_plot_type.items()},
            "by_point": {site_meta[k]["point"]: int(v)
                         for k, v in sorted(by_point.items())
                         if k in site_meta},
            "n_sites_detected": len(det_sites),
            "naive_occupancy_pct": (round(100 * len(det_sites) / n_sites, 1)
                                    if n_sites else None),
            "detection_rate_per_100": (round(100 * n_det / total_camera_days, 3)
                                       if total_camera_days else None),
            "activity": pack_anchored_activity(act),
            "n_activity_binned": int(sum(sum(v) for v
                                         in act["clock"].values())),
        })
    species.sort(key=lambda r: -r["n_sequences"])

    by_class = []
    for k in sorted({s["class"] for s in species if s["class"]},
                    key=class_rank):
        rows = [s for s in species if s["class"] == k]
        by_class.append({
            "class": k,
            "label": CLASS_LABELS.get(k, k),
            "n_species": len(rows),
            "n_detections": sum(r["n_sequences"] for r in rows),
        })

    payload = {
        "source": "data/WI_Download/sequences.csv (CT deployments only)",
        "unit": "sequences",
        "note": (
            "A Wildlife Insights sequence is one identification unit -- a "
            "burst of images of one species at one camera -- not a count of "
            "individual animals. Only human-reviewed sequences are counted; "
            "vehicle, blank and human labels are excluded."
        ),
        "n_species": len(species),
        "n_identified_sequences": int(len(sp)),
        "n_detections": int(len(sp)),
        "n_coarse_sequences": int(len(coarse)),
        "coarse_note": (
            "Sequences identified only to a coarse group (\"Bird\", "
            "\"Rodent\", \"Rabbit and Hare Family\") or to a non-wildlife "
            "label (vehicle, human, blank) are counted here and excluded "
            "from the species chart."
        ),
        "by_class": by_class,
        "effort_unit": "camera-days",
        "by_plot_type": [
            {"plot_type": pt,
             "n_sequences": int((sp["plot_type"] == pt).sum()),
             "n_detections": int((sp["plot_type"] == pt).sum()),
             "n_species": int(sp.loc[sp["plot_type"] == pt,
                                     "common_name"].nunique()),
             "n_sites": sum(1 for v in site_meta.values()
                            if v["plot_type"] == pt),
             "camera_days": round(sum(d for k, d in site_days.items()
                                      if site_meta[k]["plot_type"] == pt), 1),
             "effort": round(sum(d for k, d in site_days.items()
                                 if site_meta[k]["plot_type"] == pt), 1)}
            for pt in PLOT_TYPE_ORDER
        ],
        "species": species,
        "rate": {
            "unit": "sequences per 100 camera-days",
            "denominator": round(total_camera_days, 1),
            "denominator_unit": "camera-days",
            "note": (
                f"{total_camera_days:,.0f} camera-days were logged across "
                f"{n_sites} parallel-camera stations. Detection rate divides "
                "a species' sequences by that total. Naive occupancy is the "
                f"percentage of the {n_sites} stations -- not the "
                "50 plots -- where the species was detected at least once, "
                "an observed proportion uncorrected for imperfect detection, "
                "so a floor on true occupancy rather than an estimate of it."
            ),
            "n_sites": n_sites,
            "site_unit": "camera station",
            "total_camera_days": round(total_camera_days, 1),
        },
        "activity": {
            "bins": ACT_BINS,
            "bin_seconds": ACT_BIN_SECONDS,
            "effort_mode": "uniform",
            "anchors": uniform_anchor_meta(),
            "anchor_note": ANCHOR_NOTE,
            "note": (
                "Parallel cameras run continuously, so detection times need "
                "no effort correction. Curves are kernel-smoothed half-hour "
                "histograms of camera-local clock time, scaled so each "
                "integrates to 1 over the 24-hour cycle."
            ),
        },
    }

    progress = {
        "n_sequences_total": int(n_seq_total),
        "n_sequences_human_reviewed": n_reviewed,
        "pct_human_reviewed": round(100 * n_reviewed / n_seq_total, 2),
        "n_sequences_ahdrift_in_export": n_ahdrift_rows,
        "n_images_uploaded": sum(count_lines(p)
                                 for p in sorted(WI_DIR.glob("images_*.csv"))),
        # Reviewer identities are deliberately not published: per-person
        # sequence counts are individual productivity data, not a result.
        "n_reviewers": len(reviewers),
        "n_ct_deployment_rows_raw": n_dep_raw,
        "n_ct_deployment_rows_used": len(effort_rows),
        "note": (
            "Sequences are the Wildlife Insights identification unit. The "
            "export's AHDriFT rows are no longer used for the bucket-camera "
            "view: those identifications are superseded by the cleaned "
            "AHDriFT table, which also records the plot-days that produced "
            "no detection."
        ),
    }
    site_payload = {k: {**v, "days": round(d, 1)}
                    for k, (v, d) in ((k, (site_meta[k], site_days[k]))
                                      for k in site_days)}
    return payload, effort_rows, dict(point_counts), {"sites": site_payload,
                                                      "progress": progress}


# --------------------------------------------------------------------------
# 3. BirdNET -- per-species confidence cutoffs from manual validation
# --------------------------------------------------------------------------
# Every species label in the BirdNET output has a row in BirdNet_Thresholds.csv.
# Four states exist in that file, and they are not interchangeable, so each
# becomes its own group on the dashboard rather than being averaged together.
BN_GROUPS = [
    ("validated", "Validated birds",
     "Cutoff applied",
     "150 clips were reviewed per species and the confidence at which 95% of "
     "detections are true positives was recorded. Only detections at or above "
     "that species-specific cutoff are shown."),
    ("no_cutoff", "Birds with no attainable cutoff",
     "Cutoff not found",
     "Listening found no confidence at which 95% of detections were true "
     "positives, so these species carry a nominal threshold of 1.0. No "
     "filtered count can be published for them; the raw detections are shown "
     "and must not be treated as occurrences."),
    ("frogs", "Frogs and toads",
     "Not yet validated",
     "Anuran detections have not been validated, so no cutoff exists and no "
     "filter is applied. These are raw classifier hits at the 0.2 confidence "
     "floor and the false-positive rate is unknown."),
    ("pending", "Birds awaiting validation",
     "Not yet validated",
     "These species are in the validation queue but have not been reviewed "
     "yet, so no cutoff exists and no filter is applied."),
    ("other", "Anthropogenic and domestic labels",
     "Not wildlife",
     "Engine, gunshot, human and domestic-dog labels. Kept visible because "
     "they are a real part of the soundscape and a known source of "
     "false positives in the bird classes, but excluded from every species "
     "and activity figure."),
]


def load_thresholds() -> dict:
    """species label -> {group, threshold, validation tallies}."""
    th = pd.read_csv(TH_CSV)
    th.columns = [c.strip() for c in th.columns]
    out = {}
    for _, r in th.iterrows():
        name = str(r["Common Name"]).strip()
        if not name:
            continue
        klass = str(r.get("class") or "").strip()
        cut = pd.to_numeric(pd.Series([r.get("Threshold")]),
                            errors="coerce").iloc[0]
        done = str(r.get("Completed") or "").strip().upper()
        pos = pd.to_numeric(pd.Series([r.get("Positive")]),
                            errors="coerce").fillna(0).iloc[0]
        neg = pd.to_numeric(pd.Series([r.get("Negative")]),
                            errors="coerce").fillna(0).iloc[0]
        skip = pd.to_numeric(pd.Series([r.get("Skipped")]),
                             errors="coerce").fillna(0).iloc[0]

        if klass == "Anthropogenic" or name == "Dog":
            group = "other"
        elif pd.notna(cut) and cut >= 1.0:
            group = "no_cutoff"
        elif pd.notna(cut):
            group = "validated"
        elif klass == "Amphibia":
            group = "frogs"
        else:
            group = "pending"

        notes = r.get("Other notes")
        out[name] = {
            "group": group,
            "threshold": (round(float(cut), 3)
                          if pd.notna(cut) and cut < 1.0 else None),
            "class_in_log": klass or None,
            "completed": done or None,
            "n_listened": int(pos + neg + skip),
            "n_positive": int(pos),
            "n_negative": int(neg),
            "n_skipped": int(skip),
            "reviewer_note": (str(notes).strip()
                              if isinstance(notes, str) and notes.strip()
                              else None),
        }
    return out


def build_birdnet() -> dict:
    """Species tallies, validation groups and activity curves from BirdNET.

    One streaming pass over the 777 MB detection table collects, per species,
    raw and retained counts, plot and plot-type tallies and a half-hour
    activity histogram, and in parallel collects one record per recording file
    so that recording effort per half-hour can be reconstructed.

    The effort reconstruction matters more here than anywhere else on the
    dashboard. ARU effort is NOT uniform across the day: the schedule runs
    roughly 1,800 five-minute recordings per hour through the night and a
    60-minute recording over the dawn chorus, but only about 65 recordings in
    total across the whole season for each midday hour. A raw histogram of
    detection times would therefore show a dawn spike and an empty afternoon
    that are largely artefacts of when the recorders were switched on, so the
    published activity figure is detections per recording-hour.
    """
    thresholds = load_thresholds()

    sp_raw = Counter()
    sp_ret = Counter()
    sp_meta = {}
    sp_plots = defaultdict(set)
    sp_plot_type = defaultdict(Counter)
    sp_plot = defaultdict(Counter)
    sp_act = defaultdict(
        lambda: {x: defaultdict(empty_bins) for x in ACT_ANCHORS})
    conf_hist = Counter()            # 0.05-wide confidence bins, all species
    plot_dates = defaultdict(set)
    plot_type_of_plot = {}
    file_max = {}
    file_meta = {}
    n_rows = 0
    unlisted = Counter()

    usecols = ["Plot", "Plot.Type", "Date", "Rec.Hour", "Rec.Min", "Start.sec",
               "End.sec", "Species", "Confidence", "Latin.Name", "class",
               "order", "File"]
    for chunk in pd.read_csv(BN_CSV, usecols=usecols, chunksize=750_000,
                             low_memory=False):
        n_rows += len(chunk)
        chunk = chunk.dropna(subset=["Species"]).copy()
        chunk["Species"] = chunk["Species"].astype(str).str.strip()
        chunk["conf"] = pd.to_numeric(chunk["Confidence"],
                                      errors="coerce").fillna(0.0)
        chunk["pt"] = chunk["Plot.Type"].map(
            lambda c: PLOT_TYPES.get(str(c).strip(), str(c).strip()))

        # recording-file inventory for the effort denominator
        fg = chunk.groupby("File").agg(mx=("End.sec", "max"),
                                       h=("Rec.Hour", "first"),
                                       m=("Rec.Min", "first"),
                                       pt=("pt", "first"),
                                       plot=("Plot", "first"),
                                       date=("Date", "first"))
        for fname, r in fg.iterrows():
            prev = file_max.get(fname)
            mx = float(r["mx"]) if pd.notna(r["mx"]) else 0.0
            file_max[fname] = mx if prev is None else max(prev, mx)
            if fname not in file_meta:
                file_meta[fname] = (
                    int(r["h"]) if pd.notna(r["h"]) else 0,
                    int(r["m"]) if pd.notna(r["m"]) else 0,
                    r["pt"], str(r["plot"]), str(r["date"]))

        for sp, g in chunk.groupby("Species"):
            info = thresholds.get(sp)
            if info is None:
                unlisted[sp] += len(g)
                continue
            sp_raw[sp] += len(g)
            if sp not in sp_meta:
                latin = g["Latin.Name"].dropna()
                klass = g["class"].dropna()
                order = g["order"].dropna()
                sp_meta[sp] = {
                    "latin_name": str(latin.iloc[0]) if len(latin) else None,
                    "class": str(klass.iloc[0]) if len(klass) else None,
                    "order": str(order.iloc[0]) if len(order) else None,
                }
            cut = info["threshold"]
            keep = g if cut is None else g.loc[g["conf"] >= cut]
            if not len(keep):
                continue
            sp_ret[sp] += len(keep)
            sp_plots[sp].update(keep["Plot"].dropna().astype(str))
            for pt, n in keep["pt"].value_counts().items():
                sp_plot_type[sp][str(pt)] += int(n)
            for p, n in keep["Plot"].value_counts().items():
                sp_plot[sp][str(p)] += int(n)
            if info["group"] != "other":
                secs = ((pd.to_numeric(keep["Rec.Hour"], errors="coerce")
                         .fillna(0) * 3600
                         + pd.to_numeric(keep["Rec.Min"], errors="coerce")
                         .fillna(0) * 60
                         + pd.to_numeric(keep["Start.sec"], errors="coerce")
                         .fillna(0)) % 86400).astype(int)
                k = keep.assign(_s=secs, _d=keep["Date"].astype(str))
                # Group by (plot type, date, second) once and bin the groups:
                # the solar offset depends only on the date, so this collapses
                # 3.5 M per-row solar lookups into one per distinct date.
                sized = k.groupby(["pt", "_d", "_s"]).size()
                for (pt, day, sec), n in sized.items():
                    for anchor in ACT_ANCHORS:
                        bb = anchor_bin(anchor, day, sec)
                        if bb is not None:
                            sp_act[sp][anchor][str(pt)][bb] += int(n)

        conf_hist.update((chunk["conf"] // 0.05).astype(int)
                         .value_counts().to_dict())
        for (plot, pt), g in chunk.groupby(["Plot", "pt"]):
            plot_dates[str(plot)].update(g["Date"].dropna().astype(str))
            plot_type_of_plot[str(plot)] = str(pt)

    # ---- recording effort per half-hour bin, per plot type ----------------
    # Spread each recording over the bins it actually covers, once per anchor.
    # A file that starts 40 minutes before sunrise lands in different bins
    # under the solar anchors than under the clock, so the denominator has to
    # be rebuilt for each rather than rotated from the clock version: the
    # rotation differs by date, and a season's dates do not share one offset.
    def spread(target, pt, t, dur):
        """Add one recording's seconds to the bins it covers."""
        left = dur
        while left > 0:
            b = int(t // ACT_BIN_SECONDS) % ACT_BINS
            room = (b + 1) * ACT_BIN_SECONDS - t
            take = min(left, room)
            target[pt][b] += take
            t = (t + take) % 86400
            left -= take

    file_dur = {}
    file_count = defaultdict(int)
    n_long = 0
    for fname, mx in file_max.items():
        _h, _m, pt, _plot, _day = file_meta[fname]
        dur = ARU_LONG_SECONDS if mx > ARU_DURATION_SPLIT else ARU_SHORT_SECONDS
        file_dur[fname] = dur
        n_long += dur == ARU_LONG_SECONDS
        file_count[pt] += 1

    # Whether a recording was on schedule is a property of the RECORDING, not
    # of a bin, so it is settled once on the clock profile -- where the three
    # effort regimes separate cleanly -- and that verdict is then reused for
    # every anchor. Deriving it separately per anchor would re-apply a
    # threshold calibrated on the clock profile to a smeared one: anchoring on
    # sunset spreads the dawn chorus over the 3.2 h that night length varies,
    # which pushes genuinely scheduled bins under the cut and truncates the
    # window across the dawn peak.
    clock_all = defaultdict(lambda: [0] * ACT_BINS)
    for fname, dur in file_dur.items():
        h, m, pt, _plot, _day = file_meta[fname]
        spread(clock_all, pt, float((h * 3600 + m * 60) % 86400), dur)
    clock_total = [sum(clock_all[pt][b] for pt in clock_all)
                   for b in range(ACT_BINS)]
    clock_mask = derive_window(
        clock_total, min_fraction=ACT_MIN_EFFORT_FRACTION)["sampled"]
    on_schedule = {
        fname for fname in file_dur
        if clock_mask[((file_meta[fname][0] * 3600 + file_meta[fname][1] * 60)
                       % 86400) // ACT_BIN_SECONDS]
    }

    effort_by_anchor = {a: defaultdict(lambda: [0] * ACT_BINS)
                        for a in ACT_ANCHORS}
    sched_by_anchor = {a: defaultdict(lambda: [0] * ACT_BINS)
                       for a in ACT_ANCHORS}
    for fname, dur in file_dur.items():
        h, m, pt, _plot, day = file_meta[fname]
        start = (h * 3600 + m * 60) % 86400
        for anchor in ACT_ANCHORS:
            t = anchor_offset_seconds(anchor, day, start)
            if t is None:
                continue
            spread(effort_by_anchor[anchor], pt, t, dur)
            if fname in on_schedule:
                spread(sched_by_anchor[anchor], pt, t, dur)
    effort = effort_by_anchor["clock"]
    effort_hours = {pt: [round(s / 3600.0, 3) for s in arr]
                    for pt, arr in effort.items()}
    total_rec_hours = sum(sum(a) for a in effort_hours.values())

    # ---- which half-hours the schedule actually sampled -------------------
    # The recorders run a night schedule, not a 24-hour one, and the effort
    # profile separates into three clean regimes: scheduled night bins carry
    # 80-150 recorded hours each, the dawn-chorus hour reaches ~1,580, and the
    # middle of the day sits on a flat ~32-hour plateau contributed by a
    # handful of plots that also ran off-schedule daytime recordings.
    #
    # Those daytime bins must not be drawn. Dividing a handful of detections
    # by a near-zero denominator produces a rate with no useful precision, and
    # plotting it next to the dawn peak invites reading a sampling artefact as
    # a behavioural one. The cut is placed in the gap between the two regimes
    # rather than at a round number chosen by eye: the daytime plateau never
    # exceeds ~2.1% of the peak bin and no scheduled bin falls below ~3.6%.
    anchor_meta = {}
    off_counters = {}
    for anchor in ACT_ANCHORS:
        eff_a = effort_by_anchor[anchor]
        sch_a = sched_by_anchor[anchor]
        # The window is the span the SCHEDULED recordings cover under this
        # anchor; the denominator inside it still counts every recorded
        # second, including any off-schedule time that happens to fall there.
        sched_total = [sum(sch_a[pt][b] for pt in sch_a)
                       for b in range(ACT_BINS)]
        win = derive_window(
            sched_total, min_absolute=ACT_MIN_BIN_HOURS * 3600.0)
        samp = win["sampled"]
        bin_tot_a = [sum(eff_a[pt][b] for pt in eff_a) for b in range(ACT_BINS)]
        win["pct_effort_covered"] = round(
            100.0 * sum(v for b, v in enumerate(bin_tot_a) if samp[b])
            / sum(bin_tot_a), 2) if sum(bin_tot_a) else 0.0

        # The off-schedule recordings, named so they are accounted for rather
        # than silently cut. The set is the same under every anchor by
        # construction; the per-plot tally is reported from it.
        off_a = Counter()
        for fname in file_dur:
            if fname not in on_schedule:
                off_a[file_meta[fname][3]] += 1

        # How many detections the activity panel therefore leaves out.
        # Published rather than inferred: a reader comparing the activity
        # panel against the species chart can see the difference accounted for.
        d_in = d_out = 0
        for _sp, per_anchor in sp_act.items():
            for _pt, arr in per_anchor[anchor].items():
                for b, v in enumerate(arr):
                    if samp[b]:
                        d_in += v
                    else:
                        d_out += v

        off_counters[anchor] = off_a
        anchor_meta[anchor] = {
            "label": ANCHOR_LABELS[anchor],
            "sampled": samp,
            "anchor_bin": None if anchor == "clock" else ACT_ANCHOR_BIN,
            "effort": {pt: [round(s / 3600.0, 3) for s in arr]
                       for pt, arr in eff_a.items()},
            "window": window_extent(anchor, win),
            "off_schedule": {
                "n_recordings": int(sum(off_a.values())),
                "n_plots": len(off_a),
                "plots": [p for p, _ in off_a.most_common()],
                "n_detections_in_window": int(d_in),
                "n_detections_excluded": int(d_out),
                "pct_detections_excluded": (round(100.0 * d_out / (d_in + d_out), 2)
                                            if (d_in + d_out) else 0.0),
            },
        }

    # The clock anchor stays the one the surrounding payload reports, so the
    # existing summary fields keep their published meaning.
    clock_meta = anchor_meta["clock"]
    sampled = clock_meta["sampled"]
    off_plots = off_counters["clock"]
    n_off = clock_meta["off_schedule"]["n_recordings"]
    pct_covered = clock_meta["window"]["pct_effort_covered"]
    det_in = clock_meta["off_schedule"]["n_detections_in_window"]
    det_out = clock_meta["off_schedule"]["n_detections_excluded"]
    first_bin = clock_meta["window"]["start_bin"]
    last_bin = clock_meta["window"]["end_bin"]

    def clock(b):
        return bin_label("clock", b)

    # ---- per-species rows -------------------------------------------------
    species = []
    for sp, raw in sp_raw.most_common():
        info = thresholds[sp]
        meta = sp_meta.get(sp, {})
        ret = int(sp_ret.get(sp, 0))
        n_listened = info["n_listened"]
        species.append({
            "species": sp,
            "latin_name": meta.get("latin_name"),
            "class": meta.get("class") or info["class_in_log"],
            "order": meta.get("order"),
            "group": info["group"],
            "threshold": info["threshold"],
            "filtered": info["threshold"] is not None,
            "n_detections_raw": int(raw),
            "n_detections": ret,
            "pct_retained": (round(100 * ret / raw, 1) if raw else None),
            "n_plots": len(sp_plots[sp]),
            "by_plot_type": {k: int(v) for k, v in sp_plot_type[sp].items()},
            "by_plot": {k: int(v) for k, v in sorted(sp_plot[sp].items())},
            "activity": (pack_anchored_activity(sp_act[sp])
                         if sp in sp_act else {}),
            "validation": {
                "n_listened": n_listened,
                "n_positive": info["n_positive"],
                "n_negative": info["n_negative"],
                "n_skipped": info["n_skipped"],
                "completed": info["completed"],
                # The share of listened clips that were genuinely the species.
                # This is the outcome of a stratified listening exercise, not
                # the precision of the dataset, and is labelled as such
                # wherever it is displayed.
                "sample_positive_rate": (
                    round(info["n_positive"] / n_listened, 3)
                    if n_listened else None),
                "note": info["reviewer_note"],
            },
        })

    groups = []
    for gid, label, status, note in BN_GROUPS:
        rows = [s for s in species if s["group"] == gid]
        groups.append({
            "id": gid,
            "label": label,
            "status": status,
            "note": note,
            "n_species": len(rows),
            "n_detections_raw": sum(s["n_detections_raw"] for s in rows),
            "n_detections": sum(s["n_detections"] for s in rows),
            "filtered": gid == "validated",
            "classes": sorted({s["class"] for s in rows if s["class"]},
                              key=class_rank),
        })

    dates = sorted({d for ds in plot_dates.values() for d in ds})
    plots = [{"plot": p,
              "plot_type": plot_type_of_plot.get(p),
              "n_recording_days": len(plot_dates[p]),
              "first_date": min(plot_dates[p]),
              "last_date": max(plot_dates[p])}
             for p in sorted(plot_dates)]

    wildlife = [s for s in species if s["group"] != "other"]
    val = [s for s in species if s["group"] == "validated"]
    listened_total = sum(s["validation"]["n_listened"] for s in species)
    cuts = sorted(s["threshold"] for s in val if s["threshold"] is not None)

    point_counts = defaultdict(Counter)
    for s in wildlife:
        for p, n in s["by_plot"].items():
            point_counts[p][s["species"]] += int(n)

    payload = {
        "source": "data/Bird_Frog_Audio_Summaries/preliminary_BirdNET_Results.csv",
        "unit": "classifier detections",
        "note": (
            "BirdNET detections are classifier hits on 3-second windows, not "
            "verified occurrences. Bird species that have been validated are "
            "filtered to their own 95% confidence cutoff; every other group "
            "is raw and unfiltered. Counts are not corrected for recording "
            "effort, which differs among plots and, far more sharply, among "
            "hours of the day -- see the activity panel."
        ),
        "plot_label_note": (
            "Bird/frog ARUs at turbine plots are logged under the turbine "
            "code: each unit sits at the edge of the opening with the "
            "microphone aimed inward, sampling both the opening and the "
            "adjacent forest."
        ),
        "n_detections_total": int(n_rows),
        "n_detections_raw": int(sum(sp_raw.values())),
        "n_detections_retained": int(sum(sp_ret.values())),
        "n_species_total": len(species),
        "n_wildlife_species": len(wildlife),
        "confidence_floor": round(min(b * 0.05 for b in conf_hist), 2),
        "confidence_histogram": [{"lower": round(b * 0.05, 2), "n": int(n)}
                                 for b, n in sorted(conf_hist.items())],
        "labels_not_in_threshold_file": [{"species": k, "n": int(v)}
                                         for k, v in unlisted.most_common()],
        "groups": groups,
        "group_order": [g[0] for g in BN_GROUPS],
        "recording_window": {"first_date": dates[0] if dates else None,
                             "last_date": dates[-1] if dates else None,
                             "n_dates": len(dates)},
        "n_plots": len(plots),
        "plots": plots,
        "by_class": [
            {"class": k, "label": CLASS_LABELS.get(k, k),
             "n_species": sum(1 for s in wildlife if s["class"] == k),
             "n_detections": sum(s["n_detections"] for s in wildlife
                                 if s["class"] == k)}
            for k in sorted({s["class"] for s in wildlife if s["class"]},
                            key=class_rank)
        ],
        # Per-plot-type survey effort, so the species chart can be divided by
        # it. Recording HOURS rather than recorder-days is the denominator
        # that matches the detections: the schedule records a few hours a
        # night, and dividing a detection count by whole days would imply far
        # more listening than took place.
        "by_plot_type": [
            {"plot_type": pt,
             "n_plots": sum(1 for p in plots if p["plot_type"] == pt),
             "n_recording_days": sum(p["n_recording_days"] for p in plots
                                     if p["plot_type"] == pt),
             "recording_hours": round(sum(effort_hours.get(pt, [])), 1),
             "effort": round(sum(effort_hours.get(pt, [])), 1),
             "n_recordings": int(file_count.get(pt, 0)),
             "n_detections": sum(s["by_plot_type"].get(pt, 0)
                                 for s in wildlife)}
            for pt in PLOT_TYPE_ORDER
            if any(p["plot_type"] == pt for p in plots)
        ],
        "effort_unit": "recording-hours",
        "activity": {
            "bins": ACT_BINS,
            "bin_seconds": ACT_BIN_SECONDS,
            "effort_mode": "per_bin_hours",
            "effort_hours": effort_hours,
            "anchors": anchor_meta,
            "anchor_note": ANCHOR_NOTE,
            "solar_note": (
                f"Solar times are computed for the study site "
                f"({SITE_LAT:.2f} N, {abs(SITE_LON):.2f} W) with the NOAA "
                f"sunrise equation, one value per date. Across the plots the "
                f"spread in sunrise is a few seconds, well inside one "
                f"half-hour bin, so a single site position is used rather "
                f"than a per-plot calculation."
            ),
            # 1 where the schedule sampled that half-hour, 0 where it did not.
            # The frontend draws only the sampled run and normalises each curve
            # over it, so a density here is a density over the recorded window
            # and not over the 24-hour day.
            "sampled": sampled,
            "min_effort_fraction": ACT_MIN_EFFORT_FRACTION,
            "min_bin_hours": ACT_MIN_BIN_HOURS,
            "window": {
                "start_clock": clock(first_bin) if first_bin is not None else None,
                "end_clock": (clock((last_bin + 1) % ACT_BINS)
                              if last_bin is not None else None),
                "n_bins": int(sum(sampled)),
                "hours": round(sum(sampled) * ACT_BIN_SECONDS / 3600.0, 1),
                "pct_effort_covered": round(pct_covered, 2),
                "note": (
                    "The recorders ran a night schedule rather than a "
                    "24-hour one, so the activity curves are drawn only over "
                    "the half-hours the schedule actually sampled. The "
                    "schedule is solar-anchored, not a fixed clock time: the "
                    "first recording of the night shifts about 1.7 hours "
                    "later between March and August, tracking sunset. The "
                    "window below is therefore the seasonal envelope of a "
                    "moving window, and effort within it is uneven -- which "
                    "is exactly what the per-recording-hour correction "
                    "handles."
                ),
            },
            "off_schedule": {
                "n_recordings": int(n_off),
                "n_plots": len(off_plots),
                "plots": [p for p, _ in off_plots.most_common()],
                "n_detections_in_window": int(det_in),
                "n_detections_excluded": int(det_out),
                "pct_detections_excluded": (
                    round(100.0 * det_out / (det_in + det_out), 2)
                    if (det_in + det_out) else 0.0),
                "note": (
                    f"{n_off:,} recordings at {len(off_plots)} plots "
                    f"({', '.join(p for p, _ in off_plots.most_common(6))}) "
                    f"started outside the scheduled window, almost all of "
                    f"them hour-long daytime files. Their detections are "
                    f"still counted in the species and rate panels; they are "
                    f"excluded from the activity curves because a handful of "
                    f"plots recording through the middle of the day cannot "
                    f"describe the daily activity of the whole array."
                ),
            },
            "n_recordings": {k: int(v) for k, v in file_count.items()},
            "n_recordings_total": len(file_max),
            "n_recordings_long": int(n_long),
            "total_recording_hours": round(total_rec_hours, 1),
            "note": (
                "Recording effort is strongly uneven across the day: the "
                "schedule takes short recordings through the night, a long "
                "recording over the dawn chorus, and very few recordings at "
                f"all in the middle of the day. All {len(file_max):,} "
                "recordings were therefore reduced to recorded hours per "
                "half-hour of the clock, and the curves plot detections per "
                "recording-hour, not raw detections. Each curve is scaled to "
                "integrate to 1 over the recorded window so plot types are "
                "comparable in shape. Because that window is a night rather "
                "than a full cycle, the smoother does not wrap: dusk and the "
                "following morning are at opposite ends of the curve, not "
                "adjacent to one another."
            ),
            "duration_note": (
                "Recording length is inferred per file from the largest "
                "detection offset it contains: the two scheduled lengths "
                f"({ARU_SHORT_SECONDS} s and {ARU_LONG_SECONDS} s) separate "
                "cleanly, with no file in the dataset having a maximum offset "
                f"between {ARU_SHORT_SECONDS} and {ARU_DURATION_SPLIT} s. A "
                "long recording whose only detections fell in its first few "
                "minutes would be scored short, which would slightly "
                "under-state effort in the affected bin."
            ),
        },
        "validation": {
            "design": "listen_n_per_species_then_fixed_cutoff",
            "target_p": VALIDATION_TARGET_P,
            "n_listened_per_species": VALIDATION_N_PER_SPECIES,
            "n_species_in_log": len(thresholds),
            # Listening effort and cutoff yield are different counts and the
            # panel reports both. 47 species produced a usable cutoff, but
            # clips were reviewed for more than that: a species that never
            # reached the target was still listened to, and reporting only the
            # cutoff count understates the work done.
            "n_species_reviewed": sum(
                1 for s in species if s["validation"]["n_listened"] > 0),
            "n_species_full_quota": sum(
                1 for s in species
                if s["validation"]["n_listened"] >= VALIDATION_N_PER_SPECIES),
            "n_species_validated": len(val),
            "n_species_no_cutoff": sum(1 for s in species
                                       if s["group"] == "no_cutoff"),
            "n_species_pending": sum(1 for s in species
                                     if s["group"] == "pending"),
            "n_species_frogs": sum(1 for s in species
                                   if s["group"] == "frogs"),
            "n_clips_listened": listened_total,
            "n_clips_positive": sum(s["validation"]["n_positive"]
                                    for s in species),
            "n_clips_negative": sum(s["validation"]["n_negative"]
                                    for s in species),
            "n_clips_skipped": sum(s["validation"]["n_skipped"]
                                   for s in species),
            "cutoff_min": cuts[0] if cuts else None,
            "cutoff_median": (cuts[len(cuts) // 2] if cuts else None),
            "cutoff_max": cuts[-1] if cuts else None,
            "cutoff_at_floor": sum(1 for c in cuts if c <= 0.25),
            "n_detections_validated_raw": sum(s["n_detections_raw"]
                                              for s in val),
            "n_detections_validated_retained": sum(s["n_detections"]
                                                   for s in val),
            "pct_retained_validated": (
                round(100 * sum(s["n_detections"] for s in val)
                      / max(sum(s["n_detections_raw"] for s in val), 1), 1)),
            "note": (
                "For each species, 150 detections were reviewed by ear and "
                "the lowest confidence at which 95% of detections were true "
                "positives was recorded as that species' cutoff. The "
                "dashboard applies each cutoff to its own species. Five "
                "species never reached 95% at any confidence and carry a "
                "nominal 1.0 instead of a usable cutoff; anurans and the "
                "remaining birds have not been reviewed yet and are shown "
                "unfiltered."
            ),
            "sampling_note": (
                "The share of listened clips that were true positives "
                "describes the clips that were listened to, not the dataset: "
                "clips were drawn to pin down each species' cutoff, not as a "
                "random sample of its detections. Read it as validation "
                "effort, never as the precision of the published counts."
            ),
        },
        "species": species,
    }
    return payload, dict(point_counts)


# --------------------------------------------------------------------------
# 4. Locations, with per-point species tallies for the map popups
# --------------------------------------------------------------------------
def load_locations() -> pd.DataFrame:
    df = pd.read_csv(LOC_CSV)
    df["plot_type"] = df["Plot_Type"].map(canon_plot_type)
    df["plot"] = df["Point_Name"].map(plot_code)
    df["sensor_type"] = df["Point_type"].astype(str).str.strip()
    df["key"] = df["Point_Name"].map(norm_key)
    return df


def build_locations(df: pd.DataFrame, ah_counts: dict, ct_counts: dict,
                    aru_counts: dict, ah_effort: list, ct_sites: dict,
                    bn_plots: list) -> dict:
    """Published coordinates plus, per point, the species detected there.

    The three sensor streams resolve to different spatial units and the popup
    must not pretend otherwise. Parallel-camera sequences are attributed to
    the individual camera station. The cleaned AHDriFT table and the BirdNET
    output are both recorded at the plot, so their popups are labelled as
    plot totals -- there is exactly one AHDriFT array and one ARU per plot,
    so no information is lost, but the label still says which unit it is.
    """
    ah_days = {r["plot"]: r for r in ah_effort}
    bn_day = {p["plot"]: p for p in bn_plots}

    def listify(counter):
        """Species tally for one point, every species, largest first.

        Not truncated. An ARU plot carries sixty-odd species and the whole
        point of the popup is to be able to read what was recorded there, so
        the published list is complete and the frontend decides how much of it
        to show on hover versus on click. The cost is about 60 KB of JSON.
        """
        items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        return [{"name": k, "n": int(v)} for k, v in items]

    points = []
    displacements = []
    for _, r in df.iterrows():
        lat0, lon0 = float(r["y"]), float(r["x"])
        pid = str(r["Point_Name"])
        jlat, jlon = jitter(pid, lat0, lon0)
        displacements.append(math.hypot(
            (jlat - lat0) * 111_320.0,
            (jlon - lon0) * 111_320.0 * math.cos(math.radians(lat0))))

        entry = {
            "id": pid,
            "plot": r["plot"],
            "plot_type": r["plot_type"],
            "sensor_type": r["sensor_type"],
            "lat": jlat,
            "lon": jlon,
        }
        if r["sensor_type"] == "AHDriFT" and r["plot"] in ah_counts:
            c = ah_counts[r["plot"]]
            eff = ah_days.get(r["plot"], {})
            entry["detections"] = {
                "bucket_camera": {
                    "scope": "plot",
                    "scope_label": f"AHDriFT array at plot {r['plot']}",
                    "unit": "detection events",
                    "effort": (f"{eff.get('days', 0)} array-days, "
                               f"{eff.get('hut_days', 0)} hut-days"),
                    "n_detections": int(sum(c.values())),
                    "n_species": len(c),
                    "species": listify(c),
                }
            }
        if r["sensor_type"] != "AHDriFT" and r["key"] in ct_counts:
            c = ct_counts[r["key"]]
            site = ct_sites.get(r["key"], {})
            entry["detections"] = {
                "parallel_camera": {
                    "scope": "station",
                    "scope_label": f"Camera station {pid}",
                    "unit": "sequences",
                    "effort": (f"{site.get('days', 0)} camera-days"
                               if site else None),
                    "n_detections": int(sum(c.values())),
                    "n_species": len(c),
                    "species": listify(c),
                }
            }
        if r["sensor_type"] == "AHDriFT" and r["plot"] in aru_counts:
            c = aru_counts[r["plot"]]
            day = bn_day.get(r["plot"], {})
            entry.setdefault("detections", {})["bird_frog_audio"] = {
                "scope": "plot",
                "scope_label": f"ARU at plot {r['plot']}",
                "unit": "detections after validation filtering",
                "effort": (f"{day.get('n_recording_days', 0)} recording days"
                           if day else None),
                "n_detections": int(sum(c.values())),
                "n_species": len(c),
                "species": listify(c),
            }
        points.append(entry)

    d_lo, d_hi = min(displacements), max(displacements)
    d_med = sorted(displacements)[len(displacements) // 2]
    return {
        "precision_note": (
            f"Coordinates are deliberately obfuscated: each point is "
            f"displaced along a fixed pseudo-random bearing and rounded to "
            f"{COORD_DECIMALS} decimal places, putting every published marker "
            f"{d_lo:.0f}-{d_hi:.0f} m from its true position (median "
            f"{d_med:.0f} m). Marker positions are approximate by design and "
            f"cannot be used to navigate to a sensor or to infer where any "
            f"individual animal was detected."
        ),
        "displacement_m": {"min": round(d_lo, 1), "median": round(d_med, 1),
                           "max": round(d_hi, 1)},
        "jitter_min_m": JITTER_MIN_M,
        "jitter_max_m": JITTER_MAX_M,
        "popup_note": (
            "Hovering a marker lists every species recorded by that sensor "
            "and how many times. Parallel-camera tallies belong to the "
            "individual camera station; AHDriFT and ARU tallies belong to the "
            "plot, which carries one array and one recorder respectively."
        ),
        "n_points": len(points),
        "n_plots": int(df["plot"].nunique()),
        "counts": [
            {"plot_type": r.plot_type, "sensor_type": r.sensor_type,
             "n": int(r.n)}
            for r in (df.groupby(["plot_type", "sensor_type"]).size()
                        .reset_index(name="n").itertuples())
        ],
        "points": points,
    }


# --------------------------------------------------------------------------
# 5. Effort
# --------------------------------------------------------------------------
def build_effort(ah_rows: list, ct_rows: list, ahdrift: dict,
                 parallel: dict) -> dict:
    records = ah_rows + ct_rows
    summary = {}
    for view, rows in (("bucket_camera", ah_rows),
                       ("parallel_camera", ct_rows)):
        per_type = defaultdict(lambda: {"n": 0, "days": 0.0})
        for r in rows:
            per_type[r["plot_type"]]["n"] += 1
            per_type[r["plot_type"]]["days"] += r["days"]
        days = sorted(r["days"] for r in rows)
        summary[view] = {
            "n_deployments": len(rows),
            "total_sensor_days": round(sum(days), 1),
            "mean_days": round(sum(days) / len(days), 1) if days else 0,
            "median_days": round(days[len(days) // 2], 1) if days else 0,
            "min_days": round(days[0], 1) if days else 0,
            "max_days": round(days[-1], 1) if days else 0,
            "unit_label": ("AHDriFT array (one per plot)"
                           if view == "bucket_camera"
                           else "camera deployment"),
            "by_plot_type": [
                {"plot_type": k, "n_deployments": v["n"],
                 "sensor_days": round(v["days"], 1)}
                for k, v in sorted(
                    per_type.items(),
                    key=lambda kv: (PLOT_TYPE_ORDER.index(kv[0])
                                    if kv[0] in PLOT_TYPE_ORDER else 99))
            ],
            "functioning": dict(Counter(r["functioning"] or "Unknown"
                                        for r in rows)),
        }
    summary["bucket_camera"]["total_hut_days"] = sum(
        r.get("hut_days", 0) for r in ah_rows)

    return {
        "note": (
            "Bucket-camera effort is one bar per AHDriFT array -- the plot-"
            "days actually reviewed in the cleaned detection table, which is "
            "the same denominator the detection rates use. Parallel-camera "
            "effort is one bar per deployment (a camera at one station over "
            "one date window). The two are not comparable units and are "
            "never summed."
        ),
        "n_deployment_rows_raw": len(records),
        "n_deployment_rows_used": len(records),
        "summary": summary,
        "deployments": records,
    }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main() -> int:
    if not RAW.exists():
        print(f"ERROR: data directory not found: {RAW}", file=sys.stderr)
        return 1

    print("Timbermill dashboard :: building summaries")

    print("[1/5] AHDriFT bucket cameras (cleaned detection table)")
    ahdrift, ah_rows, ah_counts = build_ahdrift()
    write_json("species_ahdrift.json", ahdrift)

    print("[2/5] parallel camera traps (Wildlife Insights)")
    loc_df = load_locations()
    parallel, ct_rows, ct_counts, ct_extra = build_camera_traps(loc_df)
    write_json("species_parallel.json", parallel)

    print("[3/5] BirdNET acoustic detections")
    birdnet, aru_counts = build_birdnet()
    write_json("birdnet.json", birdnet)

    print("[4/5] locations and effort")
    loc_payload = build_locations(loc_df, ah_counts, ct_counts, aru_counts,
                                  ah_rows, ct_extra["sites"],
                                  birdnet["plots"])
    write_json("locations.json", loc_payload)
    effort = build_effort(ah_rows, ct_rows, ahdrift, parallel)
    write_json("effort.json", effort)

    print("[5/5] manifest")
    media_path = OUT / "media.json"
    media = {}
    if media_path.exists():
        try:
            media = json.loads(media_path.read_text())
        except json.JSONDecodeError:
            log("WARNING: media.json is present but unparseable")

    def media_count(view: str) -> int:
        return len(media.get("views", {}).get(view, {}).get("items", []))

    # ---- data gaps -------------------------------------------------------
    mappable_plots = {p["plot"] for p in loc_payload["points"] if p["plot"]}
    mapped_keys = {norm_key(p["id"]) for p in loc_payload["points"]}
    gaps = []
    for p in birdnet["plots"]:
        if p["plot"] not in mappable_plots:
            gaps.append({
                "kind": "missing_location", "id": p["plot"],
                "detail": (f"ARU plot {p['plot']} has {p['n_recording_days']} "
                           f"recording days in the BirdNET output "
                           f"({p['first_date']} to {p['last_date']}) but no "
                           f"entry in the location table, so it cannot be "
                           f"mapped."),
            })
    unmapped_ct = sorted({r["point"] for r in ct_rows
                          if r["point_key"] not in mapped_keys})
    if unmapped_ct:
        gaps.append({
            "kind": "missing_location", "id": ", ".join(unmapped_ct),
            "detail": (f"{len(unmapped_ct)} parallel-camera station(s) "
                       f"({', '.join(unmapped_ct)}) have Wildlife Insights "
                       f"deployments but no row in "
                       f"cam_trap_locations_info.csv, so they contribute "
                       f"effort and detections but no marker."),
        })
    # A species carrying a threshold decision but no logged clip counts: the
    # log says it was adjudicated, the counts say nothing was reviewed. One of
    # the two is incomplete and only the researcher knows which.
    unlogged = sorted(
        s["species"] for s in birdnet["species"]
        if s["group"] in ("validated", "no_cutoff")
        and not s["validation"]["n_listened"])
    if unlogged:
        gaps.append({
            "kind": "threshold_without_counts", "id": ", ".join(unlogged),
            "detail": (f"{len(unlogged)} species ({', '.join(unlogged)}) carry "
                       f"a threshold decision in BirdNet_Thresholds.csv but no "
                       f"Positive/Negative/Skipped counts, so the clips behind "
                       f"that decision are not recorded. The detection "
                       f"filtering is unaffected; only the reported listening "
                       f"effort is."),
        })
    if birdnet["labels_not_in_threshold_file"]:
        names = ", ".join(x["species"] for x
                          in birdnet["labels_not_in_threshold_file"][:8])
        gaps.append({
            "kind": "unlisted_label", "id": names,
            "detail": (f"{len(birdnet['labels_not_in_threshold_file'])} "
                       f"BirdNET label(s) ({names}) have no row in "
                       f"BirdNet_Thresholds.csv, so no validation state is "
                       f"known and they are excluded from every figure."),
        })
    herp_in_data = {s["common_name"] for s in ahdrift["species"]
                    if s["class"] in ("Reptilia", "Amphibia")}
    album = media.get("views", {}).get("bucket_camera", {}).get("items", [])
    herp_with_photo = {i.get("common_name") for i in album}
    missing_photo = sorted(herp_in_data - herp_with_photo)
    if album and missing_photo:
        gaps.append({
            "kind": "missing_photo", "id": ", ".join(missing_photo),
            "detail": (f"{len(missing_photo)} reptile/amphibian taxon(s) in "
                       f"the cleaned AHDriFT table have no photograph in the "
                       f"album: {', '.join(missing_photo)}."),
        })

    ah_rate = ahdrift["rate"]
    ct_rate = parallel["rate"]
    bv = birdnet["validation"]
    identification = {
        "ahdrift": {
            "label": "Bucket cameras (AHDriFT)",
            "stats": [
                ["Plot-days reviewed", ahdrift["n_plot_days"],
                 f"across {ah_rate['n_sites']} plots, "
                 f"{ahdrift['date_range']['first']} to "
                 f"{ahdrift['date_range']['last']}"],
                ["Detection events identified", ahdrift["n_detections"],
                 f"{ahdrift['n_species']} taxa in "
                 f"{len(ahdrift['by_class'])} classes"],
                ["Plot-days with no detection", ahdrift["n_blank_plot_days"],
                 f"{round(100 * ahdrift['n_blank_plot_days'] / max(ahdrift['n_plot_days'], 1))}%"
                 f" of reviewed plot-days, recorded explicitly as zeroes"],
                ["Hut-days surveyed", ah_rate["total_hut_days"],
                 f"{ah_rate['total_array_days']} array-days; "
                 f"the detection-rate denominator"],
            ],
            "note": (
                "Motion-capture identification is complete for the 2026 "
                "season. Because plot-days with no detection are recorded "
                "rather than left out, survey effort, detection rate and "
                "naive occupancy are all computable from this one table."
            ),
        },
        "parallel": {
            "label": "Parallel cameras",
            "stats": [
                ["Sequences reviewed",
                 ct_extra["progress"]["n_sequences_human_reviewed"],
                 f"of {ct_extra['progress']['n_sequences_total']} in the "
                 f"export "
                 f"({ct_extra['progress']['pct_human_reviewed']}%), by "
                 f"{ct_extra['progress']['n_reviewers']} reviewers"],
                ["Images uploaded",
                 ct_extra["progress"]["n_images_uploaded"], None],
                ["Species-level sequences", parallel["n_identified_sequences"],
                 f"{parallel['n_coarse_sequences']} more stop at a coarse or "
                 f"non-wildlife label"],
                ["Camera-days logged", round(ct_rate["total_camera_days"]),
                 f"across {ct_rate['n_sites']} stations"],
            ],
            "note": (
                "The AHDriFT rows in the same export "
                f"({ct_extra['progress']['n_sequences_ahdrift_in_export']} "
                "sequences) are no longer used anywhere on this dashboard; "
                "the cleaned bucket-camera table supersedes them."
            ),
        },
        "birdnet": {
            "label": "Bird and frog audio (BirdNET)",
            "stats": [
                ["Clips listened to", bv["n_clips_listened"],
                 f"{bv['n_clips_positive']} true positives, "
                 f"{bv['n_clips_negative']} false, {bv['n_clips_skipped']} "
                 f"skipped"],
                ["Species with a 95% cutoff", bv["n_species_validated"],
                 f"cutoffs {bv['cutoff_min']}-{bv['cutoff_max']}, median "
                 f"{bv['cutoff_median']}"],
                ["Detections kept after filtering",
                 bv["n_detections_validated_retained"],
                 f"{bv['pct_retained_validated']}% of the "
                 f"{bv['n_detections_validated_raw']} raw detections of those "
                 f"species"],
                ["Species still unvalidated",
                 bv["n_species_pending"] + bv["n_species_frogs"]
                 + bv["n_species_no_cutoff"],
                 f"{bv['n_species_frogs']} anurans, "
                 f"{bv['n_species_pending']} birds in the queue, "
                 f"{bv['n_species_no_cutoff']} birds with no attainable "
                 f"cutoff"],
            ],
            "note": bv["note"],
        },
    }

    views = [
        {"id": "bucket_camera", "label": "Bucket Cameras (AHDriFT)",
         "short": "AHDriFT", "status": "available",
         "taxa": "Reptiles, amphibians, small mammals",
         "sensor_type": "AHDriFT",
         "n_species": ahdrift["n_species"],
         "n_deployments": effort["summary"]["bucket_camera"]["n_deployments"],
         "sensor_days": effort["summary"]["bucket_camera"]["total_sensor_days"],
         "n_media": media_count("bucket_camera")},
        {"id": "parallel_camera", "label": "Parallel Cameras",
         "short": "Camera Traps", "status": "available",
         "taxa": "Mid-sized and large mammals",
         "sensor_type": "Camera Trap",
         "n_species": parallel["n_species"],
         "n_deployments": effort["summary"]["parallel_camera"]["n_deployments"],
         "sensor_days": effort["summary"]["parallel_camera"]["total_sensor_days"],
         "n_media": media_count("parallel_camera")},
        {"id": "bird_frog_audio", "label": "Bird & Frog Audio",
         "short": "Bird/Frog ARUs", "status": "available",
         "taxa": "Vocalizing birds and anurans", "sensor_type": "ARU",
         "n_species": birdnet["n_wildlife_species"],
         "n_deployments": birdnet["n_plots"],
         "sensor_days": sum(p["n_recording_days"] for p in birdnet["plots"]),
         "n_media": media_count("bird_frog_audio")},
        {"id": "bat_audio", "label": "Bat Audio", "short": "Bat ARUs",
         "status": "pending", "taxa": "Bats (ultrasonic)",
         "sensor_type": "Ultrasonic ARU",
         "pending_note": (
             "26,268 ultrasonic recordings were collected at 50 locations "
             "for 14-55 nights each. Classification with Kaleidoscope Pro "
             "has not yet begun.")},
        {"id": "vegetation", "label": "Vegetation", "short": "Vegetation",
         "status": "pending",
         "taxa": "Understory structure and canopy cover",
         "sensor_type": "Wiens pole / densiometer",
         "pending_note": (
             "Wiens-pole understory measurements (41 points per sensor "
             "location) and 360-degree canopy photographs were collected "
             "June-July 2026 and are being digitized.")},
    ]

    manifest = {
        "project": "Timbermill Wind & Wildlife",
        "subtitle": ("Wildlife response to wind energy development in "
                     "industrial forests -- Chowan County, North Carolina"),
        "investigator": "Will Harrod, PhD student, NC State University",
        "field_season": "2026",
        "generated_utc": datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"),
        "disclaimer": (
            "PRELIMINARY DATA -- annotation and validation are in progress. "
            "Bucket-camera identifications are complete; acoustic bird "
            "detections are filtered to validated per-species cutoffs, and "
            "anuran detections are not validated at all. Counts are "
            "provisional. Do not cite, redistribute, or draw ecological "
            "conclusions from these figures."
        ),
        "plot_types": PLOT_TYPE_ORDER,
        "class_labels": CLASS_LABELS,
        "class_order": CLASS_ORDER,
        "views": views,
        "totals": {
            "n_sensor_points": loc_payload["n_points"],
            "n_plots": loc_payload["n_plots"],
            "n_camera_deployments": len(ct_rows),
            "n_ahdrift_arrays": len(ah_rows),
            "n_sequences": ct_extra["progress"]["n_sequences_total"],
            "n_sequences_reviewed":
                ct_extra["progress"]["n_sequences_human_reviewed"],
            "n_images_uploaded": ct_extra["progress"]["n_images_uploaded"],
            "n_ahdrift_detections": ahdrift["n_detections"],
            "n_ahdrift_plot_days": ahdrift["n_plot_days"],
            "n_birdnet_detections": birdnet["n_detections_total"],
            "n_birdnet_retained": birdnet["n_detections_retained"],
            "n_clips_listened": bv["n_clips_listened"],
            "n_camera_species": len({s["common_name"]
                                     for s in ahdrift["species"]}
                                    | {s["common_name"]
                                       for s in parallel["species"]}),
            "n_acoustic_species": birdnet["n_wildlife_species"],
        },
        "annotation_progress": ct_extra["progress"],
        "identification_progress": identification,
        "data_gaps": gaps,
    }
    write_json("manifest.json", manifest)

    print("\nDone. Summaries in docs/data/ -- no raw records published.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
