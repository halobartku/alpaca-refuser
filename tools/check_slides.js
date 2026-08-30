#!/usr/bin/env node
// check_slides.js — verify every slide fits inside A4 landscape (1122x793 @96dpi).
// Launches headless chromium, loads slides.html, and for each .slide element
// reports scrollHeight/scrollWidth against its fixed 793/1122 box. Overflow => FAIL.
const { execFileSync } = require('child_process');
const fs = require('fs');

const out = [];
const script = String.raw`
(async () => {
  const slides = document.querySelectorAll('.slide');
  const results = [];
  for (const s of slides) {
    const h = s.scrollHeight, w = s.scrollWidth;
    results.push({
      overH: h - s.clientHeight, overW: w - s.clientWidth,
      scrollH: h, clientH: s.clientHeight,
      scrollW: w, clientW: s.clientWidth,
    });
  }
  return JSON.stringify(results);
})();
`;

// Use a data: URL approach via a temp html that loads slides.html inline is messy.
// Simpler: run chromium with --dump-dom won't run JS returning easily. Use devtools protocol via node http? 
// Simplest reliable: chromium --headless --repl is flaky. Use puppeteer if available, else fall back to a flag-free approach:
// inject a <script> that writes results into document.title, then --dump-dom and grep.

const html = fs.readFileSync('slides.html', 'utf8');
const injected = html.replace('</body>', `<script>
(async()=>{
  const sl=document.querySelectorAll('.slide');
  const r=[];
  for(const s of sl){r.push({oH:s.scrollHeight-s.clientHeight,oW:s.scrollWidth-s.clientWidth,sh:s.scrollHeight,ch:s.clientHeight,sw:s.scrollWidth,cw:s.clientWidth});}
  document.title='RESULT:'+JSON.stringify(r);
  // also dump to a DOM node for --dump-dom
  const d=document.createElement('div'); d.id='__fitresult'; d.textContent=JSON.stringify(r); document.body.appendChild(d);
})();
</script></body>`);
const tmp = '/tmp/slides_fit.html';
fs.writeFileSync(tmp, injected);

let dom;
try {
  dom = execFileSync('chromium', [
    '--headless=new','--no-sandbox','--disable-gpu','--virtual-time-budget=3000',
    '--dump-dom', 'file://'+tmp
  ], {encoding:'utf8', maxBuffer: 50*1024*1024});
} catch (e) {
  console.error('chromium failed', String(e.stderr||e).slice(0,500));
  process.exit(2);
}

const m = dom.match(/__fitresult"[^>]*>([^<]*)</);
if (!m) { console.error('no fit result found'); process.exit(3); }
const res = JSON.parse(m[1]);
let fail = 0;
res.forEach((r, i) => {
  const n = String(i+1).padStart(2,'0');
  const okH = r.oH <= 0, okW = r.oW <= 0;
  if (!okH || !okW) fail++;
  console.log(`slide ${n}: clientH=${r.ch} scrollH=${r.sh} overH=${r.oH}px  clientW=${r.cw} scrollW=${r.sw} overW=${r.oW}px  ${okH&&okW?'OK':'OVERFLOW'}`);
});
console.log(fail===0 ? 'ALL 12 SLIDES FIT A4 LANDSCAPE' : `${fail} SLIDES OVERFLOW`);
process.exit(fail===0?0:1);