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
        self.data["schema_version"] = 2
        self.data.setdefault("last_responded", False)
        self.data.setdefault("visible_responses", 0)
        self.data.setdefault("last_attention_at", self.data["last_event_at"])
        self._bound_edges()

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

    def _attend(self, context_node):
        candidates = {context_node["id"]}
        for edge in self.data["edges"]:
            if context_node["id"] in (edge["source"], edge["target"]):
                candidates.update((edge["source"], edge["target"]))
        candidates = [node for node in self.data["nodes"] if node["id"] in candidates]
        self.data["attention"] = max(candidates, key=lambda n: n["activation"] +
                                     .12 * n["novelty"] + float(self.rng.uniform(0, .08)))["id"]

    def dump(self):
        return {"rng": self.rng.bit_generator.state, "model": self.model.dump(),
                "data": deepcopy(self.data)}

    def _behavior(self, name, now):
        if self.data["behavior"] != name:
            self.data["behavior"] = name
            self.data["behavior_since"] = now

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
            old = min(candidates, key=lambda n: n["activation"] + n["familiarity"] * .2)
            self.data["nodes"].remove(old)
            if self.data["previous_context"] == old["id"]:
                self.data["previous_context"] = None
            if self.data["attention"] == old["id"]:
                self.data["attention"] = None
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

    def event(self, event, now):
        d = self.data
        kind, context = event["kind"], event["context"]
        node = self._context_node(context, now)
        novelty = 1 / math.sqrt(1 + node["seen"])
        surprise = self.model.observe(self.model.bucket(kind, context))
        strength = clamp(event["intensity"] * (.16 + .84 * novelty) * (.55 + .45 * surprise))
        d["last_response"] = strength
        node["seen"] += 1
        node["familiarity"] = node["seen"] / (node["seen"] + 4)
        node["novelty"] = 1 / math.sqrt(1 + node["seen"])
        node["last_seen"] = now
        node["activation"] = clamp(node["activation"] * .55 + strength)
        base = self._node(kind)
        if base:
            base["activation"] = clamp(base["activation"] + strength * .6)
            base["seen"] += 1
            base["familiarity"] = base["seen"] / (base["seen"] + 4)
            base["novelty"] = 1 / math.sqrt(1 + base["seen"])
        self._edge(kind, node["id"], .08 + strength * .12)
        self._edge(d["previous_context"], node["id"], .05 + strength * .08)
        d["previous_context"] = node["id"]
        self._spread_activation(.5)
        lat = d["latent"]
        probability = strength * (.25 + .65 * novelty + .10 * surprise)
        resting = d["behavior"] in ("sleep", "dream")
        if resting and not (kind == "poke" and strength > .55):
            probability *= .12
        if kind == "presence":
            probability *= .35
            if resting and strength < .45:
                probability = 0.
        responds = strength > 0 and self.rng.random() < probability
        explicit_drag = kind == "drag" and event.get("x") is not None and event.get("y") is not None
        if explicit_drag:
            # Direct manipulation always moves the creature, including a silent
            # zero-intensity placement; it need not wake or seize attention.
            d["position"] = {"x": event["x"], "y": event["y"]}
            responds = strength > 0
        d["last_responded"] = bool(responds)
        d["visible_responses"] += int(responds)
        if responds:
            d["last_attention_at"] = now
            self._attend(node)
            lat["curiosity"] = clamp(lat["curiosity"] * (1 - .28 * strength) + novelty * .28 * strength)
            lat["focus"] = clamp(lat["focus"] + strength * .45)
            lat["agitation"] = clamp(lat["agitation"] + strength * (.35 if kind == "poke" else .10))
            lat["sleepiness"] = clamp(lat["sleepiness"] - strength * .04)
            lat["symbolic_charge"] = clamp(lat["symbolic_charge"] + strength * (.06 + novelty * .13))
            if explicit_drag:
                self._behavior("inspect", now)
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
                self._speak(topics[kind], affect, now, 17 if novelty > .7 else 16)
        devices = {item["id"]: item for item in d["devices"]}
        devices[event["device_id"]] = {"id": event["device_id"], "last_seen": now}
        d["devices"] = sorted(devices.values(), key=lambda x: x["last_seen"], reverse=True)[:32]
        d["events_seen"] += 1
        d["recent_events"].append({key: event[key] for key in ("id", "kind", "context", "device_id", "source")})
        d["recent_events"][-1]["timestamp"] = now
        del d["recent_events"][:-40]
        d["last_event_at"] = now
        d["server_time"] = now
        d["revision"] += 1

    def tick(self, now):
        d, lat = self.data, self.data["latent"]
        # Event delivery updates server_time for clients, but must not consume
        # the clock used by physiology. Frequent events cannot stop ageing.
        dt = clamp(now - d["last_tick_at"], 0, 30)
        quiet = now - d["last_attention_at"]
        for node in d["nodes"]:
            node["activation"] *= math.exp(-dt / 25)
        self._spread_activation(dt)
        lat["agitation"] *= math.exp(-dt / 18)
        lat["focus"] *= math.exp(-dt / 55)
        lat["sleepiness"] = clamp(lat["sleepiness"] + dt * (-.0006 if d["behavior"] in ("sleep", "dream") else .0015))
        lat["curiosity"] = clamp(lat["curiosity"] + dt * (.0007 if quiet > 15 else -.0001))
        lat["symbolic_charge"] = clamp(lat["symbolic_charge"] + dt * .0015)
        age = now - d["behavior_since"]
        if d["behavior"] == "startled" and age > 1.2:
            self._behavior("settle", now)
        elif d["behavior"] in ("attend", "inspect", "settle") and age > 4 + lat["focus"] * 8:
            self._behavior("idle", now)
        elif d["behavior"] in ("sleep", "dream"):
            if now - d["last_consolidation_at"] > 12:
                self.model.consolidate()
                d["consolidations"] += 1
                d["last_consolidation_at"] = now
                for edge in d["edges"]:
                    edge["weight"] = clamp(edge["weight"] * .999)
            if lat["sleepiness"] < .13:
                self._behavior("settle", now)
            elif age > 10 and self.rng.random() < .04 * dt:
                self._behavior("dream" if d["behavior"] == "sleep" else "sleep", now)
                if d["behavior"] == "dream":
                    known = [n for n in d["nodes"] if n["seen"]]
                    if known:
                        remembered = known[int(self.rng.integers(len(known)))]
                        d["attention"] = remembered["id"]
                        remembered["activation"] = .5
                    if now - d["last_utterance_at"] > 35:
                        self._speak(15, 10, now, 6)
        elif quiet > 35 and lat["sleepiness"] > .35 and self.rng.random() < .045 * dt:
            self._behavior("sleep", now)
        elif d["behavior"] == "idle" and quiet > 14 and age > 7 and self.rng.random() < .035 * dt:
            self._behavior("inspect", now)
            active = max(d["nodes"], key=lambda n: n["activation"] + .15 * n["novelty"])
            d["attention"] = active["id"]
            d["position"]["x"] = clamp(d["position"]["x"] + float(self.rng.normal(0, .035)), .06, .94)
        if d["utterance"] and now - d["utterance"]["created_at"] > 8:
            d["utterance"] = None
        d["server_time"] = now
        d["last_tick_at"] = now
        d["revision"] += 1

    def state(self):
        d = deepcopy(self.data)
        for name in ("events_seen", "last_event_at", "last_utterance_at", "last_consolidation_at",
                     "last_tick_at", "last_attention_at", "previous_context", "last_response", "last_responded", "visible_responses", "consolidations"):
            d.pop(name, None)
        for node in d["nodes"]:
            node.pop("seen", None)
            node.pop("last_seen", None)
        d["learning"] = {"events_seen": self.data["events_seen"], "updates": self.model.updates,
                         "loss": self.model.loss, "prediction_error": self.model.prediction_error,
                         "model": "online-rnn-v1", "initialized": "random"}
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
