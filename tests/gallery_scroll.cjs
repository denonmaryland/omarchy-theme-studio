// Exercise the shared QML handler with pixel and angle input, without a desktop.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const qml = fs.readFileSync(path.join(__dirname, '../ThemeStudio.qml'), 'utf8');
const start = qml.indexOf('    function scroll(event, useAngles) {');
assert.notEqual(start, -1);
const end = qml.indexOf('\n    }', start);
const body = qml.slice(qml.indexOf('{', start) + 1, end);
const pixelScale = Number(qml.match(/readonly property real pixelScale: ([\d.]+)/)[1]);
const handlerStart = qml.indexOf('    onWheel: function(event) {', qml.indexOf('component GalleryScroll:'));
const handlerEnd = qml.indexOf('\n    }', handlerStart);
const handlerBody = qml.slice(qml.indexOf('{', handlerStart) + 1, handlerEnd);

function fixture(overrides = {}) {
  const view = { originY: 0, topMargin: 4, bottomMargin: 0, contentHeight: 2000,
    height: 400, cellHeight: 150, contentY: 300, cancelled: 0,
    cancelFlick() { this.cancelled++; }, ...overrides };
  return { view, scroll(pixelY, angleY = 0, useAngles = false) {
    const event = { pixelDelta: { y: pixelY }, angleDelta: { y: angleY }, accepted: false };
    new Function('view', 'pixelScale', 'event', 'useAngles', body)(view, pixelScale, event, useAngles);
    return event;
  } };
}

test('small trackpad deltas stay proportional and take precedence over angles', () => {
  const { view, scroll } = fixture();
  assert.equal(scroll(-0.5, -120).accepted, true);
  assert.equal(view.contentY, 301.5);
  scroll(0.5, 120);
  assert.equal(view.contentY, 300);
  assert.equal(view.cancelled, 2);
});

test('angle-only input moves one row per notch and preserves fractional notches', () => {
  const { view, scroll } = fixture();
  scroll(0, -120);
  assert.equal(view.contentY, 450);
  scroll(0, 30);
  assert.equal(view.contentY, 412.5);
});

test('Wayland wheel events without a gesture phase keep the row step', () => {
  const { view, scroll } = fixture();
  scroll(-15, -120, true);
  assert.equal(view.contentY, 450);
});

test('the QML event handler distinguishes gestures from phase-free and physical wheels', () => {
  const handle = new Function('point', 'Qt', 'PointerDevice', 'scroll', 'event', handlerBody);
  for (const [device, phase, expected] of [[4, 2, 321], [4, 0, 450], [1, 2, 450]]) {
    const { view, scroll } = fixture();
    const event = { pixelDelta: { y: -7 }, angleDelta: { y: -120 }, phase };
    handle({ device: { type: device } }, { NoScrollPhase: 0 }, { Mouse: 1 },
      (event, useAngles) => scroll(event.pixelDelta.y, event.angleDelta.y, useAngles), event);
    assert.equal(view.contentY, expected);
  }
});

test('scroll limits include margins and a shifted view origin', () => {
  const { view, scroll } = fixture({ originY: 120, bottomMargin: 10 });
  scroll(10000);
  assert.equal(view.contentY, 116);
  scroll(-10000);
  assert.equal(view.contentY, 1730);
});

test('a short or empty gallery stays at its top boundary', () => {
  for (const contentHeight of [0, 100]) {
    const { view, scroll } = fixture({ contentHeight, contentY: -4 });
    scroll(-30);
    assert.equal(view.contentY, -4);
  }
});

test('horizontal-only and gesture-end events leave vertical scrolling alone', () => {
  const { view, scroll } = fixture();
  assert.equal(scroll(0, 0).accepted, false);
  assert.equal(view.contentY, 300);
  assert.equal(view.cancelled, 0);
});
