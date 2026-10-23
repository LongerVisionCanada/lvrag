#!/usr/bin/env python3
"""Convert a CHECKSUM-VALID GuanGong legacy release to an independent generic preview release.
Never writes or modifies the source tree. Source Python is parsed as AST, never imported.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

BASE_FILES = ('approved-atomic-index.json', 'retrieval-records.json', 'release-manifest.json')
OUTPUT_FILES = ('approved-atomic-index.json', 'retrieval-records.json', 'retrieval-policy.json')


def need(ok, message):
    if not ok:
        raise ValueError(message)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def filehash(p):
    need(p.is_file() and not p.is_symlink(), 'missing/unsafe file: ' + str(p))
    return sha(p.read_bytes())


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def encode(o):
    return (json.dumps(o, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')


def create_file(p, raw):
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())


def parse_legacy_policy(py):
    tree = ast.parse(py.read_text(encoding='utf-8'), filename=str(py))
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ('TOPICS', 'UNSUPPORTED'):
                    try:
                        values[target.id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError, SyntaxError) as exc:
                        raise ValueError('legacy policy is not a static literal: ' + target.id) from exc
    need(set(values) == {'TOPICS', 'UNSUPPORTED'}, 'cannot extract exact TOPICS/UNSUPPORTED literals')
    topics, blocked = values['TOPICS'], values['UNSUPPORTED']
    need(isinstance(topics, (tuple, list)) and len(topics) > 0, 'TOPICS malformed')
    need(isinstance(blocked, (tuple, list, set)) and len(blocked) > 0, 'UNSUPPORTED malformed')
    need(all(isinstance(x, str) and x for x in blocked), 'unsupported phrase invalid')
    output = []
    for entry in topics:
        need(isinstance(entry, (tuple, list)) and len(entry) == 3, 'legacy topic format changed')
        label, triggers, suffixes = entry
        need(isinstance(label, str), 'bad topic label')
        need(isinstance(triggers, (tuple, list)) and triggers and all(isinstance(x, str) and x for x in triggers), 'bad phrases')
        need(isinstance(suffixes, (tuple, list)) and suffixes and all(re.fullmatch(r'\d{4}', x) for x in suffixes), 'bad suffixes')
        ids = ['GG-ATOM-' + x for x in suffixes]
        output.append({'label': label, 'phrases': list(triggers), 'ids': ids})
    return {'schema': 'lvrag-policy-v0.1', 'ip_id': 'guangong',
            'blocked_phrases': sorted(blocked), 'topics': output}


def validate_legacy(src):
    need(src.is_dir() and not src.is_symlink(), 'source directory invalid')
    checks = (src / 'SHA256SUMS').read_text(encoding='utf-8').splitlines()
    need(len(checks) == 3, 'unexpected legacy checksum count')
    expected = {name: filehash(src / name) for name in BASE_FILES}
    expected_lines = {f'{h}  {n}' for n, h in expected.items()}
    need(set(checks) == expected_lines, 'legacy SHA256SUMS mismatch')
    index, recs, mani = [read(src / n) for n in BASE_FILES]
    need(index.get('schema') == 'lvrag-approved-atomic-v1', 'legacy index schema')
    need(recs.get('schema') == 'lvrag-retrieval-records-v0.1', 'legacy records schema')
    need(mani.get('schema') == 'lvrag-guangong-release-v0.1', 'legacy manifest schema')
    need(index.get('ip') == recs.get('ip') == mani.get('ip') == 'guangong', 'legacy IP identity')
    need(all(x.get('attribution_only') is True for x in (index,recs,mani)), 'legacy attribution-only flag absent')
    need(mani.get('index_sha256') == expected['approved-atomic-index.json'], 'legacy manifest index digest mismatch')
    need(mani.get('source_sha256') == index.get('source_sha256'), 'legacy source provenance mismatch')
    need(mani.get('decisions_sha256') == index.get('decisions_sha256'), 'legacy decision provenance mismatch')
    docs, records = index.get('documents'), recs.get('documents')
    need(isinstance(docs, list) and isinstance(records, list) and len(docs) == len(records) == mani.get('record_count') == 10, 'legacy record count')
    ids = [f'GG-ATOM-{x:04d}' for x in range(1,11)]
    need([d.get('id') for d in docs] == [d.get('id') for d in records] == ids, 'legacy IDs/order mismatch')
    need(mani.get('record_ids') == ids, 'legacy manifest IDs mismatch')
    for d, r in zip(docs, records):
        need({k:v for k,v in d.items() if k not in {'vector','source_sha256','span'}} == r, 'legacy record/index fields inconsistent: ' + d['id'])
        need(isinstance(d.get('vector'), list) and len(d['vector']) == 768, 'legacy vector dimension')
        need(isinstance(d.get('span'), list) and len(d['span']) == 2, 'legacy source span')
        need(d.get('source_sha256') == index.get('source_sha256'), 'legacy source sha mismatch in record')
    script = src / 'lvrag_retrieve.py'
    need(script.is_file() and not script.is_symlink(), 'missing legacy retriever')
    policy = parse_legacy_policy(script)
    valid_ids = set(ids)
    need(all(set(t['ids']) <= valid_ids for t in policy['topics']), 'legacy topic references unknown cards')
    need(all(t['ids'] for t in policy['topics']), 'empty topic mapping')
    return index,recs,mani,policy,expected


def adapt(src,dst):
    idx, recs, legacy_mani, policy, digests = validate_legacy(src)
    need(not dst.exists(), 'destination already exists; REFUSING OVERWRITE')
    docs=[]
    for d in idx['documents']:
        new=dict(d)
        new['quote_span']=new.pop('span')
        new['source_layer']='legacy-guangong-attributed-record'
        new['evidence_limitation']=d.get('review_note') or '仅限关公原发布包已审核的史料归属式断言；不得额外推断。'
        new['related_annotations']=[]
        docs.append(new)
    out_index=dict(idx)
    out_index['ip_id']=out_index.pop('ip')
    out_index['schema']='lvrag-legacy-adapted-index-v0.1'
    out_index['final_review_packet_sha256']=digests['release-manifest.json']
    out_index['documents']=docs
    out_recs={'schema':'lvrag-retrieval-records-v0.1','ip_id':'guangong',
              'records':[{k:v for k,v in d.items() if k!='vector'} for d in docs]}
    need(dst.parent.is_dir(), 'destination parent must exist')
    dst.mkdir(mode=0o700)
    try:
        contents={'approved-atomic-index.json':encode(out_index), 'retrieval-records.json':encode(out_recs), 'retrieval-policy.json':encode(policy)}
        for name,raw in contents.items():
            create_file(dst / name,raw)
        file_shas={name:filehash(dst/name) for name in OUTPUT_FILES}
        mani={'schema':'lvrag-generic-preview-v0.1', 'ip_id':'guangong',
              'review_scope':'attributed_historical_record_only',
              'source_index_sha256': file_shas['approved-atomic-index.json'],
              'source_packet_sha256':digests['release-manifest.json'],
              'source_decisions_sha256':idx['decisions_sha256'],
              'legacy_source_files_sha256':digests, 'legacy_policy_script_sha256':filehash(src/'lvrag_retrieve.py'),
              'files':file_shas}
        create_file(dst/'release-manifest.json',encode(mani))
        sums=''.join(f'{filehash(dst/name)}  {name}\n' for name in (*OUTPUT_FILES,'release-manifest.json'))
        create_file(dst/'SHA256SUMS',sums.encode())
    except BaseException:
        print('FAIL: incomplete destination may exist; do not reuse',file=sys.stderr)
        raise
    print('ADAPT PASS:',dst)
    print('RECORDS:',len(docs),'TOPICS:',len(policy['topics']))
    print('MANIFEST_SHA256:',filehash(dst/'release-manifest.json'))
    print('SOURCE: read-only',src)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True)
    p.add_argument('--release',required=True)
    p.add_argument('--mode',choices=['audit','adapt'],required=True)
    a=p.parse_args()
    src=Path(a.source).expanduser().absolute()
    dst=Path(a.release).expanduser().absolute()
    if a.mode=='audit':
        _,_,_,policy,_=validate_legacy(src)
        print('LEGACY AUDIT PASS: 10 cards;',len(policy['topics']),'topic policies; no writes')
    else:
        adapt(src,dst)

if __name__=='__main__':
    try: main()
    except (ValueError,OSError,KeyError,TypeError,AssertionError,json.JSONDecodeError) as exc:
        print('FAIL CLOSED:',exc,file=sys.stderr)
        sys.exit(1)
