// Runs the arena simulation headlessly and prints the match result.
// Usage: node scripts/check-sim.js [jevLatency] [opponentLatency]
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, '..', 'arena', 'index.html'), 'utf8');
const src = html.split('/* ===== SIM (pure, deterministic) ===== */')[1].split('/* ===== END SIM ===== */')[0];
const createSim = new Function(src + ';return createSim')();

const latency = [Number(process.argv[2] || 0.36), Number(process.argv[3] || 5.99)];
const sim = createSim({ seed: 13, duration: 60, latency, jitter: [0.05, 0.7], elixirRate: 1, towerHp: 3800, kingHp: 6000 });
while (!sim.S.over) sim.step(1 / 30);

const S = sim.S;
const names = ['Jev', 'Opponent'];
console.log(`${names[S.winner]} wins (${S.reason}) at ${S.t.toFixed(1)}s`);
S.sides.forEach((s, i) =>
  console.log(`${names[i].padEnd(9)} latency ${latency[i]}s  decisions ${s.decisions}  elixir wasted ${s.wasted.toFixed(1)}  crowns ${s.crowns}`));
