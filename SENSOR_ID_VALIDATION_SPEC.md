# Sensor-ID follow-up: expanding supported claims

Status: planning only. No implementation, experiments, or stronger claims are
authorized or completed by this document. Read with SENSOR_ID_SPEC.md, which
continues to govern module scope, interfaces, secrets, and evidence integrity.

## Branch and handoff

This follow-up spec lives on `culubo/sensor-id-specs`. Follow the branch and
handoff rules in SENSOR_ID_SPEC.md: check the active branch before changes,
keep checkpoint commits off `main`, and record any subsequently authorized
implementation branch. Branch setup does not authorize implementation,
experiments, pushing, or merging.

## Purpose

Turn today's limits into explicit research questions and measurable gates.
The baseline defines the prototype; this second spec defines how later evidence
can expand its documented support. It cannot make a claim true by changing words.
“Outside baseline scope” does not mean “impossible”; “untested” does not mean
“failed.” Keep those distinctions visible in the README and demo.

## Planning prompt: privacy and reliability under interference

Use this prompt for the follow-up planning work. It does not authorize
implementation or radio experiments:

> Extend the offline search-and-rescue sensor-ID validation spec to evaluate
> identity privacy and communication reliability under interference. Separate
> message confidentiality, authentication, identity linkability, radio
> detectability, and availability.
>
> Identify what the existing iPhone -> passive ESP32 architecture can support,
> what remains untested, and what requires a separately authorized hardware or
> protocol change. Do not promise invisibility or immunity to jamming.
>
> For each proposed improvement, define the threat model, platform constraints,
> controls, measurable acceptance criteria, raw evidence, and video demonstration
> required. Use controlled laboratory interference testing rather than deploying
> a jammer.
>
> Require checkpoint commits and plain-language reports showing expected versus
> observed results, failures, and remaining limitations. Propose the plan only;
> do not implement it.

Keep the five properties distinct in proposals and reports:

| Property | Question the plan must answer |
| --- | --- |
| Confidentiality | Can an observer read the protected contents? The baseline HMAC authenticates; it does not encrypt. |
| Authentication | Can the verifier reject unauthorized or altered messages? |
| Identity linkability | Can an observer associate successive broadcasts with the same enrollment or person? |
| Radio detectability | What can a specified observer and instrument detect under the tested conditions? Encrypted contents do not establish concealed radio activity. |
| Availability | How often and how quickly does verification succeed under a specified interference condition, including failures and recovery? |

Treat the pasted covert-link proposal as unvalidated background material, not
an implementation prescription. Custom waveforms, backscatter, and transmitting
drone interrogation require a separate scope/design review. Do not import claims
about connected Bluetooth frequency hopping into this advertising-only module.
Cryptographic encodings such as Elligator do not establish concealment of the
complete radio transmission. No finite demo establishes universal undetectability
or immunity to interference.

## Claims register

Maintain one table of claims with status, tested revision, exact configuration,
run IDs, sample counts, acceptance target, measurements, video timestamps, and
remaining limits. Initially all experimental claims below are UNTESTED.

| Candidate claim | Evidence required before promoting it |
| --- | --- |
| Works while the phone is locked/backgrounded | Sustained real iPhone-to-passive-ESP32 reception and authentication, including counter rotations, lifecycle transitions, and repeated trials; state exact phone, OS, app state, and required user actions. |
| Supports Apple Watch | Independent actual-watch build and radio trials; state watch model/OS, app lifecycle, and whether a paired phone was present or required. iPhone results do not transfer. |
| Detects beacons through a particular obstruction | Measured trials with that material, thickness, placement, orientation, distance, and controls; report detection rate and latency including failures. |
| Works for a stated duration offline | Timed disconnected run with documented initial clock offset, drift, rotation, restarts, and replay-state behavior. |
| Supports a stated device population | Multi-device trials at the claimed population with reception, serial throughput, verification latency, and missed windows measured. Synthetic load is labeled separately. |
| Has a stated battery cost | Repeated baseline/control and advertising trials on actual hardware using a documented measurement method, duration, and uncertainty. |
| Preserves observations across verifier restart | Real restart/power interruption trials with durable replay state and no previously accepted token becoming verified again. |
| Scanner sends no BLE packets | Independent RF capture with documented instrument/channel coverage and observation duration, plus scan configuration review. State capture limits. |

Promote only the tested configuration. One phone/OS does not establish support
for all iPhones, and one obstruction is not “works through rubble.” A public alias
is not anonymous. RSSI observations do not establish precise location.

