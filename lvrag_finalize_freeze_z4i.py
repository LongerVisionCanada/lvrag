#!/usr/bin/env python3
"""Finalize LVRAG v0.2 local preview freeze, exclusively and fail-closed.

No original file is edited. Creates a separate attestation JSON and SHA256 sidecar.
The user must explicitly have approved the R2 note correction (provided in chat).
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

CANDIDATE_SHA = '40c41b42ba0fb4eafc55ff113a6d6689f9086b7fbd66919783205a4eb12d0cf8'
ENGINE_SHA = '57ac8c45194ca76e2029482ea244edb3ef585f15bd3c5269280a1f1553df4f57'
ADAPTER_SHA = '3ea9fd6e3de0c1f4bf40ac8f7841a5aeb2df448aa943048e00ec8ce9514bab0b'
GG_MANIFEST_SHA = 'c5abc73dd4e4fad18b3bba060ca61af822e178daaa75d94014ddef38cf039d89'
ZGL_MANIFEST_SHA = '4ee781e4f84447d6f097b325376e1f510d2b4d16d1ed1149c4f8ed842631271a'
GG_LEGACY = 'lvrag-guangong-v0.1.0-preview/guangong-release'
ZGL_OLD = 'lvrag-zhugeliang-v0.1.0-preview'
CORRECTION = 'ZGL-ATOM-0010'
OLD_NOTE = '当前引文缺少五丈原地点前文；裴注24存在死亡情形异文，须扩大证据范围。'
NEW_NOTE = '当前陈寿正文引文已明确记载诸葛亮据武功五丈原、与司马懿相持百余日，以及其年八月病逝于军中。裴注24所引《魏书》《汉晋春秋》等对死亡情形或地点存在不同记载，应分别归属，不得混为一致史实。'
RELEASE_FILES = ('approved-atomic-index.json', 'retrieval-records.json', 'retrieval-policy.json', 'release-manifest.json')

def require(ok, reason):
    if not ok:
        raise ValueError(reason)

def readbytes(p):
    require(p.is_file() and not p.is_symlink(), 'missing or unsafe file: ' + str(p))
    return p.read_bytes()

def sha(b):
    return hashlib.sha256(b).hexdigest()

def digest(p):
    return sha(readbytes(p))

def obj(p):
    return json.loads(readbytes(p).decode('utf-8'))

def serialize(x):
    return (json.dumps(x, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')

def check_release(folder, expected_manifest):
    require(folder.is_dir() and not folder.is_symlink(), 'unsafe release directory: ' + str(folder))
    require(digest(folder/'release-manifest.json') == expected_manifest, 'manifest SHA mismatch: ' + str(folder))
    checked = ''.join(f'{digest(folder / name)}  {name}\n' for name in RELEASE_FILES).encode()
    require(readbytes(folder/'SHA256SUMS') == checked, 'SHA256SUMS mismatch: ' + str(folder))
    return {p.name: digest(p) for p in sorted(folder.iterdir()) if p.is_file() and not p.is_symlink()}

def validate(candidate_path):
    require(digest(candidate_path) == CANDIDATE_SHA, 'Z4-H candidate SHA256 mismatch')
    candidate = obj(candidate_path)
    require(candidate.get('schema') == 'lvrag-universal-freeze-candidate-v0.1', 'candidate schema mismatch')
    require(candidate.get('engine_version') == '0.2' and candidate.get('status') == 'FREEZE_CANDIDATE', 'candidate status mismatch')
    require(candidate.get('human_correction_signoff') == 'PENDING', 'unexpected prior signoff')
    require(candidate.get('scope') == 'Local preview freeze candidate, not production deployment', 'candidate scope mismatch')
    require(candidate.get('validated_gates') == {
        'legacy_parity': '8/8', 'dual_http_health': '2/2',
        'dual_http_retrieval_isolation': '6/6', 'zhugeliang_r2_correction': 'PASS'
    }, 'gate summary mismatch')
    for key, expect in (('engine', ENGINE_SHA), ('legacy_adapter', ADAPTER_SHA)):
        path = Path(candidate[key]['path'])
        require(path.is_absolute() and candidate[key]['sha256'] == expect and digest(path) == expect, 'tool mismatch: ' + key)
    releases = candidate['releases']
    require(set(releases) == {'guangong','zhugeliang'}, 'unexpected IP release set')
    release_dirs = {}
    for ip, mh in (('guangong', GG_MANIFEST_SHA), ('zhugeliang', ZGL_MANIFEST_SHA)):
        folder = Path(releases[ip]['directory'])
        require(folder.is_absolute(), 'release location must be absolute')
        actual = check_release(folder, mh)
        require(actual == releases[ip]['files'], 'release files differ from Z4-H: ' + ip)
        manifest = obj(folder/'release-manifest.json')
        require(manifest.get('ip_id') == ip, 'release IP mismatch')
        release_dirs[ip] = folder
    gg = release_dirs['guangong']
    zgl = release_dirs['zhugeliang']
    # Verify correction is strictly textual and does not mutate claims, quotes, annotations or vectors.
    zgl_orig = zgl.parent/'lvrag-zhugeliang-v0.1.0-preview'
    if zgl_orig == zgl or not zgl_orig.is_dir():
        zgl_orig = Path.home()/'Downloads'/ZGL_OLD
    require(zgl_orig.is_dir() and not zgl_orig.is_symlink(), 'original ZhugeLiang preview missing')
    newman = obj(zgl/'release-manifest.json')
    oldman = obj(zgl_orig/'release-manifest.json')
    correction = newman.get('editorial_correction', {})
    require(correction.get('status') == 'PREVIEW_CORRECTION_PENDING_REVIEW', 'correction marker mismatch')
    require(correction.get('target_id') == CORRECTION and correction.get('fields') == ['evidence_limitation','review_note'], 'correction target mismatch')
    require(correction.get('original_limitation') == OLD_NOTE and correction.get('corrected_limitation') == NEW_NOTE, 'correction text mismatch')
    require(correction.get('original_release_manifest_sha256') == digest(zgl_orig/'release-manifest.json'), 'original preview mismatch')
    require(newman.get('source_decisions_sha256') == oldman.get('source_decisions_sha256') and newman.get('source_packet_sha256') == oldman.get('source_packet_sha256'), 'source signoff provenance mismatch')
    require(readbytes(zgl/'retrieval-policy.json') == readbytes(zgl_orig/'retrieval-policy.json'), 'policy changed')
    for file, field in (('approved-atomic-index.json','documents'),('retrieval-records.json','records')):
        old = obj(zgl_orig/file); new = obj(zgl/file)
        require(set(old) == set(new) and old.keys() == new.keys(), 'container fields changed: ' + file)
        items_old = old[field]; items_new = new[field]
        require(len(items_old) == len(items_new) == 10, 'record count changed')
        old_meta = {k:v for k,v in old.items() if k != field}
        new_meta = {k:v for k,v in new.items() if k != field}
        require(old_meta == new_meta, 'index metadata changed: ' + file)
        for a,b in zip(items_old, items_new):
            require(a.get('id') == b.get('id'), 'record order changed')
            if a.get('id') == CORRECTION:
                require(a.get('evidence_limitation') == OLD_NOTE and b.get('evidence_limitation') == NEW_NOTE, 'limitation change mismatch')
                require(a.get('review_note','').count(OLD_NOTE) == 1, 'original review note unexpected')
                require(b.get('review_note') == a['review_note'].replace(OLD_NOTE, NEW_NOTE), 'review note change mismatch')
                before = {k:v for k,v in a.items() if k not in ('review_note','evidence_limitation')}
                after = {k:v for k,v in b.items() if k not in ('review_note','evidence_limitation')}
                require(before == after, 'non-text fields changed: ' + file)
            else:
                require(a == b, 'unapproved card changed: ' + str(a.get('id')))
    # GuanGong RC1 original release must still validate in-place. No writes.
    legacy = Path.home()/'Downloads'/GG_LEGACY
    require(legacy.is_dir() and not legacy.is_symlink(), 'legacy GuanGong RC1 missing')
    for filename in ('approved-atomic-index.json','retrieval-records.json','release-manifest.json'):
        expected = None
        for line in readbytes(legacy/'SHA256SUMS').decode('utf-8').splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] == filename:
                expected = parts[0]
        require(expected is not None and digest(legacy/filename) == expected, 'legacy GuanGong RC1 integrity mismatch')
    return candidate

def paths(candidate_path):
    return candidate_path.with_name('lvrag-universal-v0.2-final-freeze.json'), candidate_path.with_name('lvrag-universal-v0.2-final-freeze.json.sha256')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--mode',choices=('create','verify'),required=True)
    p.add_argument('--candidate',type=Path,default=Path.home()/'Downloads'/'lvrag-universal-v0.2-freeze-candidate.json')
    args=p.parse_args()
    candidate_path=args.candidate.expanduser().resolve(strict=True)
    report=validate(candidate_path)
    final_path, hash_path = paths(candidate_path)
    expected = {
        'schema':'lvrag-universal-final-freeze-v0.1',
        'status':'FROZEN_LOCAL_PREVIEW',
        'engine_version':'0.2',
        'scope':'Local preview only; no production deployment or long-running stability claim',
        'approval':{
            'decision':'APPROVED',
            'authority':'User explicit confirmation in conversation, 2026-10-23',
            'target':'ZGL-ATOM-0010',
            'change_type':'Editorial evidence_limitation and review_note only',
            'corrected_evidence_limitation':NEW_NOTE,
            'original_z2i_signoff_unchanged':True,
            'claim_quote_annotations_vector_unchanged':True,
        },
        'candidate':{'path':str(candidate_path),'sha256':CANDIDATE_SHA},
        'engine':report['engine'],
        'legacy_adapter':report['legacy_adapter'],
        'releases':report['releases'],
        'validated_gates':report['validated_gates'],
        'preservation':{
            'guangong_rc1':'read-only; original unchanged',
            'original_releases':'read-only; original unchanged',
            'git_commit_push':False,
            'runtime_services':'not modified',
        },
    }
    payload=serialize(expected)
    checksum=(sha(payload)+'  '+final_path.name+'\n').encode('ascii')
    if args.mode == 'create':
        require(not final_path.exists() and not final_path.is_symlink(), 'final freeze exists; refusing overwrite')
        require(not hash_path.exists() and not hash_path.is_symlink(), 'checksum sidecar exists; refusing overwrite')
        fd=os.open(final_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o444)
        with os.fdopen(fd,'wb') as f:
            f.write(payload); f.flush(); os.fsync(f.fileno())
        fd=os.open(hash_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o444)
        with os.fdopen(fd,'wb') as f:
            f.write(checksum); f.flush(); os.fsync(f.fileno())
        print('Z4-I CREATE PASS:', final_path)
    else:
        require(readbytes(final_path) == payload, 'final freeze content mismatch')
        require(readbytes(hash_path) == checksum, 'final checksum mismatch')
        print('Z4-I VERIFY PASS:', final_path)
    print('FINAL_SHA256:',sha(payload))
    print('SIDECAR:',hash_path)
    print('STATUS: FROZEN_LOCAL_PREVIEW; NO SOURCE/RELEASE MODIFICATIONS')

if __name__ == '__main__':
    try:
        main()
    except (OSError,KeyError,ValueError,TypeError,AssertionError,json.JSONDecodeError) as exc:
        print('Z4-I FAIL CLOSED:',exc,file=sys.stderr)
        sys.exit(1)
