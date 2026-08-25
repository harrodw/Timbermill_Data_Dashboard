#!/usr/bin/env python3
"""
Timbermill Wind & Wildlife -- dashboard summary pipeline.

Reads the raw, preliminary sensor data in ``raw_data/`` and writes ONLY
aggregated summaries into ``docs/data/``. No individual detection record, no
raw media, and no full-precision coordinate ever reaches ``docs/``.

Run from the repository root:

    python build/build_summaries.py

Outputs (all JSON, all safe to publish):

    docs/data/manifest.json        build metadata, view registry, headline totals
    docs/data/locations.json       jittered + rounded sensor coordinates
    docs/data/effort.json          per-deployment durations by plot type
    docs/data/species_ahdrift.json bucket-camera (AHDriFT) species tallies
    docs/data/species_parallel.json parallel-camera species tallies
    docs/data/birdnet.json         BirdNET species tallies + validation progress
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
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw_data"
WI_DIR = RAW / "WI_Download" / "WI_Data_20260823"
OUT = ROOT / "docs" / "data"
PRIVATE = ROOT / "private"
VALIDATION_LOG = ROOT / "build" / "validation_log.csv"

# --------------------------------------------------------------------------
# Privacy controls
# --------------------------------------------------------------------------
# Published coordinates are rounded to COORD_DECIMALS and then displaced by a
# deterministic per-point offset of up to JITTER_DEG degrees. Deterministic
# means the same point lands in the same place on every rebuild (so the map is
# stable) while never revealing the true location. Full-precision coordinates
# stay in raw_data/ and private/, both git-ignored.
COORD_DECIMALS = 3
# Offsets are applied as a polar vector with a guaranteed minimum radius, so
# no published point can land close to its true position by chance (which
# independent per-axis jitter allows when the offsets cancel the rounding).
JITTER_MIN_M = 40.0
JITTER_MAX_M = 110.0

# BirdNET confidence thresholds reported on the dashboard. 0.25 is the liberal
# prospectus threshold fed to the false-positive model; the higher bins show how
# quickly the detection pool shrinks as the threshold tightens.
BIRDNET_THRESHOLDS = [0.25, 0.50, 0.75, 0.90]

# ---- Validation design ---------------------------------------------------
# 150 recordings are validated per species, drawn STRATIFIED across confidence
# bins, and a logistic regression of true-positive outcome on BirdNET
# confidence gives the threshold at which P(true positive) = 0.95. Detections
# at or above that fitted cutoff are the positives carried into the
# multi-species occupancy model.
#
# Stratifying matters here: raw confidences are heavily skewed toward the 0.25
# floor (median 0.43), so a simple random 150 would place almost no
# validations near the crossing point and the cutoff would be extrapolated
# rather than estimated. Equal allocation per bin puts data on both sides of
# it. The consequence is that validated detections are NOT a random sample of
# all detections, so the pooled validated precision is not the dataset
# precision -- the fitted curve is the object of interest, and per-bin
# precision is reported instead of a pooled average.
VALIDATION_N_PER_SPECIES = 150
VALIDATION_TARGET_P = 0.95

# Bin edges over the retained confidence range. Eight bins at 150 per species
# is ~19 validations per bin.
VALIDATION_BIN_EDGES = [0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95, 1.001]

# Detections at or above this confidence make up the pool eligible for
# validation, matching the liberal BirdNET threshold in the prospectus.
VALIDATION_POOL_THRESHOLD = 0.25

# Non-wildlife / non-identification labels excluded from species tallies.
NON_SPECIES_LABELS = {
    "no cv result", "blank", "vehicle", "animal", "unknown", "",
    "human", "homo sapiens", "camera trapper", "setup/pickup",
}
# Labels that are real detections but not resolved to a useful taxon; kept out
# of the species bar chart but counted separately so nothing silently vanishes.
COARSE_LABELS = {
    "mammal", "bird", "insect", "spider", "rodent", "reptile", "amphibian",
    "hymenoptera order", "snake", "lizard", "turtle", "frog", "toad",
    "arachnid", "millipede", "centipede", "snail", "slug",
}

PLOT_TYPES = {
    "TO": "Turbine Opening",
    "TE": "Turbine Edge",
    "IF": "Interior Forest",
    "RE": "Reference Edge",
}
PLOT_TYPE_ORDER = ["Turbine Opening", "Turbine Edge", "Interior Forest",
                   "Reference Edge"]


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
    m = re.match(r"([A-Z]{2})\s*0*(\d+)", str(name).upper())
    if not m:
        return None
    if m.group(1) not in PLOT_TYPES:
        return None
    return f"{m.group(1)}{int(m.group(2)):02d}"


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


def jitter(point_id: str, lat: float, lon: float) -> tuple[float, float]:
    """Deterministic, stable coordinate obfuscation.

    The true position is rounded, then displaced along a pseudo-random bearing
    by a distance drawn from [JITTER_MIN_M, JITTER_MAX_M]. Keying the offset on
    the point id makes it identical on every rebuild, so the map does not
    shuffle between builds, while the enforced minimum radius guarantees no
    published marker sits on top of a real sensor.
    """
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = m_per_deg_lat * max(math.cos(math.radians(lat)), 0.1)

    # Displace the TRUE coordinate, then round. Rounding to COORD_DECIMALS
    # quantizes the result onto a ~100 m grid, which can pull a point back
    # toward its true position, so the displacement is re-measured AFTER
    # rounding and the draw is repeated with a wider radius until the floor
    # actually holds. The attempt counter feeds the hash, so the outcome stays
    # deterministic across rebuilds.
    for attempt in range(64):
        h = hashlib.sha256(f"timbermill/{point_id}/{attempt}".encode()).digest()
        bearing = int.from_bytes(h[0:4], "big") / 2**32 * 2 * math.pi
        frac = int.from_bytes(h[4:8], "big") / 2**32
        # sqrt keeps the draws area-uniform within the annulus.
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
    return bool(t) and t not in NON_SPECIES_LABELS and t not in COARSE_LABELS


def count_lines(path: Path) -> int:
    """Fast line count for very large CSVs (header excluded)."""
    try:
        out = subprocess.run(["wc", "-l", str(path)], capture_output=True,
                             text=True, check=True)
        return max(int(out.stdout.split()[0]) - 1, 0)
    except Exception:
        with path.open("rb") as fh:
            return max(sum(1 for _ in fh) - 1, 0)


def bin_index(conf: float) -> int:
    """Confidence -> validation stratum index, or -1 below the pool floor."""
    for i in range(len(VALIDATION_BIN_EDGES) - 1):
        if VALIDATION_BIN_EDGES[i] <= conf < VALIDATION_BIN_EDGES[i + 1]:
            return i
    return -1


def bin_label(i: int) -> str:
    lo = VALIDATION_BIN_EDGES[i]
    hi = VALIDATION_BIN_EDGES[i + 1]
    hi = min(hi, 1.0)
    return f"{lo:.2f}-{hi:.2f}"


def fit_logistic_cutoff(rows):
    """Fit P(true positive) ~ confidence and solve for VALIDATION_TARGET_P.

    ``rows`` is a list of (confidence, n_checked, n_true_positive) at the bin
    level; the fit is on grouped binomial data, which is what a per-bin
    validation tally gives you. Newton-Raphson on the two-parameter logit --
    small, dependency-free, and the design matrix is Nx2, so this converges in
    a handful of iterations.

    Returns None when the data cannot identify a cutoff: fewer than two bins
    with validations, no variation in outcome, a non-increasing fit, or a
    crossing point outside the confidence range. Reporting "not yet
    identifiable" is correct in those cases -- a number extrapolated from one
    bin would look like a result without being one.
    """
    pts = [(float(c), int(n), int(k)) for c, n, k in rows if int(n) > 0]
    if len({c for c, _, _ in pts}) < 2:
        return None
    total_n = sum(n for _, n, _ in pts)
    total_k = sum(k for _, _, k in pts)
    if total_k == 0 or total_k == total_n:
        return None  # no variation: the fit is degenerate

    b0, b1 = 0.0, 0.0
    for _ in range(200):
        # Score vector and Fisher information for the logit likelihood.
        g0 = g1 = h00 = h01 = h11 = 0.0
        for c, n, k in pts:
            eta = b0 + b1 * c
            eta = max(min(eta, 30.0), -30.0)
            p = 1.0 / (1.0 + math.exp(-eta))
            w = n * p * (1.0 - p)
            r = k - n * p
            g0 += r
            g1 += r * c
            h00 += w
            h01 += w * c
            h11 += w * c * c
        det = h00 * h11 - h01 * h01
        if abs(det) < 1e-12:
            return None
        d0 = (h11 * g0 - h01 * g1) / det
        d1 = (h00 * g1 - h01 * g0) / det
        b0 += d0
        b1 += d1
        if max(abs(d0), abs(d1)) < 1e-9:
            break
    else:
        return None

    if b1 <= 0:
        # Precision not increasing with confidence -- the premise of a
        # threshold does not hold for this species yet.
        return {"slope": round(b1, 4), "intercept": round(b0, 4),
                "cutoff": None,
                "reason": "fitted precision does not increase with confidence"}

    logit_t = math.log(VALIDATION_TARGET_P / (1.0 - VALIDATION_TARGET_P))
    cutoff = (logit_t - b0) / b1
    out = {"slope": round(b1, 4), "intercept": round(b0, 4),
           "n_validated": total_n, "n_true_positive": total_k,
           "n_bins": len(pts)}
    if cutoff > 1.0:
        out["cutoff"] = None
        out["reason"] = (f"P={VALIDATION_TARGET_P:.2f} is not reached within "
                         f"the confidence range (extrapolates to "
                         f"{cutoff:.2f})")
    elif cutoff < VALIDATION_POOL_THRESHOLD:
        # Already above target everywhere retained; the floor is the cutoff.
        out["cutoff"] = round(VALIDATION_POOL_THRESHOLD, 3)
        out["reason"] = (f"fit reaches P={VALIDATION_TARGET_P:.2f} below the "
                         f"retained floor; floor applies")
    else:
        out["cutoff"] = round(cutoff, 3)
    return out


def write_json(name: str, payload) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    with p.open("w") as fh:
        json.dump(payload, fh, separators=(",", ":"), sort_keys=False,
                  allow_nan=False)
    log(f"wrote {p.relative_to(ROOT)}  ({p.stat().st_size/1024:.1f} KB)")


# --------------------------------------------------------------------------
# 1. Locations
# --------------------------------------------------------------------------
def build_locations() -> tuple[dict, pd.DataFrame]:
    src = RAW / "Locations" / "cam_trap_locations_info.csv"
    df = pd.read_csv(src)
    df["plot_type"] = df["Plot_Type"].map(canon_plot_type)
    df["plot"] = df["Point_Name"].map(plot_code)
    df["sensor_type"] = df["Point_type"].astype(str).str.strip()
    df["key"] = df["Point_Name"].map(norm_key)

    points = []
    displacements = []
    for _, r in df.iterrows():
        lat0, lon0 = float(r["y"]), float(r["x"])
        jlat, jlon = jitter(str(r["Point_Name"]), lat0, lon0)
        # Measure what was actually published so the note states the real
        # range. Rounding to COORD_DECIMALS adds up to ~78 m on top of the
        # drawn offset, so the effective maximum exceeds JITTER_MAX_M.
        displacements.append(math.hypot(
            (jlat - lat0) * 111_320.0,
            (jlon - lon0) * 111_320.0 * math.cos(math.radians(lat0))))
        points.append({
            "id": str(r["Point_Name"]),
            "plot": r["plot"],
            "plot_type": r["plot_type"],
            "sensor_type": r["sensor_type"],
            "lat": jlat,
            "lon": jlon,
        })

    by_type = (df.groupby(["plot_type", "sensor_type"]).size()
                 .reset_index(name="n"))
    d_lo, d_hi = min(displacements), max(displacements)
    d_med = sorted(displacements)[len(displacements) // 2]
    payload = {
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
        "n_points": len(points),
        "n_plots": int(df["plot"].nunique()),
        "counts": [
            {"plot_type": r.plot_type, "sensor_type": r.sensor_type,
             "n": int(r.n)}
            for r in by_type.itertuples()
        ],
        "points": points,
    }
    return payload, df


# --------------------------------------------------------------------------
# 2. Effort (deployment durations)
# --------------------------------------------------------------------------
def build_effort(loc: pd.DataFrame) -> dict:
    dep = pd.read_csv(WI_DIR / "deployments.csv")
    dep["key"] = dep["placename"].map(norm_key)
    dep["plot"] = dep["placename"].map(plot_code)
    dep["plot_type"] = dep["placename"].map(plot_type_of)

    # Prefer the sensor type implied by the placename; fall back to the
    # Wildlife Insights subproject name.
    dep["sensor_type"] = dep["placename"].map(sensor_type_of)
    sub = dep["subproject_name"].fillna("")
    dep.loc[dep["sensor_type"].isna() & sub.str.contains("AHDriFT"),
            "sensor_type"] = "AHDriFT"
    dep.loc[dep["sensor_type"].isna() & sub.str.contains("Camera_Traps"),
            "sensor_type"] = "Camera Trap"

    # Fill missing plot type from the location table where possible.
    lut = dict(zip(loc["key"], loc["plot_type"]))
    dep["plot_type"] = dep["plot_type"].fillna(dep["key"].map(lut))

    dep["start"] = pd.to_datetime(dep["start_date"], errors="coerce")
    dep["end"] = pd.to_datetime(dep["end_date"], errors="coerce")
    dep["days"] = (dep["end"] - dep["start"]).dt.total_seconds() / 86400.0

    n_total = len(dep)
    bad = dep["days"].isna() | (dep["days"] <= 0) | dep["plot_type"].isna()
    dep = dep.loc[~bad].copy()

    # AHDriFT deployments are recorded twice per array (motion capture "MC" and
    # time-lapse "TL" schedules on the same physical camera). Effort is the
    # union of the two, so collapse to one row per camera per date window.
    dep["camera_slot"] = (dep["deployment_id"].astype(str)
                          .str.extract(r"(Cam[A-Z])", expand=False)
                          .fillna("CamA"))
    dep["unit"] = dep["plot"].astype(str) + "|" + dep["camera_slot"]

    records = []
    for view, sensor in (("bucket_camera", "AHDriFT"),
                         ("parallel_camera", "Camera Trap")):
        d = dep.loc[dep["sensor_type"] == sensor]
        if sensor == "AHDriFT":
            d = (d.sort_values("days", ascending=False)
                  .drop_duplicates(subset=["unit", "start", "end"]))
        for r in d.itertuples():
            records.append({
                "view": view,
                "deployment_id": str(r.deployment_id),
                "plot": r.plot,
                "plot_type": r.plot_type,
                "sensor_type": sensor,
                "start": r.start.strftime("%Y-%m-%d"),
                "end": r.end.strftime("%Y-%m-%d"),
                "days": round(float(r.days), 1),
                "functioning": (str(r.camera_functioning)
                                if pd.notna(r.camera_functioning) else None),
            })

    # Bird/frog ARU effort comes from the BirdNET recording dates, since ARU
    # deployments are not tracked in Wildlife Insights.
    summary = {}
    for view in ("bucket_camera", "parallel_camera"):
        rs = [r for r in records if r["view"] == view]
        per_type = defaultdict(lambda: {"n": 0, "days": 0.0})
        for r in rs:
            per_type[r["plot_type"]]["n"] += 1
            per_type[r["plot_type"]]["days"] += r["days"]
        days = sorted(r["days"] for r in rs)
        summary[view] = {
            "n_deployments": len(rs),
            "total_sensor_days": round(sum(days), 1),
            "mean_days": round(sum(days) / len(days), 1) if days else 0,
            "median_days": round(days[len(days) // 2], 1) if days else 0,
            "min_days": round(days[0], 1) if days else 0,
            "max_days": round(days[-1], 1) if days else 0,
            "by_plot_type": [
                {"plot_type": k, "n_deployments": v["n"],
                 "sensor_days": round(v["days"], 1)}
                for k, v in sorted(per_type.items(),
                                   key=lambda kv: PLOT_TYPE_ORDER.index(kv[0])
                                   if kv[0] in PLOT_TYPE_ORDER else 99)
            ],
            "functioning": dict(Counter(
                r["functioning"] or "Unknown" for r in rs)),
        }

    return {
        "note": (
            "One bar per camera deployment (a camera at one point over one "
            "date window). AHDriFT arrays log a motion-capture and a "
            "time-lapse schedule for the same physical camera; these are "
            "collapsed so effort is not double counted."
        ),
        "n_deployment_rows_raw": n_total,
        "n_deployment_rows_used": len(records),
        "summary": summary,
        "deployments": records,
    }


# --------------------------------------------------------------------------
# 3. Camera species (Wildlife Insights sequences)
# --------------------------------------------------------------------------
def build_camera_species() -> tuple[dict, dict, dict]:
    cols = ["deployment_id", "sequence_id", "is_blank", "identified_by",
            "class", "order", "family", "genus", "species", "common_name",
            "group_size"]
    seq = pd.read_csv(WI_DIR / "sequences.csv", usecols=cols,
                      low_memory=False)
    n_seq_total = len(seq)

    ident = seq["identified_by"].fillna("")
    seq["human_reviewed"] = (ident != "") & (ident != "Computer vision")
    seq["plot"] = seq["deployment_id"].map(plot_code)
    seq["plot_type"] = seq["deployment_id"].map(plot_type_of)
    seq["sensor_type"] = seq["deployment_id"].map(sensor_type_of)

    reviewers = Counter(x for x in ident if x and x != "Computer vision")
    n_reviewed = int(seq["human_reviewed"].sum())

    hum = seq.loc[seq["human_reviewed"]].copy()
    hum["latin"] = (hum["genus"].fillna("").astype(str).str.strip() + " " +
                    hum["species"].fillna("").astype(str).str.strip()
                    ).str.strip()

    views = {}
    for view, sensor in (("bucket_camera", "AHDriFT"),
                         ("parallel_camera", "Camera Trap")):
        d = hum.loc[hum["sensor_type"] == sensor].copy()
        keep = d["common_name"].map(is_species_label)
        sp = d.loc[keep]
        coarse = d.loc[~keep & d["common_name"].notna()]

        rows = []
        for name, g in sp.groupby("common_name"):
            per_type = Counter(g["plot_type"].dropna())
            latin = next((x for x in g["latin"] if x), None)
            klass = next((x for x in g["class"].dropna() if x), None)
            rows.append({
                "common_name": str(name),
                "latin_name": latin or None,
                "class": str(klass) if klass else None,
                "order": (str(g["order"].dropna().iloc[0])
                          if g["order"].notna().any() else None),
                "n_sequences": int(len(g)),
                "n_plots": int(g["plot"].nunique()),
                "by_plot_type": {k: int(v) for k, v in per_type.items()},
            })
        rows.sort(key=lambda r: -r["n_sequences"])

        by_class = Counter(r["class"] or "Unclassified" for r in rows)
        views[view] = {
            "n_species": len(rows),
            "n_identified_sequences": int(len(sp)),
            "n_coarse_sequences": int(len(coarse)),
            "coarse_note": (
                "Detections identified only to a coarse group (e.g. 'Rodent', "
                "'Insect') or to a non-wildlife label are counted here and "
                "excluded from the species chart."
            ),
            "by_class": [{"class": k, "n_species": int(v)}
                         for k, v in sorted(by_class.items(),
                                            key=lambda kv: -kv[1])],
            "by_plot_type": [
                {"plot_type": pt,
                 "n_sequences": int((sp["plot_type"] == pt).sum()),
                 "n_species": int(sp.loc[sp["plot_type"] == pt,
                                         "common_name"].nunique())}
                for pt in PLOT_TYPE_ORDER
            ],
            "species": rows,
        }

    n_images = sum(count_lines(p)
                   for p in sorted(WI_DIR.glob("images_*.csv")))
    progress = {
        "n_sequences_total": int(n_seq_total),
        "n_sequences_human_reviewed": n_reviewed,
        "pct_human_reviewed": round(100 * n_reviewed / n_seq_total, 2),
        "n_images_uploaded": n_images,
        # Reviewer identities are deliberately NOT published: per-person
        # sequence counts are individual productivity data, not a study result.
        # Only the team size is reported.
        "n_reviewers": len(reviewers),
        "note": (
            "Sequences are the Wildlife Insights identification unit. The "
            "remainder carry computer-vision output (MegaDetector) awaiting "
            "expert review; vehicle and blank sequences are filtered out of "
            "the species tallies."
        ),
    }
    return views["bucket_camera"], views["parallel_camera"], progress


# --------------------------------------------------------------------------
# 4. BirdNET + validation progress
# --------------------------------------------------------------------------
def build_birdnet() -> dict:
    src = RAW / "Bird_Frog_Audio_Summaries" / "preliminary_BirdNET_Results.csv"

    sp_tot = Counter()
    sp_thresh = {t: Counter() for t in BIRDNET_THRESHOLDS}
    # species -> stratum index -> n detections, for the validation design and
    # for counting how many positives a fitted cutoff would retain.
    sp_bins = defaultdict(Counter)
    sp_meta = {}
    sp_plots = defaultdict(set)
    sp_plot_type = defaultdict(Counter)
    plot_dates = defaultdict(set)
    plot_type_of_plot = {}
    hour_hist = defaultdict(Counter)   # class -> hour -> n
    n_rows = 0

    usecols = ["Plot", "Plot.Type", "Date", "Rec.Hour", "Species",
               "Confidence", "Latin.Name", "class", "order"]
    for chunk in pd.read_csv(src, usecols=usecols, chunksize=400_000,
                             low_memory=False):
        n_rows += len(chunk)
        chunk = chunk.dropna(subset=["Species"])
        conf = pd.to_numeric(chunk["Confidence"], errors="coerce").fillna(0)

        for sp, n in chunk["Species"].value_counts().items():
            sp_tot[sp] += int(n)
        for t in BIRDNET_THRESHOLDS:
            sub = chunk.loc[conf >= t, "Species"]
            for sp, n in sub.value_counts().items():
                sp_thresh[t][sp] += int(n)

        # Stratum tallies for the validation design.
        strata = conf.map(bin_index)
        keep = strata >= 0
        if keep.any():
            grouped = (chunk.loc[keep, "Species"]
                       .groupby([chunk.loc[keep, "Species"],
                                 strata.loc[keep]]).size())
            for (sp, b), n in grouped.items():
                sp_bins[sp][int(b)] += int(n)

        for sp, g in chunk.groupby("Species"):
            if sp not in sp_meta:
                latin = g["Latin.Name"].dropna()
                klass = g["class"].dropna()
                order = g["order"].dropna()
                sp_meta[sp] = {
                    "latin_name": str(latin.iloc[0]) if len(latin) else None,
                    "class": str(klass.iloc[0]) if len(klass) else None,
                    "order": str(order.iloc[0]) if len(order) else None,
                }
            sp_plots[sp].update(g["Plot"].dropna().astype(str))
            for pt, n in g["Plot.Type"].value_counts().items():
                sp_plot_type[sp][str(pt)] += int(n)

        for (plot, pt), g in chunk.groupby(["Plot", "Plot.Type"]):
            plot_dates[str(plot)].update(g["Date"].dropna().astype(str))
            plot_type_of_plot[str(plot)] = str(pt)

        hr = pd.to_numeric(chunk["Rec.Hour"], errors="coerce")
        for klass, g in chunk.assign(_h=hr).groupby("class"):
            for h, n in g["_h"].dropna().astype(int).value_counts().items():
                hour_hist[str(klass)][int(h)] += int(n)

    # ---- validation log ----------------------------------------------------
    # species -> confidence bin label -> {n_checked, n_true_positive}
    val = defaultdict(dict)
    if VALIDATION_LOG.exists():
        with VALIDATION_LOG.open() as fh:
            for row in csv.DictReader(fh):
                name = (row.get("species") or "").strip()
                cbin = (row.get("confidence_bin") or "").strip()
                if not name or not cbin:
                    continue
                try:
                    nc = int(float(row.get("n_checked") or 0))
                    ntp = int(float(row.get("n_true_positive") or 0))
                except ValueError:
                    continue
                if ntp > nc:
                    log(f"WARNING: {name} [{cbin}] has more true positives "
                        f"({ntp}) than checked ({nc}); check the log")
                val[name][cbin] = {"n_checked": nc, "n_true_positive": ntp}

    # Plot-type label mapping: bird/frog ARUs at turbine plots are recorded
    # under the "TO" code (they sit at the opening edge, sampling both the
    # opening and adjacent forest -- see TNC report Table 1 footnote).
    def expand_pt(code: str) -> str:
        return {"TO": "Turbine Opening", "IF": "Interior Forest",
                "RE": "Reference Edge", "TE": "Turbine Edge"}.get(code, code)

    n_bins = len(VALIDATION_BIN_EDGES) - 1
    species = []
    for sp, total in sp_tot.most_common():
        meta = sp_meta.get(sp, {})
        pool = sp_thresh[VALIDATION_POOL_THRESHOLD][sp]
        bins = sp_bins.get(sp, Counter())
        v = val.get(sp, {})

        # Stratified allocation: spread VALIDATION_N_PER_SPECIES evenly over
        # the strata that actually contain detections, so no effort is
        # allocated to an empty confidence band. Remainders go to the
        # highest-confidence occupied strata, where the cutoff usually sits.
        occupied = [b for b in range(n_bins) if bins.get(b, 0) > 0]
        alloc = {}
        if occupied:
            base, extra = divmod(min(VALIDATION_N_PER_SPECIES, pool),
                                 len(occupied))
            for b in occupied:
                alloc[b] = min(base, bins[b])
            for b in sorted(occupied, reverse=True)[:extra]:
                if alloc[b] < bins[b]:
                    alloc[b] += 1
            # Redistribute any shortfall from strata too small to fill.
            short = min(VALIDATION_N_PER_SPECIES, pool) - sum(alloc.values())
            for b in sorted(occupied, key=lambda x: -bins[x]):
                while short > 0 and alloc[b] < bins[b]:
                    alloc[b] += 1
                    short -= 1
                if short <= 0:
                    break

        strata = []
        fit_rows = []
        done = tp = 0
        for b in range(n_bins):
            n_avail = int(bins.get(b, 0))
            if n_avail == 0:
                continue
            key = bin_label(b)
            rec = v.get(key, {})
            nc = int(rec.get("n_checked", 0))
            ntp = int(rec.get("n_true_positive", 0))
            done += nc
            tp += ntp
            mid = (VALIDATION_BIN_EDGES[b] +
                   min(VALIDATION_BIN_EDGES[b + 1], 1.0)) / 2.0
            if nc > 0:
                fit_rows.append((mid, nc, ntp))
            strata.append({
                "bin": key,
                "midpoint": round(mid, 3),
                "n_available": n_avail,
                "target": int(alloc.get(b, 0)),
                "n_checked": nc,
                "n_true_positive": ntp,
                "precision": round(ntp / nc, 3) if nc else None,
            })

        fit = fit_logistic_cutoff(fit_rows)
        target_total = sum(alloc.values())

        entry = {
            "species": str(sp),
            "latin_name": meta.get("latin_name"),
            "class": meta.get("class"),
            "order": meta.get("order"),
            "n_detections": int(total),
            "n_by_threshold": {str(t): int(sp_thresh[t][sp])
                               for t in BIRDNET_THRESHOLDS},
            "n_plots": len(sp_plots[sp]),
            "by_plot_type": {expand_pt(k): int(v2)
                             for k, v2 in sp_plot_type[sp].items()},
            "pool_size": int(pool),
            "validation_target": int(target_total),
            "n_validated": done,
            "n_true_positive": tp,
            "pct_of_target": (round(100 * done / target_total, 1)
                              if target_total else 0.0),
            "strata": strata,
            "fit": fit,
        }
        # Per-bin precision is what the fit consumes; a pooled ratio over a
        # stratified sample is not this species' precision, so it is labelled
        # as sample-only rather than presented as a precision estimate.
        entry["sample_true_positive_rate"] = (round(tp / done, 3)
                                              if done else None)

        cutoff = (fit or {}).get("cutoff")
        if cutoff is not None:
            retained = sum(n for b, n in bins.items()
                           if VALIDATION_BIN_EDGES[b] >= cutoff)
            # Partial stratum containing the cutoff: attribute pro rata.
            for b, n in bins.items():
                lo, hi = VALIDATION_BIN_EDGES[b], min(
                    VALIDATION_BIN_EDGES[b + 1], 1.0)
                if lo < cutoff < hi and hi > lo:
                    retained += int(round(n * (hi - cutoff) / (hi - lo)))
            entry["cutoff"] = cutoff
            entry["n_retained_positives"] = int(retained)
            entry["pct_retained"] = (round(100 * retained / pool, 1)
                                     if pool else None)
        else:
            entry["cutoff"] = None
            entry["n_retained_positives"] = None
            entry["pct_retained"] = None
        species.append(entry)

    wildlife = [s for s in species
                if s["class"] in ("Aves", "Amphibia", "Mammalia")]
    dates = sorted({d for ds in plot_dates.values() for d in ds})
    plots = [
        {"plot": p,
         "plot_type": expand_pt(plot_type_of_plot.get(p, "")),
         "n_recording_days": len(plot_dates[p]),
         "first_date": min(plot_dates[p]),
         "last_date": max(plot_dates[p])}
        for p in sorted(plot_dates)
    ]

    total_pool = sum(s["pool_size"] for s in wildlife)
    total_target = sum(s["validation_target"] for s in wildlife)
    total_done = sum(s["n_validated"] for s in wildlife)
    total_tp = sum(s["n_true_positive"] for s in wildlife)
    n_fitted = sum(1 for s in wildlife if s.get("cutoff") is not None)
    cutoffs = sorted(s["cutoff"] for s in wildlife if s.get("cutoff") is not None)
    retained = sum(s["n_retained_positives"] for s in wildlife
                   if s.get("n_retained_positives") is not None)

    return {
        "note": (
            "BirdNET output is preliminary and unvalidated. Counts are raw "
            "classifier detections (3-second windows), not verified "
            "occurrences, and are not corrected for false positives or for "
            "differences in recording effort among plots."
        ),
        "plot_label_note": (
            "Bird/frog ARUs at turbine plots are logged under the turbine "
            "code: each unit sits at the edge of the opening with the "
            "microphone aimed inward, sampling both the opening and the "
            "adjacent forest."
        ),
        "n_detections_total": int(n_rows),
        "thresholds": BIRDNET_THRESHOLDS,
        "confidence_floor": float(min(BIRDNET_THRESHOLDS)),
        "n_species_total": len(species),
        "n_wildlife_species": len(wildlife),
        "recording_window": {"first_date": dates[0] if dates else None,
                             "last_date": dates[-1] if dates else None,
                             "n_dates": len(dates)},
        "n_plots": len(plots),
        "plots": plots,
        "by_class": [
            {"class": k, "n_detections": int(v),
             "n_species": sum(1 for s in species if s["class"] == k)}
            for k, v in Counter(
                {c: sum(s["n_detections"] for s in species if s["class"] == c)
                 for c in {s["class"] for s in species} if c}
            ).most_common()
        ],
        "hourly": {k: [{"hour": h, "n": n}
                       for h, n in sorted(v.items())]
                   for k, v in hour_hist.items()
                   if k in ("Aves", "Amphibia")},
        "validation": {
            "design": "stratified_logistic",
            "n_per_species": VALIDATION_N_PER_SPECIES,
            "target_p": VALIDATION_TARGET_P,
            "bin_edges": VALIDATION_BIN_EDGES,
            "pool_threshold": VALIDATION_POOL_THRESHOLD,
            "pool_size": int(total_pool),
            "n_target": int(total_target),
            "n_validated": int(total_done),
            "pct_complete": (round(100 * total_done / total_target, 2)
                             if total_target else 0.0),
            "n_species_target": len(wildlife),
            "n_species_fitted": n_fitted,
            "cutoff_median": (cutoffs[len(cutoffs) // 2] if cutoffs else None),
            "cutoff_min": (cutoffs[0] if cutoffs else None),
            "cutoff_max": (cutoffs[-1] if cutoffs else None),
            "n_retained_positives": int(retained) if n_fitted else None,
            "sample_true_positive_rate": (round(total_tp / total_done, 3)
                                          if total_done else None),
            "log_present": VALIDATION_LOG.exists(),
            "note": (
                f"{VALIDATION_N_PER_SPECIES} detections are validated per "
                f"species, allocated across "
                f"{len(VALIDATION_BIN_EDGES) - 1} confidence strata. A "
                f"logistic regression of true-positive outcome on BirdNET "
                f"confidence gives the cutoff at which "
                f"P(true positive) = {VALIDATION_TARGET_P:.2f}; detections at "
                f"or above it are the positives carried into the "
                f"multi-species occupancy model. Update "
                f"build/validation_log.csv and rebuild to refresh progress."
            ),
            "sampling_note": (
                "Validations are stratified by confidence, not drawn at "
                "random, because raw confidences are concentrated near the "
                "0.25 floor and a random sample would leave the region around "
                "the cutoff almost unobserved. Stratification means the "
                "pooled true-positive rate over validated clips is a property "
                "of the sample, not the precision of the dataset -- read the "
                "fitted curve and the per-stratum rates instead."
            ),
        },
        "species": species,
    }


# --------------------------------------------------------------------------
# 5. Validation log template
# --------------------------------------------------------------------------
def ensure_validation_log(birdnet: dict) -> None:
    """Create or extend the validation log: one row per species per stratum.

    Counts you have already entered are preserved, keyed on
    (species, confidence_bin), so rebuilding after new BirdNET output never
    discards validation work.
    """
    header = ["species", "latin_name", "class", "confidence_bin",
              "n_available", "target", "n_checked", "n_true_positive", "notes"]
    existing = {}
    if VALIDATION_LOG.exists():
        with VALIDATION_LOG.open() as fh:
            for row in csv.DictReader(fh):
                name = (row.get("species") or "").strip()
                cbin = (row.get("confidence_bin") or "").strip()
                if name and cbin:
                    existing[(name, cbin)] = row

    rows = []
    for s in birdnet["species"]:
        if s["class"] not in ("Aves", "Amphibia", "Mammalia"):
            continue
        for st in s["strata"]:
            prev = existing.get((s["species"], st["bin"]), {})
            rows.append({
                "species": s["species"],
                "latin_name": s["latin_name"] or "",
                "class": s["class"] or "",
                "confidence_bin": st["bin"],
                "n_available": st["n_available"],
                "target": st["target"],
                "n_checked": prev.get("n_checked", "0"),
                "n_true_positive": prev.get("n_true_positive", "0"),
                "notes": prev.get("notes", ""),
            })

    VALIDATION_LOG.parent.mkdir(parents=True, exist_ok=True)
    with VALIDATION_LOG.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        w.writerows(rows)
    n_sp = len({r["species"] for r in rows})
    log(f"validation log: {len(rows)} stratum rows across {n_sp} species -> "
        f"{VALIDATION_LOG.relative_to(ROOT)}")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main() -> int:
    if not RAW.exists():
        print(f"ERROR: raw data directory not found: {RAW}", file=sys.stderr)
        return 1

    print("Timbermill dashboard :: building summaries")

    print("[1/5] locations")
    loc_payload, loc_df = build_locations()
    write_json("locations.json", loc_payload)

    print("[2/5] deployment effort")
    effort = build_effort(loc_df)
    write_json("effort.json", effort)

    print("[3/5] camera species (Wildlife Insights)")
    bucket, parallel, cam_progress = build_camera_species()
    write_json("species_ahdrift.json", bucket)
    write_json("species_parallel.json", parallel)

    print("[4/5] BirdNET acoustic detections")
    birdnet = build_birdnet()
    write_json("birdnet.json", birdnet)
    ensure_validation_log(birdnet)

    # Rebuild BirdNET validation figures if the log was empty on first run and
    # has since been populated -- cheap because the log is tiny.
    print("[5/5] manifest")
    # media.json is produced by the media pipeline, not here. If it already
    # exists its item counts are folded into the view registry; the frontend
    # also reads media.json directly and prefers that live count, so a stale
    # or absent value here degrades to a correct display either way.
    media_path = OUT / "media.json"
    media = {}
    if media_path.exists():
        try:
            media = json.loads(media_path.read_text())
        except json.JSONDecodeError:
            log("WARNING: media.json is present but unparseable; "
                "media counts omitted from the manifest")

    def media_count(view: str) -> int:
        items = media.get("views", {}).get(view, {}).get("items", [])
        return len(items)

    # ---- data gaps -------------------------------------------------------
    # Surface upstream inconsistencies on the dashboard rather than hiding
    # them: a plot that produced data but has no coordinate record cannot be
    # mapped, and that is worth seeing while annotation is still in progress.
    mappable = {p["plot"] for p in loc_payload["points"] if p["plot"]}
    gaps = []
    for p in birdnet["plots"]:
        if p["plot"] not in mappable:
            gaps.append({
                "kind": "missing_location",
                "id": p["plot"],
                "detail": (
                    f"ARU plot {p['plot']} has {p['n_recording_days']} "
                    f"recording days in the BirdNET output "
                    f"({p['first_date']} to {p['last_date']}) but no entry in "
                    f"the location table, so it cannot be mapped."
                ),
            })

    views = [
        {
            "id": "bucket_camera",
            "label": "Bucket Cameras (AHDriFT)",
            "short": "AHDriFT",
            "status": "available",
            "taxa": "Reptiles, amphibians, small mammals",
            "sensor_type": "AHDriFT",
            "n_species": bucket["n_species"],
            "n_deployments": effort["summary"]["bucket_camera"]["n_deployments"],
            "sensor_days": effort["summary"]["bucket_camera"]["total_sensor_days"],
            "n_media": media_count("bucket_camera"),
        },
        {
            "id": "parallel_camera",
            "label": "Parallel Cameras",
            "short": "Camera Traps",
            "status": "available",
            "taxa": "Mid-sized and large mammals",
            "sensor_type": "Camera Trap",
            "n_species": parallel["n_species"],
            "n_deployments": effort["summary"]["parallel_camera"]["n_deployments"],
            "sensor_days": effort["summary"]["parallel_camera"]["total_sensor_days"],
            "n_media": media_count("parallel_camera"),
        },
        {
            "id": "bird_frog_audio",
            "label": "Bird & Frog Audio",
            "short": "Bird/Frog ARUs",
            "status": "available",
            "taxa": "Vocalizing birds and anurans",
            "sensor_type": "ARU",
            "n_species": birdnet["n_wildlife_species"],
            "n_deployments": birdnet["n_plots"],
            "sensor_days": sum(p["n_recording_days"]
                               for p in birdnet["plots"]),
            "n_media": media_count("bird_frog_audio"),
        },
        {
            "id": "bat_audio",
            "label": "Bat Audio",
            "short": "Bat ARUs",
            "status": "pending",
            "taxa": "Bats (ultrasonic)",
            "sensor_type": "Ultrasonic ARU",
            "pending_note": (
                "26,268 ultrasonic recordings were collected at 50 locations "
                "for 14-55 nights each. Classification with Kaleidoscope Pro "
                "has not yet begun."
            ),
        },
        {
            "id": "vegetation",
            "label": "Vegetation",
            "short": "Vegetation",
            "status": "pending",
            "taxa": "Understory structure and canopy cover",
            "sensor_type": "Wiens pole / densiometer",
            "pending_note": (
                "Wiens-pole understory measurements (41 points per sensor "
                "location) and 360-degree canopy photographs were collected "
                "June-July 2026 and are being digitized."
            ),
        },
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
            "All counts are provisional, unvalidated, and uncorrected for "
            "survey effort or false positives. Do not cite, redistribute, or "
            "draw ecological conclusions from these figures."
        ),
        "plot_types": PLOT_TYPE_ORDER,
        "views": views,
        "totals": {
            "n_sensor_points": loc_payload["n_points"],
            "n_plots": loc_payload["n_plots"],
            "n_camera_deployments": effort["n_deployment_rows_used"],
            "n_sequences": cam_progress["n_sequences_total"],
            "n_sequences_reviewed": cam_progress["n_sequences_human_reviewed"],
            "n_images_uploaded": cam_progress["n_images_uploaded"],
            "n_birdnet_detections": birdnet["n_detections_total"],
            "n_camera_species": len({s["common_name"]
                                     for s in bucket["species"]} |
                                    {s["common_name"]
                                     for s in parallel["species"]}),
            "n_acoustic_species": birdnet["n_wildlife_species"],
        },
        "annotation_progress": cam_progress,
        "data_gaps": gaps,
    }
    write_json("manifest.json", manifest)

    print("\nDone. Summaries in docs/data/ -- no raw records published.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
