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
    assert restored.data["schema_version"] == 3
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


def test_ethology_migration_preserves_identity_graph_model_and_random_stream():
    creature = Organism(seed=61, now=0)
    for i in range(12):
        creature.event(stimulus(i, context=f"place {i % 3}"), i + 1)
    legacy = creature.dump()
    for field in ("traits", "motives", "gesture", "motion", "ethology", "last_model_observed_at", "source_counts"):
        legacy["data"].pop(field)
    legacy["data"]["schema_version"] = 2
    restored = Organism(saved=legacy)
    assert restored.dump()["rng"] == legacy["rng"]
    assert restored.model.dump() == legacy["model"]
    for field in ("organism_id", "nodes", "edges", "latent", "recent_events", "devices", "events_seen"):
        assert restored.data[field] == legacy["data"][field]
    assert all(.2 <= trait <= .8 for trait in restored.data["traits"].values())
    assert Organism(saved=legacy).dump() == restored.dump()
    assert Organism(saved=restored.dump()).dump() == restored.dump()


def test_familiar_cues_recover_response_after_absence_without_losing_history():
    creature = Organism(seed=19, now=0)
    for i in range(240):
        creature.event(stimulus(i), i + 1)
    immediate, absent = Organism(saved=creature.dump()), Organism(saved=creature.dump())
    immediate.event(stimulus(241), 241)
    absent.event(stimulus(241), 2040)
    # The larger gap also clears the live prediction context, so isolate the
    # independent time-based habituation recovery directly as well.
    node = creature._context_node("editor", 240)
    assert creature._novelty(node, 2040) > creature._novelty(node, 241) * 5
    assert absent.data["last_response"] > immediate.data["last_response"] * 2
    assert absent._context_node("editor", 2040)["seen"] == 241
    assert absent._context_node("editor", 2040)["familiarity"] > .98


def test_attention_uses_learned_associations_and_lingers_on_weak_cues():
    creature = Organism(seed=15, now=0)
    cue = creature._context_node("cue", 0)
    linked = creature._context_node("learned companion", 0)
    unlinked = creature._context_node("equally familiar", 0)
    for node in (cue, linked, unlinked):
        node.update(seen=8, familiarity=2 / 3, novelty=1 / 3, activation=0)
    creature._edge(cue["id"], linked["id"], .95)
    control = Organism(saved=creature.dump())
    control.data["edges"] = [e for e in control.data["edges"] if e.get("origin") != "learned"]
    choices, negatives = [], []
    for index in range(80):
        now = index * 60
        choices.append(creature._attend(cue, now, revisit=True)["id"])
        negatives.append(control._attend(control._node(cue["id"]), now, revisit=True)["id"])
    assert choices.count(linked["id"]) > 70
    assert 15 < negatives.count(linked["id"]) < 65
    creature.data["attention"] = linked["id"]
    creature.data["ethology"]["linger_until"] = 6000
    creature._attend(unlinked, 5000)
    assert creature.data["attention"] == linked["id"]


def test_learned_next_event_prediction_changes_attention_with_equal_counts():
    creature = Organism(seed=123, now=0)
    work = creature._context_node("work", 0)
    rest = creature._context_node("break", 0)
    for node, context in ((work, "work"), (rest, "break")):
        node.update(seen=300, familiarity=.98, activation=0,
                    last_bucket=creature.model.bucket("context", context))
    for index in range(600):
        creature.model.observe(work["last_bucket"] if index % 2 == 0 else rest["last_bucket"])
    cue = creature._node("self")
    scores = {node["id"]: score for node, score in creature._attention_scores(cue, 0, revisit=True)}
    assert scores[work["id"]] > scores[rest["id"]] + .7
    creature.model.observe(work["last_bucket"])
    changed = {node["id"]: score for node, score in creature._attention_scores(cue, 0, revisit=True)}
    assert changed[rest["id"]] > changed[work["id"]] + .7
    assert work["seen"] == rest["seen"] == 300


def test_historical_cues_do_not_claim_current_presence_or_wake_or_drag():
    creature = Organism(seed=77, now=1000)
    before = creature.dump()
    for kind in ("presence", "poke", "drag"):
        creature.event(stimulus(kind, kind=kind, observed_at=10, received_at=1000,
                                intensity=1, x=.1, y=.9), 1000)
        assert creature.data["last_responded"] is False
    for field in ("behavior", "attention", "latent", "motives", "position", "gesture", "motion", "last_attention_at"):
        assert creature.data[field] == before["data"][field]
    assert creature.model.dump() == before["model"]
    assert creature.data["devices"] == [{"id": "test-device", "last_seen": 10}]
    assert creature.data["events_seen"] == 3
    assert all(e["historical"] and e["timestamp"] == 10 and e["received_at"] == 1000
               for e in creature.data["recent_events"])
    assert creature._node("poke")["last_seen"] == 10
    assert creature._node("poke")["activation"] == before["data"]["nodes"][4]["activation"]


