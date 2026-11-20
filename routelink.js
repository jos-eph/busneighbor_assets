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
const ROUTE_ID = /^[A-Za-z0-9_-]{1,16}$/;

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

/** The well-formed route ids in a `?routes=4,9,21` query, in order, without repeats. */
export function parseRoutes(search) {
  const raw = new URLSearchParams(search).get('routes') ?? '';
  const ids = raw.split(',').map((id) => id.trim()).filter((id) => ROUTE_ID.test(id));
  return [...new Set(ids)].slice(0, MAX_ROUTES);
}

/**
 * The buses a `?track=47:3112,21:1234` query names, as `{route, vehicle}`
 * pairs in order, each vehicle once and at most MAX_TRACKED. Null when the
 * query has no `track`; empty when it names no valid pair.
 */
export function parseTrack(search) {
  const raw = new URLSearchParams(search).get('track');
  if (raw === null) return null;
  const byVehicle = new Map();
  for (const item of raw.split(',')) {
    const parts = item.trim().split(':');
    if (parts.length !== 2) continue;
    const [route, vehicle] = parts;
    if (ROUTE_ID.test(route) && ROUTE_ID.test(vehicle) && !byVehicle.has(vehicle)) {
      byVehicle.set(vehicle, { route, vehicle });
    }
  }
  return [...byVehicle.values()].slice(0, MAX_TRACKED);
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
 * button, and the app link (null hides the button). A link with `track`
 * keeps it in the app link, so the app tracks the buses instead of only
 * showing their routes.
 */
export function goPageContent(search) {
  const routes = parseRoutes(search);
  const track = parseTrack(search);
  if (track !== null) return trackingContent(routes, track);
  if (routes.length === 0) {
    return { summary: "This link doesn't name any routes.", hint: null, href: null };
  }
  return {
    summary:
      routes.length === 1
        ? `This link shows route ${routes[0]} in BusNeighbor.`
        : `This link shows these routes in BusNeighbor: ${routes.join(', ')}.`,
    hint: 'BusNeighbor asks before it replaces the routes you already have.',
    href: buildLink(APP_LINK_BASE, routes),
  };
}

function trackingContent(routes, track) {
  // Like the app, a broken `track` never falls back to the routes.
  if (track.length === 0) {
    return { summary: "This link doesn't name a bus BusNeighbor can show.", hint: null, href: null };
  }
  // The app's links repeat the buses' routes in `routes`, for builds that
  // don't track; keep that true for a hand-made link that leaves it out.
  const linkRoutes = routes.length > 0 ? routes : [...new Set(track.map((bus) => bus.route))];
  const buses = track.map(({ route, vehicle }) => `bus ${vehicle} on route ${route}`);
  return {
    summary: `This link tracks ${joinWithAnd(buses)} in BusNeighbor.`,
    hint: `BusNeighbor adds ${track.length === 1 ? 'the bus' : 'the buses'} to your map. Your routes stay as they are.`,
    href: buildLink(APP_LINK_BASE, linkRoutes, track),
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
      for (const id of [...preselect, ...parseRoutes(location.search)]) {
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

export function initGoPage(root = document) {
  const { summary, hint, href } = goPageContent(location.search);
  // textContent only: the ids come from the URL.
  root.getElementById('go-summary').textContent = summary;
  const hintNode = root.getElementById('go-hint');
  hintNode.textContent = hint ?? '';
  hintNode.hidden = hint === null;
  const open = root.getElementById('go-open');
  open.hidden = href === null;
  if (href !== null) open.href = href;
}
