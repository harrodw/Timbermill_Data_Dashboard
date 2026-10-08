/* ==========================================================================
   media.js -- example media panel.

   Source: data/media.json, written by a separate media pipeline step.
     {"views": {"<view_id>": {"kind": "photo"|"audio", "items": [...]}}}
   Paths inside it are relative to docs/, so they are used as-is.
   The file may legitimately not exist yet; absence renders an explicit
   "not yet published" state, never an error.
   ========================================================================== */

import {
  $, el, clear, fmtInt, fmtNum, plotColor, orderPlotTypes, classLabel,
  classRank, showPanelError, hidePanelError
} from './data.js?v=17f780a779';

let lightboxBound = false;

function emptyState(title, detail) {
  const box = el('div', 'media-empty');
  box.appendChild(el('h4', null, title));
  box.appendChild(el('p', null, detail));
  return box;
}

/** Number of items published for a view, for the headline stat strip. */
export function mediaCount(media, viewId) {
  const v = media && media.views && media.views[viewId];
  return (v && Array.isArray(v.items)) ? v.items.length : 0;
}

function onImgError(img, label) {
  img.addEventListener('error', () => {
    const ph = el('div', 'thumb-missing', label);
    if (img.parentNode) img.parentNode.replaceChild(ph, img);
  }, { once: true });
}

/* ------------------------------------------------------------------ photos */

function tile(item) {
  const src = item.thumb || item.display;
  if (!src) return null;
  const name = item.display_name || item.common_name || item.caption || item.id;
  const btn = el('button', 'gallery-item');
  btn.type = 'button';
  const img = el('img');
  img.src = src;
  img.loading = 'lazy';
  img.alt = name
    ? `${name}${item.sensor_type ? ' recorded by ' + item.sensor_type : ''}`
    : (item.caption || 'Wildlife photograph');
  onImgError(img, 'Image file not found');
  btn.appendChild(img);

  const meta = el('div', 'gallery-meta');
  meta.appendChild(el('div', 'gallery-common', name || 'Untitled'));
  if (item.latin_name) meta.appendChild(el('div', 'gallery-latin', item.latin_name));
  const bits = [];
  if (item.plot) bits.push(`Plot ${item.plot}`);
  if (item.schedule) bits.push(item.schedule);
  meta.appendChild(el('div', 'gallery-sensor',
    bits.length ? bits.join(' \u00b7 ') : (item.sensor_type || '')));
  // Number.isFinite on the RAW value, not on Number(...): Number(null) is 0,
  // which is finite, so coercing first sends a taxon with no detection-table
  // entry down the "has a count" branch and prints an em dash where the
  // explanation belongs.
  if (Number.isFinite(item.n_detections_season)) {
    meta.appendChild(el('div', 'gallery-count',
      `${fmtInt(item.n_detections_season)} records`));
  } else if (item.context) {
    // Photographed but absent from the detection table -- say so on the tile
    // rather than letting a missing count read as zero effort.
    meta.appendChild(el('div', 'gallery-count off', 'not in detection table'));
  }
  btn.appendChild(meta);

  btn.addEventListener('click', () => openLightbox(item));
  return btn;
}

/**
 * Photo gallery, grouped by taxonomic class.
 *
 * Grouping matters for this album specifically: the bucket-camera set is
 * twenty-odd reptiles and amphibians with a handful of mammals mixed in, and
 * ungrouped it reads as an undifferentiated wall of bucket interiors.
 */