def test_discontinuous_observations_do_not_teach_a_false_transition():
    creature = Organism(now=0)
    creature.event(stimulus(0, context="yesterday"), 1)
    yesterday = creature.data["previous_context"]
    creature.event(stimulus(1, context="today"), 2000)
    today = creature.data["previous_context"]
    assert creature.model.updates == 0
    assert creature.model.replay == []
    assert not any({edge["source"], edge["target"]} == {yesterday, today}
                   for edge in creature.data["edges"])
    creature.event(stimulus(2, context="offline", observed_at=1999), 2001)
    assert creature.model.updates == 0  # Recent reordered cues cannot teach sequence.
    creature.event(stimulus(3, context="now"), 2002)
    assert creature.model.updates == 1
    assert len(creature.model.replay) == 1
    assert any({edge["source"], edge["target"]} == {today, creature.data["previous_context"]}
               for edge in creature.data["edges"])


def test_recent_reordered_drag_places_without_corrupting_live_sequence_or_recency():
    creature = Organism(now=0)
    creature.event(stimulus(0, kind="presence", intensity=0, observed_at=100), 100)
    before_model = creature.model.dump()
    before_context = creature.data["previous_context"]
    before_latent = creature.data["latent"].copy()
    # Another device's slightly slow clock must not drop a current direct
    # manipulation. Zero intensity places silently, just as an ordered drag.
    creature.event(stimulus(1, context="pointer", kind="drag", intensity=0,
                            observed_at=99, x=.2, y=.8), 101)
    assert creature.data["position"] == {"x": .2, "y": .8}
    assert creature.data["latent"] == before_latent
    assert creature.data["last_responded"] is False
    creature.event(stimulus(2, context="pointer", kind="drag", intensity=1,
                            observed_at=98, x=.3, y=.7), 102)
    assert creature.data["position"] == {"x": .3, "y": .7}
    assert creature.data["last_responded"] is True
    assert creature.data["behavior"] == "inspect"
    assert creature.model.dump() == before_model
    assert creature.data["previous_context"] == before_context
    assert creature.data["last_model_observed_at"] == 100
    assert creature.data["devices"] == [{"id": "test-device", "last_seen": 100}]
    assert creature._context_node("pointer", 102)["last_seen"] == 99
    assert creature.data["recent_events"][-1]["historical"] is False
    assert creature.data["recent_events"][-1]["sequence_eligible"] is False
    assert not any({edge["source"], edge["target"]} == {
        before_context, creature._context_node("pointer", 102)["id"]} for edge in creature.data["edges"])


def test_real_typing_imitation_is_modest_habituating_and_not_a_generic_activity_skin():
    fresh = Organism(seed=19, now=0)
    fresh.data["behavior"] = "idle"
    fresh._context_node("typing", 0)
    familiar = Organism(saved=fresh.dump())
    for index in range(300):
        familiar.event(stimulus(index, kind="activity", context="typing", source="live", intensity=0), index + 1)
    fresh_count = familiar_count = 0
    for seed in range(200):
        for template, label in ((fresh, "fresh"), (familiar, "familiar")):
            instance = Organism(saved=template.dump())
            instance.rng = np.random.default_rng(seed)
            instance.event(stimulus(seed, kind="activity", context="typing", source="live", intensity=.16), 401)
            imitates = instance.data["gesture"] and instance.data["gesture"]["kind"] == "imitate"
            if label == "fresh":
                fresh_count += bool(imitates)
            else:
                familiar_count += bool(imitates)
            assert instance.data["events_seen"] == template.data["events_seen"] + 1
    assert 10 < fresh_count < 60
    assert 1 < familiar_count < fresh_count * .7
    for source, context in (("manual", "typing"), ("synthetic", "typing"), ("live", "making")):
        for seed in range(30):
            instance = Organism(seed=seed, now=0)
            instance.data["behavior"] = "idle"
            instance.event(stimulus(seed, kind="activity", context=context, source=source, intensity=.16), 1)
            assert not instance.data["gesture"] or instance.data["gesture"]["kind"] != "imitate"


def test_background_typing_never_wakes_sleep_or_claims_stale_or_silent_activity():
    creature = Organism(now=0)
    quiet_attention = creature.data["last_attention_at"]
    quiet_latent = creature.data["latent"].copy()
    for index in range(200):
        creature.event(stimulus(index, kind="activity", context="typing", source="live", intensity=.16), index + 1)
        assert creature.data["behavior"] == "sleep"
        assert creature.data["gesture"] is None
        assert creature.data["last_responded"] is False
    assert creature.data["latent"] == quiet_latent
    assert creature.data["last_attention_at"] == quiet_attention
    assert creature.model.updates == 199
    creature.data["behavior"] = "idle"
    for observed_at, intensity in ((200, .16), (499, 0)):
        creature.event(stimulus(observed_at, kind="activity", context="typing", source="live",
                                observed_at=observed_at, intensity=intensity), 500)
        assert creature.data["gesture"] is None
        assert creature.data["last_responded"] is False


