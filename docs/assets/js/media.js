/* ==========================================================================
   media.js -- example media panel.

   Source: data/media.json, written by a separate media pipeline step.
     {"views": {"<view_id>": {"kind": "photo"|"audio", "items": [...]}}}
   Paths inside it are relative to docs/, so they are used as-is.
   The file may legitimately not exist yet; absence renders an explicit
   "not yet published" state, never an error.
   ========================================================================== */

import { $, el, clear, fmtInt, fmtNum, plotColor, orderPlotTypes, showPanelError, hidePanelError } from './data.js';

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

function renderPhotos(items, body) {
  const gallery = el('div', 'gallery');
  let usable = 0;
  for (const item of items) {
    const src = item.thumb || item.display;
    if (!src) continue;
    usable += 1;
    const btn = el('button', 'gallery-item');
    btn.type = 'button';
    const img = el('img');
    img.src = src;
    img.loading = 'lazy';
    img.alt = item.common_name
      ? `${item.common_name}${item.sensor_type ? ' recorded by ' + item.sensor_type : ''}`
      : (item.caption || 'Wildlife photograph');
    onImgError(img, 'Image file not found');
    btn.appendChild(img);

    const meta = el('div', 'gallery-meta');
    meta.appendChild(el('div', 'gallery-common', item.common_name || item.caption || item.id || 'Untitled'));
    if (item.latin_name) meta.appendChild(el('div', 'gallery-latin', item.latin_name));
    if (item.sensor_type) meta.appendChild(el('div', 'gallery-sensor', item.sensor_type));
    btn.appendChild(meta);

    btn.addEventListener('click', () => openLightbox(item));
    gallery.appendChild(btn);
  }
  if (!usable) {
    body.appendChild(emptyState('Media entries have no image paths.',
      'data/media.json listed items for this view but none carried a thumb or display path.'));
    return;
  }
  body.appendChild(gallery);
}

function openLightbox(item) {
  const box = $('#lightbox');
  const img = $('#lightbox-img');
  if (!box || !img) return;
  img.src = item.display || item.thumb || '';
  img.alt = item.caption || item.common_name || 'Wildlife photograph';
  $('#lightbox-common').textContent = item.common_name || '';
  $('#lightbox-latin').textContent = item.latin_name || '';
  $('#lightbox-caption').textContent = item.caption || '';
  const credit = [];
  if (item.sensor_type) credit.push(item.sensor_type);
  if (item.credit) credit.push(item.credit);
  $('#lightbox-credit').textContent = credit.join(' \u2014 ');
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
        bits.push(`${fmtInt(sctx.n_detections)} unvalidated BirdNET detections`);
      }
      if (Number.isFinite(Number(sctx.n_plots))) {
        bits.push(`at ${fmtInt(sctx.n_plots)} of 35 ARU plots`);
      }
      if (bits.length) meta.appendChild(el('p', 'audio-caption', bits.join(' ') + '.'));

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
          'Detections by plot type for this species over the whole season, ' +
          'not for this clip. Uncorrected for differences in recording effort ' +
          'among plots.'));
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
