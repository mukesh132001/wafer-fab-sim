# Dispatch policy study

30 replications x 8 policies, 200 days each (30-day warm-up), Poisson order arrivals every 2.4 h on average. Common random numbers: every policy sees the same tool failures and lots for a given seed.

Mean ± 95% CI. Δ = paired difference vs FIFO; p = paired t-test, Holm-adjusted.


## Mean cycle time (h)  (lower is better)

Randomized-block ANOVA: F(7, 203) = 42.4, p < 0.001

| Policy | Mean ± CI | Δ vs FIFO | % | p (Holm) |
|---|---|---|---|---|
| FIFO (baseline) | 77.66 ± 3.15 | - | - | - |
| SPT | 77.55 ± 3.14 | -0.11 | -0.1% | 0.640 |
| EDD | 73.73 ± 2.34 | -3.93 | -5.1% | < 0.001 |
| LEAST_SLACK | 72.95 ± 2.31 | -4.71 | -6.1% | < 0.001 |
| CR | 74.55 ± 1.92 | -3.11 | -4.0% | < 0.001 |
| FIFO+CONWIP | 69.43 ± 0.93 | -8.23 | -10.6% | < 0.001 |
| CR+CONWIP | 70.06 ± 0.85 | -7.61 | -9.8% | < 0.001 |
| CR+DBR | 70.17 ± 0.98 | -7.49 | -9.7% | < 0.001 |

## P90 cycle time (h)  (lower is better)

Randomized-block ANOVA: F(7, 203) = 38.4, p < 0.001

| Policy | Mean ± CI | Δ vs FIFO | % | p (Holm) |
|---|---|---|---|---|
| FIFO (baseline) | 108.33 ± 8.00 | - | - | - |
| SPT | 107.98 ± 7.81 | -0.35 | -0.3% | 0.606 |
| EDD | 98.24 ± 4.84 | -10.08 | -9.3% | < 0.001 |
| LEAST_SLACK | 96.95 ± 4.74 | -11.37 | -10.5% | < 0.001 |
| CR | 97.87 ± 3.33 | -10.45 | -9.6% | < 0.001 |
| FIFO+CONWIP | 82.09 ± 0.96 | -26.23 | -24.2% | < 0.001 |
| CR+CONWIP | 88.48 ± 0.97 | -19.85 | -18.3% | < 0.001 |
| CR+DBR | 89.21 ± 1.31 | -19.12 | -17.6% | < 0.001 |

## Cycle time std dev (h)  (lower is better)

Randomized-block ANOVA: F(7, 203) = 45.6, p < 0.001

| Policy | Mean ± CI | Δ vs FIFO | % | p (Holm) |
|---|---|---|---|---|
| FIFO (baseline) | 20.14 ± 2.68 | - | - | - |
| SPT | 20.11 ± 2.70 | -0.03 | -0.2% | 0.880 |
| EDD | 16.99 ± 1.64 | -3.15 | -15.7% | < 0.001 |
| LEAST_SLACK | 16.71 ± 1.64 | -3.43 | -17.0% | < 0.001 |
| CR | 16.36 ± 1.17 | -3.78 | -18.8% | < 0.001 |
| FIFO+CONWIP | 9.96 ± 0.20 | -10.18 | -50.5% | < 0.001 |
| CR+CONWIP | 12.68 ± 0.21 | -7.46 | -37.0% | < 0.001 |
| CR+DBR | 13.17 ± 0.40 | -6.97 | -34.6% | < 0.001 |

## On-time delivery (%)  (higher is better)

Randomized-block ANOVA: F(7, 203) = 102.8, p < 0.001

| Policy | Mean ± CI | Δ vs FIFO | % | p (Holm) |
|---|---|---|---|---|
| FIFO (baseline) | 66.30 ± 4.62 | - | - | - |
| SPT | 66.49 ± 4.56 | +0.19 | +0.3% | 0.543 |
| EDD | 75.24 ± 5.03 | +8.94 | +13.5% | < 0.001 |
| LEAST_SLACK | 79.40 ± 4.91 | +13.10 | +19.8% | < 0.001 |
| CR | 79.76 ± 4.56 | +13.46 | +20.3% | < 0.001 |
| FIFO+CONWIP | 65.27 ± 5.54 | -1.03 | -1.6% | 0.396 |
| CR+CONWIP | 73.47 ± 6.34 | +7.17 | +10.8% | < 0.001 |
| CR+DBR | 73.01 ± 6.03 | +6.71 | +10.1% | < 0.001 |

