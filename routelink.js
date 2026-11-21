// Route links: shared by share.html and the route pages (build a link) and
// go.html (opens one). No dependencies, no storage, no network beyond the
// same-origin route list. share.html adds its QR code through onLink
// (routeqr.js), so the route pages never load the encoder.

// Same-origin copy of the route catalog, written into the site by the Pages
// build. The release asset itself cannot be fetched from a browser: it sends
// no Access-Control-Allow-Origin header.
// Root-relative, so the route pages under /route/ find it too.
export const ROUTE_LIST_URL = '/septameta.json';

export const LINK_BASE = 'https://bus.dydx.org/go';
export const APP_LINK_BASE = 'busneighbor://go';
const SHARE_PAGE = '/share.html';

// Keep in step with the app's parsers (route_link.dart, track_link.dart).
export const MAX_ROUTES = 20;
export const MAX_TRACKED = 3;
export const MAX_ROUTE_LENGTH = 16;
export const MAX_VEHICLE_DIGITS = 5;
const ROUTE_ID = /^[A-Za-z0-9_-]{1,16}$/;
const VEHICLE_ID = /^[0-9]{1,5}$/;

/** Routes the app offers: the catalog's order, minus routes with no live positions. */
export function offeredRoutes(meta) {
  const list = meta?.buses?.route_list;
  if (!Array.isArray(list)) throw new TypeError('route_list missing');
  const hidden = new Set(meta?.realtime?.overrides?.no_vehicle_positions ?? []);
  const seen = new Set();
  const routes = [];
  for (const entry of list) {
    const id = typeof entry === 'string' ? entry.trim() : '';
    if (ROUTE_ID.test(id) && !hidden.has(id) && !seen.has(id)) {
      seen.add(id);
      routes.push(id);
    }
  }
  if (routes.length === 0) throw new TypeError('route_list empty');
  return routes;
}

/**
 * The route ids in a `?routes=4,9,21` query, in order, without repeats,
 * along with whether any non-empty item failed validation.
 */
export function parseRoutes(search) {
  const raw = new URLSearchParams(search).get('routes');
  if (raw === null) return { routes: [], malformed: false };
  const ids = new Set();
  for (const item of raw.split(',')) {
    const id = item.trim();
    if (id === '') continue;
    if (!ROUTE_ID.test(id)) return { routes: [], malformed: true };
    ids.add(id);
  }
  return { routes: [...ids].slice(0, MAX_ROUTES), malformed: false };
}

/**
 * The buses a `?track=47:3112,21:1234` query names, as `{route, vehicle}`
 * pairs in order, each vehicle once and at most MAX_TRACKED, along with
 * whether any non-empty item failed validation. Null when the query has no
 * `track`.
 */
export function parseTrack(search) {
  const raw = new URLSearchParams(search).get('track');
  if (raw === null) return null;
  const byVehicle = new Map();
  for (const item of raw.split(',')) {
    const trimmed = item.trim();
    if (trimmed === '') continue;
    const parts = trimmed.split(':');
    if (parts.length !== 2) return { pairs: [], malformed: true };
    const [route, vehicle] = parts;
    if (!ROUTE_ID.test(route) || !VEHICLE_ID.test(vehicle)) {
      return { pairs: [], malformed: true };
    }
    if (!byVehicle.has(vehicle)) byVehicle.set(vehicle, { route, vehicle });
  }
  return { pairs: [...byVehicle.values()].slice(0, MAX_TRACKED), malformed: false };
}

export function buildLink(base, routes, track = null) {
  // Ids are limited to URL-safe characters, so commas and colons stay readable.
  const link = `${base}?routes=${routes.join(',')}`;
  if (track === null) return link;
  return `${link}&track=${track.map(({ route, vehicle }) => `${route}:${vehicle}`).join(',')}`;
}

function joinWithAnd(items) {
  if (items.length <= 2) return items.join(' and ');
  return `${items.slice(0, -1).join(', ')}, and ${items.at(-1)}`;
}

/**
 * What go.html shows for a link's query: the summary, the hint under the
 * button, and the app link (null hides the button). When `offered` is given,
 * only catalog routes are named and kept in `href`; when `offered` is null
 * (catalog unavailable), generic text with no ids is shown.
 */
