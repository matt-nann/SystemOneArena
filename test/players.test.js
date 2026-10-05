// Request and response handling for both players. No network: fetch is stubbed.
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const { settings, decide, jevRequest, jevParse, solRequest, solParse } = require('../server/players');
const { createServer } = require('../server/server');

const SNAP = {
  timeLeft: 42,
  elixir: 4,
  hand: ['knight', 'giant', 'swarm', 'archers'],
  crowns: { you: 0, opponent: 1 },
  kings: { your_hp: 6000, their_hp: 6000 },
  lanes: [
    { your_tower_hp: 3800, their_tower_hp: 1200, your_troops: [], their_troops: [{ type: 'giant', hp: 2000, tiles_from_your_king: 6 }], enemy_troops_on_your_side: 1 },
    { your_tower_hp: 0, their_tower_hp: 3800, your_troops: [], their_troops: [], enemy_troops_on_your_side: 0 },
  ],
};
const cfg = settings({ OPENROUTER_API_KEY: 'or-key' });

test('Jev is asked two choice questions, offering only affordable cards plus wait', () => {
  const body = jevRequest(cfg, SNAP);
  assert.equal(body.model, 'typesafe/jev-1.13');
  assert.equal(body.questions.card.type, 'choice');
  assert.deepEqual(Object.keys(body.questions.card.criteria).sort(), ['archers', 'knight', 'swarm', 'wait']);
  assert.deepEqual(Object.keys(body.questions.lane.criteria), ['left', 'right']);
  assert.equal(body.state.lanes.left.their_tower_hp, 1200);
  assert.equal(body.state.your_elixir, 4);
});

test("Sol gets the same options as a strict JSON schema, routed only to upstreams that honour it", () => {
  const body = solRequest(cfg, SNAP);
  const schema = body.response_format.json_schema.schema;
  assert.equal(body.model, 'openai/gpt-6-sol');
  assert.equal(body.response_format.json_schema.strict, true);
  assert.deepEqual(schema.properties.card.enum.sort(), Object.keys(jevRequest(cfg, SNAP).questions.card.criteria).sort());
  assert.deepEqual(body.provider, { require_parameters: true });
  assert.equal(body.reasoning, undefined);
  assert.deepEqual(solRequest(settings({ SOL_REASONING_EFFORT: 'high' }), SNAP).reasoning, { effort: 'high' });
});

test('answers become {card, lane index}; wait becomes no card', () => {
  const jev = (card, lane) => ({ model: 'typesafe/jev-1.13-x', answers: { card: { type: 'choice', choice: card, confidence: 0.9 }, lane: { type: 'choice', choice: lane } } });
  const sol = (content, finish = 'stop') => ({ model: 'openai/gpt-6-sol', choices: [{ finish_reason: finish, message: { content } }] });
  assert.deepEqual([jevParse(SNAP, jev('swarm', 'left')).card, jevParse(SNAP, jev('swarm', 'left')).lane], ['swarm', 0]);
  assert.equal(jevParse(SNAP, jev('wait', 'right')).card, null);
  assert.equal(solParse(SNAP, sol('{"card":"knight","lane":"right"}')).lane, 1);
  assert.throws(() => jevParse(SNAP, jev('giant', 'left')), /not one of the options/); // costs 5, only 4 elixir
  assert.throws(() => solParse(SNAP, sol('{"card":"knight","lane":"middle"}')), /not one of the options/);
  assert.throws(() => solParse(SNAP, sol('{"card":')), /not valid JSON/);
  assert.throws(() => solParse(SNAP, sol('{}', 'length')), /cut off/);
});

test('decide posts to the right endpoint with the OpenRouter headers', async (t) => {
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    calls.push({ url, init });
    const body = url.endsWith('/decisions')
      ? { answers: { card: { type: 'choice', choice: 'knight' }, lane: { type: 'choice', choice: 'left' } } }
      : { choices: [{ finish_reason: 'stop', message: { content: '{"card":"wait","lane":"left"}' } }] };
    return new Response(JSON.stringify(body), { status: 200 });
  });
  const j = await decide(cfg, 'jev', SNAP);
  const s = await decide(cfg, 'sol', SNAP);
  assert.equal(calls[0].url, 'https://openrouter.ai/api/alpha/decisions');
  assert.equal(calls[1].url, 'https://openrouter.ai/api/v1/chat/completions');
  assert.equal(calls[0].init.headers.Authorization, 'Bearer or-key');
  assert.equal(calls[0].init.headers['X-Title'], 'System One Arena');
  assert.equal(j.card, 'knight');
  assert.equal(s.card, null);
  assert.ok(j.ms >= 0);
});

test('decide surfaces HTTP errors and refuses to call without a key or a choice to make', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ error: { message: 'No endpoints found' } }), { status: 404 }));
  await assert.rejects(decide(cfg, 'sol', SNAP), /HTTP 404: No endpoints found/);
  await assert.rejects(decide(settings({}), 'jev', SNAP), /OPENROUTER_API_KEY is not set/);
  await assert.rejects(decide(cfg, 'jev', { ...SNAP, elixir: 1 }), /no affordable card/);
});

test('server: config and a dry-run decision round trip without any network', async (t) => {
  const fetchSpy = t.mock.method(globalThis, 'fetch');
  const server = createServer(settings({ ARENA_DRY_RUN: '1', JEV_DRY_RUN_MS: '1', SOL_DRY_RUN_MS: '1' }));
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  t.after(() => server.close());
  const base = `http://127.0.0.1:${server.address().port}`;
  const get = (p) => new Promise((resolve) => http.get(base + p, (res) => { let d = ''; res.on('data', (c) => (d += c)); res.on('end', () => resolve({ status: res.statusCode, body: d })); }));
  const post = (p, body) => new Promise((resolve) => {
    const req = http.request(base + p, { method: 'POST', headers: { 'Content-Type': 'application/json' } }, (res) => { let d = ''; res.on('data', (c) => (d += c)); res.on('end', () => resolve({ status: res.statusCode, body: JSON.parse(d) })); });
    req.end(JSON.stringify(body));
  });

  const config = JSON.parse((await get('/api/config')).body);
  assert.deepEqual(config.players.map((p) => p.id), ['jev', 'sol']);
  assert.equal(config.dryRun, true);
  const r = await post('/api/decide/sol', { match: 'test', snapshot: SNAP });
  assert.equal(r.status, 200);
  assert.ok(r.body.card === null || ['knight', 'swarm', 'archers'].includes(r.body.card));
  assert.equal((await post('/api/decide/sol', { match: 'test', snapshot: { ...SNAP, hand: ['dragon'] } })).status, 502);
  assert.equal((await get('/')).status, 200);
  assert.equal(fetchSpy.mock.callCount(), 0);
});
