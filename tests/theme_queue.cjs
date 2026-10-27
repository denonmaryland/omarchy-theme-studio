// Exercise the actual QML switching functions and exit handler without a desktop.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const qml = fs.readFileSync(path.join(__dirname, '../ThemeStudio.qml'), 'utf8');
const start = qml.indexOf('onExited: function(code)', qml.indexOf('id: themeProc'));
const end = qml.indexOf('\n    }', start);
const onExitBody = qml.slice(qml.indexOf('{', start) + 1, end);
const pumpStart = qml.indexOf('  function pumpTheme() {');
const pumpEnd = qml.indexOf('\n  }', pumpStart) + '\n  }'.length;
const pumpSource = qml.slice(pumpStart, pumpEnd);

function fixture() {
  const callbacks = [];
  const root = { wantTheme: 'A', activeTheme: 'A', themeSeq: 1, activeSeq: 1,
    optimistic: 'A', themeError: false,
    message: '', values: { current: 'old' }, helper: '/unused/control.py',
    themeProc: { running: false }, refresh() {} };
  const Qt = { callLater(fn) { callbacks.push(fn); } };
  const context = vm.createContext(root);
  root.pumpTheme = vm.runInContext(`(${pumpSource})`, context);
  return { root, exit(code) {
    new Function('root', 'Qt', 'code', onExitBody)(root, Qt, code);
    callbacks.splice(0).forEach(fn => fn());
  } };
}

test('a failed A still starts the newer selection B', () => {
  const { root, exit } = fixture();
  root.themeSeq++;
  root.wantTheme = root.optimistic = 'B';
  exit(1);
  assert.equal(root.activeTheme, 'B');
  assert.equal(root.optimistic, 'B');
  assert.equal(root.themeProc.running, true);
  assert.equal(root.themeProc.command.at(-1), 'B');
});

test('a failed A with no newer selection stops retrying', () => {
  const { root, exit } = fixture();
  exit(1);
  assert.equal(root.wantTheme, '');
  assert.equal(root.optimistic, '');
  assert.equal(root.activeTheme, '');
  assert.equal(root.themeProc.running, false);
  assert.equal(root.themeError, true);
});

test('a newer random selection survives a failed A', () => {
  const { root, exit } = fixture();
  root.themeSeq++;
  root.wantTheme = '*random*';
  root.optimistic = '';
  exit(1);
  assert.equal(root.activeTheme, '*random*');
  assert.equal(root.wantTheme, '');
  assert.equal(root.themeProc.command.at(-1), 'random');
  assert.equal(root.themeProc.running, true);
});

test('a successful A still starts the newer selection B', () => {
  const { root, exit } = fixture();
  root.values.current = 'A';
  root.themeSeq++;
  root.wantTheme = root.optimistic = 'B';
  exit(0);
  assert.equal(root.activeTheme, 'B');
  assert.equal(root.themeProc.command.at(-1), 'B');
  assert.equal(root.themeProc.running, true);
});

test('a second random pick survives a failed first random pick', () => {
  const { root, exit } = fixture();
  root.activeTheme = '*random*';
  root.optimistic = '';
  root.themeSeq++;
  root.wantTheme = '*random*';
  exit(1);
  assert.equal(root.activeTheme, '*random*');
  assert.equal(root.activeSeq, root.themeSeq);
  assert.equal(root.themeProc.command.at(-1), 'random');
  assert.equal(root.themeProc.running, true);
});