export function goPageContent(search, offered = null) {
  const routeResult = parseRoutes(search);
  const trackResult = parseTrack(search);
  if (routeResult.malformed || trackResult?.malformed) {
    return { summary: "This link isn't valid.", hint: null, href: null };
  }
  const routes = routeResult.routes;
  const track = trackResult === null ? null : trackResult.pairs;
  if (offered === null) return genericContent(routes, track);
  const available = new Set(offered);
  const knownRoutes = routes.filter((id) => available.has(id));
  if (track !== null) return trackingContent(knownRoutes, track, available);
  if (routes.length === 0) {
    return { summary: "This link doesn't name any routes.", hint: null, href: null };
  }
  if (knownRoutes.length === 0) {
    return { summary: "The routes in this link aren't available.", hint: null, href: null };
  }
  return {
    summary:
      knownRoutes.length === 1
        ? `This link shows route ${knownRoutes[0]} in BusNeighbor.`
        : `This link shows these routes in BusNeighbor: ${knownRoutes.join(', ')}.`,
    hint: 'BusNeighbor asks before it replaces the routes you already have.',
    href: buildLink(APP_LINK_BASE, knownRoutes),
  };
}

function genericContent(routes, track) {
  if (track !== null) {
    if (track.length === 0) {
      return { summary: "This link doesn't name a bus BusNeighbor can show.", hint: null, href: null };
    }
    const busRoutes = new Set(track.map((bus) => bus.route));
    const linkRoutes = routes.length > 0 ? routes : [...busRoutes];
    const theBuses = track.length === 1 ? 'the bus' : 'the buses';
    return {
      summary: 'This link opens routes in BusNeighbor.',
      hint: `BusNeighbor adds ${theBuses} to your map. Your routes stay as they are.`,
      href: buildLink(APP_LINK_BASE, linkRoutes, track),
    };
  }
  if (routes.length === 0) {
    return { summary: "This link doesn't name any routes.", hint: null, href: null };
  }
  return {
    summary: 'This link opens routes in BusNeighbor.',
    hint: 'BusNeighbor asks before it replaces the routes you already have.',
    href: buildLink(APP_LINK_BASE, routes),
  };
}

function trackingContent(routes, track, available) {
  // Like the app, a broken `track` never falls back to the routes.
  if (track.length === 0) {
    return { summary: "This link doesn't name a bus BusNeighbor can show.", hint: null, href: null };
  }
  const knownTrack = track.filter((bus) => available.has(bus.route));
  if (knownTrack.length === 0) {
    return {
      summary: "This link's bus is on a route BusNeighbor doesn't have.",
      hint: null,
      href: null,
    };
  }
  // The app's links repeat the buses' routes in `routes`, for builds that
  // don't track; keep that true for a hand-made link that leaves it out.
  const busRoutes = new Set(knownTrack.map((bus) => bus.route));
  const linkRoutes = routes.length > 0 ? routes : [...busRoutes];
  // The rest of the sender's map, which the app adds along with the buses.
  const extra = routes.filter((route) => !busRoutes.has(route));
  const buses = joinWithAnd(knownTrack.map(({ route, vehicle }) => `bus ${vehicle} on route ${route}`));
  const theBuses = knownTrack.length === 1 ? 'the bus' : 'the buses';
  const href = buildLink(APP_LINK_BASE, linkRoutes, knownTrack);
  if (extra.length === 0) {
    return {
      summary: `This link tracks ${buses} in BusNeighbor.`,
      hint: `BusNeighbor adds ${theBuses} to your map. Your routes stay as they are.`,
      href,
    };
  }
  const shows = extra.length === 1 ? `route ${extra[0]}` : `routes ${joinWithAnd(extra)}`;
  const theseRoutes = extra.length === 1 ? 'this route' : 'these routes';
  return {
    summary: `This link shows ${shows} in BusNeighbor and tracks ${buses}.`,
    hint: `BusNeighbor adds ${theseRoutes} and ${theBuses} to your map. Your other routes stay as they are.`,
    href,
  };
}

async function fetchRoutes() {
  // no-cache revalidates on every load, so a new route list shows up at once.
  const response = await fetch(ROUTE_LIST_URL, { cache: 'no-cache' });
  if (!response.ok) throw new Error(`route list: HTTP ${response.status}`);
  return offeredRoutes(await response.json());
}

function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
}

/**
 * `preselect`: routes chosen when the page opens, as on a route's own page.
 * `onLink(link, chosen)`: called after every change, with ('', []) when nothing is chosen.
 */
