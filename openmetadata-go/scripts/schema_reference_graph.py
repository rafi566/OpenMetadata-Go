#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Independently enumerate the immutable corpus's active schema/reference graph."""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import unquote, urldefrag, urljoin

from rebuild_schema_policy import inventory, load, esc

BASE = 'https://open-metadata.org/schema/'


def children(value, pointer, draft):
    if not isinstance(value, dict):
        return []
    modern = 'draft-07' not in draft
    latest = modern and '2019-09' not in draft
    if not modern and '$ref' in value:
        return []
    result = []
    for keyword in ('$defs', 'definitions', 'properties', 'patternProperties', 'dependentSchemas'):
        if not modern and keyword in ('$defs', 'dependentSchemas'):
            continue
        if isinstance(value.get(keyword), dict):
            result.extend((pointer + '/' + keyword + '/' + esc(name), keyword)
                          for name in sorted(value[keyword]))
    for keyword in ('additionalProperties', 'unevaluatedProperties', 'propertyNames', 'contains',
                    'additionalItems', 'unevaluatedItems', 'not', 'if', 'then', 'else', 'contentSchema'):
        if latest and keyword == 'additionalItems':
            continue
        if not modern and keyword in ('unevaluatedProperties', 'unevaluatedItems', 'contentSchema'):
            continue
        if keyword in value:
            result.append((pointer + '/' + keyword, keyword))
    for keyword in ('allOf', 'anyOf', 'oneOf', 'prefixItems', 'items'):
        if keyword == 'prefixItems' and not latest:
            continue
        item = value.get(keyword)
        if isinstance(item, list):
            result.extend((pointer + '/' + keyword + '/' + str(i), keyword) for i in range(len(item)))
        elif keyword == 'items' and keyword in value:
            result.append((pointer + '/' + keyword, keyword))
    if isinstance(value.get('dependencies'), dict):
        result.extend((pointer + '/dependencies/' + esc(name), 'dependencies')
                      for name, child in sorted(value['dependencies'].items()) if not isinstance(child, list))
    return sorted(result)


def components(nodes, edges):
    """Iterative Kosaraju avoids recursion proportional to corpus graph size."""
    outgoing = {node: [] for node in nodes}
    incoming = {node: [] for node in nodes}
    for edge in edges:
        outgoing[edge['source']].append(edge['target'])
        incoming[edge['target']].append(edge['source'])
    seen, order = set(), []
    for start in sorted(nodes):
        if start in seen:
            continue
        stack = [(start, False)]
        while stack:
            node, done = stack.pop()
            if done:
                order.append(node)
            elif node not in seen:
                seen.add(node)
                stack.append((node, True))
                stack.extend((child, False) for child in sorted(outgoing[node], reverse=True) if child not in seen)
    seen, result = set(), []
    for start in reversed(order):
        if start in seen:
            continue
        group, stack = [], [start]
        seen.add(start)
        while stack:
            node = stack.pop()
            group.append(node)
            for parent in incoming[node]:
                if parent not in seen:
                    seen.add(parent)
                    stack.append(parent)
        if len(group) > 1 or start in outgoing[start]:
            result.append(sorted(group))
    return sorted(result)


def build(root):
    documents, _, raw_references, _, manifest = inventory(root)
    raw, drafts, aliases = {}, {}, {}
    for doc in documents:
        path = doc['path']
        value = load((root / path).read_bytes())
        drafts[path] = value['$schema']
        aliases.setdefault(value['$id'], []).append(path)
        stack = [(value, '')]
        while stack:
            item, pointer = stack.pop()
            raw[(path, pointer)] = item
            if isinstance(item, dict):
                # This producer is deliberately source-bound: fail on a newly
                # introduced nested resource instead of guessing its scope.
                if pointer and ('$id' in item or '$schema' in item):
                    raise ValueError('nested resource requires explicit graph support: ' + path + '#' + pointer)
                stack.extend((child, pointer + '/' + esc(key)) for key, child in item.items())
            elif isinstance(item, list):
                stack.extend((child, pointer + '/' + str(i)) for i, child in enumerate(item))
    physical = {BASE + doc['path']: doc['path'] for doc in documents}

    def resolve(path, ref):
        url, fragment = urldefrag(urljoin(BASE + path, ref))
        targets = [physical[url]] if url in physical else aliases.get(url, [])
        pointer = unquote(fragment)
        if len(targets) != 1 or (targets[0], pointer) not in raw:
            raise ValueError('unresolved/ambiguous reference: ' + path + ' -> ' + ref)
        return targets[0], pointer

    references = []
    for ref in raw_references:
        if ref['keyword'] != '$ref':
            raise ValueError('dynamic/recursive scope requires explicit graph support')
        path, pointer = resolve(ref['path'], ref['value'])
        references.append(dict(ref, target_path=path, target_pointer=pointer))
    nodes, edges = {}, []
    pending = [(doc['path'], '') for doc in documents]
    # The explicit legacy profile admits reference objects inside unknown
    # annotation containers independently, without inventing containment edges.
    pending.extend((ref['path'], ref['pointer'].rsplit('/', 1)[0]) for ref in references)
    while pending:
        path, pointer = pending.pop()
        locator = path + '#' + pointer
        if locator in nodes:
            continue
        value = raw[(path, pointer)]
        if not isinstance(value, (dict, bool)):
            raise ValueError('not a schema: ' + locator)
        types = value.get('type', []) if isinstance(value, dict) else []
        if isinstance(types, str):
            types = [types]
        nodes[locator] = dict(path=path, pointer=pointer, types=types)
        for child, keyword in children(value, pointer, drafts[path]):
            edges.append(dict(source=locator, target=path + '#' + child, kind='containment', keyword=keyword))
            pending.append((path, child))
        if isinstance(value, dict) and '$ref' in value:
            target_path, target_pointer = resolve(path, value['$ref'])
            edges.append(dict(source=locator, target=target_path + '#' + target_pointer, kind='reference', keyword='$ref'))
            pending.append((target_path, target_pointer))
    edges.sort(key=lambda edge: (edge['source'], edge['target'], edge['kind'], edge['keyword']))
    active_refs = {(edge['source'] + '/$ref') for edge in edges if edge['kind'] == 'reference'}
    raw_refs = {ref['path'] + '#' + ref['pointer'] for ref in references}
    if active_refs != raw_refs:
        raise ValueError('raw and admitted reference locators differ: ' + repr(sorted(active_refs ^ raw_refs)[:30]))
    groups = components(nodes, edges)
    return dict(baseline='2f0d4a4a42663d565b23c6018f098cfb07516fd6',
                producer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                source_manifest_sha256=hashlib.sha256(manifest.encode()).hexdigest(),
                documents=sorted(documents, key=lambda doc: doc['path']), references=references,
                nodes=[nodes[key] for key in sorted(nodes)], edges=edges, recursive_components=groups)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    graph = build(args.root)
    data = (json.dumps(graph, ensure_ascii=False, indent=2) + '\n').encode()
    if len(data) > 256 << 20:
        raise ValueError('graph output exceeds 256 MiB')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    print(json.dumps({key: len(graph[key]) for key in ('documents', 'references', 'nodes', 'edges', 'recursive_components')}, sort_keys=True))


if __name__ == '__main__':
    main()
