#!/usr/bin/env python3
"""Controlled offline diagnostics. Never opens or trains the live organism."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from terminus.core import Organism


def frozen_continuation(model, tokens):
    # Evaluate forward equations on local copies; no observe/gradient/replay call.
    h = model.h.copy()
    correct, losses = 0, []
    for token in tokens:
        logits = model.wy @ h + model.by
        p = np.exp(logits - logits.max())
        p /= p.sum()
        correct += int(np.argmax(p) == token)
        losses.append(float(-np.log(max(float(p[token]), 1e-12))))
        h = np.tanh(model.wx[:, token] + model.wh @ h + model.bh)
    return {'accuracy': correct / len(tokens), 'mean_cross_entropy': float(np.mean(losses)), 'events': len(tokens), 'weight_updates': 0}


def run():
    predictor = Organism(seed=123, now=0)
    work = predictor.model.bucket('context', 'work')
    rest = predictor.model.bucket('context', 'break')
    assert work != rest
    sequence = [work if i % 2 == 0 else rest for i in range(600)]
    continuation = [work if i % 2 == 0 else rest for i in range(120)]
    cold = frozen_continuation(predictor.model, continuation)
    for token in sequence:
        predictor.model.observe(token)
    snapshot = predictor.dump()
    trained = frozen_continuation(predictor.model, continuation)
    assert predictor.dump() == snapshot
    quiet = Organism(seed=814, now=0)
    behaviors = Counter()
    for second in range(1, 1001):
        quiet.tick(second)
        behaviors[quiet.data['behavior']] += 1
    return {
        'scope': 'Synthetic two-context temporal continuation; not held-out worlds or semantic understanding',
        'model': 'online-rnn-v1', 'initialization': 'random', 'seed': 123,
        'training_events': len(sequence), 'gradient_updates': predictor.model.updates,
        'cold_frozen': cold, 'trained_frozen': trained,
        'quiet_ecology': {'seed': 814, 'seconds': 1000, 'behaviors': dict(behaviors),
                          'resting_fraction': (behaviors['sleep'] + behaviors['dream']) / 1000},
        'live_state_accessed': False,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = json.dumps(run(), indent=2) + '\n'
    if args.output:
        args.output.write_text(result)
    print(result, end='')
