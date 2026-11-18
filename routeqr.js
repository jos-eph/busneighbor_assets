// QR codes for route links, drawn in the page: on screen, on a printable sign,
// and as a PNG to download. Only share.html loads this file, and it is the only
// file that imports the vendored encoder. No network, no storage.

import qrcode from './vendor/qrcode-generator/qrcode.mjs';

// The QR standard's minimum margin, in modules.
export const QR_QUIET_ZONE_MODULES = 4;
// Recovers from about a quarter of the code being damaged: printed signs get
// scuffed, taped over, and photographed at an angle.
export const QR_ERROR_CORRECTION = 'Q';
export const PNG_PIXELS_PER_MODULE = 16;
const FILE_NAME_MAX_ROUTES = 6;
const SVG_NS = 'http://www.w3.org/2000/svg';
const DARK = '#000000';
const LIGHT = '#ffffff';

/** Square grid of booleans, true = dark, without the quiet zone. */
export function qrModules(text) {
  if (!text) throw new TypeError('no text to encode');
  const qr = qrcode(0, QR_ERROR_CORRECTION);
  qr.addData(text, 'Byte');
  qr.make();
  const size = qr.getModuleCount();
  return Array.from({ length: size }, (_, row) =>
    Array.from({ length: size }, (_, col) => qr.isDark(row, col)),
  );
}

/** Side of the drawn code in modules, quiet zone included. */
export function qrSide(modules, quiet = QR_QUIET_ZONE_MODULES) {
  return modules.length + 2 * quiet;
}

/** Each row's runs of dark modules, as [x, y, length], offset by the quiet zone. */
export function qrRuns(modules, quiet = QR_QUIET_ZONE_MODULES) {
  const runs = [];
  modules.forEach((row, y) => {
    let x = 0;
    while (x < row.length) {
      if (row[x]) {
        const start = x;
        while (x < row.length && row[x]) x += 1;
        runs.push([start + quiet, y + quiet, x - start]);
      } else {
        x += 1;
      }
    }
  });
  return runs;
}

/** SVG path data drawing every dark module, one rectangle per run. */
export function qrPathData(modules, quiet = QR_QUIET_ZONE_MODULES) {
  return qrRuns(modules, quiet)
    .map(([x, y, length]) => `M${x} ${y}h${length}v1h-${length}z`)
    .join('');
}

/** "47", "17 and 23", "17, 23, and 47". */
export function routeList(routes) {
  if (routes.length <= 2) return routes.join(' and ');
  return `${routes.slice(0, -1).join(', ')}, and ${routes.at(-1)}`;
}

export function qrLabel(routes) {
  const which = routes.length === 1 ? 'route' : 'routes';
  return `QR code for the link to ${which} ${routeList(routes)}`;
}

export function signTitle(routes) {
  return routes.length === 1
    ? `Live buses on Route ${routes[0]}`
    : `Live buses on routes ${routeList(routes)}`;
}

/** The link as people read it: no scheme. The code itself holds the full link. */
export function displayLink(link) {
  return link.replace(/^https:\/\//, '');
}

/** Route ids are limited to [A-Za-z0-9_-], so they are safe in a file name. */
export function qrFileName(routes) {
  if (routes.length === 1) return `busneighbor-route-${routes[0]}.png`;
  if (routes.length <= FILE_NAME_MAX_ROUTES) return `busneighbor-routes-${routes.join('-')}.png`;
  const rest = routes.length - 3;
  return `busneighbor-routes-${routes.slice(0, 3).join('-')}-and-${rest}-more.png`;
}

/** The code as an <svg>: black modules on a white square, quiet zone included. */
export function qrSvg(doc, modules, label) {
  const side = qrSide(modules);
  const svg = doc.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${side} ${side}`);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', label);
  svg.setAttribute('shape-rendering', 'crispEdges');
  const background = doc.createElementNS(SVG_NS, 'rect');
  background.setAttribute('width', side);
  background.setAttribute('height', side);
  background.setAttribute('fill', LIGHT);
  const path = doc.createElementNS(SVG_NS, 'path');
  path.setAttribute('d', qrPathData(modules));
  path.setAttribute('fill', DARK);
  svg.append(background, path);
  return svg;
}

/** The code as a PNG Blob, whole pixels per module, or null if the browser can't make one. */
export function qrPngBlob(doc, modules, pixelsPerModule = PNG_PIXELS_PER_MODULE) {
  const canvas = doc.createElement('canvas');
  canvas.width = canvas.height = qrSide(modules) * pixelsPerModule;
  const context = canvas.getContext('2d');
  if (!context) return Promise.resolve(null);
  context.imageSmoothingEnabled = false;
  context.fillStyle = LIGHT;
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = DARK;
  for (const [x, y, length] of qrRuns(modules)) {
    context.fillRect(x * pixelsPerModule, y * pixelsPerModule, length * pixelsPerModule, pixelsPerModule);
  }
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
}

/**
 * Wires the share page's QR section, sign, and buttons. Returns the callback for
 * initSharePage's onLink, called with the link and the chosen routes on every change.
 */
export function initQr(root = document) {
  const section = root.getElementById('qr-section');
  const card = root.getElementById('link-qr');
  const status = root.getElementById('route-status');
  const signTitleText = root.getElementById('print-title');
  const signQr = root.getElementById('print-qr');
  const signLink = root.getElementById('print-link');
  let current = null;

  function update(link, chosen) {
    current = null;
    root.body.classList.remove('has-sign');
    if (chosen.length === 0) {
      card.replaceChildren();
      signQr.replaceChildren();
      return;
    }
    try {
      const modules = qrModules(link);
      const label = qrLabel(chosen);
      card.replaceChildren(qrSvg(root, modules, label));
      signTitleText.textContent = signTitle(chosen);
      signQr.replaceChildren(qrSvg(root, modules, label));
      signLink.textContent = displayLink(link);
      section.hidden = false;
      root.body.classList.add('has-sign');
      current = { modules, chosen };
    } catch (error) {
      // The link still works without its code.
      console.error(error);
      section.hidden = true;
      status.textContent = "Couldn't make a QR code for this link.";
    }
  }

  root.getElementById('qr-print').addEventListener('click', () => {
    if (current) window.print();
  });

  root.getElementById('qr-download').addEventListener('click', async () => {
    if (!current) return;
    const blob = await qrPngBlob(root, current.modules);
    if (!blob) {
      status.textContent = "Couldn't make the image. Try printing the sign instead.";
      return;
    }
    const url = URL.createObjectURL(blob);
    const anchor = root.createElement('a');
    anchor.href = url;
    anchor.download = qrFileName(current.chosen);
    anchor.hidden = true;
    root.body.append(anchor);
    anchor.click();
    anchor.remove();
    // Give the download a moment to start before the URL goes away.
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
    status.textContent = 'QR code downloaded.';
  });

  return update;
}
