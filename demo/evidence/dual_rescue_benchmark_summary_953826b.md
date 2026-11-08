# Benchmark summary

Revision `953826b`, 1540 completed runs of 1540 planned, wall 98.3 s.

## Configurations

| environment | mode | aerial planner | runs | mission success | correct outcome | located/survivors | coverage | 1st discovery s | drone path m | rover path m | replans | STOP events | collisions | unknown entries | incorrect assign. | safety viol. | mean sim s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| collapsed_building | coordinated | greedy | 20 | 100% | 100% | 20/20 | 0.97 | 27.973 | 317.68 | 47.198 | 0 | 0 | 0 | 0 | 0 | 0 | 131.13 |
| collapsed_building | coordinated | lawnmower | 20 | 100% | 100% | 20/20 | 0.97 | 171.31 | 1015.31 | 47.2 | 0 | 0 | 0 | 0 | 0 | 0 | 312.36 |
| collapsed_building | coordinated | mcts | 100 | 98% | 100% | 100/100 | 0.97 | 32.611 | 338.615 | 49.443 | 0 | 0 | 0 | 0 | 0 | 0 | 143.765 |
| collapsed_building | independent | mcts | 20 | 100% | 100% | 20/20 | 0.97 | 28.837 | 314.06 | 56.204 | 0.4 | 0.4 | 0 | 0 | 0 | 0 | 157.227 |
| collapsed_building | static_route | mcts | 20 | 100% | 100% | 20/20 | 0.98 | 28.837 | 325.515 | 48.4 | 0 | 0 | 0 | 0 | 0 | 0 | 136.953 |
| dynamic | coordinated | greedy | 20 | 90% | 100% | 20/20 | 0.97 | 27.973 | 385.28 | 62.407 | 0.9 | 1 | 0 | 0 | 0 | 0 | 203.03 |
| dynamic | coordinated | lawnmower | 20 | 90% | 100% | 20/20 | 0.97 | 171.31 | 1146.155 | 62.384 | 0.9 | 1 | 0 | 0 | 0 | 0 | 373.305 |
| dynamic | coordinated | mcts | 100 | 88% | 100% | 100/100 | 0.97 | 32.611 | 422.69 | 61.421 | 0.88 | 1 | 0 | 0 | 0 | 0 | 218.835 |
| dynamic | independent | mcts | 20 | 90% | 100% | 20/20 | 0.97 | 28.837 | 314.06 | 63.848 | 1.2 | 1.3 | 0 | 0 | 0 | 0 | 205.852 |
| dynamic | static_route | mcts | 20 | 0% | 10% | 20/20 | 0.97 | 28.837 | 347.655 | 9.056 | 0 | 1 | 0 | 0 | 0 | 0 | 105.612 |
| maze | coordinated | greedy | 20 | 55% | 100% | 20/20 | 0.97 | 37.885 | 315.65 | 48.519 | 0 | 0 | 0 | 0 | 0 | 0 | 167.857 |
| maze | coordinated | lawnmower | 20 | 55% | 100% | 20/20 | 0.97 | 233.512 | 1010.01 | 48.52 | 0 | 0 | 0 | 0 | 0 | 0 | 359.502 |
| maze | coordinated | mcts | 100 | 62% | 100% | 97/100 | 0.97 | 42.357 | 332.001 | 54.156 | 0 | 0 | 0 | 0 | 0 | 0 | 182.674 |
| maze | independent | mcts | 20 | 55% | 100% | 20/20 | 0.97 | 44.538 | 310.0 | 74.37 | 0.3 | 0.75 | 0 | 0 | 0 | 0 | 226.873 |
| maze | static_route | mcts | 20 | 55% | 100% | 20/20 | 0.97 | 44.538 | 336.21 | 48.519 | 0 | 0 | 0 | 0 | 0 | 0 | 177.653 |
| multi_survivor | coordinated | greedy | 20 | 100% | 100% | 60/60 | 0.97 | 11.682 | 319.62 | 139.649 | 0 | 0 | 0 | 0 | 8 | 0 | 355.657 |
| multi_survivor | coordinated | lawnmower | 20 | 100% | 100% | 60/60 | 0.97 | 59.9 | 1033.26 | 130.952 | 0 | 0 | 0 | 0 | 12 | 0 | 432.373 |
| multi_survivor | coordinated | mcts | 100 | 99% | 99% | 299/300 | 0.97 | 15.611 | 388.028 | 139.782 | 0 | 0 | 0 | 0 | 43 | 0 | 363.66 |
| multi_survivor | independent | mcts | 20 | 100% | 100% | 60/60 | 0.98 | 16.04 | 386.195 | 151.013 | 0.5 | 0.5 | 0 | 0 | 11 | 0 | 399.445 |
| multi_survivor | static_route | mcts | 20 | 100% | 100% | 60/60 | 0.97 | 16.04 | 388.465 | 145.049 | 0 | 0 | 0 | 0 | 9 | 0 | 376.902 |
| narrow_corridors | coordinated | greedy | 20 | 85% | 100% | 20/20 | 0.97 | 35.72 | 291.565 | 57.759 | 0 | 0 | 0 | 0 | 0 | 0 | 161.85 |
| narrow_corridors | coordinated | lawnmower | 20 | 85% | 100% | 20/20 | 0.95 | 161.213 | 986.605 | 57.758 | 0 | 0 | 0 | 0 | 0 | 0 | 325.3 |
| narrow_corridors | coordinated | mcts | 100 | 84% | 100% | 95/100 | 0.97 | 23.167 | 363.228 | 54.505 | 0 | 0 | 0 | 0 | 0 | 0 | 154.97 |
| narrow_corridors | independent | mcts | 20 | 85% | 100% | 18/20 | 0.97 | 22.708 | 326.775 | 64.157 | 0.45 | 0.5 | 0 | 0 | 0 | 0 | 176.577 |
| narrow_corridors | static_route | mcts | 20 | 75% | 100% | 18/20 | 0.97 | 22.708 | 387.26 | 55.462 | 0 | 0 | 0 | 0 | 0 | 0 | 161.745 |
| open_outdoor | coordinated | greedy | 20 | 90% | 100% | 20/20 | 0.97 | 44.737 | 331.605 | 61.988 | 0 | 0 | 0 | 0 | 0 | 0 | 171.778 |
| open_outdoor | coordinated | lawnmower | 20 | 90% | 100% | 20/20 | 0.96 | 190.528 | 1004.125 | 58.391 | 0 | 0 | 0 | 0 | 0 | 0 | 340.005 |
| open_outdoor | coordinated | mcts | 100 | 89% | 100% | 97/100 | 0.96 | 28.702 | 364.197 | 55.98 | 0 | 0 | 0 | 0 | 0 | 0 | 151.78 |
| open_outdoor | independent | mcts | 20 | 95% | 100% | 19/20 | 0.98 | 29.216 | 354.25 | 48.371 | 0.15 | 0.15 | 0 | 0 | 0 | 0 | 144.785 |
| open_outdoor | static_route | mcts | 20 | 85% | 100% | 19/20 | 0.97 | 29.216 | 366.315 | 54.545 | 0 | 0 | 0 | 0 | 0 | 0 | 151.555 |
| partially_observable | coordinated | greedy | 20 | 70% | 100% | 16/20 | 0.84 | 33.019 | 261.0 | 38.438 | 0 | 0 | 0 | 0 | 0 | 0 | 122.093 |
| partially_observable | coordinated | lawnmower | 20 | 70% | 100% | 16/20 | 0.95 | 178.6 | 991.575 | 37.242 | 0 | 0 | 0 | 0 | 0 | 0 | 302.793 |
| partially_observable | coordinated | mcts | 100 | 73% | 100% | 84/100 | 0.77 | 29.525 | 269.563 | 49.295 | 0 | 0 | 0 | 0 | 0 | 0 | 139.937 |
| partially_observable | independent | mcts | 20 | 75% | 100% | 15/20 | 0.75 | 31.273 | 275.6 | 34.893 | 0 | 0 | 0 | 0 | 0 | 0 | 111.86 |
| partially_observable | static_route | mcts | 20 | 70% | 100% | 15/20 | 0.76 | 31.273 | 282.66 | 37.287 | 0 | 0 | 0 | 0 | 0 | 0 | 119.752 |
| warehouse | coordinated | greedy | 20 | 30% | 100% | 19/20 | 0.98 | 38.747 | 313.74 | 59.693 | 0 | 0 | 0 | 0 | 0 | 0 | 168.458 |
| warehouse | coordinated | lawnmower | 20 | 30% | 100% | 20/20 | 0.92 | 165.875 | 955.735 | 54.591 | 0 | 0 | 0 | 0 | 0 | 0 | 301.88 |
| warehouse | coordinated | mcts | 100 | 45% | 100% | 96/100 | 0.97 | 39.823 | 386.155 | 51.487 | 0 | 0 | 0 | 0 | 0 | 0 | 156.239 |
| warehouse | independent | mcts | 20 | 90% | 100% | 19/20 | 0.98 | 43.571 | 326.565 | 70.555 | 0.7 | 0.75 | 0 | 0 | 0 | 0 | 214.708 |
| warehouse | static_route | mcts | 20 | 30% | 100% | 19/20 | 0.98 | 43.571 | 395.62 | 49.955 | 0 | 0 | 0 | 0 | 0 | 0 | 158.485 |

