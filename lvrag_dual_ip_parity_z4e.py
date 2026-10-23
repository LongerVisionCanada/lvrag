#!/usr/bin/env python3
"""Read-only real legacy GuanGong vs generic GuanGong parity audit.
No external network, writes, or changes to frozen release contents.
"""
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys


def need(test, why):
    if not test:
        raise RuntimeError(why)


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def snapshot(root):
    return {p.relative_to(root).as_posix(): sha(p) for p in root.rglob('*') if p.is_file()}


def cases_from_legacy(source):
    tree = ast.parse(source.read_text(encoding='utf-8'), filename=str(source))
    matches = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == 'selftest':
            for child in ast.walk(node):
                if isinstance(child, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'cases' for t in child.targets):
                    matches.append(ast.literal_eval(child.value))
    need(len(matches) == 1, 'legacy selftest cases not statically recoverable')
    cases = matches[0]
    need(len(cases) == 8, 'unexpected legacy test count')
    need(all(isinstance(q, str) and status in ('evidence_found', 'insufficient_evidence') and isinstance(ids, set)
             for q, status, ids in cases), 'invalid legacy cases')
    return cases


def legacy_result(src, gg, q):
    completed = subprocess.run([sys.executable, str(src), '--release', str(gg), '--top-k', '4', 'retrieve', q],
                               capture_output=True, text=True, timeout=30)
    need(completed.returncode == 0, f'legacy retrieval failed for {q}: {completed.stderr[-600:]}')
    output = completed.stdout.strip()
    decoder = json.JSONDecoder()
    candidates = []
    for start, char in enumerate(output):
        if char != '{':
            continue
        try:
            obj, _ = decoder.raw_decode(output[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get('status') in ('evidence_found', 'insufficient_evidence'):
            candidates.append(obj)
    need(len(candidates) == 1, f'cannot uniquely parse legacy response for {q}: {output[:350]}')
    return candidates[0]


def fields(result):
    evidence = result.get('evidence', [])
    need(isinstance(evidence, list), 'bad evidence array')
    ids = [item.get('knowledge_id', item.get('id')) for item in evidence]
    need(len(ids) == len(set(ids)) and all(isinstance(x, str) for x in ids), 'duplicate/invalid evidence IDs')
    return result.get('status'), set(ids)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', type=Path, required=True)
    ap.add_argument('--legacy', type=Path, required=True)
    ap.add_argument('--generic-gg', type=Path, required=True)
    ap.add_argument('--generic-zgl', type=Path, required=True)
    args = ap.parse_args()
    roots = [p.resolve(strict=True) for p in (args.legacy, args.generic_gg, args.generic_zgl)]
    need(len(set(roots)) == 3, 'input release directories must be distinct')
    old_gg, new_gg, zgl = roots
    snapshots = [snapshot(p) for p in roots]
    need(all(s for s in snapshots), 'empty release folder')
    runtime = args.repo / 'lvrag_universal_preview_v0_2.py'
    need(sha(runtime) == '57ac8c45194ca76e2029482ea244edb3ef585f15bd3c5269280a1f1553df4f57', 'universal runtime SHA changed')
    spec = importlib.util.spec_from_file_location('lvrag_universal_parity_runtime', runtime)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    gg_release = mod.load_release(new_gg)
    zgl_release = mod.load_release(zgl)
    need(gg_release[0] == 'guangong' and zgl_release[0] == 'zhugeliang', 'release IP mismatch')
    source = old_gg / 'lvrag_retrieve.py'
    cases = cases_from_legacy(source)
    passed = 0
    for q, expected_status, expected_ids in cases:
        old = legacy_result(source, old_gg, q)
        new = mod.retrieve('guangong', q, 4, gg_release)
        os_, oi = fields(old)
        ns, ni = fields(new)
        good = os_ == ns == expected_status and oi == ni == expected_ids
        print(('PASS' if good else 'FAIL'), repr(q), 'old=', os_, sorted(oi), 'new=', ns, sorted(ni))
        need(good, 'legacy-vs-generic disagreement')
        passed += 1
    need(fields(mod.retrieve('guangong', '诸葛亮在哪里去世？', 4, zgl_release)) == ('unsupported_ip_id', set()), 'wrong-IP ZGL access')
    need(fields(mod.retrieve('zhugeliang', '关羽字什么？', 4, gg_release)) == ('unsupported_ip_id', set()), 'wrong-IP GG access')
    print('PASS cross-IP rejection in both directions')
    for path, old in zip(roots, snapshots):
        need(snapshot(path) == old, 'release tree mutated: ' + str(path))
    print('PASS release bytes unchanged')
    print(f'Z4-E PARITY PASS: {passed}/8 legacy cases; both IP boundaries; READ ONLY')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('FAIL CLOSED:', error, file=sys.stderr)
        sys.exit(1)
