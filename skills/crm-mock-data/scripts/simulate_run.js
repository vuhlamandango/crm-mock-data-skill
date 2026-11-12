// Minimal Postman sandbox simulator: runs prereq/test scripts, follows setNextRequest.
const fs = require('fs');
const c = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const failOn = process.argv[3] || null;       // request name to fail
const vars = {}; c.variable.forEach(v => vars[v.key] = v.value);
let next, nextSet, guidN = 0, resp, logs = [];
const pm = {
  collectionVariables: {
    get: k => vars[k], set: (k, v) => { vars[k] = v; }, unset: k => { delete vars[k]; },
    toObject: () => ({ ...vars }) },
  variables: { replaceIn: s => s.replace('{{$guid}}', 'guid-' + (++guidN)) },
  execution: { setNextRequest: n => { next = n; nextSet = true; } },
  test: (n, f) => { try { f(); } catch (e) { logs.push('TEST FAIL ' + n + ': ' + e.message); } },
  expect: v => ({ to: { be: { within: (a, b) => { if (!(v >= a && v <= b)) throw new Error(v + ' not in ' + a + '..' + b); } } } }),
  get response() { return resp; },
};
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
const run = async (src) => new AsyncFunction('pm', 'console', 'setTimeout', src)(pm, { log: m => logs.push(m), error: m => logs.push('ERR ' + m) }, (f) => f());
(async () => {
  let idx = 0, steps = 0; const order = c.item.map(i => i.name);
  while (idx !== null && steps++ < 200) {
    const it = c.item[idx]; const ev = Object.fromEntries((it.event||[]).map(e => [e.listen, e.script.exec.join('\n')]));
    const body = it.request.body.raw;
    if (ev.prerequest) await run(ev.prerequest);
    const status = it.name === failOn ? 500 : 200;
    let json;
    if (it.name === 'Create New Loan') json = { data: { items: [{ loanGuid: 'LG' + steps, loanNumber: 'N' + steps }] } };
    else if (it.request.url.includes('/Create')) json = 'crm-' + steps;
    else json = { Xml: '' };
    resp = { code: status, json: () => json, text: () => JSON.stringify(json) };
    next = undefined; nextSet = false;
    await run(ev.test);
    if (!nextSet) idx = idx + 1 < order.length ? idx + 1 : null; // runner default order
    else idx = next === null ? null : order.indexOf(next);
    process.stdout.write(it.name + ' -> ' + (idx === null ? 'END' : order[idx]) + '\n');
  }
  console.log('\n--- logs ---'); logs.forEach(l => console.log(String(l).slice(0, 700)));
})();
