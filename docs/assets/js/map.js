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
} from './data.js?v=a5de6b6827';

let map = null;
let layer = null;

/* Which basemap loads first. A light labelled base keeps the plot-type marker
   colours legible, which is what this map is for; aerial imagery is one click
   away for anyone who wants to see the stands. Change this string to any key
   in the `layers` object built in renderMap().

   Deliberately NOT OpenStreetMap's own tiles. Those are served by volunteer
   infrastructure under a usage policy that asks not to be treated as a free
   CDN for websites, and requests lacking an identifying User-Agent are
   refused outright with a "403 Access blocked" tile. They stay available in
   the switcher for local or occasional use; they are a poor choice to point a
   published, shared dashboard at by default. */
const BASEMAP_DEFAULT = 'Topographic (Esri)';

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

/** The detection block this view publishes for a point, if any. */
export function detectionsFor(point, viewId) {
  const d = point && point.detections;
  return (d && d[viewId]) ? d[viewId] : null;
}

/**
 * Species-tally table for a marker.
 *
 * Capped on hover and complete on click. An ARU plot carries detections of
 * sixty-odd species, which is a useful list to be able to read in full and an
 * unusable one to have follow the cursor around, so the hover tooltip shows
 * the leading rows and says how many it left out.
 */
function speciesTableHTML(det, limit) {
  const rows = Array.isArray(det.species) ? det.species : [];
  if (!rows.length) {
    return '<p class="popup-empty">No detections recorded at this sensor.</p>';
  }
  const shown = (limit && rows.length > limit) ? rows.slice(0, limit) : rows;
  const body = shown.map(s =>
    `<tr><th>${escapeHTML(s.name)}</th><td>${fmtInt(s.n)}</td></tr>`).join('');
  const hiddenHere = rows.length - shown.length;
  // species_truncated counts rows the BUILD dropped before publishing; add it
  // to the rows this render is hiding, so the "+N more" is never an undercount.
  const hiddenUpstream = Number(det.species_truncated) || 0;
  const more = hiddenHere + hiddenUpstream;
  return `<table class="popup-table popup-species">${body}</table>` +
         (more
           ? `<p class="popup-more">+${fmtInt(more)} more species\u2014click the marker for the full list.</p>`
           : '');
}