## Outcome distribution

| environment | mode | planner | outcomes |
|---|---|---|---|
| collapsed_building | coordinated | greedy | SUCCESS 20 |
| collapsed_building | coordinated | lawnmower | SUCCESS 20 |
| collapsed_building | coordinated | mcts | SUCCESS 98, UNREACHABLE_REPORTED 2 |
| collapsed_building | independent | mcts | SUCCESS 20 |
| collapsed_building | static_route | mcts | SUCCESS 20 |
| dynamic | coordinated | greedy | SUCCESS 18, UNREACHABLE_REPORTED 2 |
| dynamic | coordinated | lawnmower | SUCCESS 18, UNREACHABLE_REPORTED 2 |
| dynamic | coordinated | mcts | SUCCESS 88, UNREACHABLE_REPORTED 12 |
| dynamic | independent | mcts | SUCCESS 18, UNREACHABLE_REPORTED 2 |
| dynamic | static_route | mcts | UNREACHABLE_REPORTED 20 |
| maze | coordinated | greedy | SUCCESS 11, UNREACHABLE_REPORTED 9 |
| maze | coordinated | lawnmower | SUCCESS 11, UNREACHABLE_REPORTED 9 |
| maze | coordinated | mcts | SUCCESS 62, SURVIVOR_NOT_FOUND 3, UNREACHABLE_REPORTED 35 |
| maze | independent | mcts | SUCCESS 11, UNREACHABLE_REPORTED 9 |
| maze | static_route | mcts | SUCCESS 11, UNREACHABLE_REPORTED 9 |
| multi_survivor | coordinated | greedy | SUCCESS 20 |
| multi_survivor | coordinated | lawnmower | SUCCESS 20 |
| multi_survivor | coordinated | mcts | PARTIAL 1, SUCCESS 99 |
| multi_survivor | independent | mcts | SUCCESS 20 |
| multi_survivor | static_route | mcts | SUCCESS 20 |
| narrow_corridors | coordinated | greedy | INSUFFICIENT_INFORMATION 2, SUCCESS 17, UNREACHABLE_REPORTED 1 |
| narrow_corridors | coordinated | lawnmower | INSUFFICIENT_INFORMATION 2, SUCCESS 17, UNREACHABLE_REPORTED 1 |
| narrow_corridors | coordinated | mcts | INSUFFICIENT_INFORMATION 9, SUCCESS 84, SURVIVOR_NOT_FOUND 5, UNREACHABLE_REPORTED 2 |
| narrow_corridors | independent | mcts | SUCCESS 17, SURVIVOR_NOT_FOUND 2, UNREACHABLE_REPORTED 1 |
| narrow_corridors | static_route | mcts | INSUFFICIENT_INFORMATION 2, SUCCESS 15, SURVIVOR_NOT_FOUND 2, UNREACHABLE_REPORTED 1 |
| open_outdoor | coordinated | greedy | INSUFFICIENT_INFORMATION 2, SUCCESS 18 |
| open_outdoor | coordinated | lawnmower | INSUFFICIENT_INFORMATION 2, SUCCESS 18 |
| open_outdoor | coordinated | mcts | INSUFFICIENT_INFORMATION 8, SUCCESS 89, SURVIVOR_NOT_FOUND 3 |
| open_outdoor | independent | mcts | SUCCESS 19, SURVIVOR_NOT_FOUND 1 |
| open_outdoor | static_route | mcts | INSUFFICIENT_INFORMATION 2, SUCCESS 17, SURVIVOR_NOT_FOUND 1 |
| partially_observable | coordinated | greedy | INSUFFICIENT_INFORMATION 2, SUCCESS 14, SURVIVOR_NOT_FOUND 4 |
| partially_observable | coordinated | lawnmower | INSUFFICIENT_INFORMATION 2, SUCCESS 14, SURVIVOR_NOT_FOUND 4 |
| partially_observable | coordinated | mcts | INSUFFICIENT_INFORMATION 11, SUCCESS 73, SURVIVOR_NOT_FOUND 16 |
| partially_observable | independent | mcts | SUCCESS 15, SURVIVOR_NOT_FOUND 5 |
| partially_observable | static_route | mcts | INSUFFICIENT_INFORMATION 1, SUCCESS 14, SURVIVOR_NOT_FOUND 5 |
| warehouse | coordinated | greedy | INSUFFICIENT_INFORMATION 12, SUCCESS 6, SURVIVOR_NOT_FOUND 1, UNREACHABLE_REPORTED 1 |
| warehouse | coordinated | lawnmower | INSUFFICIENT_INFORMATION 13, SUCCESS 6, UNREACHABLE_REPORTED 1 |
| warehouse | coordinated | mcts | CANDIDATE_UNCONFIRMED 1, INSUFFICIENT_INFORMATION 48, SUCCESS 45, SURVIVOR_NOT_FOUND 4, UNREACHABLE_REPORTED 2 |
| warehouse | independent | mcts | SUCCESS 18, SURVIVOR_NOT_FOUND 1, UNREACHABLE_REPORTED 1 |
| warehouse | static_route | mcts | INSUFFICIENT_INFORMATION 12, SUCCESS 6, SURVIVOR_NOT_FOUND 1, UNREACHABLE_REPORTED 1 |