function renderPhotos(items, body) {
  const usable = items.filter(i => i.thumb || i.display);
  if (!usable.length) {
    body.appendChild(emptyState('Media entries have no image paths.',
      'data/media.json listed items for this view but none carried a thumb or display path.'));
    return;
  }

  const byClass = new Map();
  for (const item of usable) {
    const k = item.taxon_class || null;
    if (!byClass.has(k)) byClass.set(k, []);
    byClass.get(k).push(item);
  }
  const keys = Array.from(byClass.keys())
    .sort((a, b) => classRank(a) - classRank(b));

  if (keys.length <= 1) {
    const gallery = el('div', 'gallery');
    for (const item of usable) {
      const t = tile(item);
      if (t) gallery.appendChild(t);
    }
    body.appendChild(gallery);
    return;
  }

  for (const k of keys) {
    const group = byClass.get(k);
    const wrap = el('div', 'gallery-group');
    const head = el('h4', 'gallery-group-head');
    head.appendChild(el('span', null, classLabel(k)));
    head.appendChild(el('span', 'gallery-group-count', `${group.length}`));
    wrap.appendChild(head);
    const gallery = el('div', 'gallery');
    for (const item of group) {
      const t = tile(item);
      if (t) gallery.appendChild(t);
    }
    wrap.appendChild(gallery);
    body.appendChild(wrap);
  }
}

function openLightbox(item) {
  const box = $('#lightbox');
  const img = $('#lightbox-img');
  if (!box || !img) return;
  img.src = item.display || item.thumb || '';
  img.alt = item.caption || item.display_name || item.common_name || 'Wildlife photograph';
  $('#lightbox-common').textContent = item.display_name || item.common_name || '';
  $('#lightbox-latin').textContent = item.latin_name || '';
  $('#lightbox-caption').textContent =
    [item.caption, item.context].filter(Boolean).join(' ');
  const credit = [];
  if (item.sensor_type) credit.push(item.sensor_type);
  if (item.plot) credit.push(`plot ${item.plot}`);
  if (item.schedule) credit.push(`${item.schedule} schedule`);
  if (item.recorded_local) credit.push(item.recorded_local);
  // Where the species name came from. A Wildlife Insights identification of
  // this exact frame and the researcher's own identification of a
  // hand-exported file are different kinds of claim.
  if (item.id_source === 'wildlife_insights') {
    credit.push('identified in Wildlife Insights');
  } else if (item.id_source === 'researcher') {
    credit.push('identified by the researcher');
  }
  if (item.credit) credit.push(item.credit);
  $('#lightbox-credit').textContent = credit.join(' \u00b7 ');
  box.hidden = false;
  const close = $('#lightbox-close');
  if (close) close.focus();
}

function closeLightbox() {
  const box = $('#lightbox');
  if (box) box.hidden = true;
  const img = $('#lightbox-img');
  if (img) img.src = '';
}

function bindLightbox() {
  if (lightboxBound) return;
  lightboxBound = true;
  const box = $('#lightbox');
  const close = $('#lightbox-close');
  if (close) close.addEventListener('click', closeLightbox);
  if (box) box.addEventListener('click', (ev) => { if (ev.target === box) closeLightbox(); });
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && box && !box.hidden) closeLightbox();
  });
}

/* ------------------------------------------------------------------- audio */

/** A list of BirdNET detections, each with confidence and offset when given. */
function detList(dets) {
  const ul = el('ul', 'det-list');
  for (const d of dets) {
    const li = el('li');
    li.appendChild(el('span', 'det-sp', d.species || 'Unidentified'));
    if (d.latin_name) li.appendChild(el('span', 'det-latin', d.latin_name));
    const bits = [];
    if (Number.isFinite(Number(d.confidence))) bits.push(`confidence ${fmtNum(Number(d.confidence), 2)}`);
    if (Number.isFinite(Number(d.start_sec))) bits.push(`at ${fmtNum(Number(d.start_sec), 0)} s`);
    if (bits.length) li.appendChild(el('span', 'det-num', bits.join(' \u2014 ')));
    ul.appendChild(li);
  }
  return ul;
}

