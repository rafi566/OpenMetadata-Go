// SPDX-License-Identifier: Apache-2.0

package tableread

import (
	"context"
	"errors"

	"github.com/jackc/pgx/v5/pgxpool"
)

type Store struct{ Pool *pgxpool.Pool }

func Open(ctx context.Context) (*Store, error) {
	config, err := pgxpool.ParseConfig("")
	if err != nil {
		return nil, errors.New("invalid Go PostgreSQL configuration")
	}
	config.MaxConns = 4
	config.MinConns = 0
	config.ConnConfig.StatementCacheCapacity = 32
	config.ConnConfig.DescriptionCacheCapacity = 32
	config.ConnConfig.RuntimeParams["default_transaction_read_only"] = "on"
	config.ConnConfig.RuntimeParams["statement_timeout"] = "200"
	pool, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil {
		return nil, errors.New("cannot initialize Go PostgreSQL pool")
	}
	if err = pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, errors.New("Go PostgreSQL connection failed")
	}
	return &Store{Pool: pool}, nil
}

func (s *Store) Read(ctx context.Context, id string) (Snapshot, error) {
	var snapshot Snapshot
	err := s.Pool.QueryRow(ctx, plainTableSQL, id).Scan(&snapshot.Entity, &snapshot.Service, &snapshot.Enriched)
	return snapshot, err
}

// shortcut: enriched tables stay on Java; expand only with their differential contracts.
const plainTableSQL = `
SELECT t.json,
       ref.service,
       EXISTS (SELECT 1 FROM entity_relationship owner
               WHERE owner.toid=ANY(ARRAY[t.id, schema.id, db.id, service.id])
                 AND owner.relation=8)
       OR EXISTS (SELECT 1 FROM tag_usage tag
                  WHERE tag.targetfqnhash=ANY(ARRAY[t.fqnhash,schema.fqnhash,db.fqnhash,service.namehash])
                     OR tag.targetfqnhash LIKE t.fqnhash || '.%')
       OR EXISTS (SELECT 1 FROM field_relationship field
                  WHERE field.fromfqnhash=t.fqnhash OR field.tofqnhash=t.fqnhash
                     OR field.fromfqnhash LIKE t.fqnhash || '.%'
                     OR field.tofqnhash LIKE t.fqnhash || '.%')
       OR schema.json->>'retentionPeriod' IS NOT NULL
       OR db.json->>'retentionPeriod' IS NOT NULL
       OR service.json->>'retentionPeriod' IS NOT NULL
FROM table_entity t
JOIN database_schema_entity schema ON schema.id=t.json->'databaseSchema'->>'id'
JOIN database_entity db ON db.id=t.json->'database'->>'id'
JOIN entity_relationship parent ON parent.toid=db.id AND parent.toentity='database'
  AND parent.fromentity='databaseService' AND parent.relation=0 AND parent.deleted=false
JOIN dbservice_entity service ON service.id=parent.fromid
CROSS JOIN LATERAL (SELECT jsonb_strip_nulls(jsonb_build_object(
  'id', service.id, 'type', 'databaseService',
  'name', service.json->'name', 'fullyQualifiedName', service.json->'fullyQualifiedName',
  'description', service.json->'description',
  'displayName', COALESCE(NULLIF(service.json->>'displayName',''),service.json->>'name'),
  'deleted', service.deleted)) AS service) ref
WHERE t.id=$1 AND t.deleted=false AND schema.deleted=false AND db.deleted=false
  AND service.deleted=false
  AND octet_length(t.json::text)+octet_length(ref.service::text)<=262144
`
