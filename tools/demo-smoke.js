#!/usr/bin/env node
/* Headless smoke test — The Refuser hosted demo (docs/index.html).
   Raw CDP, same proven pattern as jam-bezi13/smoke-test.js.
   Verifies the page ACTUALLY WORKS in a real browser: boot, live eval,
   presets, verdict flips, chain verify + tamper detection, disclosure.
   Exit 0 = all pass AND zero console errors. */
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');
const WebSocket = require('/workspace/forge/jam-bezi13/node_modules/ws');

const DIR = __dirname + '/..';
const results = [], consoleErrors = [];
let msgId = 1;
const pending = new Map();
function check(name, cond, detail) { results.push({ name, pass: !!cond, detail: detail || '' }); }
const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  const server = http.createServer((req, res) => {
    const u = req.url.split('?')[0];
    const rel = u === '/' ? 'index.html' : u.replace(/^\//, '');
    const fp = path.join(DIR, 'docs', path.normalize(rel));
    fs.readFile(fp, (e, b) => {
      if (e) { res.writeHead(404); res.end(); return; }
      res.writeHead(200, { 'Content-Type': rel.endsWith('.js') ? 'text/javascript' : 'text/html' });
      res.end(b);
    });
  });
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const PORT = server.address().port;

  const chrome = spawn('/usr/bin/chromium', [
    '--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
    '--remote-debugging-port=0', '--remote-allow-origins=*', 'about:blank'
  ], { stdio: ['pipe', 'pipe', 'pipe'] });
  // --remote-debugging-port=0 prints the real port on stderr
  let chromeErr = '', dbgPort = 0;
  chrome.stderr.on('data', d => {
    const s = String(d); chromeErr += s;
    const m = s.match(/DevTools listening on ws:\/\/127\.0\.0\.1:(\d+)/);
    if (m) dbgPort = +m[1];
  });
  for (let i = 0; i < 40 && !dbgPort; i++) await sleep(250);
  if (!dbgPort) { console.log('CHROME_FAIL', chromeErr.slice(0, 300)); chrome.kill('SIGKILL'); process.exit(1); }

  function hget(p, pth) {
    return new Promise((res, rej) => {
      const rq = http.get({ host: '127.0.0.1', port: p, path: pth, timeout: 2000 }, r0 => { let b = ''; r0.on('data', c => b += c); r0.on('end', () => res(b)); });
      rq.on('error', rej); rq.on('timeout', () => { rq.destroy(); rej(new Error('timeout')); });
    });
  }
  let target = null;
  const hput = (p, pth) => new Promise((res, rej) => {
    const rq = http.request({ host: '127.0.0.1', port: p, path: pth, method: 'PUT', timeout: 5000 }, r0 => { let b = ''; r0.on('data', c => b += c); r0.on('end', () => res(b)); });
    rq.on('error', rej); rq.end();
  });
  for (let i = 0; i < 15 && !target; i++) {
    try { target = JSON.parse(await hput(dbgPort, `/json/new?http://127.0.0.1:${PORT}/`)); }
    catch (e) { await sleep(300); }
  }
  if (!target) { console.log('TARGET_FAIL'); chrome.kill('SIGKILL'); process.exit(1); }

  const ws = new WebSocket(target.webSocketDebuggerUrl, { maxPayload: 64 * 1024 * 1024 });
  await new Promise((res, rej) => { ws.on('open', res); ws.on('error', rej); });
  ws.on('message', m => {
    const d = JSON.parse(m);
    if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
    if (d.method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(d.params.type))
      consoleErrors.push((d.params.args || []).map(a => a.value || a.description || '').join(' ').slice(0, 200));
    if (d.method === 'Runtime.exceptionThrown')
      consoleErrors.push('EXC: ' + (((d.params.exceptionDetails || {}).exception || {}).description || d.params.exceptionDetails.text || '').slice(0, 300));
  });
  const send = (method, params) => new Promise(res => {
    const id = msgId++; pending.set(id, res);
    ws.send(JSON.stringify({ id, method, params: params || {} }));
  });
  await send('Runtime.enable');
  await send('Page.enable');
  const ev = async (expr) => {
    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    return r.result ? r.result.result.value : undefined;
  };

  try {
    await sleep(1500); // boot + initial render

    const title = await ev('document.title');
    check('page boots (title)', title === 'The Refuser — live gate stack', title);

    let verdict = await ev('document.getElementById("verdict").textContent');
    check('baseline verdict ACCEPT', /^ACCEPT/.test(verdict), verdict);

    let n = await ev('document.querySelectorAll(".gate").length');
    check('all 9 gates rendered', n === 9, 'n=' + n);

    const details = await ev('Array.from(document.querySelectorAll(".gate .gdet")).map(e=>e.textContent).join(" || ")');
    check('gate details show real numbers', details.includes('dte=25') && details.includes('net delta'), details.slice(0, 90));

    await ev('document.querySelector("[data-p=deep]").click()');
    await sleep(200);
    verdict = await ev('document.getElementById("verdict").textContent');
    check('Δ0.45 preset -> REFUSE', /^REFUSE/.test(verdict), verdict);
    let failGate = await ev('Array.from(document.querySelectorAll(".gate.fail .gname")).map(e=>e.textContent).join(",")');
    check('short_delta gate named as refusing', /short_delta/.test(failGate), failGate);

    await ev('document.querySelector("[data-p=gme]").click()');
    await sleep(200);
    failGate = await ev('Array.from(document.querySelectorAll(".gate.fail .gname")).map(e=>e.textContent).join(",")');
    check('GME -> calendar refuses (not in universe)', /calendar/.test(failGate), failGate);

    await ev('document.querySelector("[data-p=group]").click()');
    await sleep(200);
    failGate = await ev('Array.from(document.querySelectorAll(".gate.fail .gname")).map(e=>e.textContent).join(",")');
    const gdet = await ev('Array.from(document.querySelectorAll(".gate.fail .gdet")).map(e=>e.textContent).join(" || ")');
    check('group cap -> portfolio refuses w/ correlation text', /portfolio/.test(failGate) && /index_beta holds 2\/2/.test(gdet), failGate + ' | ' + String(gdet).slice(0, 70));

    await ev('document.querySelector("[data-p=clean]").click()');
    await ev('var c=document.getElementById("f_credit"); c.value="0.80"; c.dispatchEvent(new Event("input"))');
    await sleep(200);
    verdict = await ev('document.getElementById("verdict").textContent');
    check('typed credit 0.80 -> REFUSE live', /^REFUSE/.test(verdict), verdict);

    await ev('document.getElementById("b_load").click()');
    await sleep(800);
    const chainOut = await ev('document.getElementById("chainout").textContent');
    check('sample chain verifies CHAIN OK', /CHAIN OK — 3 records/.test(chainOut), chainOut);

    await ev('document.getElementById("b_tamper").click()');
    await sleep(500);
    const tamOut = await ev('document.getElementById("chainout").textContent');
    check('tamper detected -> CHAIN BROKEN', /CHAIN BROKEN/.test(tamOut), tamOut);

    check('AI disclosure present', await ev('document.body.textContent.includes("built autonomously by an AI operator")') === true);
    check('parity battery referenced', await ev('document.body.textContent.includes("parity_test.py")') === true);

  } finally {
    try { ws.close(); } catch (e) {}
    chrome.kill('SIGKILL');
    server.close();
  }

  const pass = results.filter(r => r.pass).length;
  console.log(results.map(r => `  ${r.pass ? 'PASS' : 'FAIL'}  ${r.name}${r.pass ? '' : '  [' + r.detail + ']'}`).join('\n'));
  console.log(`${pass}/${results.length} PASS${consoleErrors.length ? ' — console errors: ' + consoleErrors.join(' | ') : ' — no console errors'}`);
  process.exit(pass === results.length && !consoleErrors.length ? 0 : 1);
})().catch(e => { console.error('SMOKE CRASH', e); process.exit(2); });