## Failure injection

| fault | environment | injected | expected behaviour | runs | check passed | outcomes |
|---|---|---|---|---|---|---|
| unexpected_debris | dynamic | debris drops onto the rover's route after dispatch | rover stops before contact (no collision), marks the corridor blocked, replans or reports | 10 | 10/10 | SUCCESS 9, UNREACHABLE_REPORTED 1 |
| blocked_corridors | maze | static debris in a maze with dead ends | no route through a BLOCKED corridor; correct outcome (rescue, or unreachable reported) | 10 | 10/10 | SUCCESS 5, UNREACHABLE_REPORTED 5 |
| missing_observations | collapsed_building | 30 % of aerial frames lost | lost frames give no evidence: no false CLEAR, no unsafe motion | 10 | 10/10 | SUCCESS 10 |
| delayed_observations | collapsed_building | aerial observations delivered 5 s late | decisions wait for evidence; no unsafe motion; correct outcome | 10 | 10/10 | SUCCESS 10 |
| false_detections | multi_survivor | a false heat source (decoy) in another room | a decoy is never reported as a rescue (incorrect claims = 0) | 10 | 10/10 | SUCCESS 10 |
| unreachable_target | collapsed_building | debris on the survivor's only doorway | UNREACHABLE (or INSUFFICIENT_INFORMATION) reported; never AT_STANDOFF | 10 | 10/10 | UNREACHABLE_REPORTED 10 |
| lost_communication | collapsed_building | rover mission link down from t=40 s to t=70 s | COMMS_LOST latched by the rover safety supervisor, rover stopped, no auto-resume | 10 | 10/10 | SAFE_STOP_FAULT 10 |
| agent_timeout | collapsed_building | AIR-1 stops responding at t=15 s | AIR-1 marked UNAVAILABLE; UNKNOWN corridors stay UNKNOWN; no unsafe motion | 10 | 10/10 | CANDIDATE_UNCONFIRMED 4, SURVIVOR_NOT_FOUND 6 |
| invalid_coordinates | collapsed_building | a corrupted aerial observation with coordinates off the site | observation rejected, never placed on the map | 10 | 10/10 | SUCCESS 10 |
| conflicting_observations | dynamic | drone camera blind to debris (reports corridors CLEAR) | rover ultrasonic still stops it; BLOCKED is kept over a later aerial CLEAR | 10 | 10/10 | SUCCESS 9, UNREACHABLE_REPORTED 1 |

Charts: success_by_environment.png, baselines.png
