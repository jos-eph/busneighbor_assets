// Unit tests for routeqr.js. Node's built-in runner, no packages:
//   node --test tests/js/

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import {
  displayLink,
  qrFileName,
  qrLabel,
  qrModules,
  qrPathData,
  qrRuns,
  qrSide,
  routeList,
  signTitle,
} from '../../routeqr.js';

const ONE_ROUTE = 'https://bus.dydx.org/go?routes=47';
const TWENTY_ROUTES = `https://bus.dydx.org/go?routes=${[
  'T1', '17', '23', '33', '47', '52', '56', '66', '108', '124', '125', 'LUCYGO', 'LUCYGR',
  'BLVDDIR', 'FOX_BUS', 'NOR_BUS', 'WTR_BUS', 'D1_BUS', 'D2_BUS', 'M1_BUS',
].join(',')}`;
// The parser's limit: 20 ids of 16 characters.
const LONGEST = `https://bus.dydx.org/go?routes=${Array(20).fill('A'.repeat(16)).join(',')}`;

function fixture(name) {
  const text = readFileSync(new URL(`fixtures/${name}`, import.meta.url), 'utf8');
  return text.trimEnd().split('\n').map((line) => [...line].map((c) => c === '#'));
}

test('one route fits a version 4 code (33 modules)', () => {
  assert.equal(qrModules(ONE_ROUTE).length, 33);
});

test('twenty real routes fit a version 10 code (57 modules)', () => {
  assert.equal(qrModules(TWENTY_ROUTES).length, 57);
});

test('the longest link the parser allows still encodes', () => {
  assert.equal(qrModules(LONGEST).length, 89);
});

test('the grid is square', () => {
  const modules = qrModules(TWENTY_ROUTES);
  for (const row of modules) assert.equal(row.length, modules.length);
});

test('matches the decoded golden fixture', () => {
  // Catches an encoder change that alters the output.
  assert.deepEqual(qrModules(ONE_ROUTE), fixture('go_routes_47.txt'));
});

test('finder patterns sit in three corners, not the fourth', () => {
  const modules = qrModules(ONE_ROUTE);
  const n = modules.length;
  const finder = (top, left) =>
    [0, 1, 2, 3, 4, 5, 6].every((i) =>
      modules[top][left + i] && modules[top + 6][left + i] && modules[top + i][left] && modules[top + i][left + 6]);
  assert.ok(finder(0, 0), 'top left');
  assert.ok(finder(0, n - 7), 'top right');
  assert.ok(finder(n - 7, 0), 'bottom left');
  assert.ok(!finder(n - 7, n - 7), 'bottom right');
});

test('empty text is refused', () => {
  assert.throws(() => qrModules(''), TypeError);
});

test('runs are offset by the quiet zone and cover every dark module', () => {
  const modules = [
    [true, true, false],
    [false, false, false],
    [true, false, true],
  ];
  assert.deepEqual(qrRuns(modules), [[4, 4, 2], [4, 6, 1], [6, 6, 1]]);
  assert.equal(qrSide(modules), 11);
  const dark = qrModules(ONE_ROUTE).flat().filter(Boolean).length;
  const covered = qrRuns(qrModules(ONE_ROUTE)).reduce((sum, [, , length]) => sum + length, 0);
  assert.equal(covered, dark);
});

test('path data draws one rectangle per run', () => {
  assert.equal(qrPathData([[true, true], [false, true]]), 'M4 4h2v1h-2zM5 5h1v1h-1z');
});

test('route lists use a serial comma', () => {
  assert.equal(routeList(['47']), '47');
  assert.equal(routeList(['17', '23']), '17 and 23');
  assert.equal(routeList(['17', '23', '47']), '17, 23, and 47');
});

test('labels and sign titles name the routes', () => {
  assert.equal(qrLabel(['47']), 'QR code for the link to route 47');
  assert.equal(qrLabel(['17', '23', '47']), 'QR code for the link to routes 17, 23, and 47');
  assert.equal(signTitle(['47']), 'Live buses on Route 47');
  assert.equal(signTitle(['17', '23']), 'Live buses on routes 17 and 23');
});

test('the link shown on the sign drops the scheme only', () => {
  assert.equal(displayLink(ONE_ROUTE), 'bus.dydx.org/go?routes=47');
});

test('file names stay short', () => {
  assert.equal(qrFileName(['47']), 'busneighbor-route-47.png');
  assert.equal(qrFileName(['17', '23', '47']), 'busneighbor-routes-17-23-47.png');
  const twenty = Array.from({ length: 20 }, (_, i) => String(i + 1));
  assert.equal(qrFileName(twenty), 'busneighbor-routes-1-2-3-and-17-more.png');
});
