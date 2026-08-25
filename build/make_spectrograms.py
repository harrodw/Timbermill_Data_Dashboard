"""Render one publication-quality spectrogram PNG per ARU clip.

Outputs land in docs/media/spectrograms/. Raw audio is read from raw_data/
and never copied into docs/.
"""
import os
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

# Recording-level context, matched on recorder+timestamp against the
# File column of preliminary_BirdNET_Results.csv. The clip-level species
# is NOT resolvable from that table (see report), so no species is named.
CLIPS = {
    "SMM2-02_20260311_070102_001_C80.wav": dict(
        clip_id="TO02_20260311_0701",
        plot="TO02", plot_type="Turbine Opening",
        recorder="SMM2-02", recorded_local="2026-03-11 07:01:02",
    ),
    "SMM2-23_20260418_060802_001_C32.wav": dict(
        clip_id="RE07_20260418_0608_a",
        plot="RE07", plot_type="Reference Edge",
        recorder="SMM2-23", recorded_local="2026-04-18 06:08:02",
    ),
    "SMM2-23_20260418_060802_001_C57.wav": dict(
        clip_id="RE07_20260418_0608_b",
        plot="RE07", plot_type="Reference Edge",
        recorder="SMM2-23", recorded_local="2026-04-18 06:08:02",
    ),
}

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

    accent = PLOT_TYPE_COLOR[meta["plot_type"]]

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

    # Plot identity carried in the dashboard's plot-type color (colour threading)
    ax.set_title(f"{meta['plot']} \u00b7 {meta['plot_type']}", loc="left",
                 color=accent)
    ax.text(1.0, 1.02, f"{meta['recorded_local']} local",
            transform=ax.transAxes, ha="right", va="bottom")

    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(direction="out")

    caption = (f"Songmeter Micro 2 ({meta['recorder']}), {dur:.0f} s excerpt, "
               f"{sr/1000:g} kHz mono. Species not resolvable to this clip.")
    fig.text(0.105, 0.015, caption, ha="left", va="bottom",
             fontsize=mpl.rcParams["legend.fontsize"], color="#444444")

    fig.subplots_adjust(left=0.105, right=0.965, top=0.90, bottom=0.20)

    out = os.path.join(outdir, meta["clip_id"] + ".png")
    fig.savefig(out, dpi=DPI)
    return fig, out, dict(dur=dur, sr=sr, vmin=vmin, vmax=vmax)