function popupHTML(p, viewId, opts) {
  const o = opts || {};
  const det = detectionsFor(p, viewId);
  const head = [
    ['Plot', p.plot],
    ['Plot type', p.plot_type],
    ['Sensor', p.sensor_type]
  ];
  if (det) {
    head.push([det.unit.charAt(0).toUpperCase() + det.unit.slice(1),
      `${fmtInt(det.n_detections)} of ${fmtInt(det.n_species)} taxa`]);
    if (det.effort) head.push(['Effort', det.effort]);
  }
  if (o.full) {
    head.push(['Approx. position',
      `${Number(p.lat).toFixed(3)}, ${Number(p.lon).toFixed(3)}`]);
  }
  const headBody = head.filter(([, v]) => v !== null && v !== undefined)
    .map(([k, v]) => `<tr><th>${escapeHTML(k)}</th><td>${escapeHTML(v)}</td></tr>`)
    .join('');

  let detail = '';
  if (det) {
    const scope = det.scope === 'plot'
      ? `Tallied for the ${escapeHTML(det.scope_label)} \u2014 the plot carries one.`
      : `Tallied for ${escapeHTML(det.scope_label)}.`;
    detail = `<p class="popup-scope">${scope}</p>` +
             speciesTableHTML(det, o.full ? null : 14);
  } else {
    detail = '<p class="popup-empty">This view publishes no detection tally for ' +
             'this sensor.</p>';
  }

  return `<div class="popup-title">${escapeHTML(p.id)}</div>` +
         `<table class="popup-table">${headBody}</table>` +
         detail +
         (o.full
           ? '<p class="popup-approx">Position is displaced by design; see the note above the map.</p>'
           : '');
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
    if (locations.popup_note) parts.push(locations.popup_note);
    const withTallies = points.filter(p => detectionsFor(p, viewId)).length;
    if (points.length && withTallies < points.length) {
      parts.push(`${fmtInt(points.length - withTallies)} of ${fmtInt(points.length)} ` +
        `markers recorded nothing in this view and carry no species list.`);
    }
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

    // Basemaps are offered as a switchable set, all of them KEYLESS.
    //
    // This panel previously used CARTO's open "light_all" endpoint. CARTO has
    // since moved its basemaps behind an API key, and an unauthenticated
    // request now returns a placeholder tile reading "API key required" --
    // which is worse than no basemap, because it renders as content rather
    // than failing and tripping the tileerror handler below. Offering a
    // choice means the next provider to change its terms costs a click
    // instead of a code edit, and "No basemap" makes the offline-correct
    // state reachable deliberately rather than only by accident.
    const layers = {};
    layers['Topographic (Esri)'] = L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}', {
        maxZoom: 19,
        attribution:
          'Tiles &copy; <a href="https://www.esri.com/">Esri</a> and the GIS ' +
          'User Community'
      });
    // Aerial imagery earns its place here beyond cartographic taste: the
    // stand boundaries, harvest openings and turbine clearings that the plot
    // types are defined by are visible in it and invisible on a street map.
    layers['Aerial imagery (Esri)'] = L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        maxZoom: 19,
        attribution:
          'Imagery &copy; <a href="https://www.esri.com/">Esri</a>, Maxar, ' +
          'Earthstar Geographics, and the GIS User Community'
      });
    // Available but not the default -- see the note on BASEMAP_DEFAULT.
    layers['OpenStreetMap'] = L.tileLayer(
      'https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
      });
    layers['No basemap'] = L.tileLayer('', { attribution: '' });

    // The basemap is the only remaining network dependency. Sensor markers,
    // the legend and the precision note are all drawn from local data and
    // stay correct without it, so a tile failure gets a quiet caption rather
    // than an error: the map is still readable, just without the backdrop.
    const note = document.getElementById('map-basemap-note');
    const warned = new Set();
    for (const [name, layer] of Object.entries(layers)) {
      if (name === 'No basemap') continue;
      layer.on('tileerror', () => {
        if (warned.has(name)) return;
        warned.add(name);
        if (!note) return;
        note.hidden = false;
        note.textContent =
          `Background tiles from ${name} could not be loaded. Sensor ` +
          `positions, colours and the legend below are drawn from local data ` +
          `and remain accurate. If this is not simply a lack of network ` +
          `access, pick a different basemap from the control in the top ` +
          `right of the map.`;
      });
      layer.on('tileload', () => {
        if (note && !warned.size) note.hidden = true;
      });
    }

    layers[BASEMAP_DEFAULT].addTo(map);
    L.control.layers(layers, null, { position: 'topright', collapsed: true })
      .addTo(map);
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
    const marker = L.circleMarker([pt.lat, pt.lon], {
      radius: 6,
      color: '#ffffff',
      weight: 1.5,
      opacity: 1,
      fillColor: plotColor(pt.plot_type),
      fillOpacity: 0.92,
      className: 'sensor-marker'
    });
    // Hover gives the capped species tally straight away; click pins the
    // full list, which is the only readable way to show sixty-odd species.
    marker.bindTooltip(popupHTML(pt, viewId, { full: false }), {
      sticky: true, direction: 'top', opacity: 1,
      className: 'sensor-tooltip'
    });
    marker.bindPopup(popupHTML(pt, viewId, { full: true }), { maxWidth: 340 });
    marker.on('popupopen', () => marker.closeTooltip());
    marker.addTo(layer);
  }
  layer.addTo(map);
  map.fitBounds(L.latLngBounds(valid.map(p => [p.lat, p.lon])).pad(0.12));
  // Leaflet needs a nudge when its container was hidden at init time.
  window.setTimeout(() => map && map.invalidateSize(), 60);
}

export function invalidateMap() {
  if (map) window.setTimeout(() => map.invalidateSize(), 40);
}
