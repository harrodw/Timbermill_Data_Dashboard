"""Render one publication-quality spectrogram PNG per ARU clip.

Outputs land in docs/media/spectrograms/. Raw audio is read from raw_data/
and never copied into docs/.
"""
import json
import os
import subprocess
import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt
from scipy.io import wavfile
from scipy.signal import spectrogram

REPO = "/home/will/NCSU/Claude_Science/2026_Sensor_Dashboard"
AUDIO_IN = os.path.join(REPO, "raw_data", "Audio_Data")
SPEC_OUT = os.path.join(REPO, "docs", "media", "spectrograms")

PLOT_TYPE_COLOR = {
    "Turbine Opening": "#C1666B",
    "Turbine Edge": "#E4A05E",
    "Interior Forest": "#4F7942",
    "Reference Edge": "#6B8EAD",
}

# Class accent for the title, used when a clip is a single named species
# rather than a whole-recording excerpt tied to one plot.
CLASS_COLOR = {"Aves": "#4F7942", "Amphibia": "#6B8EAD"}

# The clips are named by species: the identification is the researcher's,
# made by listening, and is the authority here. Latin names, taxonomic class
# and all detection counts are looked up from the BirdNET summary so nothing
# on the figure is typed from memory.
#
# These files carry no recorder, plot or timestamp -- unlike the earlier
# SMM2-<unit>_<date>_<time> exports -- so no per-clip location or date is
# claimed. Context shown is season-wide for the species.
CLIP_SPECIES = {
    "brimleys_chorus_frog": "Brimley's Chorus Frog",
    "field_sparrow": "Field Sparrow",
    "hooded_warbler": "Hooded Warbler",
    "pickerel_frog": "Pickerel Frog",
    "pine_warbler": "Pine Warbler",
}

BIRDNET_JSON = os.path.join(REPO, "docs", "data", "birdnet.json")


def clip_stem(fname):
    """Filename -> clip id, tolerating a present or absent .wav suffix."""
    stem = fname[:-4] if fname.lower().endswith(".wav") else fname
    return stem


def load_species_index():
    """Species name -> BirdNET summary row (latin name, class, counts)."""
    with open(BIRDNET_JSON) as fh:
        bn = json.load(fh)
    return {s["species"]: s for s in bn["species"]}


def discover_clips():
    """Build the clip table from what is actually in raw_data/Audio_Data.

    Every clip must resolve to a species present in the BirdNET results; an
    unrecognized filename is reported rather than guessed at, so a typo
    surfaces instead of silently producing an unlabelled figure.
    """
    index = load_species_index()
    clips, problems = {}, []
    for fname in sorted(os.listdir(AUDIO_IN)):
        if fname.startswith("."):
            continue
        stem = clip_stem(fname)
        species = CLIP_SPECIES.get(stem)
        if species is None:
            problems.append(f"{fname}: no species mapping for '{stem}'")
            continue
        row = index.get(species)
        if row is None:
            problems.append(f"{fname}: '{species}' absent from birdnet.json")
            continue
        clips[fname] = dict(
            clip_id=stem,
            species=species,
            latin_name=row.get("latin_name"),
            taxon_class=row.get("class"),
            n_detections=row.get("n_detections"),
            n_plots=row.get("n_plots"),
            by_plot_type=row.get("by_plot_type") or {},
        )
    return clips, problems

NPERSEG, NOVERLAP = 1024, 896
DB_RANGE = 62.0   # dB below clip maximum
DPI = 180         # 6.4 in -> ~1150 px, sized for web display