export async function initSharePage(root = document, { preselect = [], onLink = () => {} } = {}) {
  const picker = root.getElementById('route-picker');
  const filter = root.getElementById('route-filter');
  const status = root.getElementById('route-status');
  const result = root.getElementById('link-result');
  const output = root.getElementById('link-output');
  const copy = root.getElementById('link-copy');
  const share = root.getElementById('link-share');
  const open = root.getElementById('link-open');
  // Route pages only: a link to the link maker, which also makes QR codes.
  const qrPage = root.getElementById('link-qr-page');
  const clear = root.getElementById('route-clear');
  const retry = root.getElementById('route-retry');
  const selected = new Set();
  let routes = [];

  function update() {
    // Catalog order, so the same choices always give the same link.
    const chosen = routes.filter((id) => selected.has(id));
    const full = chosen.length >= MAX_ROUTES;
    for (const box of picker.querySelectorAll('input')) {
      box.disabled = full && !box.checked;
    }
    result.hidden = chosen.length === 0;
    clear.disabled = chosen.length === 0;
    if (chosen.length === 0) {
      status.textContent = 'No routes chosen yet.';
      onLink('', []);
      return;
    }
    const link = buildLink(LINK_BASE, chosen);
    output.value = link;
    open.href = buildLink(APP_LINK_BASE, chosen);
    if (qrPage) qrPage.href = buildLink(SHARE_PAGE, chosen);
    const count = chosen.length === 1 ? '1 route' : `${chosen.length} routes`;
    status.textContent = full
      ? `${count} chosen: ${chosen.join(', ')}. That is the most one link can hold.`
      : `${count} chosen: ${chosen.join(', ')}.`;
    onLink(link, chosen);
  }

  function render() {
    picker.replaceChildren(
      ...routes.map((id) => {
        const box = el('input', { type: 'checkbox', value: id, checked: selected.has(id) });
        box.addEventListener('change', () => {
          if (box.checked) selected.add(id);
          else selected.delete(id);
          update();
        });
        return el('label', { className: 'route-option' }, box, el('span', {}, id));
      }),
    );
    applyFilter();
    update();
  }

  function applyFilter() {
    const needle = filter.value.trim().toLowerCase();
    for (const label of picker.children) {
      const id = label.querySelector('input').value.toLowerCase();
      label.hidden = needle !== '' && !id.includes(needle);
    }
  }

  async function load() {
    retry.hidden = true;
    picker.setAttribute('aria-busy', 'true');
    status.textContent = 'Loading the route list…';
    try {
      routes = await fetchRoutes();
      // Start from a link's routes when the page is opened with ?routes=.
      for (const id of [...preselect, ...parseRoutes(location.search).routes]) {
        if (routes.includes(id)) selected.add(id);
      }
      render();
      // Bring the first chosen route into view inside the scrolling list.
      const first = picker.querySelector('input:checked');
      if (first) {
        const top = first.parentElement.offsetTop - picker.offsetTop;
        picker.scrollTop = top - picker.clientHeight / 3;
      }
    } catch (error) {
      console.error(error);
      status.textContent = "Couldn't load the route list. Check your connection, then try again.";
      retry.hidden = false;
    } finally {
      picker.removeAttribute('aria-busy');
    }
  }

  root.getElementById('route-form').addEventListener('submit', (event) => event.preventDefault());
  filter.addEventListener('input', applyFilter);
  retry.addEventListener('click', load);
  clear.addEventListener('click', () => {
    selected.clear();
    render();
    status.textContent = 'All routes cleared.';
  });
  copy.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(output.value);
      status.textContent = 'Link copied.';
    } catch {
      // Clipboard access can be refused; leave the link selected to copy by hand.
      output.focus();
      output.select();
      status.textContent = 'Select the link and copy it.';
    }
  });
  if (navigator.share) {
    share.hidden = false;
    share.addEventListener('click', async () => {
      try {
        await navigator.share({ title: 'BusNeighbor routes', url: output.value });
      } catch (error) {
        if (error.name !== 'AbortError') console.error(error);
      }
    });
  }

  await load();
}

export async function initGoPage(root = document, { loadRoutes = fetchRoutes } = {}) {
  let offered = null;
  try {
    offered = await loadRoutes();
  } catch (error) {
    console.error(error);
  }
  const { summary, hint, href } = goPageContent(location.search, offered);
  // textContent only: the ids come from the URL.
  root.getElementById('go-summary').textContent = summary;
  const hintNode = root.getElementById('go-hint');
  hintNode.textContent = hint ?? '';
  hintNode.hidden = hint === null;
  const open = root.getElementById('go-open');
  open.hidden = href === null;
  if (href !== null) open.href = href;
}
