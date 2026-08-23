// Inlines dagre, the d3 bundle, data.json, style.css and app.js into template.html -> one self-contained page.
// Usage: node build.js --data <data.json> --out <lineage.html> [--title "Workspace lineage"] [--subtitle "..."] [--explainer explainer.html]
// Run `npm run bundle` first (esbuild d3-entry.js -> d3.min.js).
const fs = require('fs');
const path = require('path');
const args = {};
for (let i = 2; i < process.argv.length; i += 2) args[process.argv[i].replace(/^--/, '')] = process.argv[i + 1];
if (!args.data || !args.out) { console.error('usage: node build.js --data data.json --out lineage.html [--title T] [--subtitle S] [--explainer explainer.html]'); process.exit(1); }
const d = __dirname;
const r = f => fs.readFileSync(f, 'utf8');
const dagre = r(path.join(d, 'node_modules/@dagrejs/dagre/dist/dagre.min.js')).replace(/\/\/# sourceMappingURL=.*$/m, '');
const d3 = r(path.join(d, 'd3.min.js'));
const data = r(args.data).replace(/<\/script/gi, '<\\/script').replace(/<!--/g, '<\\!--');
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
let html = r(path.join(d, 'template.html'));
const rep = (tok, val, all) => {
  if (!html.includes(tok)) throw new Error('missing ' + tok);
  html = all ? html.split(tok).join(val) : html.replace(tok, () => val);
};
rep('/*__TITLE__*/', esc(args.title || 'Fabric lineage'), true);
rep('/*__SUBTITLE__*/', esc(args.subtitle || 'Bronze → Silver → Gold → DirectLake'));
rep('<!--__EXPLAINER__-->', args.explainer ? r(args.explainer) : '');
rep('/*__CSS__*/', r(path.join(d, 'style.css')));
rep('/*__DAGRE__*/', dagre);
rep('/*__D3__*/', d3);
rep('/*__DATA__*/', data);
rep('/*__APP__*/', r(path.join(d, 'app.js')));
fs.writeFileSync(args.out, html);
console.log(args.out, html.length, 'bytes');
