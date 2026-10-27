// In-memory timing only. This module never executes components or writes files.
export function createTaskClock(stageIds, now = () => ({
  wall: new Date().toISOString(), mono: performance.now(),
})) {
  if (!Array.isArray(stageIds) || !stageIds.length ||
      stageIds.some(id => typeof id !== 'string' || !id.trim()) ||
      new Set(stageIds).size !== stageIds.length) {
    throw new Error('Provide unique, nonempty stage IDs');
  }
  let previous = -Infinity;
  function stamp() {
    const { wall, mono } = now();
    if (typeof wall !== 'string' || !Number.isFinite(Date.parse(wall)) ||
        !Number.isFinite(mono) || mono < previous) {
      throw new Error('Invalid or regressing clock');
    }
    previous = mono;
    return Object.freeze({ wall, mono });
  }
  const preparation = stamp();
  const stages = new Map(stageIds.map(id => [id, {}]));
  let captured;
  function stage(id) {
    if (captured) throw new Error('Clock already captured');
    if (!stages.has(id)) throw new Error('Unknown stage: ' + id);
    return stages.get(id);
  }
  const seconds = (a, b) => a && b ? (b.mono - a.mono) / 1000 : null;
  return Object.freeze({
    dispatch(id) {
      const entry = stage(id);
      if (entry.start) throw new Error('Stage already dispatched: ' + id);
      entry.start = stamp();
      return entry.start;
    },
    settle(id, status, cacheReuse = false) {
      const entry = stage(id);
      if (!entry.start || entry.end) throw new Error('Stage is not active: ' + id);
      if (!['succeeded', 'failed', 'cancelled', 'uncertain'].includes(status) ||
          typeof cacheReuse !== 'boolean') throw new Error('Invalid outcome');
      entry.end = stamp();
      entry.status = status;
      entry.cacheReuse = cacheReuse;
      return entry.end;
    },
    snapshot() {
      const launched = [...stages.values()].filter(s => s.start);
      const first = launched.reduce((a, s) => !a || s.start.mono < a.mono ? s.start : a, null);
      const last = launched.reduce((a, s) => s.end && (!a || s.end.mono > a.mono) ? s.end : a, null);
      const complete = launched.every(s => s.end);
      return {
        preparation, captured: captured ?? null,
        stages: [...stages].map(([id, s]) => ({
          id, start: s.start ?? null, end: s.end ?? null,
          durationSeconds: seconds(s.start, s.end),
          status: s.status ?? (s.start ? 'active' : 'not run'),
          cacheReuse: s.cacheReuse ?? null,
        })),
        preparationSeconds: seconds(preparation, first ?? captured),
        workflowSeconds: complete ? seconds(first, last) : null,
        reportingSeconds: complete ? seconds(last, captured) : null,
        totalSeconds: seconds(preparation, captured),
      };
    },
    capture() {
      if ([...stages.values()].some(s => s.start && !s.end)) {
        throw new Error('Settle all launched stages before capture');
      }
      captured ??= stamp();
      return this.snapshot();
    },
  });
}
