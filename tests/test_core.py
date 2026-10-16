import json

import numpy as np
import pytest

from terminus.core import Organism
from terminus.store import Store


def stimulus(index, context="editor", kind="context", **extra):
    return {"id": f"e-{index}", "kind": kind, "device_id": "test-device",
            "context": context, "intensity": .9, "source": "synthetic", **extra}


def test_prediction_learning_habituation_and_fresh_response():
    creature = Organism(now=0)
    initial_weights = creature.model.wx.copy()
    creature.event(stimulus(0), 1)
    first_response = creature.data["last_response"]
    creature.event(stimulus(1), 2)
    first_loss = creature.model.loss
    for i in range(2, 260):
        creature.event(stimulus(i), i + 1)
    familiar_response = creature.data["last_response"]
    node = next(n for n in creature.data["nodes"] if n["label"] == "editor")
    assert creature.model.updates == 259
    assert creature.model.loss < first_loss * .2
    assert not np.array_equal(initial_weights, creature.model.wx)
    assert node["familiarity"] > .98
    assert familiar_response < first_response * .3
    creature.event(stimulus(261, context="new place"), 270)
    assert creature.data["last_response"] > familiar_response * 3
    assert creature.state()["learning"]["initialized"] == "random"


def test_serialized_model_rng_and_latent_continue_identically():
    creature = Organism(seed=123, now=1)
    for i in range(30):
        creature.event(stimulus(i, context=f"context {i % 3}"), i * 3 + 2)
        creature.tick(i * 3 + 3)
    restored = Organism(saved=json.loads(json.dumps(creature.dump())))
    assert creature.dump() == restored.dump()
    for i in range(30, 50):
        for instance in (creature, restored):
            instance.event(stimulus(i, kind="poke"), i * 3 + 2)
            instance.tick(i * 3 + 3)
    assert creature.dump() == restored.dump()


def test_snapshot_is_independent_of_future_replay_and_weight_updates():
    creature = Organism(now=0)
    creature.event(stimulus(1), 1)
    backup = creature.dump()
    frozen = json.loads(json.dumps(backup))
    creature.event(stimulus(2), 2)
    creature.event(stimulus(3), 3)
    assert len(creature.model.replay) == 2
    assert backup == frozen
    restored = Organism(saved=backup)
    assert restored.dump() == frozen


def test_events_do_not_consume_physiology_elapsed_time():
    quiet = Organism(seed=12, now=0)
    busy = Organism(seed=12, now=0)
    for i in range(1, 10):
        busy.event(stimulus(i, intensity=0), i / 10)
    quiet.tick(1)
    busy.tick(1)
    assert busy.data["latent"]["sleepiness"] == pytest.approx(quiet.data["latent"]["sleepiness"])
    assert busy.data["last_tick_at"] == 1
    restored = Organism(saved=busy.dump())
    restored.event(stimulus(10, intensity=0), 1.9)
    restored.tick(2)
    quiet.tick(2)
    assert restored.data["latent"]["sleepiness"] == pytest.approx(quiet.data["latent"]["sleepiness"])


def test_balanced_alternating_events_learn_sequence_instead_of_frequency():
    creature = Organism(seed=123, now=0)
    work = creature.model.bucket("context", "work")
    rest = creature.model.bucket("context", "break")
    assert work != rest
    for index in range(600):
        creature.model.observe(work if index % 2 == 0 else rest)
    after_rest = creature.model.probabilities()
    creature.model.observe(work)
    after_work = creature.model.probabilities()
    # Equal observed frequencies cannot explain these opposite predictions.
    assert after_rest[work] > .95
    assert after_work[rest] > .95
    assert after_rest[rest] < .05
    assert after_work[work] < .05


def test_sleep_replays_only_experienced_events():
    creature = Organism(now=1)
    creature.event(stimulus(1), 2)
    creature.event(stimulus(2), 3)
    creature.data["latent"]["sleepiness"] = .9
    creature.data["behavior"] = "sleep"
    before = creature.model.updates
    hidden = creature.model.h.copy()
    creature.tick(20)
    assert creature.data["consolidations"] == 1
    assert creature.model.updates == before + 1
    assert np.array_equal(creature.model.h, hidden)
    assert creature.data["latent"]["sleepiness"] < .9


def test_associations_and_memory_remain_bounded():
    creature = Organism(now=0)
    for i in range(350):
        creature.event(stimulus(i, context=f"place {i}"), i + 1)
    assert 20 <= len(creature.data["nodes"]) <= 72
    assert len(creature.data["edges"]) <= 320
    assert len(creature.data["recent_events"]) == 40
    node_ids = {n["id"] for n in creature.data["nodes"]}
    assert all(e["source"] in node_ids and e["target"] in node_ids for e in creature.data["edges"])


