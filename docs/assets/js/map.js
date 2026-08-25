/* ==========================================================================
   map.js -- Leaflet map of approximate sensor locations.

   Source: data/locations.json (points[] + precision_note).
   Points are filtered per active view:
     bucket_camera    -> sensor_type "AHDriFT"
     parallel_camera  -> sensor_type "Camera Trap"
     bird_frog_audio  -> AHDriFT points whose plot code appears in
                         birdnet.json .plots[]  (ARUs sit at AHDriFT locations)
   ========================================================================== */

import {
  $, el, clear, orderPlotTypes, plotColor, fmtInt,
  showPanelError, hidePanelError, waitForGlobal
} from './data.js';

let map = null;
let layer = null;

/**
 * Pure selector: which location points belong to a view.
 * Exported for testing against the real JSON.
 */
export function pointsForView(locations, viewId, birdnet) {
  const points = (locations && Array.isArray(locations.points)) ? locations.points : [];
  if (viewId === 'bucket_camera') {
    return points.filter(p => p.sensor_type === 'AHDriFT');
  }
  if (viewId === 'parallel_camera') {
    return points.filter(p => p.sensor_type === 'Camera Trap');
  }
  if (viewId === 'bird_frog_audio') {
    const aruPlots = new Set(
      (birdnet && Array.isArray(birdnet.plots) ? birdnet.plots : []).map(p => p.plot)
    );
    // One marker per ARU plot: ARUs are logged at the plot, not the point, so
    // collapse the AHDriFT points of a plot to a single representative marker.
    const seen = new Set();
    const out = [];
    for (const p of points) {
      if (p.sensor_type !== 'AHDriFT' || !aruPlots.has(p.plot) || seen.has(p.plot)) continue;
      seen.add(p.plot);
      out.push({ ...p, id: p.plot, sensor_type: 'ARU (bird/frog)' });
    }
    return out;
  }
  return [];
}

/** Which ARU plots in birdnet.json have no coordinate in locations.json. */
export function unlocatedAruPlots(locations, birdnet) {
  const have = new Set(
    (locations && Array.isArray(locations.points) ? locations.points : [])
      .filter(p => p.sensor_type === 'AHDriFT').map(p => p.plot)
  );
  return (birdnet && Array.isArray(birdnet.plots) ? birdnet.plots : [])
    .map(p => p.plot).filter(code => !have.has(code));
}

/** Counts by plot type, in canonical order, for the legend. */
export function legendCounts(points) {
  const counts = new Map();
  for (const p of points) counts.set(p.plot_type, (counts.get(p.plot_type) || 0) + 1);
  return orderPlotTypes(Array.from(counts.keys()))
    .map(pt => ({ plot_type: pt, n: counts.get(pt) }));
}

function popupHTML(p, view) {
  const rows = [
    ['Sensor', p.id],
    ['Plot', p.plot],
    ['Plot type', p.plot_type],
    ['Sensor type', p.sensor_type],
    ['Approx. position', `${Number(p.lat).toFixed(3)}, ${Number(p.lon).toFixed(3)}`]
  ];
  if (view && view.extraRows) rows.push(...view.extraRows(p));
  const body = rows.map(([k, v]) =>
    `<tr><th>${escapeHTML(k)}</th><td>${escapeHTML(v)}</td></tr>`).join('');
  return `<div class="popup-title">${escapeHTML(p.id)}</div>` +
         `<table class="popup-table">${body}</table>` +
         `<p class="popup-approx">Position is displaced by design; see the note above the map.</p>`;
}

