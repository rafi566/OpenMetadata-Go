import http from 'k6/http';
import exec from 'k6/execution';
import { SharedArray } from 'k6/data';
import { Counter, Trend } from 'k6/metrics';
import { requestPlan, validResponse } from './contracts.mjs';

const tables = new SharedArray('catalog tables', () =>
  JSON.parse(open(__ENV.FIXTURE_FILE || '/fixture.json')).tables);
const token = open(__ENV.TOKEN_FILE || '/secrets/admin-token').trim();
const base = (__ENV.API_URL || 'http://api:8585/api/v1').replace(/\/$/, '');
const rate = Number(__ENV.RATE || 10);
const seconds = Number(__ENV.SECONDS || 180);
const vus = Number(__ENV.VUS || 100);
const writeEpoch = __ENV.RUN_ID;
if (!token || ![rate, seconds, vus].every(n => Number.isSafeInteger(n) && n > 0) || vus > 200) {
  throw new Error('Supply a token, positive integer RATE/SECONDS and 1–200 VUS');
}
requestPlan(0, tables, writeEpoch);

const good = new Counter('valid_ops');
const bad = new Counter('invalid_ops');
const latency = new Trend('valid_latency', true);
const completedAt = new Trend('operation_end_ms');
const thresholds = {
  valid_ops: ['count>0'],
  invalid_ops: ['count==0'],
  dropped_iterations: ['count==0'],
  valid_latency: ['p(95)<=500', 'p(99)<=1000'],
};
for (const operation of ['detail', 'list', 'search', 'patch']) {
  thresholds[`valid_ops{operation:${operation}}`] = ['count>0'];
  thresholds[`invalid_ops{operation:${operation}}`] = ['count==0'];
  thresholds[`valid_latency{operation:${operation}}`] = ['p(95)<=500', 'p(99)<=1000'];
}

export const options = {
  scenarios: {
    catalog: {
      executor: 'constant-arrival-rate', rate, timeUnit: '1s',
      duration: `${seconds}s`, preAllocatedVUs: vus, maxVUs: vus, gracefulStop: '15s',
    },
  },
  thresholds,
  summaryTrendStats: ['avg', 'min', 'max', 'p(50)', 'p(95)', 'p(99)'],
  systemTags: ['scenario', 'status', 'method', 'name', 'expected_response'],
};

export default function () {
  const request = requestPlan(exec.scenario.iterationInTest, tables, writeEpoch);
  const tags = { operation: request.operation };
  const params = {
    headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
    tags: { ...tags, name: request.operation }, timeout: '5s',
  };
  const began = Date.now();
  let valid = false;
  try {
    const response = http.request(request.method, base + request.path, request.body, {
      ...params,
      headers: request.operation === 'patch'
        ? { ...params.headers, 'Content-Type': 'application/json-patch+json' }
        : params.headers,
    });
    const body = response.json();
    valid = validResponse(request.operation, response.status, body, request.table, request.description);
    // A write counts only after a separate read confirms it was persisted.
    if (valid && request.operation === 'patch') {
      const read = http.get(`${base}/tables/${encodeURIComponent(request.table.id)}`, {
        ...params, tags: { ...tags, name: 'patch_readback' },
      });
      const stored = read.json();
      valid = validResponse('patch', read.status, stored, request.table, request.description) &&
        stored.version >= body.version;
    }
  } catch (_) {
    valid = false;
  }
  good.add(valid ? 1 : 0, tags);
  bad.add(valid ? 0 : 1, tags);
  if (valid) latency.add(Date.now() - began, tags);
  completedAt.add(Date.now() - exec.scenario.startTime);
}

export function handleSummary(data) {
  data.benchmark = {
    workload: 'catalog-v1', rate, seconds, vus, writeEpoch,
    fixtureSha256: __ENV.FIXTURE_SHA256,
    operationMix: { detail: 40, list: 20, search: 20, patch: 20 },
  };
  return {
    [__ENV.SUMMARY_FILE || '/results/summary.json']: JSON.stringify(data, null, 2),
    stdout: JSON.stringify({
      valid: data.metrics.valid_ops?.values.count || 0,
      invalid: data.metrics.invalid_ops?.values.count || 0,
      dropped: data.metrics.dropped_iterations?.values.count || 0,
    }) + '\n',
  };
}