function renderAudio(items, body) {
  const list = el('div', 'audio-list');
  let usable = 0;
  for (const item of items) {
    if (!item.audio && !item.spectrogram) continue;
    usable += 1;
    const card = el('div', 'audio-item');

    if (item.spectrogram) {
      const img = el('img', 'spectro');
      img.src = item.spectrogram;
      img.loading = 'lazy';
      img.alt = `Spectrogram of a recording from plot ${item.plot || 'unknown'}`;
      onImgError(img, 'Spectrogram file not found');
      card.appendChild(img);
    }

    const meta = el('div', 'audio-meta');
    const head = el('div', 'audio-head');
    // Species-named clips lead with the species; clips that instead carry a
    // plot and timestamp (the earlier export naming) lead with the plot.
    head.appendChild(el('span', 'audio-plot',
      item.common_name || (item.plot ? `Plot ${item.plot}` : (item.id || 'Recording'))));
    if (item.latin_name) head.appendChild(el('span', 'audio-latin', item.latin_name));
    if (item.plot_type) {
      const chip = el('span', 'audio-chip', item.plot_type);
      chip.style.background = plotColor(item.plot_type);
      head.appendChild(chip);
    }
    if (item.recorded_local) head.appendChild(el('span', 'audio-when', item.recorded_local));
    meta.appendChild(head);

    if (item.caption) meta.appendChild(el('p', 'audio-caption', item.caption));

    if (item.audio) {
      const audio = el('audio');
      audio.controls = true;
      audio.preload = 'none';
      audio.src = item.audio;
      meta.appendChild(audio);
      const fallback = el('p', 'panel-note');
      fallback.appendChild(el('span', null, 'If the player is empty, the clip file is missing: '));
      const a = el('a', null, item.audio);
      a.href = item.audio;
      fallback.appendChild(a);
      meta.appendChild(fallback);
    }

    // recording format, when the manifest reports it
    const fmt = [];
    if (Number.isFinite(Number(item.duration_sec))) fmt.push(`${fmtNum(Number(item.duration_sec), 0)} s excerpt`);
    if (Number.isFinite(Number(item.sample_rate_hz))) {
      fmt.push(`${fmtNum(Number(item.sample_rate_hz) / 1000, 0)} kHz`);
    }
    if (fmt.length) meta.appendChild(el('p', 'panel-note', fmt.join(' \u00b7 ')));

    // Clip-level detections when present. The media manifest may instead
    // publish detections: [] plus recording_context, because BirdNET detections
    // belong to the full parent recording and cannot be attributed to a short
    // excerpt -- render that context as parent-level, never as clip-level.
    const dets = Array.isArray(item.detections) ? item.detections : [];
    const ctx = item.recording_context && typeof item.recording_context === 'object'
      ? item.recording_context : null;
    const sctx = item.species_context && typeof item.species_context === 'object'
      ? item.species_context : null;

    // Species-named clip: the identification is the researcher's, and the
    // counts describe the species across the whole season. Label the scope
    // explicitly so a season total is never read as a count for this clip.
    if (sctx) {
      meta.appendChild(el('p', 'det-title', 'This species across the 2026 season'));
      const bits = [];
      if (Number.isFinite(Number(sctx.n_detections))) {
        // A cutoff-filtered count and a raw one are different quantities and
        // must not share a label.
        bits.push(sctx.filtered
          ? `${fmtInt(sctx.n_detections)} BirdNET detections at or above the ` +
            `validated cutoff of ${fmtNum(Number(sctx.threshold), 2)}` +
            (Number.isFinite(Number(sctx.n_detections_raw))
              ? ` (of ${fmtInt(sctx.n_detections_raw)} raw)` : '')
          : `${fmtInt(sctx.n_detections)} unvalidated BirdNET detections`);
      }
      if (Number.isFinite(Number(sctx.n_plots))) {
        bits.push(`at ${fmtInt(sctx.n_plots)} ARU plots`);
      }
      if (bits.length) meta.appendChild(el('p', 'audio-caption', bits.join(' ') + '.'));
      if (Number.isFinite(Number(sctx.n_clips_listened)) && sctx.n_clips_listened) {
        meta.appendChild(el('p', 'audio-caption',
          `${fmtInt(sctx.n_clips_listened)} clips of this species were reviewed by ear ` +
          `to establish that cutoff.`));
      }

      const byPt = sctx.by_plot_type && typeof sctx.by_plot_type === 'object'
        ? sctx.by_plot_type : null;
      if (byPt) {
        const total = Object.values(byPt).reduce((a, b) => a + Number(b || 0), 0);
        const rows = orderPlotTypes(Object.keys(byPt));
        const bars = el('div', 'ctx-bars');
        for (const pt of rows) {
          const n = Number(byPt[pt] || 0);
          const pct = total > 0 ? (100 * n / total) : 0;
          const row = el('div', 'ctx-row');
          row.appendChild(el('span', 'ctx-label', pt));
          const track = el('span', 'ctx-track');
          const fill = el('span', 'ctx-fill');
          fill.style.width = `${pct.toFixed(1)}%`;
          fill.style.background = plotColor(pt);
          track.appendChild(fill);
          row.appendChild(track);
          row.appendChild(el('span', 'ctx-value',
            `${fmtInt(n)} (${pct.toFixed(0)}%)`));
          bars.appendChild(row);
        }
        meta.appendChild(bars);
        meta.appendChild(el('p', 'panel-note',
          (sctx.note ? sctx.note + ' ' : '') +
          'Split by plot type and uncorrected for differences in recording ' +
          'effort among plots.'));
      }
    } else if (dets.length) {
      meta.appendChild(el('p', 'det-title', 'BirdNET detections in this clip'));
      meta.appendChild(detList(dets));
    } else if (ctx) {
      const bits = [];
      if (Number.isFinite(Number(ctx.n_detections))) bits.push(`${fmtInt(ctx.n_detections)} detections`);
      if (Number.isFinite(Number(ctx.n_species))) bits.push(`${fmtInt(ctx.n_species)} species`);
      meta.appendChild(el('p', 'det-title', 'BirdNET detections in the full parent recording'));
      meta.appendChild(el('p', 'audio-caption',
        (bits.length ? bits.join(', ') + ' ' : '') +
        `were flagged in the source recording` +
        (ctx.parent_recording ? ` (${ctx.parent_recording})` : '') +
        `. No detection can be attributed to this short excerpt, so none is listed against the clip.`));
      const top = Array.isArray(ctx.top_species) ? ctx.top_species : [];
      if (top.length) {
        meta.appendChild(el('p', 'det-title', 'Highest-confidence detections in that recording'));
        meta.appendChild(detList(top));
      }
    } else {
      meta.appendChild(el('p', 'det-title', 'No BirdNET detections listed for this clip'));
    }

    card.appendChild(meta);
    list.appendChild(card);
  }
  if (!usable) {
    body.appendChild(emptyState('Media entries have no audio or spectrogram paths.',
      'data/media.json listed items for this view but none carried an audio or spectrogram path.'));
    return;
  }
  body.appendChild(list);
}

