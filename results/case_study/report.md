# Root-cause case study: cycle-time spike

Incident injected: **LITHO_02** out of service from day 80 to day 94 (e.g. a stage part on back-order). The analysis below uses only the logged data, the way an IE would investigate.

## 1. Symptom: weekly cycle time

Mean cycle time was ~68 h before the event and peaked at **240 h in week 13**.

```sql
        SELECT CAST(FLOOR(complete_time / 168) AS INTEGER) AS week,
               COUNT(*) AS lots_out,
               ROUND(AVG(complete_time - release_time), 1) AS mean_ct_h
        FROM lots WHERE run_id = ? AND complete_time IS NOT NULL AND complete_time >= ?
        GROUP BY 1 ORDER BY 1
```

| week | lots out | mean CT (h) |
|---|---|---|
| 4 | 49 | 63.4 |
| 5 | 72 | 66.6 |
| 6 | 65 | 74.9 |
| 7 | 75 | 68.2 |
| 8 | 68 | 71.1 |
| 9 | 76 | 61.2 |
| 10 | 68 | 61.9 |
| 11 | 49 | 74.1 |
| 12 | 29 | 170.2 |
| 13 | 53 | 240.0 |
| 14 | 86 | 231.6 |
| 15 | 83 | 196.5 |
| 16 | 84 | 162.6 |
| 17 | 81 | 136.2 |
| 18 | 81 | 100.9 |
| 19 | 80 | 69.6 |
| 20 | 74 | 58.6 |
| 21 | 69 | 69.2 |
| 22 | 67 | 74.0 |
| 23 | 68 | 76.6 |
| 24 | 75 | 66.6 |
| 25 | 47 | 68.3 |


## 2. Locate: which queue exploded?

Average queue time per tool group, before vs during the event window:

```sql
        SELECT tool_group,
               ROUND(AVG(CASE WHEN arrive_time <  ? THEN start_time - arrive_time END), 2) AS before_h,
               ROUND(AVG(CASE WHEN arrive_time >= ? AND arrive_time < ?
                              THEN start_time - arrive_time END), 2) AS during_h
        FROM lot_moves WHERE run_id = ? AND arrive_time >= ?
        GROUP BY tool_group ORDER BY during_h - before_h DESC
```

| tool group | before (h) | during (h) |
|---|---|---|
| LITHO | 1.41 | 26.3 |
| IMPLANT | 0.07 | 0.08 |
| CLEAN | 0.06 | 0.03 |
| PVD | 0.09 | 0.04 |
| DEPO | 0.18 | 0.11 |
| CMP | 0.08 | 0.01 |
| METRO | 0.1 | 0.03 |
| DIFF | 1.96 | 1.88 |
| PROBE | 0.38 | 0.24 |
| ETCH | 0.45 | 0.04 |


## 3. Cause: which tool was down?

```sql
        SELECT tool_id, COUNT(*) AS down_events,
               ROUND(SUM(end_time - start_time), 1) AS down_hours,
               ROUND(MAX(end_time - start_time), 1) AS longest_h
        FROM tool_states
        WHERE run_id = ? AND state = 'DOWN' AND end_time > ? AND start_time < ?
        GROUP BY tool_id ORDER BY down_hours DESC LIMIT 5
```

| tool | down events | down hours | longest (h) |
|---|---|---|---|
| LITHO_02 | 1 | 336.0 | 336.0 |
| LITHO_03 | 7 | 75.7 | 20.9 |
| IMPLANT_02 | 5 | 36.6 | 17.6 |
| ETCH_03 | 5 | 35.8 | 11.9 |
| ETCH_01 | 4 | 35.1 | 15.9 |


## 4. Why one tool hurts this much: capacity math

LITHO is the bottleneck and every lot visits it 6 times (6.1 h of litho work per lot). With 3 tools its utilization is 91%; with 2 it would need to be **137%**, i.e. demand exceeds capacity, so WIP grows by about 2.7 lots/day for as long as the tool is out, and takes weeks to drain afterwards. No dispatch rule can create capacity; it can only decide who waits.

## 5. Countermeasures (20 paired replications, mean ± 95% CI)

% = paired change vs as-is; * = p < 0.05 (paired t-test).

| Scenario | Mean CT (h) | Peak weekly CT (h) | On-time % | Q-time viol. % | Wafers/day | Order lead time (h) |
|---|---|---|---|---|---|---|
| No incident (reference) | 64.6 ± 0.8 | 76.6 ± 2.7 | 89.8 ± 1.6 | 1.0 ± 0.1 | 244.5 ± 0.3 | 64.6 ± 0.8 |
| As-is: incident, FIFO, push release | 95.8 ± 3.7 | 207.7 ± 8.0 | 60.1 ± 2.9 | 1.0 ± 0.1 | 244.5 ± 0.3 | 95.8 ± 3.7 |
| Fix A: CR dispatch | 83.6 ± 2.5 (-13%*) | 148.8 ± 5.3 (-28%*) | 66.6 ± 3.0 (+11%*) | 1.9 ± 0.2 (+91%*) | 244.5 ± 0.3 (+0%) | 83.6 ± 2.5 (-13%*) |
| Fix B: CR + DBR rope on litho | 71.9 ± 1.2 (-25%*) | 88.9 ± 2.5 (-57%*) | 56.8 ± 5.2 (-5%*) | 2.2 ± 0.2 (+119%*) | 244.3 ± 0.4 (-0%) | 90.0 ± 4.5 (-6%*) |
| Fix C: expedite repair (14 -> 5 days) | 69.0 ± 1.4 (-28%*) | 111.8 ± 5.5 (-46%*) | 81.6 ± 2.5 (+36%*) | 1.0 ± 0.1 (-4%) | 244.6 ± 0.3 (+0%) | 69.0 ± 1.4 (-28%*) |
| Fix C + B (expedite + CR + DBR) | 66.5 ± 0.9 (-31%*) | 78.3 ± 1.8 (-62%*) | 89.4 ± 3.1 (+49%*) | 1.1 ± 0.1 (+12%) | 244.5 ± 0.3 (+0%) | 68.7 ± 1.5 (-28%*) |


### Reading the result

- **Shortening the outage (expedite repair (14 -> 5 days))** is the root-cause fix: mean cycle time -28%, on-time delivery 60% -> 82%.
- **CR dispatch** cannot add capacity, but by serving the latest lots first it cuts the peak weekly cycle time -28%; the cost is more Q-time violations (1.0% -> 1.9%).
- **DBR rope** holds new lots outside the fab while litho is short: in-fab cycle time -25%, but order lead time only -6% and on-time delivery 57% - the waiting moves to the order queue, it does not disappear.
- **Combining all three** brings the fab back near its no-incident baseline: on-time 89% (reference 90%), peak weekly cycle time -62% vs as-is.

