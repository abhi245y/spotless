// Builds the community compatibility table in README.md from issue-form reports.
const START = '<!-- compat:start -->';
const END = '<!-- compat:end -->';
const STATUS = { 'Works': 0, 'Does not work': 1 };

function field(body, label) {
  const m = (body || '').match(new RegExp(`### ${label}\\s*\\n+([^\\n]+)`));
  return m ? m[1].trim() : '';
}

function parse(issue) {
  const fw = field(issue.body, 'PS5 firmware').match(/\b(\d{1,2})\.(\d{2})\b/);
  // 'Result' is the heading used by reports filed before the form was renamed.
  const status = STATUS[field(issue.body, 'Status') || field(issue.body, 'Result')];
  if (!fw || status === undefined) return null;
  return { firmware: `${Number(fw[1])}.${fw[2]}`, status };
}

function table(issues, repo) {
  const rows = {};
  for (const issue of issues) {
    if (issue.pull_request || issue.state_reason === 'not_planned') continue;
    const r = parse(issue);
    if (!r) continue;
    (rows[r.firmware] ||= [0, 0])[r.status]++;
  }
  const fws = Object.keys(rows).sort((a, b) => parseFloat(b) - parseFloat(a));
  if (!fws.length) return '_No community reports yet._';
  const q = fw => `https://github.com/${repo}/issues?q=${encodeURIComponent(`label:compat-report "${fw}"`)}`;
  return [
    '| Firmware | Status | Reports |',
    '| --- | --- | --- |',
    // ponytail: majority wins, ties count as working; the report counts show any disagreement.
    ...fws.map(fw => {
      const [works, broken] = rows[fw];
      const status = works >= broken ? 'Works' : 'Does not work';
      return `| ${fw} | ${status} | [${works} works, ${broken} does not](${q(fw)}) |`;
    }),
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
  const body = '### PS5 firmware\n\n13.2\n\n### Status\n\nWorks\n\n### Spotless version\n\n_No response_';
  assert.strictEqual(parse({ body }), null, 'needs two-digit minor');
  const ok = n => ({ body: `### PS5 firmware\n\nFW 12.40\n\n### Status\n\n${n}` });
  assert.deepStrictEqual(parse(ok('Works')), { firmware: '12.40', status: 0 });
  const t = table([ok('Works'), ok('Does not work'), { ...ok('Works'), state_reason: 'not_planned' },
    { body: '### PS5 firmware\n\n09.00\n\n### Result\n\nDoes not work' }], 'o/r');
  assert.match(t, /\| 12\.40 \| Works \| \[1 works, 1 does not\]/);
  assert.match(t, /\| 9\.00 \| Does not work \| \[0 works, 1 does not\]/);
  assert.ok(t.indexOf('12.40') < t.indexOf('9.00'), 'newest firmware first');
  assert.strictEqual(update(`x\n${START}\nold\n${END}\ny`, 'new'), `x\n${START}\nnew\n${END}\ny`);
  const tpl = '  options:\n    # releases:start\n    - 0.1.0\n    # releases:end\n    - Built from source';
  assert.strictEqual(versions(tpl, [{ tag_name: 'v0.3.0' }, { tag_name: 'v0.2.9', draft: true }, { tag_name: 'v0.2.0-beta' }]),
    '  options:\n    # releases:start\n    - 0.3.0\n    - 0.2.0-beta\n    # releases:end\n    - Built from source');
  console.log('ok');
}
