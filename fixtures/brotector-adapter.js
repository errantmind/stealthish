// Observe the unchanged upstream page. Crash mode is disabled by its public URL option.
const output = document.querySelector('#lab-result');
const state = {status:'RUNNING', errors:[], events:{}, untrustedEvents:0, crashTests:'NOT_RUN'};
addEventListener('error', e => state.errors.push(String(e.message)));
addEventListener('unhandledrejection', e => state.errors.push(String(e.reason)));
for (const type of ['mousemove','pointermove','click','wheel']) {
  addEventListener(type, event => {
    state.events[type] = (state.events[type] || 0) + 1;
    if (!event.isTrusted) state.untrustedEvents++;
  }, {passive:true});
}
addEventListener('load', async () => {
  try {
    const detector = window.brotector;
    if (!detector || detector.crash !== false) throw Error('Brotector crash mode must be off');
    await detector.init_done;
    state.initComplete = true;
    // The original init does not await this asynchronous test. Await a second
    // invocation, without replacing its method, to verify completion.
    await detector.test_HighEntropyValues();
    state.highEntropyCompleted = true;
    state.highEntropyValues = await get_worker_response(getHighEntropyValues, 3000);
    state.status = 'READY';
    function publish() {
      state.raw = detector.detections;
      state.buttonText = document.querySelector('#clickHere').textContent;
      state.elapsedMs = performance.now();
      output.textContent = JSON.stringify(state);
    }
    publish(); setInterval(publish, 250);
  } catch (error) {
    state.status = 'ERROR'; state.error = String(error.stack || error);
    output.textContent = JSON.stringify(state);
  }
});
