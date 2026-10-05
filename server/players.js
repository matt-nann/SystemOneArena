// The two players and how each one is asked for a move through OpenRouter.
// Mirrors matt-nann/aven: Jev goes through OpenRouter's Decisions endpoint
// (packages/llm/decisions.py), Sol through chat completions with a strict
// JSON schema and provider.require_parameters (packages/llm/service.py).

const game = require('./game');

function settings(env = process.env) {
  const num = (v, d) => (v === undefined || v === '' ? d : Number(v));
  return {
    apiKey: env.OPENROUTER_API_KEY || '',
    baseUrl: env.OPENROUTER_BASE_URL || 'https://openrouter.ai/api/v1',
    decisionsUrl: env.OPENROUTER_DECISIONS_URL || 'https://openrouter.ai/api/alpha/decisions',
    appName: env.OPENROUTER_APP_NAME || 'System One Arena',
    appUrl: env.OPENROUTER_APP_URL || 'https://github.com/matt-nann/SystemOneArena',
    dryRun: env.ARENA_DRY_RUN === '1',
    jev: {
      name: env.JEV_NAME || 'Jev',
      model: env.JEV_MODEL || 'typesafe/jev-1.13',
      timeoutMs: num(env.JEV_TIMEOUT_SECONDS, 20) * 1000,
      dryMs: num(env.JEV_DRY_RUN_MS, 350),
    },
    sol: {
      name: env.SOL_NAME || 'Sol',
      model: env.SOL_MODEL || 'openai/gpt-6-sol',
      effort: env.SOL_REASONING_EFFORT || '',
      maxTokens: num(env.SOL_MAX_TOKENS, 4000),
      timeoutMs: num(env.SOL_TIMEOUT_SECONDS, 60) * 1000,
      dryMs: num(env.SOL_DRY_RUN_MS, 6000),
    },
  };
}

function headers(cfg) {
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${cfg.apiKey}`,
    'HTTP-Referer': cfg.appUrl,
    'X-Title': cfg.appName,
  };
}

// ── Jev: OpenRouter Decisions ───────────────────────────────────────

function jevRequest(cfg, snap) {
  const q = game.questions(snap);
  return {
    model: cfg.jev.model,
    state: game.state(snap),
    questions: Object.fromEntries(
      Object.entries(q).map(([name, v]) => [name, { type: 'choice', instructions: v.instructions, criteria: v.options }]),
    ),
  };
}

function jevParse(snap, body) {
  const a = body && body.answers;
  if (!a || !a.card || !a.lane) throw new Error('decisions response did not answer every question');
  return {
    ...game.toMove(snap, a.card.choice, a.lane.choice),
    confidence: a.card.confidence ?? null,
    model: body.model || null,
    usage: body.usage || {},
  };
}

// ── Sol: OpenRouter chat completions, strict JSON schema ─────────────

function solRequest(cfg, snap) {
  const q = game.questions(snap);
  const prompt =
    `${q.card.instructions}\n\nCard options:\n` +
    Object.entries(q.card.options).map(([k, v]) => `- ${k}: ${v}`).join('\n') +
    `\n\n${q.lane.instructions}\n\nBoard state (JSON):\n${JSON.stringify(game.state(snap))}`;
  const body = {
    model: cfg.sol.model,
    messages: [
      { role: 'system', content: 'You are playing a real-time tower battle. Answer with your move only.' },
      { role: 'user', content: prompt },
    ],
    max_tokens: cfg.sol.maxTokens,
    response_format: {
      type: 'json_schema',
      json_schema: {
        name: 'move',
        strict: true,
        schema: {
          type: 'object',
          properties: {
            card: { type: 'string', enum: Object.keys(q.card.options) },
            lane: { type: 'string', enum: Object.keys(q.lane.options) },
          },
          required: ['card', 'lane'],
          additionalProperties: false,
        },
      },
    },
    // Route only to upstreams that honour response_format (same as Aven).
    provider: { require_parameters: true },
  };
  if (cfg.sol.effort) body.reasoning = { effort: cfg.sol.effort };
  return body;
}

function solParse(snap, body) {
  const choice = body && body.choices && body.choices[0];
  if (!choice) throw new Error('chat response had no choices');
  if (choice.finish_reason === 'length') throw new Error('answer was cut off at max_tokens');
  let move;
  try {
    move = JSON.parse(choice.message && choice.message.content);
  } catch {
    throw new Error('answer was not valid JSON');
  }
  return { ...game.toMove(snap, move.card, move.lane), model: body.model || null, usage: body.usage || {} };
}

// ── Transport ───────────────────────────────────────────────────────

async function post(url, cfg, body, timeoutMs) {
  let resp;
  try {
    resp = await fetch(url, { method: 'POST', headers: headers(cfg), body: JSON.stringify(body), signal: AbortSignal.timeout(timeoutMs) });
  } catch (err) {
    throw new Error(err.name === 'TimeoutError' ? 'timed out' : `unreachable: ${err.message}`);
  }
  const text = await resp.text();
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {}
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${(json && json.error && json.error.message) || resp.statusText}`);
  if (!json) throw new Error('response was not JSON');
  return json;
}

// Dry run: no network. Builds the real request, waits the configured time and
// answers with a provider-shaped response, so the whole pipeline runs without a key.
function dryChoice(snap) {
  const opts = game.affordable(snap);
  const pref = ['giant', 'knight', 'archers', 'bomber', 'swarm'].find((c) => opts.includes(c));
  const lane = snap.lanes[0].their_tower_hp <= snap.lanes[1].their_tower_hp ? 'left' : 'right';
  return { card: snap.elixir >= 7 || snap.lanes.some((l) => l.enemy_troops_on_your_side > 0) ? pref : 'wait', lane };
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const PLAYERS = {
  jev: {
    request: jevRequest,
    parse: jevParse,
    async call(cfg, body, snap) {
      if (cfg.dryRun) {
        await sleep(cfg.jev.dryMs);
        const m = dryChoice(snap);
        return { model: `${cfg.jev.model} (dry run)`, answers: { card: { type: 'choice', choice: m.card, confidence: 1 }, lane: { type: 'choice', choice: m.lane } } };
      }
      return post(cfg.decisionsUrl, cfg, body, cfg.jev.timeoutMs);
    },
  },
  sol: {
    request: solRequest,
    parse: solParse,
    async call(cfg, body, snap) {
      if (cfg.dryRun) {
        await sleep(cfg.sol.dryMs);
        return { model: `${cfg.sol.model} (dry run)`, choices: [{ finish_reason: 'stop', message: { content: JSON.stringify(dryChoice(snap)) } }] };
      }
      return post(`${cfg.baseUrl}/chat/completions`, cfg, body, cfg.sol.timeoutMs);
    },
  },
};

/** Asks one player for a move. Resolves {card, lane, ms, ...}; rejects with a readable error. */
async function decide(cfg, who, snap) {
  const p = PLAYERS[who];
  if (!p) throw new Error(`unknown player ${who}`);
  const bad = game.validateSnapshot(snap);
  if (bad) throw new Error(bad);
  if (!cfg.dryRun && !cfg.apiKey) throw new Error('OPENROUTER_API_KEY is not set');
  const body = p.request(cfg, snap);
  const t0 = performance.now();
  const raw = await p.call(cfg, body, snap);
  const ms = performance.now() - t0;
  return { ...p.parse(snap, raw), ms, request: body };
}

module.exports = { settings, decide, jevRequest, jevParse, solRequest, solParse };