def test_intrinsic_scaffold_propagates_activation_without_fake_experience():
    creature = Organism(now=0)
    assert len(creature.data["edges"]) == 23
    assert all(e["origin"] == "scaffold" for e in creature.data["edges"])
    assert creature.data["events_seen"] == creature.model.updates == 0
    for node in creature.data["nodes"]:
        node["activation"] = 1. if node["id"] == "self" else 0.
    creature.tick(1)
    assert creature._node("poke")["activation"] > 0
    assert creature._node("presence")["activation"] > 0
    # A connected, activated association can win attention over the source.
    creature._node("presence")["activation"] = 1.
    creature._node("self")["activation"] = 0.
    creature._attend(creature._node("self"))
    assert creature.data["attention"] == "presence"
    assert all(n["seen"] == 0 for n in creature.data["nodes"])


def test_legacy_snapshot_migrates_scaffold_once_without_lost_state():
    creature = Organism(seed=55, now=0)
    creature.event(stimulus(1), 1)
    old = creature.dump()
    old["data"].pop("schema_version")
    old["data"]["edges"] = [e for e in old["data"]["edges"] if e["origin"] == "learned"]
    for edge in old["data"]["edges"]:
        edge.pop("origin")
    restored = Organism(saved=old)
    assert restored.data["schema_version"] == 2
    assert restored.model.dump() == old["model"]
    for name in ("nodes", "organism_id", "revision", "latent", "devices", "events_seen", "recent_events"):
        assert restored.data[name] == old["data"][name]
    assert sum(e["origin"] == "scaffold" for e in restored.data["edges"]) == 23
    assert any(e["origin"] == "learned" for e in restored.data["edges"])
    assert Organism(saved=restored.dump()).dump() == restored.dump()


def test_zero_intensity_learns_without_forcing_visible_policy_and_drag_still_places():
    creature = Organism(seed=81, now=0)
    creature.data["attention"] = "self"
    original_behavior = creature.data["behavior"]
    original_latent = creature.data["latent"].copy()
    for i, kind in enumerate(("presence", "context", "poke", "activity", "git", "time", "drag")):
        creature.event(stimulus(i, kind=kind, intensity=0, x=.2, y=.8), i + 1)
        assert creature.data["behavior"] == original_behavior
        assert creature.data["attention"] == "self"
        assert creature.data["latent"] == original_latent
        assert creature.data["last_responded"] is False
    assert creature.model.updates == 6
    assert creature.data["events_seen"] == 7
    assert creature.data["position"] == {"x": .2, "y": .8}


def test_quiet_baseline_is_rest_dominant_over_1000_seconds():
    creature = Organism(seed=814, now=0)
    resting = 0
    for second in range(1, 1001):
        creature.tick(second)
        resting += creature.data["behavior"] in ("sleep", "dream")
    assert resting / 1000 > .75


def test_habituated_presence_is_often_ignored_while_learning_continues():
    creature = Organism(seed=19, now=0)
    for i in range(100):
        creature.event(stimulus(i, kind="presence", intensity=.15), i + 1)
    assert creature.data["visible_responses"] < 10
    assert creature.model.updates == 99
    assert creature.data["events_seen"] == 100


def test_quiet_presence_never_wakes_or_prevents_returning_to_rest():
    creature = Organism(seed=814, now=0)
    resting = 0
    for second in range(1, 2001):
        # Even fresh but low-salience presence labels cannot wake a sleeper.
        if second % 10 == 0:
            was_resting = creature.data["behavior"] in ("sleep", "dream")
            creature.event(stimulus(second, kind="presence", context=f"presence {second}", intensity=.05), second)
            if was_resting:
                assert creature.data["behavior"] in ("sleep", "dream")
                assert creature.data["last_responded"] is False
        creature.tick(second)
        resting += creature.data["behavior"] in ("sleep", "dream")
    assert resting / 2000 > .7


def test_sqlite_retention_restart_and_single_writer(tmp_path):
    store = Store(tmp_path, now=1)
    store.history_limit, store.dedup_limit = 12, 24
    token = store.token
    for i in range(60):
        event = stimulus(i)
        store.organism.event(event, i + 2)
        store.save(event)
    assert store.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 12
    assert store.db.execute("SELECT COUNT(*) FROM dedup").fetchone()[0] == 24
    assert store.contains("e-59") and not store.contains("e-0")
    assert (tmp_path / "token").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "organism.sqlite3").stat().st_mode & 0o777 == 0o600
    with pytest.raises(RuntimeError, match="running Terminus"):
        Store(tmp_path, now=99)
    snapshot = store.organism.dump()
    store.close()
    restarted = Store(tmp_path, now=999)
    assert restarted.token == token
    assert restarted.organism.dump() == snapshot
    assert restarted.contains("e-59")
    restarted.close()
