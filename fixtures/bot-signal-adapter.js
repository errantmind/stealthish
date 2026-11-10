import {VERSION, detectInstantClient, detectInstantClientAsync, createBehavioralClientDetector} from './bundle.js';
const output = document.querySelector('#lab-result');
const state = {status:'RUNNING', version:VERSION, errors:[], events:{}, untrustedEvents:0,
  options:{static:'upstream defaults',behavioral:'upstream defaults'}, samples:[]};
addEventListener('error', e => state.errors.push(String(e.message)));
addEventListener('unhandledrejection', e => state.errors.push(String(e.reason)));
const detector = createBehavioralClientDetector();
for (const type of ['mousemove','wheel','keydown','click','touchstart','touchmove']) {
  addEventListener(type, event => {
    state.events[type] = (state.events[type] || 0) + 1;
    if (!event.isTrusted) state.untrustedEvents++;
  }, {passive:true});
}
document.querySelector('#action').addEventListener('click', () => {
  const count = document.querySelector('#action-count'); count.textContent = Number(count.textContent) + 1;
});
try {
  state.sync = detectInstantClient(window);
  state.async = await detectInstantClientAsync(window);
  detector.start(); state.startedAt = performance.now(); state.status = 'READY';
  function publish() {
    state.behavior = detector.getResult();
    state.fieldValue = document.querySelector('#field').value;
    state.actionCount = Number(document.querySelector('#action-count').textContent);
    state.elapsedMs = performance.now() - state.startedAt;
    output.textContent = JSON.stringify(state);
  }
  publish();
  setInterval(publish, 250);
} catch (error) {
  state.status = 'ERROR'; state.error = String(error.stack || error);
  output.textContent = JSON.stringify(state);
}
