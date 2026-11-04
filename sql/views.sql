-- Starter metric views (portable PostgreSQL / SQLite). Week 3 extends these.
-- Warm-up is excluded everywhere using runs.warmup_hours.
-- Keep each view independent of other views (the loader drops & recreates them).

-- Cycle time per completed lot released after warm-up
CREATE VIEW v_lot_cycle_time AS
SELECT l.run_id, l.lot_id, l.release_time, l.complete_time,
       l.complete_time - l.release_time AS cycle_time_h,
       CASE WHEN l.complete_time <= l.due_time THEN 1 ELSE 0 END AS on_time,
       l.wafers_start, l.wafers_out
FROM lots l
JOIN runs r ON r.run_id = l.run_id
WHERE l.complete_time IS NOT NULL
  AND l.release_time >= r.warmup_hours
  AND l.wafers_out > 0;

-- Queue time by tool group
CREATE VIEW v_queue_time_by_group AS
SELECT m.run_id, m.tool_group,
       COUNT(*)                                    AS moves,
       AVG(m.start_time - m.arrive_time)           AS avg_queue_h,
       MAX(m.start_time - m.arrive_time)           AS max_queue_h,
       AVG(m.end_time - m.start_time)              AS avg_process_h,
       AVG(m.batch_size * 1.0)                     AS avg_batch_size
FROM lot_moves m
JOIN runs r ON r.run_id = m.run_id
WHERE m.arrive_time >= r.warmup_hours
GROUP BY m.run_id, m.tool_group;

-- Tool utilization (PROD / DOWN share of the post-warm-up window)
CREATE VIEW v_tool_utilization AS
SELECT s.run_id, s.tool_id, s.tool_group,
       SUM(CASE WHEN s.state = 'PROD' THEN
             (CASE WHEN s.end_time > r.sim_hours THEN r.sim_hours ELSE s.end_time END)
           - (CASE WHEN s.start_time < r.warmup_hours THEN r.warmup_hours ELSE s.start_time END)
           ELSE 0 END) / (r.sim_hours - r.warmup_hours)  AS prod_frac,
       SUM(CASE WHEN s.state = 'DOWN' THEN
             (CASE WHEN s.end_time > r.sim_hours THEN r.sim_hours ELSE s.end_time END)
           - (CASE WHEN s.start_time < r.warmup_hours THEN r.warmup_hours ELSE s.start_time END)
           ELSE 0 END) / (r.sim_hours - r.warmup_hours)  AS down_frac
FROM tool_states s
JOIN runs r ON r.run_id = s.run_id
WHERE s.end_time > r.warmup_hours
GROUP BY s.run_id, s.tool_id, s.tool_group, r.sim_hours, r.warmup_hours;

-- Daily wafer outs
CREATE VIEW v_daily_outs AS
SELECT l.run_id,
       FLOOR(l.complete_time / 24.0) AS sim_day,
       COUNT(*)                      AS lots_out,
       SUM(l.wafers_out)             AS wafers_out
FROM lots l
WHERE l.complete_time IS NOT NULL
GROUP BY l.run_id, FLOOR(l.complete_time / 24.0);

-- Line yield = wafers out / wafers started (completed lots, post warm-up)
CREATE VIEW v_line_yield AS
SELECT l.run_id,
       SUM(l.wafers_out) * 1.0 / SUM(l.wafers_start) AS line_yield,
       COUNT(*) AS lots
FROM lots l
JOIN runs r ON r.run_id = l.run_id
WHERE l.complete_time IS NOT NULL AND l.release_time >= r.warmup_hours
GROUP BY l.run_id;

-- Weekly cycle time trend (by completion week)
CREATE VIEW v_weekly_cycle_time AS
SELECT l.run_id,
       CAST(FLOOR(l.complete_time / 168.0) AS INTEGER) AS week,
       COUNT(*)                                 AS lots_out,
       AVG(l.complete_time - l.release_time)    AS mean_ct_h,
       AVG(CASE WHEN l.complete_time <= l.due_time THEN 1.0 ELSE 0.0 END) AS on_time_frac
FROM lots l
JOIN runs r ON r.run_id = l.run_id
WHERE l.complete_time IS NOT NULL AND l.complete_time >= r.warmup_hours AND l.wafers_out > 0
GROUP BY l.run_id, CAST(FLOOR(l.complete_time / 168.0) AS INTEGER);

-- Bottleneck heatmap: average queue time per tool group per week
CREATE VIEW v_queue_heatmap AS
SELECT m.run_id, m.tool_group,
       CAST(FLOOR(m.arrive_time / 168.0) AS INTEGER) AS week,
       AVG(m.start_time - m.arrive_time)             AS avg_queue_h,
       COUNT(*)                                      AS moves
FROM lot_moves m
JOIN runs r ON r.run_id = m.run_id
WHERE m.arrive_time >= r.warmup_hours
GROUP BY m.run_id, m.tool_group, CAST(FLOOR(m.arrive_time / 168.0) AS INTEGER);

-- WIP by tool group (time-average of 4-hourly snapshots)
CREATE VIEW v_wip_by_group AS
SELECT w.run_id, w.tool_group,
       AVG(w.queued * 1.0)                 AS avg_queued,
       AVG(w.in_process * 1.0)             AS avg_in_process,
       MAX(w.queued + w.in_process)        AS max_wip
FROM wip_snapshots w
JOIN runs r ON r.run_id = w.run_id
WHERE w.t >= r.warmup_hours
GROUP BY w.run_id, w.tool_group;

-- Queue time by route step (where in the flow lots wait)
CREATE VIEW v_step_queue AS
SELECT m.run_id, m.step_idx, m.recipe, m.tool_group,
       AVG(m.start_time - m.arrive_time) AS avg_queue_h,
       AVG(m.end_time - m.start_time)    AS avg_process_h
FROM lot_moves m
JOIN runs r ON r.run_id = m.run_id
WHERE m.arrive_time >= r.warmup_hours
GROUP BY m.run_id, m.step_idx, m.recipe, m.tool_group;
