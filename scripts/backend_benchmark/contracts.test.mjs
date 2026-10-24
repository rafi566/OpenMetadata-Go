import assert from 'node:assert/strict';
import test from 'node:test';
import { requestPlan, validResponse } from './contracts.mjs';

const table = {
  id: '00000000-0000-0000-0000-000000000001',
  name: 'table_0000000',
  fullyQualifiedName: 'svc.db.public.table_0000000',
  schemaFqn: 'svc.db.public',
  schemaTableCount: 2,
};
const second = {
  ...table,
  id: '00000000-0000-0000-0000-000000000002',
  name: 'table_0000001',
  fullyQualifiedName: 'svc.db.public.table_0000001',
};
const columns = [
  { name: 'id', dataType: 'BIGINT', description: 'Primary key' },
  { name: 'name', dataType: 'VARCHAR', dataLength: 255 },
  { name: 'created_at', dataType: 'TIMESTAMP' },
  { name: 'data', dataType: 'JSON' },
];
const entity = {
  id: table.id,
  name: table.name,
  fullyQualifiedName: table.fullyQualifiedName,
  databaseSchema: { fullyQualifiedName: table.schemaFqn },
  columns,
  version: 0.1,
  deleted: false,
};

test('HTTP 200 with an empty/error payload cannot count as useful throughput', () => {
  for (const operation of ['detail', 'list', 'search', 'patch']) {
    assert.equal(validResponse(operation, 200, {}, table, 'changed'), false);
    assert.equal(validResponse(operation, 200, { message: 'error' }, table, 'changed'), false);
    assert.equal(validResponse(operation, 401, entity, table, 'changed'), false);
  }
});

test('detail requires the expected entity and its column metadata', () => {
  assert.equal(validResponse('detail', 200, entity, table), true);
  assert.equal(validResponse('detail', 200, { ...entity, id: second.id }, table), false);
  assert.equal(validResponse('detail', 200, { ...entity, columns: [] }, table), false);
  assert.equal(validResponse('detail', 200, { ...entity, deleted: undefined }, table), false);
});

test('malformed FQN values are rejected without throwing', () => {
  for (const fullyQualifiedName of [null, 42, [], {}]) {
    assert.equal(validResponse('detail', 200, { ...entity, fullyQualifiedName }, table), false);
  }
});

test('list requires actual rows from the selected schema and the right total', () => {
  const page = {
    data: [entity, { ...entity, id: second.id, name: second.name, fullyQualifiedName: second.fullyQualifiedName }],
    paging: { total: 2 },
  };
  assert.equal(validResponse('list', 200, page, table), true);
  assert.equal(validResponse('list', 200, { ...page, data: [] }, table), false);
  assert.equal(validResponse('list', 200, { ...page, paging: { total: 0 } }, table), false);
  const wrongSchema = { ...entity, databaseSchema: { fullyQualifiedName: 'other.schema' } };
  assert.equal(validResponse('list', 200, { ...page, data: [entity, wrongSchema] }, table), false);
});

test('search must find the exact ID/FQN without timeouts or failed shards', () => {
  const response = {
    timed_out: false,
    _shards: { failed: 0 },
    hits: { total: { value: 1 }, hits: [{ _id: table.id, _source: entity }] },
  };
  assert.equal(validResponse('search', 200, response, table), true);
  assert.equal(validResponse('search', 200, { ...response, timed_out: true }, table), false);
  assert.equal(validResponse('search', 200, { ...response, _shards: { failed: 1 } }, table), false);
  response.hits.hits[0]._id = second.id;
  assert.equal(validResponse('search', 200, response, table), false);
});

test('patch must preserve the table and return the requested description', () => {
  assert.equal(validResponse('patch', 200, { ...entity, description: 'changed' }, table, 'changed'), true);
  assert.equal(validResponse('patch', 200, { ...entity, description: 'old' }, table, 'changed'), false);
});

test('the request schedule retains the 80/20 operation mix and covers every read path', () => {
  const counts = { detail: 0, list: 0, search: 0, patch: 0 };
  for (let iteration = 0; iteration < 100; iteration++) {
    counts[requestPlan(iteration, [table, second], 'benchmark').operation]++;
  }
  assert.deepEqual(counts, { detail: 40, list: 20, search: 20, patch: 20 });
});

test('adjacent writes target different tables and encode an actual JSON Patch', () => {
  const first = requestPlan(8, [table, second], 'benchmark');
  const next = requestPlan(9, [table, second], 'benchmark');
  assert.equal(first.method, 'PATCH');
  assert.equal(first.path, '/tables/00000000-0000-0000-0000-000000000001');
  assert.notEqual(first.table.id, next.table.id);
  assert.deepEqual(JSON.parse(first.body), [
    { op: 'add', path: '/description', value: 'bettermetadata-benchmark-8' },
  ]);
});

test('search requests scope the query to the selected fully qualified name', () => {
  const request = requestPlan(6, [table, second], 'benchmark');
  assert.equal(request.method, 'GET');
  assert.equal(request.path, '/search/query?q=fullyQualifiedName%3A%22svc.db.public.table_0000000%22&index=table_search_index&size=5');
});

test('warmup and measurement writes cannot become accidental no-ops', () => {
  const warmup = requestPlan(8, [table, second], 'warmup');
  const measurement = requestPlan(8, [table, second], 'measured');
  assert.notEqual(warmup.description, measurement.description);
});
