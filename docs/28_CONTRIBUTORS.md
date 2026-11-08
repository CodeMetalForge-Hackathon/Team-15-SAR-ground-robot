# 28 · Contributors

This page records who contributed what to the Team-15 repository, as shown by Git commits and GitHub pull requests up to the final hackathon merge `d1b607a`. People are identified by their **GitHub handles only**. The areas listed are the paths each person's commits touched, which is a factual record rather than a judgement of effort. Hardware handling, testing at the bench and discussion that left no commit are **not** visible here. The page also describes how AI coding assistance was used, counted from commit trailers.

**Status:** Complete for pushed history at `d1b607a` (8 Nov 2026).

**Related:** [27 Project timeline](27_PROJECT_TIMELINE.md) · [00 Overview](00_PROJECT_OVERVIEW.md)

---

## 1. Method

```bash
git log --all --format='%an' | sort | uniq -c                          # authors (names as committed)
git log --all --no-merges --author=<name> --name-only --format=''      # paths touched
gh pr list --state all --json number,author,mergedBy                   # PR authors and mergers
gh api repos/<owner>/<repo>/commits/<sha> --jq .author.login           # map a commit to a GitHub login
```

Commit author names were mapped to GitHub logins through the GitHub API, one commit per name. Email addresses are not published. Counts cover all pushed branches (164 commits) unless they say "on `main`" (84 commits).

## 2. Contributors

