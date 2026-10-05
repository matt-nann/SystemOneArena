// Local server for a live match. Serves the arena page and asks the models for
// moves, so the OpenRouter key stays on this machine and never reaches the page.
//
//   GET  /                     the arena (arena/index.html)
//   GET  /api/config           player names and models; tells the page to play live
//   POST /api/decide/:player   {match, snapshot} -> {card, lane, ms, model}
//   POST /api/result           the final scoreboard, appended to the match log
//
// Every decision and the result go to logs/<match>.jsonl.

const fs = require('fs');
const http = require('http');
const path = require('path');
const { settings, decide } = require('./players');

const ROOT = path.join(__dirname, '..');
const LOGS = path.join(ROOT, 'logs');

function loadEnv(file) {
  if (!fs.existsSync(file)) return;
  for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
    if (m && process.env[m[1]] === undefined) process.env[m[1]] = m[2].replace(/^(['"])(.*)\1$/, '$2');
  }
}

function send(res, status, body, type = 'application/json') {
  res.writeHead(status, { 'Content-Type': type, 'Cache-Control': 'no-store' });
  res.end(type === 'application/json' ? JSON.stringify(body) : body);
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', (c) => {
      data += c;
      if (data.length > 1e6) req.destroy();
    });
    req.on('end', () => {
      try {
        resolve(JSON.parse(data || '{}'));
      } catch {
        reject(new Error('body is not JSON'));
      }
    });
    req.on('error', reject);
  });
}

function log(match, entry) {
  if (!/^[\w-]{1,64}$/.test(String(match))) return;
  fs.mkdirSync(LOGS, { recursive: true });
  fs.appendFileSync(path.join(LOGS, `${match}.jsonl`), JSON.stringify({ at: new Date().toISOString(), ...entry }) + '\n');
}

function createServer(cfg) {
  return http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    try {
      if (req.method === 'GET' && (url.pathname === '/' || url.pathname === '/index.html')) {
        return send(res, 200, fs.readFileSync(path.join(ROOT, 'arena', 'index.html')), 'text/html; charset=utf-8');
      }
      if (req.method === 'GET' && url.pathname === '/api/config') {
        return send(res, 200, {
          live: true,
          dryRun: cfg.dryRun,
          keySet: Boolean(cfg.apiKey),
          // Index 0 is the bottom (blue) side, index 1 the top (red) side, as in the page.
          players: [
            { id: 'jev', name: cfg.jev.name, model: cfg.jev.model },
            { id: 'sol', name: cfg.sol.name, model: cfg.sol.model, effort: cfg.sol.effort || null },
          ],
        });
      }
      const m = url.pathname.match(/^\/api\/decide\/(jev|sol)$/);
      if (req.method === 'POST' && m) {
        const { match, snapshot } = await readJson(req);
        try {
          const move = await decide(cfg, m[1], snapshot);
          log(match, { player: m[1], snapshot, request: move.request, card: move.card, lane: move.lane, ms: move.ms, model: move.model, usage: move.usage });
          return send(res, 200, { card: move.card, lane: move.lane, ms: move.ms, model: move.model });
        } catch (err) {
          log(match, { player: m[1], snapshot, error: err.message });
          return send(res, 502, { error: err.message });
        }
      }
      if (req.method === 'POST' && url.pathname === '/api/result') {
        const { match, result } = await readJson(req);
        log(match, { result });
        return send(res, 200, { ok: true });
      }
      send(res, 404, { error: 'not found' });
    } catch (err) {
      send(res, 400, { error: err.message });
    }
  });
}

if (require.main === module) {
  loadEnv(path.join(ROOT, '.env'));
  const cfg = settings();
  const port = Number(process.env.PORT || 8787);
  if (!cfg.dryRun && !cfg.apiKey) {
    console.error('OPENROUTER_API_KEY is not set. Put it in .env, or run `npm run dry` to play without calling any model.');
    process.exit(1);
  }
  createServer(cfg).listen(port, '127.0.0.1', () => {
    console.log(`System One Arena on http://localhost:${port}`);
    console.log(`  ${cfg.jev.name}: ${cfg.jev.model}${cfg.dryRun ? ` (dry run, ${cfg.jev.dryMs} ms)` : ''}`);
    console.log(`  ${cfg.sol.name}: ${cfg.sol.model}${cfg.sol.effort ? ` · ${cfg.sol.effort}` : ''}${cfg.dryRun ? ` (dry run, ${cfg.sol.dryMs} ms)` : ''}`);
  });
}

module.exports = { createServer };
