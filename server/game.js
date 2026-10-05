// The question both players answer. The browser sends a snapshot of the board
// from the asking side's point of view; this module turns it into the same
// options and wording for Jev and for Sol, so the only thing that differs
// between them is the model.

const CARDS = {
  knight: { cost: 3, text: 'Knight (3 elixir): one sturdy melee tank, good all-round defender.' },
  archers: { cost: 3, text: 'Archers (3 elixir): two ranged attackers, good behind a tank and against swarms.' },
  swarm: { cost: 2, text: 'Swarm (2 elixir): four fast, fragile melee units; shreds a Giant, dies to splash.' },
  giant: { cost: 5, text: 'Giant (5 elixir): huge HP, only attacks towers; the main way to push.' },
  bomber: { cost: 3, text: 'Bomber (3 elixir): splash damage from range; best answer to Swarm.' },
};

const LANES = ['left', 'right'];

const RULES =
  'Real-time two-lane tower battle. Elixir regenerates at 1 per second and caps at 10; ' +
  'elixir gained while capped is wasted. The match clock does not pause while you decide, ' +
  'so a slow answer is played on a board that has already moved. ' +
  'Destroy the enemy king tower to win; otherwise the side with more towers destroyed wins at 0:00. ' +
  'A defensive card is placed in front of your own tower in that lane; otherwise it is placed at the bridge.';

/** Cards in hand that the side can pay for right now. */
function affordable(snap) {
  return snap.hand.filter((c) => CARDS[c] && CARDS[c].cost <= snap.elixir);
}

/** Checks the browser's snapshot before anything is sent to a model. */
function validateSnapshot(snap) {
  if (!snap || typeof snap !== 'object') return 'snapshot missing';
  if (!Array.isArray(snap.hand) || !snap.hand.every((c) => c in CARDS)) return 'hand must list known cards';
  if (typeof snap.elixir !== 'number') return 'elixir must be a number';
  if (!Array.isArray(snap.lanes) || snap.lanes.length !== 2) return 'lanes must have two entries';
  if (affordable(snap).length === 0) return 'no affordable card: nothing to decide';
  return null;
}

/** The two questions, as {name: {instructions, options: {value: meaning}}}. */
function questions(snap) {
  const card = { wait: 'Play nothing now and keep saving elixir.' };
  for (const c of affordable(snap)) card[c] = CARDS[c].text;
  return {
    card: {
      instructions: 'Which card do you play right now, if any? ' + RULES,
      options: card,
    },
    lane: {
      instructions: 'Which lane does the card go in? Ignored if you play nothing.',
      options: {
        left: 'The left lane, as seen from your king tower.',
        right: 'The right lane, as seen from your king tower.',
      },
    },
  };
}

/** The board as the model sees it: everything in the snapshot except the hand list, which the card options carry. */
function state(snap) {
  return {
    time_left_seconds: snap.timeLeft,
    your_elixir: snap.elixir,
    crowns: { you: snap.crowns.you, opponent: snap.crowns.opponent },
    king_towers: snap.kings,
    lanes: Object.fromEntries(snap.lanes.map((l, i) => [LANES[i], l])),
  };
}

/** Normalises either model's answer into {card, lane}; throws when it falls outside the options. */
function toMove(snap, card, lane) {
  const q = questions(snap);
  if (!(card in q.card.options)) throw new Error(`card ${JSON.stringify(card)} is not one of the options`);
  if (card === 'wait') return { card: null, lane: null };
  if (!(lane in q.lane.options)) throw new Error(`lane ${JSON.stringify(lane)} is not one of the options`);
  return { card, lane: LANES.indexOf(lane) };
}

module.exports = { CARDS, LANES, RULES, affordable, validateSnapshot, questions, state, toMove };