## Throughput (wafers/day)  (higher is better)

Randomized-block ANOVA: F(7, 203) = 0.8, p 0.618

| Policy | Mean ± CI | Δ vs FIFO | % | p (Holm) |
|---|---|---|---|---|
| FIFO (baseline) | 243.41 ± 2.58 | - | - | - |
| SPT | 243.40 ± 2.51 | -0.01 | -0.0% | 1.000 |
| EDD | 243.25 ± 2.39 | -0.17 | -0.1% | 1.000 |
| LEAST_SLACK | 243.16 ± 2.46 | -0.26 | -0.1% | 1.000 |
| CR | 243.32 ± 2.52 | -0.09 | -0.0% | 1.000 |
| FIFO+CONWIP | 243.36 ± 2.42 | -0.06 | -0.0% | 1.000 |
| CR+CONWIP | 243.28 ± 2.49 | -0.13 | -0.1% | 1.000 |
| CR+DBR | 243.22 ± 2.46 | -0.19 | -0.1% | 1.000 |

## Avg WIP (lots)  (lower is better)

Randomized-block ANOVA: F(7, 203) = 40.9, p < 0.001

| Policy | Mean ± CI | Δ vs FIFO | % | p (Holm) |
|---|---|---|---|---|
| FIFO (baseline) | 32.27 ± 1.58 | - | - | - |
| SPT | 32.22 ± 1.58 | -0.05 | -0.2% | 0.599 |
| EDD | 30.61 ± 1.23 | -1.66 | -5.1% | < 0.001 |
| LEAST_SLACK | 30.29 ± 1.21 | -1.99 | -6.2% | < 0.001 |
| CR | 30.95 ± 1.07 | -1.32 | -4.1% | < 0.001 |
| FIFO+CONWIP | 28.81 ± 0.65 | -3.46 | -10.7% | < 0.001 |
| CR+CONWIP | 29.07 ± 0.63 | -3.20 | -9.9% | < 0.001 |
| CR+DBR | 29.12 ± 0.67 | -3.16 | -9.8% | < 0.001 |

## Q-time violations (%)  (lower is better)

Randomized-block ANOVA: F(7, 203) = 79.8, p < 0.001

| Policy | Mean ± CI | Δ vs FIFO | % | p (Holm) |
|---|---|---|---|---|
| FIFO (baseline) | 1.09 ± 0.10 | - | - | - |
| SPT | 1.12 ± 0.11 | +0.03 | +3.1% | 0.459 |
| EDD | 2.39 ± 0.25 | +1.29 | +118.6% | < 0.001 |
| LEAST_SLACK | 1.72 ± 0.17 | +0.63 | +57.6% | < 0.001 |
| CR | 1.69 ± 0.19 | +0.60 | +54.6% | < 0.001 |
| FIFO+CONWIP | 1.01 ± 0.08 | -0.09 | -7.8% | 0.026 |
| CR+CONWIP | 1.48 ± 0.12 | +0.39 | +36.0% | < 0.001 |
| CR+DBR | 1.78 ± 0.20 | +0.69 | +62.8% | < 0.001 |

## Order lead time (h)  (lower is better)

Randomized-block ANOVA: F(7, 203) = 36.9, p < 0.001

| Policy | Mean ± CI | Δ vs FIFO | % | p (Holm) |
|---|---|---|---|---|
| FIFO (baseline) | 77.66 ± 3.15 | - | - | - |
| SPT | 77.55 ± 3.14 | -0.11 | -0.1% | 0.987 |
| EDD | 73.73 ± 2.34 | -3.93 | -5.1% | < 0.001 |
| LEAST_SLACK | 72.95 ± 2.31 | -4.71 | -6.1% | < 0.001 |
| CR | 74.55 ± 1.92 | -3.11 | -4.0% | < 0.001 |
| FIFO+CONWIP | 77.33 ± 3.25 | -0.33 | -0.4% | 0.987 |
| CR+CONWIP | 77.13 ± 2.82 | -0.53 | -0.7% | 0.766 |
| CR+DBR | 77.19 ± 2.69 | -0.47 | -0.6% | 0.766 |

Little's Law check: max |WIP - TH x CT| / WIP across all 240 runs = 3.06%.

