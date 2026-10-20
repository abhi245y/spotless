// Builds the community compatibility table in README.md from issue-form reports.
const START = '<!-- compat:start -->';
const END = '<!-- compat:end -->';
const RESULTS = { 'Works': 0, 'Partially works': 1, 'Does not work': 2 };

function field(body, label) {
  const m = (body || '').match(new RegExp(`### ${label}\\s*\\n+([^\\n]+)`));
  return m ? m[1].trim() : '';
}

function parse(issue) {
  const fw = field(issue.body, 'PS5 firmware').match(/\b(\d{1,2})\.(\d{2})\b/);
  const result = RESULTS[field(issue.body, 'Result')];
  if (!fw || result === undefined) return null;
  return { firmware: `${fw[1].padStart(2, '0')}.${fw[2]}`, result };
}

function table(issues, repo) {
  const rows = {};
  for (const issue of issues) {
    if (issue.pull_request || issue.state_reason === 'not_planned') continue;
    const r = parse(issue);
    if (!r) continue;
    (rows[r.firmware] ||= [0, 0, 0])[r.result]++;
  }
  const fws = Object.keys(rows).sort((a, b) => parseFloat(b) - parseFloat(a));
  if (!fws.length) return '_No community reports yet._';
  const q = fw => `https://github.com/${repo}/issues?q=${encodeURIComponent(`label:compat-report "${fw}"`)}`;
  return [
    '| Firmware | Works | Partially | Does not work | Reports |',
    '| --- | --- | --- | --- | --- |',
    ...fws.map(fw => `| ${fw} | ${rows[fw].join(' | ')} | [view](${q(fw)}) |`),
  ].join('\n');
}

function update(readme, body) {
  const a = readme.indexOf(START), b = readme.indexOf(END);
  if (a < 0 || b < a) throw new Error('compat markers missing from README.md');
  return readme.slice(0, a + START.length) + '\n' + body + '\n' + readme.slice(b);
}

// Rewrites the version dropdown options in the issue form from published releases.
function versions(template, releases) {
  const lines = template.split('\n');
  const a = lines.findIndex(l => l.includes('# releases:start'));
  const b = lines.findIndex(l => l.includes('# releases:end'));
  if (a < 0 || b < a) throw new Error('release markers missing from issue template');
  const indent = lines[a].match(/^\s*/)[0];
  const opts = releases.filter(r => !r.draft).map(r => `${indent}- ${r.tag_name.replace(/^v/, '')}`);
  return [...lines.slice(0, a + 1), ...opts, ...lines.slice(b)].join('\n');
}

module.exports = { parse, table, update, versions };

if (require.main === module) {
  const assert = require('assert');
  const body = '### PS5 firmware\n\n13.2\n\n### Result\n\nWorks\n\n### Spotless version\n\n_No response_';
  assert.strictEqual(parse({ body }), null, 'needs two-digit minor');
  const ok = n => ({ body: `### PS5 firmware\n\nFW 12.40\n\n### Result\n\n${n}` });
  assert.deepStrictEqual(parse(ok('Works')), { firmware: '12.40', result: 0 });
  const t = table([ok('Works'), ok('Does not work'), { ...ok('Works'), state_reason: 'not_planned' },
    { body: '### PS5 firmware\n\n9.00\n\n### Result\n\nPartially works' }], 'o/r');
  assert.match(t, /\| 12\.40 \| 1 \| 0 \| 1 \|/);
  assert.match(t, /\| 09\.00 \| 0 \| 1 \| 0 \|/);
  assert.ok(t.indexOf('12.40') < t.indexOf('09.00'), 'newest firmware first');
  assert.strictEqual(update(`x\n${START}\nold\n${END}\ny`, 'new'), `x\n${START}\nnew\n${END}\ny`);
  const tpl = '  options:\n    # releases:start\n    - 0.1.0\n    # releases:end\n    - Built from source';
  assert.strictEqual(versions(tpl, [{ tag_name: 'v0.3.0' }, { tag_name: 'v0.2.9', draft: true }, { tag_name: 'v0.2.0-beta' }]),
    '  options:\n    # releases:start\n    - 0.3.0\n    - 0.2.0-beta\n    # releases:end\n    - Built from source');
  console.log('ok');
}
