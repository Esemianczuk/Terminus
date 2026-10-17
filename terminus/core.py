"""Deterministic persistence, online learning, associative memory and small gestures.

The predictor starts from seeded random weights. It learns next-event buckets by
one-step truncated backpropagation; it is neither a pretrained language model nor
a claim of sentience. Its invented 20-sign language combines a topic sign, an
affect sign and (occasionally) an aspect sign. Nothing is a historical translation.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from copy import deepcopy

import numpy as np


def clamp(value, low=0.0, high=1.0):
    return float(max(low, min(high, value)))


GLYPHS = [
    {"id": i, "phoneme": syllable, "meaning": meaning}
    for i, (syllable, meaning) in enumerate([
        ("ka", "self"), ("mi", "nearby presence"), ("to", "place / context"),
        ("ru", "making / work"), ("ni", "touch"), ("sa", "passing time"),
        ("vo", "return / familiarity"), ("lu", "rest"), ("ki", "curiosity"),
        ("ha", "surprise"), ("mo", "ease"), ("te", "attention"),
        ("shi", "uncertainty"), ("no", "absence"), ("ya", "play"),
        ("mu", "dream / association"), ("li", "again"), ("po", "new"),
        ("se", "fading"), ("na", "together"),
    ])
]


class OnlineRNN:
    """A compact 64-bucket, 24-unit recurrent predictor trained on actual events."""

    vocabulary = 64
    width = 24

    def __init__(self, rng, saved=None):
        if saved:
            for name in ("wx", "wh", "wy", "bh", "by", "h", "before"):
                setattr(self, name, np.array(saved[name], dtype=np.float64))
            for name in ("previous", "updates", "loss", "prediction_error"):
                setattr(self, name, saved[name])
            self.replay = deepcopy(saved.get("replay", []))
            self.replay_cursor = saved.get("replay_cursor", 0)
            return
        self.wx = rng.normal(0, .13, (self.width, self.vocabulary))
        self.wh = rng.normal(0, .09, (self.width, self.width))
        self.wy = rng.normal(0, .12, (self.vocabulary, self.width))
        self.bh = np.zeros(self.width)
        self.by = np.zeros(self.vocabulary)
        self.h = np.zeros(self.width)
        self.before = np.zeros(self.width)
        self.previous = None
        self.updates = 0
        self.loss = 0.0
        self.prediction_error = 1.0
        self.replay = []
        self.replay_cursor = 0

    @staticmethod
    def bucket(kind, context):
        key = f"{kind}:{context.casefold()}".encode()
        return int.from_bytes(hashlib.blake2s(key, digest_size=4).digest(), "big") % 64

    def probabilities(self):
        logits = self.wy @ self.h + self.by
        exp = np.exp(logits - logits.max())
        return exp / exp.sum()

    def observe(self, token):
        p = self.probabilities()
        surprise = float(-np.log(max(p[token], 1e-12)))
        self.prediction_error = clamp(surprise / math.log(self.vocabulary))
        if self.previous is not None:
            self.replay.append({"previous": self.previous, "target": token,
                                "h": self.h.tolist(), "before": self.before.tolist()})
            del self.replay[:-64]
            self._learn(token, self.previous, self.h, self.before)
        self.before = self.h.copy()
        self.h = np.tanh(self.wx[:, token] + self.wh @ self.h + self.bh)
        self.previous = token
        return self.prediction_error

    def _learn(self, target, previous, hidden, before):
        logits = self.wy @ hidden + self.by
        p = np.exp(logits - logits.max())
        p /= p.sum()
        loss = float(-np.log(max(p[target], 1e-12)))
        self.loss = loss if not self.updates else .94 * self.loss + .06 * loss
        grad = p.copy()
        grad[target] -= 1
        dh = np.clip((self.wy.T @ grad) * (1 - hidden ** 2), -1, 1)
        rate = .055
        self.wy -= rate * np.outer(grad, hidden)
        self.by -= rate * grad
        self.wx[:, previous] -= rate * dh
        self.wh -= rate * np.outer(dh, before)
        self.bh -= rate * dh
        self.updates += 1

    def consolidate(self):
        # Replay a recorded transition; do not invent a repeated event or advance
        # the live recurrent context. The short replay ring is persisted too.
        if self.replay:
            sample = self.replay[self.replay_cursor % len(self.replay)]
            self.replay_cursor += 1
            self._learn(sample["target"], sample["previous"],
                        np.array(sample["h"]), np.array(sample["before"]))

    def dump(self):
        return {
            name: value.tolist() if isinstance(value, np.ndarray) else deepcopy(value)
            for name, value in vars(self).items()
        }


BASE = [
    ("self", "self", "body"), ("presence", "company", "social"),
    ("context", "surroundings", "world"), ("git", "making", "work"),
    ("poke", "touch", "body"), ("time", "rhythm", "world"),
    ("familiar", "familiar", "memory"), ("sleep", "rest", "body"),
    ("curious", "curiosity", "affect"), ("surprise", "surprise", "affect"),
    ("ease", "ease", "affect"), ("focus", "attention", "affect"),
    ("uncertain", "uncertainty", "affect"), ("absence", "quiet", "world"),
    ("play", "play", "affect"), ("dream", "dream", "memory"),
    ("again", "repetition", "memory"), ("new", "novelty", "memory"),
    ("fade", "fading", "memory"), ("together", "connection", "social"),
    ("drag", "movement", "body"), ("activity", "activity", "work"),
]


class Organism:
    max_nodes = 72
    max_edges = 320

    def __init__(self, seed=814, now=0.0, saved=None):
        self.rng = np.random.default_rng(seed)
        if saved:
            self.rng.bit_generator.state = saved["rng"]
            self.model = OnlineRNN(self.rng, saved["model"])
            self.data = deepcopy(saved["data"])
            self.data.setdefault("last_tick_at", self.data["server_time"])
            self._ensure_scaffold()
            self._ensure_ethology()
            return
        self.model = OnlineRNN(self.rng)
        nodes = []
        for i, (node_id, label, kind) in enumerate(BASE):
            angle = i * (math.pi * (3 - math.sqrt(5)))
            radius = .14 + .30 * math.sqrt((i + 1) / len(BASE))
            nodes.append({"id": node_id, "label": label, "kind": kind,
                          "x": .5 + math.cos(angle) * radius,
                          "y": .5 + math.sin(angle) * radius,
                          "activation": .02, "familiarity": 0., "novelty": 1.,
                          "seen": 0, "last_seen": now})
        self.data = {
            "organism_id": str(uuid.UUID(bytes=self.rng.bytes(16))),
            "revision": 0, "server_time": now, "behavior": "sleep",
            "behavior_since": now, "position": {"x": .5, "y": .62},
            "attention": None,
            "latent": {"sleepiness": .65, "curiosity": .62, "agitation": .08,
                       "focus": .25, "symbolic_charge": 0.},
            "nodes": nodes, "edges": [], "utterance": None,
            "events_seen": 0, "devices": [], "recent_events": [],
            "last_event_at": now, "last_utterance_at": now, "last_tick_at": now,
            "last_consolidation_at": now, "previous_context": None,
            "last_response": 0., "consolidations": 0,
        }
        self._ensure_scaffold()
        self._ensure_ethology()

    def _ensure_scaffold(self):
        """Migrate intrinsic body/world structure without inventing experience."""
        for edge in self.data["edges"]:
            edge.setdefault("origin", "learned")
        groups = {}
        for node_id, _, kind in BASE:
            groups.setdefault(kind, []).append(node_id)
        links = [(members[0], member, .23)
                 for members in groups.values() for member in members[1:]]
        links += [("self", "presence", .12), ("self", "curious", .16),
                  ("context", "focus", .12), ("time", "sleep", .18),
                  ("git", "focus", .14), ("dream", "sleep", .17),
                  ("together", "familiar", .12)]
        existing = {(e["source"], e["target"]) for e in self.data["edges"]}
        for first, second, weight in links:
            source, target = sorted((first, second))
            if (source, target) not in existing:
                self.data["edges"].append({"source": source, "target": target,
                                           "weight": weight, "origin": "scaffold"})
        self.data["schema_version"] = 3
        self.data.setdefault("last_responded", False)
        self.data.setdefault("visible_responses", 0)
        self.data.setdefault("last_attention_at", self.data["last_event_at"])
        self._bound_edges()

    def _ensure_ethology(self):
        """Add policy state without drawing RNG or replacing a living model.

        Temperament is a stable bias derived from identity, not a score earned by
        interaction. This migration deliberately leaves existing latent state,
        graph, history, model weights and the exact random stream untouched.
        """
        d, now = self.data, self.data["server_time"]
        identity = hashlib.blake2s(d["organism_id"].encode(), digest_size=16).digest()
        d.setdefault("traits", {name: .2 + identity[i] / 255 * .6
                               for i, name in enumerate(("curiosity", "caution", "playfulness", "sociability", "rhythm"))})
        d.setdefault("motives", {"exploration": .42, "affiliation": .28, "comfort": .72})
        d.setdefault("gesture", None)
        d.setdefault("last_model_observed_at", d["last_event_at"])
        d.setdefault("source_counts", {})
        d.setdefault("motion", {"intent": "rest", "started_at": now, "duration": 120.,
                                "target_id": d["attention"], "strength": .15})
        d.setdefault("ethology", {"gesture_serial": 0, "next_gesture_at": now + 4,
                                   "next_intent_at": now + 12, "next_revisit_at": now + 24,
                                   "next_survey_at": now + 125 + d["traits"]["rhythm"] * 50,
                                   "survey_until": 0., "dream_until": 0.,
                                   "linger_until": now, "attention_reason": "rest",
                                   "attention_visits": {}, "revisits": 0})

    @staticmethod
    def _novelty(node, now):
        # Familiarity is retained; the response to a familiar cue partly
        # recovers after an absence. A node is not made into a new experience.
        baseline = 1 / math.sqrt(1 + node["seen"])
        absence = max(0., now - node["last_seen"])
        return baseline + (1 - baseline) * .62 * (1 - math.exp(-absence / 900))

    def _gesture(self, kind, now, duration=None, strength=.5, target_id=None):
        # A blink gesture is a short double-blink envelope. Each lid closure is
        # brief in the renderer; the envelope outlives the native 1 Hz poll.
        durations = {"blink": 1.8, "peer": 3.4, "tilt": 2.8, "stretch": 5.8,
                     "yawn": 4.4, "tendril-inspect": 5.2, "startled": 1.25,
                     "curl": 5.8, "settle": 5., "sleep": 6.5, "dream": 7., "signal": 4.8,
                     "imitate": 6.}
        d, policy = self.data, self.data["ethology"]
        policy["gesture_serial"] += 1
        duration = durations[kind] if duration is None else duration
        d["gesture"] = {"id": f"g-{policy['gesture_serial']}", "kind": kind,
                        "started_at": now, "duration": duration, "target_id": target_id,
                        "strength": clamp(strength)}
        sleeping = d["behavior"] in ("sleep", "dream")
        policy["next_gesture_at"] = now + duration + float(self.rng.uniform(7, 16) if sleeping else self.rng.uniform(2, 5))

    def _motion(self, intent, now, duration, strength=.3, target_id=None):
        self.data["motion"] = {"intent": intent, "started_at": now,
                               "duration": duration, "target_id": target_id,
                               "strength": clamp(strength)}
        self.data["ethology"]["next_intent_at"] = now + duration

    def _bound_edges(self):
        if len(self.data["edges"]) > self.max_edges:
            self.data["edges"].sort(key=lambda e: (e.get("origin") == "scaffold", e["weight"]), reverse=True)
            del self.data["edges"][self.max_edges:]

    def _spread_activation(self, elapsed):
        """Move existing activation through actual weighted associations."""
        nodes = {node["id"]: node for node in self.data["nodes"]}
        adjacency = {node_id: [] for node_id in nodes}
        for edge in self.data["edges"]:
            if edge["source"] in nodes and edge["target"] in nodes:
                adjacency[edge["source"]].append((edge["target"], edge["weight"]))
                adjacency[edge["target"]].append((edge["source"], edge["weight"]))
        changes = {node_id: 0. for node_id in nodes}
        for node_id, neighbors in adjacency.items():
            total = sum(weight for _, weight in neighbors)
            if not total:
                continue
            outward = nodes[node_id]["activation"] * min(.25, .04 * elapsed)
            changes[node_id] -= outward
            for neighbor, weight in neighbors:
                changes[neighbor] += outward * weight / total
        for node_id, amount in changes.items():
            nodes[node_id]["activation"] = clamp(nodes[node_id]["activation"] + amount)

    def _attention_scores(self, context_node, now, revisit=False):
        """Actual activation, learned links and next-event prediction compete.

        Scaffold contributes a small body/world bias; experience is required
        for autonomous memory visits. Novelty alone cannot animate an untouched
        node into a fabricated memory.
        """
        candidates = {context_node["id"]}
        associations = {}
        for edge in self.data["edges"]:
            if context_node["id"] in (edge["source"], edge["target"]):
                candidates.update((edge["source"], edge["target"]))
                other = edge["target"] if edge["source"] == context_node["id"] else edge["source"]
                associations[other] = edge["weight"] * (1 if edge.get("origin") == "learned" else .12)
        if revisit:
            candidates.update(n["id"] for n in self.data["nodes"] if n["seen"])
        candidates = [node for node in self.data["nodes"] if node["id"] in candidates]
        probabilities = self.model.probabilities()
        visits = self.data["ethology"]["attention_visits"]
        scored = []
        for node in candidates:
            if revisit and (not node["seen"] or node["id"] == context_node["id"]):
                continue
            prediction = float(probabilities[node["last_bucket"]]) if node.get("last_bucket") is not None else 0.
            recent = max(0., 1 - (now - visits.get(node["id"], -1000)) / 40)
            score = (.02 + node["activation"] + associations.get(node["id"], 0.) * .6
                     + prediction * .8 + (self._novelty(node, now) * .08 if node["seen"] else 0.)
                     + node["familiarity"] * .04 - recent * .08)
            # The public model sees event categories only. Its small prior
            # supplements local attention without replacing private weights.
            shared = self.data.get("collective_prior", {}).get("probabilities", {})
            score += .10 * shared.get(node.get("last_kind", node["id"]), 0.)
            scored.append((node, max(.005, score)))
        return scored

    def _attend(self, context_node, now=None, reason="cue", revisit=False):
        d, policy = self.data, self.data["ethology"]
        now = d["server_time"] if now is None else now
        current = self._node(d["attention"])
        if not revisit and current and now < policy["linger_until"] and context_node["activation"] < .32:
            return current
        scored = self._attention_scores(context_node, now, revisit)
        if not scored:
            return current
        ordered = sorted(scored, key=lambda pair: pair[1], reverse=True)
        # A salient target wins reliably; weaker associations compete rather
        # than always taking the global maximum.
        if len(ordered) == 1 or ordered[0][1] - ordered[1][1] > .65:
            chosen = ordered[0][0]
        else:
            weights = np.array([score ** 2 for _, score in scored])
            weights /= weights.sum()
            chosen = scored[int(self.rng.choice(len(scored), p=weights))][0]
        d["attention"] = chosen["id"]
        policy["linger_until"] = now + 3 + d["traits"]["caution"] * 5
        policy["attention_reason"] = reason
        policy["attention_visits"][chosen["id"]] = now
        policy["attention_visits"] = {key: when for key, when in policy["attention_visits"].items()
                                       if self._node(key) is not None}
        return chosen

    def dump(self):
        return {"rng": self.rng.bit_generator.state, "model": self.model.dump(),
                "data": deepcopy(self.data)}

    def _behavior(self, name, now):
        if self.data["behavior"] != name:
            self.data["behavior"] = name
            self.data["behavior_since"] = now
            gesture = {"startled": "startled", "settle": "settle", "sleep": "curl",
                       "dream": "dream", "inspect": "peer", "attend": "tilt"}.get(name)
            if gesture:
                self._gesture(gesture, now, target_id=self.data["attention"])
            if name == "sleep":
                self._motion("rest", now, 120, .12, self.data["attention"])

    def _node(self, node_id):
        return next((n for n in self.data["nodes"] if n["id"] == node_id), None)

    def _edge(self, source, target, amount):
        if not source or source == target:
            return
        source, target = sorted((source, target))
        edge = next((e for e in self.data["edges"]
                     if e["source"] == source and e["target"] == target), None)
        if edge:
            edge["weight"] = clamp(edge["weight"] + amount * (1 - edge["weight"]))
        else:
            self.data["edges"].append({"source": source, "target": target, "weight": amount, "origin": "learned"})
        self._bound_edges()

    def _context_node(self, context, now):
        node_id = "ctx-" + hashlib.blake2s(context.casefold().encode(), digest_size=6).hexdigest()
        node = self._node(node_id)
        if node:
            return node
        if len(self.data["nodes"]) >= self.max_nodes:
            candidates = [n for n in self.data["nodes"] if n["id"].startswith("ctx-")]
            protected = {self.data["attention"], self.data["previous_context"],
                         self.data["motion"]["target_id"]}
            if self.data["gesture"]:
                protected.add(self.data["gesture"]["target_id"])
            candidates = [n for n in candidates if n["id"] not in protected] or candidates
            old = min(candidates, key=lambda n: n["activation"] + n["familiarity"] * .2)
            self.data["nodes"].remove(old)
            if self.data["previous_context"] == old["id"]:
                self.data["previous_context"] = None
            if self.data["attention"] == old["id"]:
                self.data["attention"] = None
            if self.data["gesture"] and self.data["gesture"]["target_id"] == old["id"]:
                self.data["gesture"]["target_id"] = None
            if self.data["motion"]["target_id"] == old["id"]:
                self.data["motion"]["target_id"] = None
            self.data["ethology"]["attention_visits"].pop(old["id"], None)
            self.data["edges"] = [e for e in self.data["edges"]
                                  if old["id"] not in (e["source"], e["target"])]
        node = {"id": node_id, "label": context, "kind": "context",
                "x": float(self.rng.uniform(.12, .88)), "y": float(self.rng.uniform(.12, .88)),
                "activation": 0., "familiarity": 0., "novelty": 1., "seen": 0, "last_seen": now}
        self.data["nodes"].append(node)
        return node

    def _speak(self, topic, affect, now, aspect=None):
        glyphs = [int(topic), int(affect)]
        if aspect is not None:
            glyphs.append(int(aspect))
        self.data["utterance"] = {
            "id": f"u-{self.data['revision'] + 1}", "glyphs": glyphs,
            "text": "·".join(GLYPHS[g]["phoneme"] for g in glyphs), "created_at": now,
        }
        self.data["last_utterance_at"] = now
        self.data["latent"]["symbolic_charge"] *= .15
        self._gesture("signal", now, strength=.45, target_id=self.data["attention"])

    def event(self, event, now):
        d = self.data
        now = max(float(now), d["server_time"])
        observed_at = min(float(event.get("observed_at", now)), now)
        # A replayed offline cue is history, not evidence of present company.
        current = now - observed_at <= 300
        sequence_eligible = current and observed_at >= d["last_model_observed_at"]
        continuous = sequence_eligible and observed_at - d["last_model_observed_at"] <= 300
        kind, context = event["kind"], event["context"]
        node = self._context_node(context, observed_at)
        novelty = self._novelty(node, observed_at)
        token = self.model.bucket(kind, context)
        if sequence_eligible:
            if not continuous:
                self.model.h = np.zeros(self.model.width)
                self.model.before = np.zeros(self.model.width)
                self.model.previous = None
            surprise = self.model.observe(token)
            d["last_model_observed_at"] = observed_at
        else:
            surprise = self.model.prediction_error
        signal = clamp(event["intensity"] * (.16 + .84 * novelty) * (.55 + .45 * surprise))
        strength = signal if current else 0.
        d["last_response"] = strength
        node["seen"] += 1
        node["familiarity"] = node["seen"] / (node["seen"] + 4)
        node["novelty"] = 1 / math.sqrt(1 + node["seen"])
        node["last_seen"] = observed_at if node["seen"] == 1 else max(node["last_seen"], observed_at)
        node["last_bucket"] = token
        node["last_kind"] = kind
        if current:
            node["activation"] = clamp(node["activation"] * .55 + strength)
        base = self._node(kind)
        if base:
            base["activation"] = clamp(base["activation"] + strength * .6)
            base["seen"] += 1
            base["familiarity"] = base["seen"] / (base["seen"] + 4)
            base["novelty"] = 1 / math.sqrt(1 + base["seen"])
            base["last_seen"] = observed_at if base["seen"] == 1 else max(base["last_seen"], observed_at)
            base["last_bucket"] = token
        self._edge(kind, node["id"], .08 + signal * .12)
        if current:
            if continuous:
                self._edge(d["previous_context"], node["id"], .05 + strength * .08)
            if sequence_eligible:
                d["previous_context"] = node["id"]
            self._spread_activation(.5)
        lat = d["latent"]
        probability = strength * (.25 + .65 * novelty + .10 * surprise)
        probability *= .8 + d["traits"]["curiosity"] * .35
        resting = d["behavior"] in ("sleep", "dream")
        if resting and not (kind == "poke" and strength > .55):
            probability *= .12
        if kind == "presence":
            probability *= .35
            if resting and strength < .45:
                probability = 0.
        typing_cue = kind == "activity" and context.casefold() == "typing" and event["source"] == "live"
        typing_eligible = (typing_cue and current and now - observed_at <= 8 and not resting
                           and lat["agitation"] < .5 and event["intensity"] > 0
                           and now - d["ethology"].get("last_imitated_at", -math.inf) >= 45)
        if typing_cue:
            if typing_eligible:
                # An occasional little imitation can survive familiarity while
                # remaining quieter than a novel stimulus. It is grounded only
                # in a fresh aggregate activity cue, never inferred text/caret.
                interest = (clamp(event["intensity"] / .16) * (.05 + .07 * novelty + .06 * surprise)
                            * (.65 + .30 * d["traits"]["curiosity"]))
                probability = max(probability, interest)
            else:
                probability = 0.
        responds = (strength > 0 and (not typing_cue or typing_eligible)
                    and self.rng.random() < probability)
        explicit_drag = current and kind == "drag" and event.get("x") is not None and event.get("y") is not None
        if explicit_drag:
            # Direct manipulation always moves the creature, including a silent
            # zero-intensity placement; it need not wake or seize attention.
            d["position"] = {"x": event["x"], "y": event["y"]}
            responds = strength > 0
        d["last_responded"] = bool(responds)
        d["visible_responses"] += int(responds)
        if responds:
            d["last_attention_at"] = now
            if kind in ("poke", "drag"):
                d["ethology"]["survey_until"] = 0.
            self._attend(node, now, reason="typing" if typing_cue else "cue")
            d["motives"]["exploration"] = clamp(d["motives"]["exploration"] - strength * .1)
            if kind == "presence":
                d["motives"]["affiliation"] = clamp(d["motives"]["affiliation"] - strength * .3)
            lat["curiosity"] = clamp(lat["curiosity"] * (1 - .28 * strength) + novelty * .28 * strength)
            lat["focus"] = clamp(lat["focus"] + strength * .45)
            lat["agitation"] = clamp(lat["agitation"] + strength * (.35 if kind == "poke" else .10))
            lat["sleepiness"] = clamp(lat["sleepiness"] - strength * .04)
            lat["symbolic_charge"] = clamp(lat["symbolic_charge"] + strength * (.06 + novelty * .13))
            if explicit_drag:
                self._behavior("inspect", now)
                self._motion("perch", now, 55, .25, d["attention"])
            elif kind == "poke" and strength > .55:
                self._behavior("startled", now)
            else:
                self._behavior("attend" if strength > .32 else "settle", now)
        # Sparse, systematic topic + affect + aspect; learned surprise and habit
        # influence both the probability and the chosen symbols.
        if responds and now - d["last_utterance_at"] >= 9 and lat["symbolic_charge"] > .5:
            if self.rng.random() < .25 + surprise * .35:
                topics = {"poke": 4, "drag": 4, "git": 3, "activity": 3, "time": 5, "presence": 1, "context": 2}
                affect = 9 if strength > .65 else 8 if novelty > .5 else 10
                self._speak(topics.get(kind, 2), affect, now, 17 if novelty > .7 else 16)
        if responds and typing_eligible:
            self._gesture("imitate", now, strength=.2 + .3 * strength, target_id=d["attention"])
            d["ethology"]["last_imitated_at"] = now
        devices = {item["id"]: item for item in d["devices"]}
        previous_seen = devices.get(event["device_id"], {}).get("last_seen", observed_at)
        devices[event["device_id"]] = {"id": event["device_id"], "last_seen": max(previous_seen, observed_at)}
        d["devices"] = sorted(devices.values(), key=lambda x: x["last_seen"], reverse=True)[:32]
        d["events_seen"] += 1
        d["source_counts"][event["source"]] = d["source_counts"].get(event["source"], 0) + 1
        d["recent_events"].append({key: event[key] for key in ("id", "kind", "context", "device_id", "source")})
        d["recent_events"][-1].update(timestamp=observed_at, observed_at=observed_at,
                                      received_at=float(event.get("received_at", now)), historical=not current,
                                      sequence_eligible=sequence_eligible)
        del d["recent_events"][:-40]
        d["last_event_at"] = max(d["last_event_at"], observed_at)
        d["server_time"] = now
        d["revision"] += 1

    def _revisit(self, now, reason="association"):
        d, policy = self.data, self.data["ethology"]
        cue = self._node(d["attention"]) or self._node(d["previous_context"]) or self._node("self")
        remembered = self._attend(cue, now, reason=reason, revisit=True)
        if remembered and remembered["seen"]:
            remembered["activation"] = clamp(remembered["activation"] + .22)
            policy["revisits"] += 1
            return remembered
        return None

    def _micro_life(self, now):
        """Choose finite movements from physiological context, not render time."""
        d, lat, traits, policy = self.data, self.data["latent"], self.data["traits"], self.data["ethology"]
        sleeping = d["behavior"] in ("sleep", "dream")
        gesture = d["gesture"]
        if gesture and now >= gesture["started_at"] + gesture["duration"]:
            d["gesture"] = None
        if now >= policy["next_revisit_at"]:
            policy["next_revisit_at"] = now + 24 + float(self.rng.uniform(0, 18))
            if not sleeping and lat["agitation"] < .35 and d["motives"]["exploration"] > .25:
                if self._revisit(now):
                    self._gesture("tendril-inspect", now, strength=.3 + .3 * traits["curiosity"], target_id=d["attention"])
                    d["motives"]["exploration"] *= .82
        if d["gesture"] is None and now >= policy["next_gesture_at"]:
            if d["behavior"] == "dream":
                kind = "dream"
            elif sleeping:
                # Sleep has small stretches and curling tendrils, not a frozen
                # face or an unprompted stream of open-eyed reactions.
                kind = self.rng.choice(("sleep", "curl", "stretch"), p=(.60, .30, .10))
            elif lat["sleepiness"] > .55:
                kind = self.rng.choice(("blink", "yawn", "stretch", "tilt"), p=(.35, .30, .20, .15))
            elif d["attention"]:
                kind = self.rng.choice(("blink", "peer", "tilt", "tendril-inspect", "stretch"),
                                       p=(.30, .20, .20, .20, .10))
            else:
                kind = self.rng.choice(("blink", "tilt", "stretch"), p=(.55, .30, .15))
            self._gesture(str(kind), now, strength=.18 + traits["playfulness"] * .35, target_id=d["attention"])
        if now >= policy["next_intent_at"]:
            if sleeping:
                self._motion("rest", now, 80, .12, d["attention"])
            elif lat["agitation"] > .5 or d["motives"]["comfort"] < .3:
                self._motion("perch", now, 55, .18, d["attention"])
            else:
                exploring = d["motives"]["exploration"] > .46 and traits["curiosity"] > traits["caution"] * .7
                self._motion("explore" if exploring else "drift", now,
                             45 + traits["rhythm"] * 38, .2 + traits["curiosity"] * .3, d["attention"])

    def tick(self, now):
        d, lat, policy = self.data, self.data["latent"], self.data["ethology"]
        now = max(float(now), d["server_time"], d["last_tick_at"])
        # Event delivery updates server_time for clients, but must not consume
        # the clock used by physiology. Frequent events cannot stop ageing.
        dt = clamp(now - d["last_tick_at"], 0, 30)
        if dt == 0:
            return
        quiet = now - d["last_attention_at"]
        for node in d["nodes"]:
            node["activation"] *= math.exp(-dt / 25)
            node["novelty"] = self._novelty(node, now)
        self._spread_activation(dt)
        lat["agitation"] *= math.exp(-dt / 18)
        lat["focus"] *= math.exp(-dt / 55)
        lat["sleepiness"] = clamp(lat["sleepiness"] + dt * (-.0006 if d["behavior"] in ("sleep", "dream") else .0015))
        lat["curiosity"] = clamp(lat["curiosity"] + dt * (.0007 if quiet > 15 else -.0001))
        lat["symbolic_charge"] = clamp(lat["symbolic_charge"] + dt * .0015)
        sleeping = d["behavior"] in ("sleep", "dream")
        motives = d["motives"]
        motives["exploration"] = clamp(motives["exploration"] + dt * (
            -.004 if d["behavior"] == "inspect" else .00045 if sleeping else .0012))
        motives["affiliation"] = clamp(motives["affiliation"] + dt * (.00018 if quiet > 30 else -.0003))
        motives["comfort"] = clamp(motives["comfort"] + dt * (.0015 if sleeping else -.0012) - dt * lat["agitation"] * .0005)
        age = now - d["behavior_since"]
        if d["behavior"] == "startled" and age > 1.2:
            self._behavior("settle", now)
        elif d["behavior"] in ("attend", "inspect", "settle") and age > 4 + lat["focus"] * 8:
            self._behavior("idle", now)
        elif d["behavior"] in ("sleep", "dream"):
            if self.model.replay and now - d["last_consolidation_at"] > 12:
                self.model.consolidate()
                d["consolidations"] += 1
                d["last_consolidation_at"] = now
                for edge in d["edges"]:
                    if edge.get("origin") == "learned":
                        edge["weight"] = clamp(edge["weight"] * .999)
            if lat["sleepiness"] < .13:
                self._behavior("settle", now)
            elif d["behavior"] == "dream" and now >= policy["dream_until"]:
                self._behavior("sleep", now)
            elif now >= policy["next_survey_at"] and motives["exploration"] > .42 and age > 35:
                # A short, motive-driven waking survey interrupts long naps.
                # Its deadline ensures that curiosity cannot abolish rest.
                policy["survey_until"] = now + 26 + d["traits"]["curiosity"] * 14
                policy["next_survey_at"] = now + 175 + d["traits"]["rhythm"] * 50
                self._behavior("inspect", now)
                self._gesture("stretch", now, strength=.45, target_id=d["attention"])
                self._motion("explore" if motives["exploration"] > .52 else "drift", now,
                             45 + d["traits"]["rhythm"] * 38, .25, d["attention"])
            elif d["behavior"] == "sleep" and self.model.replay and age > 35 and self.rng.random() < .012 * dt:
                remembered = self._revisit(now, reason="dream")
                if remembered:
                    policy["dream_until"] = now + 8 + d["traits"]["rhythm"] * 7
                    self._behavior("dream", now)
                    if now - d["last_utterance_at"] > 70 and lat["symbolic_charge"] > .65:
                        self._speak(15, 10, now, 6)
        elif policy["survey_until"] and now >= policy["survey_until"]:
            policy["survey_until"] = 0.
            self._behavior("sleep", now)
        elif not policy["survey_until"] and quiet > 35 and lat["sleepiness"] > .35 and self.rng.random() < .045 * dt:
            self._behavior("sleep", now)
            self._gesture("yawn", now, strength=.4)
        elif d["behavior"] == "idle" and quiet > 14 and age > 7 and self.rng.random() < (.015 + motives["exploration"] * .03) * dt:
            self._behavior("inspect", now)
            self._revisit(now)
            d["position"]["x"] = clamp(d["position"]["x"] + float(self.rng.normal(0, .035)), .06, .94)
        if dt > 0:
            self._micro_life(now)
        if d["utterance"] and now - d["utterance"]["created_at"] > 8:
            d["utterance"] = None
        d["server_time"] = now
        d["last_tick_at"] = now
        d["revision"] += 1

    def state(self):
        d = deepcopy(self.data)
        for name in ("events_seen", "last_event_at", "last_utterance_at", "last_consolidation_at",
                     "last_tick_at", "last_attention_at", "last_model_observed_at", "previous_context", "last_response", "last_responded", "visible_responses", "consolidations"):
            d.pop(name, None)
        for node in d["nodes"]:
            node.pop("seen", None)
            node.pop("last_seen", None)
        d["learning"] = {"events_seen": self.data["events_seen"], "updates": self.model.updates,
                         "loss": self.model.loss, "prediction_error": self.model.prediction_error,
                         "model": "online-rnn-v1", "initialized": "random"}
        d["attention_detail"] = {"reason": d["ethology"]["attention_reason"],
                                 "linger_until": d["ethology"]["linger_until"],
                                 "revisits": d["ethology"]["revisits"]}
        d.pop("ethology", None)
        return d

    def inspect(self):
        return {"learning": self.state()["learning"], "last_response": self.data["last_response"],
                "last_responded": self.data["last_responded"], "visible_responses": self.data["visible_responses"],
                "consolidations": self.data["consolidations"], "nodes": len(self.data["nodes"]),
                "edges": len(self.data["edges"]), "hidden_norm": float(np.linalg.norm(self.model.h)),
                "weight_norm": float(np.linalg.norm(self.model.wx)),
                "top_predictions": [{"bucket": int(i), "probability": float(self.model.probabilities()[i])}
                                    for i in np.argsort(self.model.probabilities())[-5:][::-1]],
                "language": {"invented": True, "grammar": "topic + affect + optional aspect", "glyphs": GLYPHS}}