def test_typing_gesture_is_finite_with_persisted_cooldown_and_exact_continuation():
    for seed in range(100):
        creature = Organism(seed=seed, now=0)
        creature.data["behavior"] = "idle"
        creature.event(stimulus(seed, kind="activity", context="typing", source="live", intensity=.16), 1)
        if creature.data["gesture"] and creature.data["gesture"]["kind"] == "imitate":
            break
    else:
        pytest.fail("No awake creature responded to the controlled typing cue")
    gesture = creature.data["gesture"].copy()
    assert gesture["duration"] == 6
    assert creature.data["ethology"]["last_imitated_at"] == 1
    restored = Organism(saved=json.loads(json.dumps(creature.dump())))
    before_rng = creature.dump()["rng"]
    for instance in (creature, restored):
        instance.event(stimulus("cooldown", kind="activity", context="typing", source="live", intensity=.16), 2)
        assert instance.data["last_responded"] is False
        assert instance.data["gesture"] == gesture
        assert instance.dump()["rng"] == before_rng
        instance.tick(8)
        assert instance.data["gesture"] is None
    assert creature.dump() == restored.dump()


def test_two_thousand_seconds_have_micro_life_and_rest_with_exact_continuation():
    creature = Organism(seed=814, now=0)
    restored = None
    gestures, intents, behaviors = {}, set(), []
    for now in range(1, 2001):
        creature.tick(now)
        if now == 1000:
            restored = Organism(saved=json.loads(json.dumps(creature.dump())))
        elif now > 1000:
            restored.tick(now)
        gesture = creature.data["gesture"]
        if gesture:
            gestures[gesture["id"]] = gesture["kind"]
            assert gesture["started_at"] <= now < gesture["started_at"] + gesture["duration"]
            assert 0 <= gesture["strength"] <= 1
        intents.add(creature.data["motion"]["intent"])
        behaviors.append(creature.data["behavior"])
        assert all(0 <= value <= 1 for value in creature.data["motives"].values())
    assert creature.dump() == restored.dump()
    assert sum(name in ("sleep", "dream") for name in behaviors) / 2000 > .75
    assert len(gestures) > 90
    assert {"curl", "stretch", "blink", "peer", "tilt"} <= set(gestures.values())
    assert {"rest", "drift", "explore"} <= intents
    assert creature.data["events_seen"] == creature.model.updates == creature.data["consolidations"] == 0
    assert creature.data["utterance"] is None
    assert creature.data["ethology"]["revisits"] == 0
    # A stopped or backwards clock is not a source of new random actions.
    final = creature.dump()
    creature.tick(2000)
    creature.tick(1999)
    assert creature.dump() == final


def test_dreams_and_consolidation_use_experienced_memories_only():
    creature = Organism(seed=814, now=0)
    for i in range(20):
        creature.event(stimulus(i, context=("making" if i % 2 else "resting"), intensity=0), i + 1)
    live_hidden = creature.model.h.copy()
    replays_before = len(creature.model.replay)
    dreaming = set()
    for now in range(21, 801):
        creature.tick(now)
        if creature.data["behavior"] == "dream":
            dreaming.add(creature.data["attention"])
            assert creature._node(creature.data["attention"])["seen"] > 0
    assert dreaming
    assert creature.data["consolidations"] > 20
    assert len(creature.model.replay) == replays_before
    assert creature.data["events_seen"] == 20
    assert np.array_equal(creature.model.h, live_hidden)


def test_slow_motives_causally_gate_waking_surveys_and_motion():
    curious = Organism(seed=814, now=0)
    curious.data["ethology"]["next_survey_at"] = 1
    curious.data["motives"]["exploration"] = .8
    content = Organism(saved=curious.dump())
    content.data["motives"]["exploration"] = .05
    for now in range(1, 41):
        curious.tick(now)
        content.tick(now)
    assert curious.data["behavior"] == "inspect"
    assert curious.data["motion"]["intent"] == "explore"
    assert content.data["behavior"] == "sleep"
    assert content.data["motion"]["intent"] == "rest"
    # Survey deadlines bring an intrigued organism back to rest.
    for now in range(41, 90):
        curious.tick(now)
    assert curious.data["behavior"] == "sleep"


def test_offline_history_at_capacity_does_not_evict_current_attention():
    creature = Organism(now=1000)
    for i in range(50):
        creature._context_node(f"past {i}", 1)
    attention = creature._context_node("past 0", 1)
    creature.data["attention"] = attention["id"]
    creature.data["previous_context"] = attention["id"]
    creature.data["motion"]["target_id"] = attention["id"]
    for i in range(70):
        creature.event(stimulus(i, context=f"offline {i}", observed_at=10, received_at=1000), 1000)
    assert creature.data["attention"] == attention["id"]
    assert creature.data["previous_context"] == attention["id"]
    assert creature.data["motion"]["target_id"] == attention["id"]
    assert creature._node(attention["id"]) is not None


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
