// Unit tests for routelink.js. Node's built-in runner, no packages:
//   node --test tests/js/

import assert from 'node:assert/strict';
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

test('parseRoutes keeps well-formed ids in order, once each', () => {
  assert.deepEqual(parseRoutes('?routes=47,9,47,bad id,21'), ['47', '9', '21']);
});

test('parseTrack is null without a track parameter', () => {
  assert.equal(parseTrack('?routes=47'), null);
});

test('parseTrack reads route:vehicle pairs in order', () => {
  assert.deepEqual(parseTrack('?track=47:3112,21:1234'), [
    { route: '47', vehicle: '3112' },
    { route: '21', vehicle: '1234' },
  ]);
});

test('parseTrack drops malformed pairs and repeated vehicles', () => {
  assert.deepEqual(parseTrack('?track=47,47:3112:9,:1,47:bad id,21:3112,47:3112, 9:77 '), [
    { route: '21', vehicle: '3112' },
    { route: '9', vehicle: '77' },
  ]);
});

test('parseTrack keeps at most MAX_TRACKED buses', () => {
  const pairs = parseTrack('?track=1:1,2:2,3:3,4:4');
  assert.equal(pairs.length, MAX_TRACKED);
  assert.deepEqual(pairs.map((bus) => bus.vehicle), ['1', '2', '3']);
});

test('parseTrack is empty when track names no valid pair', () => {
  assert.deepEqual(parseTrack('?track='), []);
  assert.deepEqual(parseTrack('?track=nonsense'), []);
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
  const content = goPageContent(SHARED);
  assert.equal(content.href, 'busneighbor://go?routes=45&track=45:3557');
  assert.equal(content.summary, 'This link tracks bus 3557 on route 45 in BusNeighbor.');
  assert.match(content.hint, /adds the bus/);
});

test('the app link round-trips through the parsers', () => {
  const { href } = goPageContent('?routes=45,21&track=45:3557,21:1234');
  const search = href.slice(href.indexOf('?'));
  assert.deepEqual(parseRoutes(search), ['45', '21']);
  assert.deepEqual(parseTrack(search), parseTrack('?track=45:3557,21:1234'));
});

test('a tracking link names every bus', () => {
  const { summary } = goPageContent('?routes=45,21,9&track=45:1,21:2,9:3');
  assert.equal(
    summary,
    'This link tracks bus 1 on route 45, bus 2 on route 21, and bus 3 on route 9 in BusNeighbor.',
  );
  assert.match(goPageContent('?track=45:1,21:2').hint, /adds the buses/);
});

test('a tracking link without routes repeats the buses’ routes', () => {
  const { href } = goPageContent('?track=45:3557,21:1234,45:9');
  assert.equal(href, 'busneighbor://go?routes=45,21&track=45:3557,21:1234,45:9');
});

test('a broken track hides the button instead of falling back to routes', () => {
  const content = goPageContent('?routes=45&track=nonsense');
  assert.equal(content.href, null);
  assert.equal(content.hint, null);
  assert.match(content.summary, /doesn't name a bus/);
});

test('a route link is unchanged', () => {
  assert.deepEqual(goPageContent('?routes=47,21'), {
    summary: 'This link shows these routes in BusNeighbor: 47, 21.',
    hint: 'BusNeighbor asks before it replaces the routes you already have.',
    href: 'busneighbor://go?routes=47,21',
  });
  assert.equal(goPageContent('?routes=47').summary, 'This link shows route 47 in BusNeighbor.');
});

test('a link with no routes and no track hides the button', () => {
  assert.deepEqual(goPageContent(''), {
    summary: "This link doesn't name any routes.",
    hint: null,
    href: null,
  });
});