/* ------------------------------------------------------------------- render */

export function renderMedia(ctx) {
  const body = $('#media-body');
  if (!body) return;
  const { media, mediaError, viewId, view } = ctx;
  clear(body);
  hidePanelError('#media-error');
  bindLightbox();

  const sub = $('#media-sub');

  if (!media) {
    if (sub) sub.textContent = '';
    body.appendChild(emptyState(
      'Example media are not published yet.',
      mediaError
        ? `data/media.json is not available (${mediaError}). Once the media step writes it, ` +
          `photographs and annotated audio clips appear here automatically.`
        : 'data/media.json has not been written yet. Once the media step publishes it, ' +
          'photographs and annotated audio clips appear here automatically.'));
    return;
  }

  const entry = media.views && media.views[viewId];
  if (!entry || !Array.isArray(entry.items) || !entry.items.length) {
    if (sub) sub.textContent = '';
    body.appendChild(emptyState(
      'No example media for this view yet.',
      `data/media.json is published but carries no items for "${viewId}".`));
    return;
  }

  const kind = entry.kind || (view && view.id === 'bird_frog_audio' ? 'audio' : 'photo');
  if (sub) {
    sub.textContent = kind === 'audio'
      ? `${entry.items.length} example recordings with spectrograms and the BirdNET detections logged for each clip. ` +
        `Clips are illustrative, not a sample for analysis.`
      : `${entry.items.length} example photographs. Images are cropped and stripped of embedded metadata; ` +
        `they are illustrative, not a sample for analysis.`;
  }

  if (kind === 'audio') renderAudio(entry.items, body);
  else renderPhotos(entry.items, body);
}
