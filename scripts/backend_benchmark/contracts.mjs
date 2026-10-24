const columnTypes = [
  ['id', 'BIGINT'],
  ['name', 'VARCHAR'],
  ['created_at', 'TIMESTAMP'],
  ['data', 'JSON'],
];

function catalogTable(value, schemaFqn) {
  return (
    typeof value?.id === 'string' && value.id.length > 0 &&
    typeof value.name === 'string' &&
    typeof value.fullyQualifiedName === 'string' &&
    value.fullyQualifiedName.startsWith(`${schemaFqn}.`) &&
    value.databaseSchema?.fullyQualifiedName === schemaFqn &&
    value.deleted === false && Number.isFinite(value.version) && value.version >= 0.1 &&
    Array.isArray(value.columns) && value.columns.length === columnTypes.length &&
    value.columns.every((column, i) =>
      column?.name === columnTypes[i][0] && column.dataType === columnTypes[i][1] &&
      (column.name !== 'name' || column.dataLength === 255))
  );
}

export function validResponse(operation, status, body, table, description) {
  if (status !== 200 || !body || typeof body !== 'object') return false;
  if (operation === 'search') {
    const hits = body.hits?.hits;
    return body.timed_out === false && body._shards?.failed === 0 &&
      body.hits?.total?.value === 1 && Array.isArray(hits) && hits.length === 1 &&
      hits[0]._id === table.id && hits[0]._source?.name === table.name &&
      hits[0]._source?.fullyQualifiedName === table.fullyQualifiedName &&
      hits[0]._source?.deleted === false;
  }
  if (operation === 'list') {
    const rows = body.data;
    return Array.isArray(rows) && rows.length === Math.min(10, table.schemaTableCount) &&
      body.paging?.total === table.schemaTableCount &&
      new Set(rows.map(row => row?.id)).size === rows.length &&
      rows.every(row => catalogTable(row, table.schemaFqn));
  }
  if (operation !== 'detail' && operation !== 'patch') return false;
  return catalogTable(body, table.schemaFqn) && body.id === table.id &&
    body.name === table.name && body.fullyQualifiedName === table.fullyQualifiedName &&
    (operation !== 'patch' || body.description === description);
}

export function requestPlan(iteration, tables, writeEpoch) {
  if (!Number.isSafeInteger(iteration) || iteration < 0 ||
      !tables || tables.length < 2 || tables.length > 100000 ||
      typeof writeEpoch !== 'string' || !writeEpoch.length || writeEpoch.length > 64) {
    throw new RangeError('Use a nonnegative iteration, 2–100000 fixture tables and a write epoch');
  }
  const slot = iteration % 10;
  const operation = slot < 4 ? 'detail' : slot < 6 ? 'list' : slot < 8 ? 'search' : 'patch';
  const ordinal = operation === 'patch'
    ? Math.floor(iteration / 10) * 2 + slot - 8
    : Math.floor(iteration / 10) * 8 + slot;
  const table = tables[ordinal % tables.length];
  const request = { operation, table, method: 'GET' };
  if (operation === 'list') {
    request.path = `/tables?databaseSchema=${encodeURIComponent(table.schemaFqn)}&limit=10&fields=owners,tags`;
  } else if (operation === 'search') {
    const query = encodeURIComponent(`fullyQualifiedName:"${table.fullyQualifiedName}"`);
    request.path = `/search/query?q=${query}&index=table_search_index&size=5`;
  } else {
    request.path = `/tables/${encodeURIComponent(table.id)}`;
    if (operation === 'detail') {
      request.path += '?fields=owners,tags';
    } else {
      request.method = 'PATCH';
      request.description = `bettermetadata-${writeEpoch}-${iteration}`;
      request.body = JSON.stringify([
        { op: 'add', path: '/description', value: request.description },
      ]);
    }
  }
  return request;
}