function escapeHTML(s) {
  return String(s === null || s === undefined ? '\u2014' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function renderLegend(points) {
  const box = $('#map-legend');
  if (!box) return;
  clear(box);
  const entries = legendCounts(points);
  if (!entries.length) {
    box.appendChild(el('span', 'muted', 'No sensors to show for this view.'));
    return;
  }
  for (const { plot_type, n } of entries) {
    const item = el('span', 'legend-item');
    const sw = el('span', 'legend-swatch');
    sw.style.background = plotColor(plot_type);
    item.appendChild(sw);
    item.appendChild(el('span', null, plot_type));
    item.appendChild(el('span', 'legend-count', `(${fmtInt(n)})`));
    box.appendChild(item);
  }
}

/**
 * Draw (or redraw) the map for one view.
 * @param {object} ctx {locations, birdnet, view, viewId}
 */
export async function renderMap(ctx) {
  const container = $('#map');
  if (!container) return;
  const { locations, birdnet, viewId, view } = ctx;

  hidePanelError('#map-error');

  // precision note -- always visible, straight from the data file
  const noteBox = $('#map-precision-note');
  if (noteBox) {
    clear(noteBox);
    noteBox.appendChild(el('span', 'label', 'Approximate locations. '));
    const note = (locations && locations.precision_note)
      ? locations.precision_note
      : 'Coordinate precision note missing from locations.json -- treat all positions as approximate.';
    noteBox.appendChild(el('span', null, note));
    if (locations && locations.jitter_min_m !== undefined && locations.jitter_max_m !== undefined) {
      noteBox.appendChild(el('span', null,
        ` Displacement applied: ${locations.jitter_min_m}\u2013${locations.jitter_max_m} m.`));
    }
  }

  if (!locations) {
    showPanelError('#map-error', 'Map unavailable.',
      'data/locations.json could not be loaded, so sensor positions cannot be drawn.');
    clear(container);
    return;
  }

  const points = pointsForView(locations, viewId, birdnet);
  renderLegend(points);

  const sub = $('#map-sub');
  if (sub) {
    const total = Array.isArray(locations.points) ? locations.points.length : 0;
    sub.textContent = viewId === 'bird_frog_audio'
      ? `${fmtInt(points.length)} recording plots shown (of ${fmtInt(total)} mapped sensor points in the study). ` +
        `Bird and frog units are logged by plot; markers sit at the co-located bucket-camera position.`
      : `${fmtInt(points.length)} of ${fmtInt(total)} mapped sensor points, filtered to ` +
        `${view && view.sensor_type ? view.sensor_type : 'this view'}.`;
  }

  const noteEl = $('#map-note');
  if (noteEl) {
    const parts = [];
    if (viewId === 'bird_frog_audio') {
      const missing = unlocatedAruPlots(locations, birdnet);
      if (missing.length) {
        parts.push(`${missing.length} recording plot${missing.length === 1 ? '' : 's'} ` +
          `(${missing.join(', ')}) ha${missing.length === 1 ? 's' : 've'} no entry in locations.json ` +
          `and cannot be mapped; the effort and species panels still include ` +
          `${missing.length === 1 ? 'it' : 'them'}.`);
      }
      if (birdnet && birdnet.plot_label_note) parts.push(birdnet.plot_label_note);
    }
    noteEl.textContent = parts.join(' ');
  }

  let L;
  try {
    L = await waitForGlobal('L');
  } catch (err) {
    showPanelError('#map-error', 'Map library unavailable.', err.message);
    return;
  }

  if (!map) {
    map = L.map(container, { scrollWheelZoom: false, zoomSnap: 0.5 });
    // Single hostname rather than Leaflet's {s} a/b/c shard placeholder: domain
    // sharding gains nothing over HTTP/2 and costs two extra DNS lookups.
    const tiles = L.tileLayer(
      'https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        maxZoom: 18,
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, ' +
          '&copy; <a href="https://carto.com/attributions">CARTO</a>'
      });
    // The basemap is the one remaining network dependency. Sensor markers,
    // the legend and the precision note are all drawn from local data and
    // stay correct without it, so a tile failure gets a quiet caption rather
    // than an error: the map is still readable, just without the backdrop.
    let tileWarned = false;
    tiles.on('tileerror', () => {
      if (tileWarned) return;
      tileWarned = true;
      const note = document.getElementById('map-basemap-note');
      if (note) {
        note.hidden = false;
        note.textContent =
          'Background map tiles could not be loaded (no network access). ' +
          'Sensor positions, colours and the legend below are drawn from ' +
          'local data and remain accurate.';
      }
    });
    tiles.addTo(map);
    map.on('click', () => { /* keeps focus behaviour predictable on touch */ });
  }
  if (layer) { layer.remove(); layer = null; }

  const valid = points.filter(p => Number.isFinite(p.lat) && Number.isFinite(p.lon));
  if (!valid.length) {
    map.setView([36.13, -76.55], 11);
    showPanelError('#map-error', 'No mappable sensors for this view.',
      'locations.json contained no points matching this view\u2019s sensor type.');
    return;
  }

  layer = L.layerGroup();
  for (const pt of valid) {
    L.circleMarker([pt.lat, pt.lon], {
      radius: 6,
      color: '#ffffff',
      weight: 1.5,
      opacity: 1,
      fillColor: plotColor(pt.plot_type),
      fillOpacity: 0.92,
      className: 'sensor-marker'
    }).bindPopup(popupHTML(pt, view), { maxWidth: 300 }).addTo(layer);
  }
  layer.addTo(map);
  map.fitBounds(L.latLngBounds(valid.map(p => [p.lat, p.lon])).pad(0.12));
  // Leaflet needs a nudge when its container was hidden at init time.
  window.setTimeout(() => map && map.invalidateSize(), 60);
}

export function invalidateMap() {
  if (map) window.setTimeout(() => map.invalidateSize(), 40);
}
