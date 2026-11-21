// Unit tests for routelink.js. Node's built-in runner, no packages:
//   node --test tests/js/

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import {
  APP_LINK_BASE,
  MAX_TRACKED,
  buildLink,
  goPageContent,
  parseRoutes,
  parseTrack,
} from '../../routelink.js';

// What the app's "Share link to this bus" builds (track_link.dart).
const SHARED = '?routes=45&track=45:3557';
const OFFERED = ['4', '9', '21', '45', '47', 'ABCDEFGHIJKLMNOP'];

test('parseRoutes keeps well-formed ids in order, once each', () => {
  assert.deepEqual(parseRoutes('?routes=47,9,47,21,'), {
    routes: ['47', '9', '21'],
    malformed: false,
  });
});

test('parseRoutes rejects malformed ids as a whole', () => {
  assert.deepEqual(parseRoutes('?routes=47,bad id,21'), {
    routes: [],
    malformed: true,
  });
});

test('parseTrack is null without a track parameter', () => {
  assert.equal(parseTrack('?routes=47'), null);
});

test('parseTrack reads route:vehicle pairs in order', () => {
  assert.deepEqual(parseTrack('?track=47:3112,21:1234'), {
    pairs: [
      { route: '47', vehicle: '3112' },
      { route: '21', vehicle: '1234' },
    ],
    malformed: false,
  });
});

test('parseTrack rejects any malformed pair and dedupes vehicles', () => {
  assert.deepEqual(parseTrack('?track=21:3112,47:3112, 9:77 '), {
    pairs: [
      { route: '21', vehicle: '3112' },
      { route: '9', vehicle: '77' },
    ],
    malformed: false,
  });
  assert.equal(parseTrack('?track=47,21:3112').malformed, true);
  assert.equal(parseTrack('?track=47:3112:9,21:3112').malformed, true);
  assert.equal(parseTrack('?track=:1,21:3112').malformed, true);
  assert.equal(parseTrack('?track=47:bad id,21:3112').malformed, true);
});

test('parseTrack keeps at most MAX_TRACKED buses', () => {
  const { pairs, malformed } = parseTrack('?track=1:1,2:2,3:3,4:4');
  assert.equal(malformed, false);
  assert.equal(pairs.length, MAX_TRACKED);
  assert.deepEqual(pairs.map((bus) => bus.vehicle), ['1', '2', '3']);
});

test('parseTrack is empty for empty track, malformed for invalid track', () => {
  assert.deepEqual(parseTrack('?track='), { pairs: [], malformed: false });
  assert.deepEqual(parseTrack('?track=nonsense'), { pairs: [], malformed: true });
});

test('buildLink without track is a plain route link', () => {
  assert.equal(buildLink(APP_LINK_BASE, ['47', '21']), 'busneighbor://go?routes=47,21');
});

test('buildLink writes track pairs the way the app does', () => {
  assert.equal(
    buildLink(APP_LINK_BASE, ['45'], [{ route: '45', vehicle: '3557' }]),
    'busneighbor://go?routes=45&track=45:3557',
  );
});

test('a shared bus link keeps its bus in the app link', () => {
  const content = goPageContent(SHARED, OFFERED);
  assert.equal(content.href, 'busneighbor://go?routes=45&track=45:3557');
  assert.equal(content.summary, 'This link tracks bus 3557 on route 45 in BusNeighbor.');
  assert.equal(
    content.hint,
    'BusNeighbor adds the bus to your map. Your routes stay as they are.',
  );
});

test('the app link round-trips through the parsers', () => {
  const { href } = goPageContent('?routes=45,21&track=45:3557,21:1234', OFFERED);
  const search = href.slice(href.indexOf('?'));
  assert.deepEqual(parseRoutes(search), { routes: ['45', '21'], malformed: false });
  assert.deepEqual(parseTrack(search), parseTrack('?track=45:3557,21:1234'));
});

test('a tracking link names every bus', () => {
  const { summary } = goPageContent('?routes=45,21,9&track=45:1,21:2,9:3', OFFERED);
  assert.equal(
    summary,
    'This link tracks bus 1 on route 45, bus 2 on route 21, and bus 3 on route 9 in BusNeighbor.',
  );
  assert.equal(
    goPageContent('?track=45:1,21:2', OFFERED).hint,
    'BusNeighbor adds the buses to your map. Your routes stay as they are.',
  );
});

test('a whole-map link names its other routes and its bus', () => {
  const content = goPageContent('?routes=4,9,21,47&track=47:3112', OFFERED);
  assert.equal(
    content.summary,
    'This link shows routes 4, 9, and 21 in BusNeighbor and tracks bus 3112 on route 47.',
  );
  assert.equal(
    content.hint,
    'BusNeighbor adds these routes and the bus to your map. Your other routes stay as they are.',
  );
  assert.equal(content.href, 'busneighbor://go?routes=4,9,21,47&track=47:3112');
});

test('a whole-map link with one other route says it once', () => {
  const content = goPageContent('?routes=4,47&track=47:3112', OFFERED);
  assert.equal(
    content.summary,
    'This link shows route 4 in BusNeighbor and tracks bus 3112 on route 47.',
  );
  assert.equal(
    content.hint,
    'BusNeighbor adds this route and the bus to your map. Your other routes stay as they are.',
  );
});

