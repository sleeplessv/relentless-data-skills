// Builds data.json for the page: the compact graph plus a few per-layer details picked from graph.json.
// Usage: node build-data.js <scratch-dir-with-graph.json-and-graph-compact.json> [out=data.json]
const fs = require('fs');
const path = require('path');
const dir = path.resolve(process.argv[2] || '.');
const outFile = process.argv[3] || path.join(dir, 'data.json');
const compact = JSON.parse(fs.readFileSync(path.join(dir, 'graph-compact.json'), 'utf8'));
const full = JSON.parse(fs.readFileSync(path.join(dir, 'graph.json'), 'utf8'));
const fullById = new Map(full.nodes.map(n => [n.id, n]));

const pick = (o, keys) => { const r = {}; for (const k of keys) if (o && o[k] !== undefined && o[k] !== null && o[k] !== '') r[k] = o[k]; return r; };

for (const n of compact.nodes) {
  const f = fullById.get(n.id); if (!f) continue;
  const d = f.details || {};
  const x = n.details = n.details || {};
  if (n.layer === 'semantic') {
    Object.assign(x, pick(d, ['partitionType', 'entity', 'schema', 'expressionSource', 'columns', 'measures', 'calculationItems', 'hidden', 'tables', 'relationships', 'datasetId', 'workspaceId', 'logicalId', 'refreshTargetNote']));
    if (Array.isArray(d.relationships)) {
      x.relationshipList = d.relationships.map(r => `${r.fromTable}.${r.fromColumn} → ${r.toTable}.${r.toColumn}${r.isActive ? '' : ' (inactive)'}`);
      x.relationships = d.relationships.length;
    }
  } else if (n.layer === 'gold') {
    Object.assign(x, pick(d, ['schema', 'entity', 'sourceLayer', 'sourceDatabase', 'partitionColumn', 'active', 'definingNotebook', 'wrapperNotebook', 'handWrittenNotebook', 'columnCount', 'order', 'lakehouse', 'configPath', 'pipeline', 'note', 'storeMapping']));
    if (Array.isArray(d.registeredIn)) x.registeredIn = d.registeredIn.map(r => `${r.orchestration} (step ${r.stepNumber}${r.critical ? ', critical' : ''})`);
    if (d.keys && typeof d.keys === 'object' && !Array.isArray(d.keys)) { const ks = Object.keys(d.keys); if (ks.length) x.keys = ks; else delete x.keys; }
  } else if (n.layer === 'silver') {
    Object.assign(x, pick(d, ['schema', 'engine', 'partitionColumn', 'columnCount', 'tableCountries', 'orchestrationConfigs', 'sourceLayer', 'sourceDatabase']));
  } else if (n.layer === 'pipeline' && !n.id.startsWith('trigger.')) {
    Object.assign(x, pick(d, ['isDevFork', 'logicalId']));
    if (Array.isArray(d.schedules)) x.schedules = d.schedules.map(s => pick(s, ['enabled', 'type', 'times', 'weekdays', 'interval', 'timezone', 'startDateTime', 'endDateTime']));
    if (Array.isArray(d.activities)) x.activities = d.activities.slice(0, 40).map(a => `${a.name} [${a.type}]${a.notebook ? ' → ' + a.notebook : ''}${a.childPipeline ? ' → ' + a.childPipeline : ''}${a.dependsOn && a.dependsOn.length ? ' ← ' + a.dependsOn.join(', ') : ''}`);
  } else if (n.layer === 'notebook') {
    Object.assign(x, pick(d, ['handWritten', 'target', 'note', 'role', 'lakehouse', 'configPath', 'wiredInWrapper', 'logicalId']));
  } else if (n.layer === 'report') {
    Object.assign(x, pick(d, ['folder', 'sandbox', 'model']));
  } else if (n.layer === 'dataflow') {
    Object.assign(x, pick(d, ['logicalId']));
  }
  delete x._conflicts;
}
const out = { meta: { counts: compact.meta.counts, coverage: compact.meta.coverage, gaps: compact.meta.gaps || {} }, nodes: compact.nodes, edges: compact.edges.map(e => ({ f: e.from, t: e.to, k: e.kind, v: e.via || null })) };
const s = JSON.stringify(out);
fs.writeFileSync(outFile, s);
console.log(outFile, 'bytes', s.length);
