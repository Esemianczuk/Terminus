# Collective memory

A computer keeps its own SQLite organism, context graph and 64-bucket private predictor. Collective exchange is opt-in and uses a second predictor with seven fixed input classes and 24 hidden units. Its 943 trainable parameters form a shared prior for broad event rhythms.

Only the event's category enters this learner. The exporter reads locally acknowledged event records but ignores every context, identifier, timestamp, device field and intensity. Synthetic test activity is excluded. Private context embeddings, hidden states, replay samples and model weights are never exported. The public learner has its own hidden state and replay, containing category indices only, and keeps those files local as well.

## Contributions

After at least 32 new category observations, a learner can release a parameter delta since its previous release. The delta has an L2 budget below 1 and values quantized to 1/4096. Sample counts are bucketed in steps of 32 and capped at 512. The public JSON contains exactly these fields:

- `schema`: fixed format version.
- `base`: SHA-256 digest of the bank used by the learner.
- `sample_bin`: coarse cohort size.
- `delta`: five numeric arrays with registered shapes.
- `id`: digest of the contribution.

No free-form text, names, device identifiers or event records are accepted. This prevents content from entering through the standard client; it is not a claim of formal differential privacy or resistance to every model-inference attack. Shared weights can reflect broad activity patterns. A malicious writer could also try to encode information in arbitrary numbers, so contributions still pass through repository permissions and review.

Maintainership is separate from participation. Anyone can clone, learn and export. A GitHub account with write access can publish through `gh`; other users submit their validated JSON as `community/contributions/<id>.json` in a pull request. No shared write token is bundled with Terminus. GitHub's commit/account metadata remains public.

## Bank updates

The `Collective memory` workflow processes contributions on the main branch. A concurrency group permits one updater at a time. It validates types, shapes, finite values, hashes and update budgets before merging. A round takes a 0.2 step toward a bounded weighted aggregate. Old-base contributions have one tenth of the normal influence, allowing offline learners to return without blocking other updates.

The workflow commits the new bank and removes processed input files in one Git commit. Applied digests make recent retries idempotent. Compare-and-push retries preserve concurrent submissions. Invalid contributions fail validation rather than execute code. Repository write access and pull-request review are the trust boundary; clipping limits damage but is not a complete defense against poisoning or coordinated submissions.

The initial bank is an explicitly untrained seeded model. Round and contribution counters show whether actual updates have been applied. They count updates, not unique people or devices.

## Local behavior

Every exchange fetches the public bank over HTTPS, falling back to the last valid cached copy when offline. A bounded local rebase preserves unreleased training. The local category predictor writes a seven-value prior that the core reads periodically. That prior adds at most 0.1 to an attention candidate's score. The private contextual predictor, associations, identity and learned history remain independent.

Use `scripts/collective.py status` to inspect bank round, local category observations and pending updates. `disable` stops exchange at the configuration gate. Local learning and the creature's ordinary services continue.

## Paired machines

One publisher can use several existing SSH aliases to relay validated numeric outboxes through a machine with GitHub publishing access. The relay retrieves only the fixed public contribution format. It never copies another machine's SQLite database, token, contexts or private model. A peer drops exported outbox entries after it observes their digests in the public bank. Direct peer connectivity is optional; each machine can pull the bank independently on any network and keep training offline.

Runtime configuration lives under `.local/`. Host aliases, paths and credentials are not committed. SSH host-key checks remain enabled.

The relay supports POSIX and Windows PowerShell peers. New peers are added without dropping old ones; failed peers do not block successful peers. Readers can use the public HTTPS bank from any network. Relaying still requires private SSH reachability, while direct publishing requires GitHub write access. [Per-OS setup and connectivity commands](SETUP.md#optional-shared-memory).
