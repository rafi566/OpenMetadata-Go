#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Rebuild the source-bound policy from unchanged schemas and fresh Java evidence."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import urllib.parse

BASELINE = '2f0d4a4a42663d565b23c6018f098cfb07516fd6'
MANIFEST = 'bc57fb1ceb163f2c724aa0436d70698388a879c4d4b5ba7f2cf46fab3a6b7584'
LIMIT = 256 << 20


def sha(b):
    return hashlib.sha256(b).hexdigest()


def pairs(items):
    out = {}
    for k, v in items:
        if k in out:
            raise ValueError('duplicate decoded key: ' + k)
        out[k] = v
    return out


def load(b):
    return json.loads(b, object_pairs_hook=pairs, parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))


def esc(s):
    return s.replace('~', '~0').replace('/', '~1')


def inventory(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError('root must be a physical directory')
    docs, entries, refs, patterns = [], [], [], []
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            p = Path(directory) / name
            mode = p.lstat().st_mode
            if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise ValueError('symlink/nonregular: ' + str(p))
            if len(name.encode()) > 240:
                raise ValueError('filename exceeds 240 bytes')
        for name in sorted(files):
            if not name.endswith('.json'):
                continue
            p = Path(directory) / name
            if p.stat().st_size > 16 << 20 or len(docs) >= 10000:
                raise ValueError('document bounds')
            raw = p.read_bytes()
            value = load(raw)
            if not isinstance(value, dict):
                raise ValueError('legacy source document must be an object')
            rel = p.relative_to(root).as_posix()
            digest = sha(raw)
            docs.append(dict(path=rel, sha256=digest, id=value.get('$id'), dialect=value.get('$schema'), physical='https://open-metadata.org/schema/' + rel))
            def walk(v, ptr='', depth=0):
                if (isinstance(v, (dict, list)) and depth >= 256) or len(entries) >= 1000000:
                    raise ValueError('structure bounds')
                entries.append(dict(path=rel, pointer=ptr))
                if isinstance(v, dict):
                    for k in sorted(v):
                        pointer = ptr + '/' + esc(k)
                        if k in ('$ref', '$dynamicRef', '$recursiveRef'):
                            refs.append(dict(path=rel, pointer=pointer, keyword=k, value=v[k]))
                        if k == 'pattern' and isinstance(v[k], str):
                            patterns.append(dict(path=rel, pointer=pointer, sha256=digest, value=v[k]))
                        walk(v[k], pointer, depth + 1)
                elif isinstance(v, list):
                    for i, item in enumerate(v):
                        walk(item, ptr + '/' + str(i), depth + 1)
            walk(value)
    # Historical manifest orders path components (Path ordering), not flat strings.
    docs.sort(key=lambda d: Path(d['path']).parts)
    for rows in (refs, patterns, entries):
        rows.sort(key=lambda d: (d['path'], d['pointer']))
    manifest = ''.join(d['sha256'] + '  ' + d['path'] + '\n' for d in docs)
    if sha(manifest.encode()) != MANIFEST:
        raise ValueError('source manifest drift; refusing to re-pin')
    return docs, entries, refs, patterns, manifest


def samples():
    out = ['', 'a', 'abc', 'a\nb', '::', ':', ':a:', 'a::b', 'a>b', 'a"b', '<', '>', '"', ' ', '.', '_-', 'a_1', "a'b-c.d", 'é', '中文', 'a\u0301', '\u0301', '\u0661', '\u203f', '\u200c', '\u200d', '\u00a0', '\u2007', '\u202f', '\ufeff', 'a@example.com', 'a\v@example.com', '<#E::tables::name>', '<#E::tábles::name>', '<#E::a\u200c::name>', '<#E::tables::a:b>', '<#E::tables::a::b>', '<#E::tables::a:::b>', '#123abc', 'TASK-123', 'username:abc', 'sha256:' + 'a'*64, 'https://open-metadata.org/ontology-extension/Name', 'rdf/ontology-packs/foo.ttl']
    out += [chr(c) for c in (0x1e4d0, 0x11f02, 0x1c89, 0x1e290, 0x1f600)]
    out += ['a' + chr(c) + 'b' for c in range(32)] + ['a' + chr(c) for c in range(32)]
    out += ['abc' + t for t in ('\n', '\r', '\r\n', '\u0085', '\u2028', '\u2029')]
    out += ['a'*4096, ':'*4096, 'a' * 4094 + '::', 'a.'*2000 + '@x.com']
    return list(dict.fromkeys(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--finalize', type=Path)
    a = ap.parse_args()
    docs, entries, refs, pats, manifest = inventory(a.root)
    out = a.output
    out.mkdir(parents=True, exist_ok=True)
    emitted = 0
    def write(p, data):
        nonlocal emitted
        b = data.encode() if isinstance(data, str) else data
        emitted += len(b)
        if emitted > LIMIT:
            raise ValueError('output exceeds 256 MiB')
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)
    def js(p, data):
        write(p, json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    script_sha = sha(Path(__file__).read_bytes())
    js(out/'inventory.json', dict(baseline=BASELINE, script_sha256=script_sha, manifest_sha256=MANIFEST, documents=docs, patterns=pats, references=refs, raw_entries=len(entries)))
    write(out/'source.sha256', manifest)
    ps, ss = sorted(set(p['value'] for p in pats)), samples()
    if len(ps) > 1000 or len(ss) > 512 or any(len(s) > 4096 for s in ps + ss):
        raise ValueError('observer input bounds')
    js(out/'regex-input.json', dict(patterns=ps, samples=ss))
    for name, seq in [('regex-patterns.b64', ps), ('regex-samples.b64', ss)]:
        write(out/name, ''.join(base64.b64encode(v.encode()).decode() + '\n' for v in seq))
    if not a.finalize:
        print(json.dumps(dict(documents=len(docs), references=len(refs), entries=len(entries), patterns=len(ps), samples=len(ss), manifest_sha256=MANIFEST)))
        return
    obs = a.finalize
    receipt = load((obs/'observer-receipt.json').read_bytes())
    for key in ('word', 'regex'):
        if receipt[key]['exit'] != 0:
            raise ValueError('observer did not succeed')
    for name in ('RegexObserver.java', 'regex-patterns.b64', 'regex-samples.b64', 'java-regex.tsv', 'java-word-ranges.tsv'):
        if sha((obs/name).read_bytes()) != receipt['sha256'][name]:
            raise ValueError('observer hash mismatch: ' + name)
    for name in ('regex-patterns.b64', 'regex-samples.b64'):
        if (out/name).read_bytes() != (obs/name).read_bytes():
            raise ValueError('observer input drift')
    ranges = [list(map(int, line.split('\t'))) for line in (obs/'java-word-ranges.tsv').read_text().splitlines()]
    rows = (obs/'java-regex.tsv').read_text().splitlines()
    if len(rows) != len(ps)*len(ss):
        raise ValueError('incomplete observer Cartesian product')
    for i, row in enumerate(rows):
        p, s, find, match = row.split('\t')
        if (int(p), int(s)) != divmod(i, len(ss)) or find not in ('true', 'false') or match not in ('true', 'false'):
            raise ValueError('invalid observer row')
    aliases = {}
    physical = {d['physical']: d['path'] for d in docs}
    for d in docs:
        aliases.setdefault(d['id'], []).append(d['path'])
    targets = []
    entry_keys = {e['path']+'#'+e['pointer'] for e in entries}
    for ref in refs:
        target = urllib.parse.urljoin('https://open-metadata.org/schema/' + ref['path'], ref['value'])
        url, fragment = urllib.parse.urldefrag(target)
        paths = [physical[url]] if url in physical else aliases.get(url, [])
        if len(paths) != 1:
            raise ValueError('unresolved/ambiguous source ref: ' + target)
        pointer = urllib.parse.unquote(fragment)
        if paths[0] + '#' + pointer not in entry_keys:
            raise ValueError('missing target pointer: ' + target)
        targets.append(dict(ref, target_path=paths[0], target_pointer=pointer))
    module = Path(__file__).resolve().parent.parent
    policy = dict(baseline=BASELINE, manifest_sha256=MANIFEST, documents=docs, patterns=pats, java_word_ranges=ranges, producer_sha256=script_sha, mismatches=[d for d in docs if d['id'] != d['physical']], collisions=[dict(id=k, members=[d for d in docs if d['path'] in v], physical_priority=physical.get(k)) for k, v in sorted(aliases.items()) if len(v) > 1])
    js(module/'internal/schema/legacy-profile.json', policy)
    dest = module/'testdata/schemas'
    for name in ('regex-input.json', 'regex-patterns.b64', 'regex-samples.b64'):
        write(dest/name, (out/name).read_bytes())
    for name in ('java-regex.tsv', 'java-word-ranges.tsv'):
        write(dest/name, (obs/name).read_bytes())
    js(dest/'regex-provenance.json', dict(baseline=BASELINE, manifest_sha256=MANIFEST, producer_sha256=script_sha, observer=receipt))
    js(dest/'reference-targets.json', targets)
    print(json.dumps(dict(documents=len(docs), references=len(refs), entries=len(entries), patterns=len(ps), samples=len(ss), observations=len(rows), word_ranges=len(ranges))))


if __name__ == '__main__':
    main()
