// Route links: shared by share.html (builds a link) and go.html (opens one).
// No dependencies, no storage, no network beyond the same-origin route list.

// Same-origin copy of the route catalog, written into the site by the Pages
// build. The release asset itself cannot be fetched from a browser: it sends
// no Access-Control-Allow-Origin header.
// Root-relative, so the route pages under /route/ find it too.
export const ROUTE_LIST_URL = '/septameta.json';

export const LINK_BASE = 'https://bus.dydx.org/go';
export const APP_LINK_BASE = 'busneighbor://go';

// Keep in step with the app's parser (route_link_parser.dart).
export const MAX_ROUTES = 20;
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

export function buildLink(base, routes) {
  // Route ids are limited to URL-safe characters, so commas stay readable.
  return `${base}?routes=${routes.join(',')}`;
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

/** `preselect`: routes chosen when the page opens, as on a route's own page. */
export async function initSharePage(root = document, { preselect = [] } = {}) {
  const picker = root.getElementById('route-picker');
  const filter = root.getElementById('route-filter');
  const status = root.getElementById('route-status');
  const result = root.getElementById('link-result');
  const output = root.getElementById('link-output');
  const copy = root.getElementById('link-copy');
  const share = root.getElementById('link-share');
  const open = root.getElementById('link-open');
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
      return;
    }
    output.value = buildLink(LINK_BASE, chosen);
    open.href = buildLink(APP_LINK_BASE, chosen);
    const count = chosen.length === 1 ? '1 route' : `${chosen.length} routes`;
    status.textContent = full
      ? `${count} chosen: ${chosen.join(', ')}. That is the most one link can hold.`
      : `${count} chosen: ${chosen.join(', ')}.`;
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
  const routes = parseRoutes(location.search);
  const summary = root.getElementById('go-summary');
  const open = root.getElementById('go-open');
  if (routes.length === 0) {
    summary.textContent = "This link doesn't name any routes.";
    open.hidden = true;
    return;
  }
  // textContent only: the ids come from the URL.
  summary.textContent =
    routes.length === 1
      ? `This link shows route ${routes[0]} in BusNeighbor.`
      : `This link shows these routes in BusNeighbor: ${routes.join(', ')}.`;
  open.href = buildLink(APP_LINK_BASE, routes);
}