| GitHub handle | Commits (all branches / on `main`) | PRs | Areas touched (by path) |
|---|---|---|---|
| `machackgo` | 96 / 75 (incl. 23 merge commits on `main`) | authored 13 (#1, #2, #3, #5, #7, #8, #10, #11, #12, #13, #14, #15, #16); merged all 14 merged PRs | `perception/`, `core/`, `contracts/`, `dashboard/`, `planner/`, `ranging/`, `rover/`, `firmware/stickc_roverc_bridge/` (draft), `lidar/` (incl. SIMULATED fixtures), `qwen_advisory/`, `camera_mapping/`, `scripts/`, `docs/` (lidar, rover, qwen, camera_mapping), `.github/workflows/`, `README.md`, `TEAM15_DRONE_SEARCH_BUILD.md`; also the integration fixes on PR #17 (`95b6f67`, `159c678`) |
| `hafsaah1` | 12 / 7 | — (commits landed through #17) | `team15_starter/` (fleet planner and hub, SAR core and planners, link protocol, ESP32 gateway and drone firmware, results CSVs, tests, `HARDWARE.md`); on branches: Crazyflie bridge, relay host and scanner app (`tests/relay_host`, `firmware/crazyflie_scanner_app`, `sar_sim/`) |
| `GavinPrescott` | 2 / 1 (one commit is attributed to the login `Gavopian`, with the same author name) | authored #17 | `team15_starter/fleet/` (drone roles: sweeper, thermal, finder; signal areas; planner speed), `team15_starter/CHANGES_ROLES.md`, `team15_starter/homebase.py`, `team15_starter/link/protocol.py`; branch `GavinPrescott-sarsim` ("Add files via upload": `sar_sim.zip`, `team_update.md`) |
| `ithlambelle` | 36 / 0 | authored #6 (open) | BLE identity: `SENSOR_ID_SPEC*.md`, `ble_id.py`, `docs/ble-id/`, `tools/c1`–`c3`, `discovery/` dashboard, `ios/BeaconC1` app, `evidence/c0-…`; Crazyflie RSSI demo; Jetson-relative tracking (`aurora-integration`) |
| `culubo` | 17 / 0 (4 committed as "Beau", which the API maps to `culubo`; 13 committed as "Culubo" with **no linked account**, so the attribution is likely but **unverified**) | — | BLE identity checkpoints C3–C5 (`docs/ble-id/`, `tools/c4`, `tools/c5`, `discovery/`); mission control, RoverC-Pro keyboard/Wi-Fi control and `firmware/roverc_usb`; Crazyflie `fly_to_phone` demo |
| `dennisnahas` | 1 / 1 | — | initial commit (`LICENSE`) |

Notes:

- Insertion counts are left out on purpose. `machackgo`'s commits on `main` add about 27,600 lines, but much of that is generated SIMULATED LiDAR fixtures and docs. Line counts would mislead.
- Work by `ithlambelle` and `culubo` is on the `culubo/sensor-id-specs` and `aurora-integration` branches. PR #6 was **left open** at the end of the event. The review comment lists merge conflicts, tracked screenshots, a committed `evidence/` folder and no CI run. That work is therefore not part of `main`, and these documents do not evaluate it.
- The original build guide divides the work among "Teammate B/C/D" roles (integration, Qwen tools and validator, Pi/SSH/BLE). Git does not show who held which role, so this page does not map those roles to handles.

## 3. Who did what on `main`, by subsystem

| Subsystem | Contributor(s) on `main` | Key PRs |
|---|---|---|
| Build guide and plan | `machackgo` | #1 |
| Route planner | `machackgo` | #2 |
| Camera person detector, Pi source, orientation | `machackgo` | #3 |
| Dashboard, ingest, mission store, range card | `machackgo` | #5 |
| Grove ultrasonic ranging | `machackgo` | #7 |
| RoverC-Pro navigation, supervisor, simulator | `machackgo` | #8, #14 |
| StickC USB bridge and draft firmware | `machackgo` | #15 |
| RPLIDAR C1 | `machackgo` | #11 |
| Qwen advisory contract, model docs | `machackgo` | #12, #13 |
| Camera-only obstacle mapping, judge demo | `machackgo` | #16 |
| CI workflows | `machackgo` | #3, #5, #7, #10, #11, #12 |
| Aurora drone-fleet simulation (`team15_starter/`) | `hafsaah1`, `GavinPrescott` | #17 |

The Qwen LoRA training, the RAG corpus and the evaluation harness live in a private workspace outside this repository. Its authorship is not visible in this Git history. The Hugging Face adapter is published under the account `MOHDMUBASHIR` ([08](08_QWEN_MODEL.md), [09](09_LORA_TRAINING.md)).

## 4. AI assistance

The team used Anthropic's Claude Code heavily. Commits it helped write carry a `Co-Authored-By: Claude …` trailer, and PR descriptions it drafted end with "Generated with Claude Code". Counted from the trailers on 8 Nov 2026:

| Scope | Commits with a Claude co-author trailer | Total |
|---|---|---|
| All pushed branches | **111** (109 "Claude Opus 5.5", 2 "Claude Sonnet 5.5") | 164 |
| `main` | **58** (53 of 61 non-merge commits; 5 of 23 merges) | 84 |

By commit author (all branches): `machackgo` 76 of 96; `ithlambelle` 27 of 36; "Beau" (`culubo`) 4 of 4, including the 2 Sonnet commits; `hafsaah1` 3 of 12; "Gavin Prescott" 1 of 1; "Culubo" 0 of 13; `GavinPrescott` 0 of 1; `dennisnahas` 0 of 1.

PR descriptions: 13 of the 15 PRs end with the Claude Code footer (every `machackgo` PR). The engineering session console log shows the work organised as several parallel Claude Code sessions, each owning one branch: perception, dashboard integration, Grove ranging, rover navigation, LiDAR and Qwen. A coordinating session ran the merge sequence. Cross-session messages appear in the log, for example "merge sequence is COMPLETE and the merge lock is lifted" at 02:04 UTC on 8 Nov. The "independent review" sections in PRs #8, #14, #15 and #16 were produced by separate reviewer sessions. They are not human GitHub reviews: no PR has a GitHub review object.

**What this means for readers:** much of the code and almost all of the prose were AI-drafted under human direction. The human operator chose the scope, ran the hardware, gave approvals (for example, merges and the decision that PR #2 needed no standalone CI), and was the only actor who could touch the Pi and robot. The repository's honesty conventions — provenance labels, UNKNOWN-by-default, hardware gates — are enforced by tests, so they do not depend on trusting either the people or the assistant.