test('a whole-map link with two buses names both', () => {
  const content = goPageContent('?routes=4,21,47&track=47:3112,21:8001', OFFERED);
  assert.equal(
    content.summary,
    'This link shows route 4 in BusNeighbor and tracks bus 3112 on route 47 and bus 8001 on route 21.',
  );
  assert.equal(
    content.hint,
    'BusNeighbor adds this route and the buses to your map. Your other routes stay as they are.',
  );
  assert.equal(content.href, 'busneighbor://go?routes=4,21,47&track=47:3112,21:8001');
});

test('a whole-map link with three other routes and two buses', () => {
  const { summary, hint } = goPageContent('?routes=4,9,21,47,45&track=47:1,45:2', OFFERED);
  assert.equal(
    summary,
    'This link shows routes 4, 9, and 21 in BusNeighbor and tracks bus 1 on route 47 and bus 2 on route 45.',
  );
  assert.equal(
    hint,
    'BusNeighbor adds these routes and the buses to your map. Your other routes stay as they are.',
  );
});

test('a tracking link without routes repeats the buses’ routes', () => {
  const { href } = goPageContent('?track=45:3557,21:1234,45:9', OFFERED);
  assert.equal(href, 'busneighbor://go?routes=45,21&track=45:3557,21:1234,45:9');
});

test('a broken track hides the button and reports invalid link', () => {
  const content = goPageContent('?routes=45&track=nonsense', OFFERED);
  assert.equal(content.href, null);
  assert.equal(content.hint, null);
  assert.equal(content.summary, "This link isn't valid.");
});

test('a route link is unchanged when all routes are offered', () => {
  assert.deepEqual(goPageContent('?routes=47,21', OFFERED), {
    summary: 'This link shows these routes in BusNeighbor: 47, 21.',
    hint: 'BusNeighbor asks before it replaces the routes you already have.',
    href: 'busneighbor://go?routes=47,21',
  });
  assert.equal(goPageContent('?routes=47', OFFERED).summary, 'This link shows route 47 in BusNeighbor.');
});

test('unoffered routes are dropped from text and href', () => {
  const content = goPageContent('?routes=CallUs-5551234,47', OFFERED);
  assert.equal(content.summary, 'This link shows route 47 in BusNeighbor.');
  assert.equal(content.href, 'busneighbor://go?routes=47');
  assert.ok(!content.summary.includes('CallUs'));
});

test('a bus on an unoffered route hides the button and never quotes the route', () => {
  const content = goPageContent('?routes=CallUs-5551234&track=CallUs-5551234:3112', OFFERED);
  assert.equal(content.href, null);
  assert.equal(content.hint, null);
  assert.equal(content.summary, "This link's bus is on a route BusNeighbor doesn't have.");
  assert.ok(!content.summary.includes('CallUs'));
});

test('when the catalog is unavailable, generic text with no ids is shown and button stays', () => {
  const routeOnly = goPageContent('?routes=CallUs-5551234', null);
  assert.equal(routeOnly.summary, 'This link opens routes in BusNeighbor.');
  assert.equal(routeOnly.href, 'busneighbor://go?routes=CallUs-5551234');
  assert.ok(!routeOnly.summary.includes('CallUs'));

  const tracked = goPageContent('?routes=47&track=47:3112', null);
  assert.equal(tracked.summary, 'This link opens routes in BusNeighbor.');
  assert.equal(tracked.href, 'busneighbor://go?routes=47&track=47:3112');
  assert.ok(!tracked.summary.includes('47'));
  assert.ok(!tracked.summary.includes('3112'));
});

test('a link with no routes and no track hides the button', () => {
  assert.deepEqual(goPageContent('', OFFERED), {
    summary: "This link doesn't name any routes.",
    hint: null,
    href: null,
  });
});

// Keep in step with busneighbor_oss test/features/route_link/fixtures/links.json
test('shared links fixture: every row matches valid/invalid and invalid rows have no href', () => {
  const rows = JSON.parse(
    readFileSync(new URL('./fixtures/links.json', import.meta.url), 'utf8'),
  );
  for (const row of rows) {
    const routeResult = parseRoutes(row.query);
    const trackResult = parseTrack(row.query);
    const isMalformed = routeResult.malformed || Boolean(trackResult?.malformed);
    assert.equal(isMalformed, row.malformed, row.name);
    const content = goPageContent(row.query, OFFERED);
    if (row.malformed) {
      assert.equal(content.href, null, `${row.name}: href must be null`);
      assert.equal(content.hint, null, `${row.name}: hint must be null`);
      assert.equal(content.summary, "This link isn't valid.", row.name);
    } else {
      assert.deepEqual(routeResult.routes, row.routes, `${row.name}: routes`);
      assert.deepEqual(trackResult ? trackResult.pairs : [], row.track, `${row.name}: track`);
      if (content.href !== null) {
        const params = new URLSearchParams(content.href.slice(content.href.indexOf('?')));
        for (const key of params.keys()) {
          assert.ok(key === 'routes' || key === 'track', `${row.name}: unexpected param ${key}`);
        }
      }
    }
  }
});

test('href never carries extra query parameters like next=', () => {
  const { href } = goPageContent('?routes=47&next=https://example.com&evil=1', OFFERED);
  assert.equal(href, 'busneighbor://go?routes=47');
});

test('go.html hides #go-open in static HTML until script checks the link', () => {
  const html = readFileSync(new URL('../../go.html', import.meta.url), 'utf8');
  assert.match(html, /<a\s[^>]*id="go-open"[^>]*\bhidden\b[^>]*>/);
});