## Register the experiment before running it

For each candidate claim, write an experiment card containing:

1. The exact proposed user-facing sentence and practical use case.
2. Hypothesis, controls, hardware/software versions, setup, and start/end events.
3. Metrics, units, sample size, success threshold, timeout, exclusion rules, and
   measurement uncertainty. Record thresholds before collecting results.
4. Raw data and video collection plan, reproduction commands, and responsible
   operator for physical actions the agent cannot perform.
5. Dependencies and any proposed change to scope, output contract, or hardware.

Do not discard failures or change thresholds afterward to manufacture a pass.
If the plan changes, create a new card/run ID and preserve the original result.
Report success fractions as counts (for example, x of n), with confidence
intervals when making reliability claims. Repetition with identical fixtures
does not measure field reliability or platform diversity.

## First follow-up experiment: locked/background support

First recheck official documentation for the actual OS release and any proposed
capability. The baseline documentation describes constraints; newer capabilities
must be demonstrated on the actual target configuration. Record prerequisites
such as starting a user-visible activity before locking. Do not promise operation
after force-quit, reboot, or battery depletion based on a locked-screen result.

Proposed screening plan after explicit experiment authorization:

- Use the same actual iPhone and passive ESP32 setup as the foreground control.
- Run at least 20 independent foreground-to-background transitions and 20
  foreground-to-lock transitions, each observed for at least 120 seconds.
- Keep the scanner running continuously; record transition time, received
  counters, first verified latency, gaps, and at least two fresh token rotations
  after each transition. Existing cached packets do not establish continued use.
- Use separate force-quit trials and report them independently. Include an
  advertiser-off control to detect cached or injected data mistaken for reception.
- Proposed screening gate: at least 19/20 trials in each claimed state produce a
  fresh verified token within 10 seconds after transition and in every complete
  subsequent 30-second window of that trial. Any stale/invalid verification fails
  the safety condition. Preserve every timeout and gap in the result table.
- Passing permits only a bounded prototype statement for that exact setup. A
  longer-duration and broader-device plan is needed for stronger reliability claims.

This is a proposed gate, not an observed result or a rescue-readiness standard.
If the user requires unattended operation over hours, register that duration and
its acceptance target explicitly before making an operational support claim.

## Limits that need a design change

Some limits are not resolved by collecting more samples:

- HMAC authenticates the message but does not encrypt its contents. Confidential
  identity requires a reviewed privacy/cryptographic design and new test vectors.
- A verified advertisement cannot establish that a person is alive or that the
  transmitter is physically nearby despite a relay. Do not promote those claims
  from BLE reception, RSSI, or software replay tests.
- A passive broadcast receiver cannot provide challenge-response liveness.
  Exploring that would change the receive-only requirement and require explicit
  scope authorization, a revised threat model, and fresh integration tests.
- A public 8-bit enrollment alias permits tracking and limits enrollment capacity.
  Removing that limit requires a versioned wire-format and provisioning revision.
- Reporting person identity or location through Reading requires an agreed
  integration design; do not repurpose zone, t, kind, or RSSI to hide new fields.

For a design change, write the proposal first: benefit, changed constraints,
alternatives, compatibility/migration, threat-model effects, and validation plan.
Obtain authorization for the scope change before implementing it. Teammates'
mapping, CV, and drone work remain outside this module.

## Commit, presentation, and amendment process

Use the checkpoint/report rules in SENSOR_ID_SPEC.md for each experiment:
commit the experiment plan; commit the authorized implementation if needed;
run and preserve measurements; commit the result report; then propose the exact
README/spec wording supported by that report. Keep all code/evidence revisions
traceable. A failed experiment gets a result commit, not a support claim.

Every proposed claim amendment contains the old wording, proposed wording,
evidence links, exact tested conditions, failures, and unresolved limits. Preserve
earlier reports as historical evidence; do not rewrite them to imply earlier
capability. Mark contradictory or obsolete claims explicitly and link the update.
If later regression tests fail, narrow or withdraw the affected support claim.

The human-facing presentation should say: “We tested [configuration] under
[conditions]. We observed [counts and measurements], against [target]. Here is
the video at [timestamp] and the raw data. This supports [bounded claim]. We have
not established [remaining limitation].” Fill this only from actual runs.

Full delivery includes the updated claims register, experiment cards, raw data,
calculations, playable video, reproduction steps, and a short readable report.
No experiment is complete merely because code was written or a build succeeded.