def render(fname, meta, outdir=SPEC_OUT):
    sr, raw = wavfile.read(os.path.join(AUDIO_IN, fname))
    x = raw.astype(np.float64) / 32768.0
    dur = len(x) / sr

    f, t, S = spectrogram(x, fs=sr, nperseg=NPERSEG, noverlap=NOVERLAP,
                          window="hann", scaling="density", mode="psd")
    Sdb = 10 * np.log10(S + 1e-14)
    vmax = float(Sdb.max())
    vmin = vmax - DB_RANGE

    accent = CLASS_COLOR.get(meta["taxon_class"], "#444444")

    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    mesh = ax.pcolormesh(t, f / 1000.0, Sdb, cmap="viridis",
                         vmin=vmin, vmax=vmax, shading="nearest",
                         rasterized=True)

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Frequency (kHz)")
    ax.set_xlim(0, dur)
    ax.set_ylim(0, sr / 2000.0)          # full Nyquist: content reaches 10-12 kHz
    ax.set_yticks(np.arange(0, sr / 2000.0 + 0.1, 2))

    cbar = fig.colorbar(mesh, ax=ax, pad=0.02, aspect=24)
    cbar.set_label("Power (dB re clip max)")
    cbar.set_ticks(np.arange(np.ceil(vmin / 10) * 10, vmax + 1, 20))

    ax.set_title(meta["species"], loc="left", color=accent)
    if meta.get("latin_name"):
        ax.text(1.0, 1.02, meta["latin_name"], transform=ax.transAxes,
                ha="right", va="bottom", style="italic")

    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(direction="out")

    caption = (f"Songmeter Micro 2, {dur:.0f} s excerpt, {sr/1000:g} kHz mono. "
               f"Identified by ear; BirdNET logged "
               f"{meta['n_detections']:,} unvalidated detections of this "
               f"species at {meta['n_plots']} plots.")
    fig.text(0.105, 0.015, caption, ha="left", va="bottom",
             fontsize=mpl.rcParams["legend.fontsize"], color="#444444")

    fig.subplots_adjust(left=0.105, right=0.965, top=0.90, bottom=0.20)

    out = os.path.join(outdir, meta["clip_id"] + ".png")
    fig.savefig(out, dpi=DPI)
    plt.close(fig)
    return fig, out, dict(dur=dur, sr=sr, vmin=vmin, vmax=vmax)


# --------------------------------------------------------------------------
# Audio transcode
# --------------------------------------------------------------------------
AUDIO_OUT = os.path.join(REPO, "docs", "media", "audio")


def ffmpeg_bin():
    """Locate ffmpeg: system install first, else the imageio-ffmpeg bundle."""
    from shutil import which
    exe = which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as err:
        raise RuntimeError(
            "No ffmpeg available. Install one of:\n"
            "  pip install imageio-ffmpeg      (bundled binary)\n"
            "  conda install -c conda-forge ffmpeg"
        ) from err


def transcode(fname, meta, outdir=AUDIO_OUT):
    """WAV -> web-playable AAC, full audible band retained."""
    os.makedirs(outdir, exist_ok=True)
    src = os.path.join(AUDIO_IN, fname)
    dst = os.path.join(outdir, meta["clip_id"] + ".m4a")
    subprocess.run(
        [ffmpeg_bin(), "-y", "-loglevel", "error", "-i", src,
         "-c:a", "aac", "-b:a", "128k", "-ac", "1",
         # Strip any container metadata rather than carrying it to the web.
         "-map_metadata", "-1", dst],
        check=True)
    return dst


def main():
    os.makedirs(SPEC_OUT, exist_ok=True)
    clips, problems = discover_clips()
    for p in problems:
        print(f"  SKIP {p}")
    if not clips:
        raise SystemExit("No clips resolved -- nothing written.")

    stale_spec = {f for f in os.listdir(SPEC_OUT) if f.endswith(".png")}
    stale_audio = (set(os.listdir(AUDIO_OUT)) if os.path.isdir(AUDIO_OUT)
                   else set())

    for fname, meta in clips.items():
        _, png, info = render(fname, meta)
        m4a = transcode(fname, meta)
        stale_spec.discard(os.path.basename(png))
        stale_audio.discard(os.path.basename(m4a))
        print(f"  {meta['species']:24s} {info['dur']:.0f}s "
              f"{info['sr']/1000:g}kHz -> {os.path.basename(png)}, "
              f"{os.path.basename(m4a)}")

    # Media for clips that no longer exist would otherwise linger in docs/
    # and keep being published after the source was replaced.
    for leftover in sorted(stale_spec):
        os.remove(os.path.join(SPEC_OUT, leftover))
        print(f"  removed stale spectrogram {leftover}")
    for leftover in sorted(stale_audio):
        os.remove(os.path.join(AUDIO_OUT, leftover))
        print(f"  removed stale audio {leftover}")

    print(f"\n{len(clips)} clips rendered and transcoded.")


if __name__ == "__main__":
    main()
