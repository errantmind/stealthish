import FingerprintScanner from './bundle.js';
const output = document.querySelector('#lab-result');
const state = {status: 'RUNNING', errors: [], options: {encrypt: false, skipWorker: false}};
addEventListener('error', e => state.errors.push(String(e.message)));
addEventListener('unhandledrejection', e => state.errors.push(String(e.reason)));
try {
  const scanner = new FingerprintScanner();
  state.ruleNames = scanner.getDetectionRules().map(rule => rule.name);
  state.raw = await scanner.collectFingerprint(state.options);
  state.status = 'DONE';
} catch (error) {
  state.status = 'ERROR'; state.error = String(error.stack || error);
}
output.textContent = JSON.stringify(state);
