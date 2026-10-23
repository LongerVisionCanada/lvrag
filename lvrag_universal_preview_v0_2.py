#!/usr/bin/env python3
"""Generic, stdlib-only, fail-closed LVRAG preview runtime.

pack-zgl is an adapter for the frozen ZhugeLiang Z3 index. Runtime is IP-neutral:
release-specific routing rules are data (retrieval-policy.json), not engine code.
No embeddings or LLM answer generation are performed by this conservative API.
"""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
import sys

INDEX_SHA = '4127f82d0d28c821d5ee62c2dde9ce8ab35309987ec71825c3ded44ca192a91e'
PACKET_SHA = 'ae1df5058d83251a41652affd3c68ab5614d54c7c6810acdf45e325c41407ade'
DECISIONS_SHA = '6c43ba19c9f578aa40bf9225d2469de2c2531e224021dbc565dd0653e7b3da0b'
SCHEMA = 'lvrag-generic-preview-v0.1'
FILES = ('approved-atomic-index.json', 'retrieval-records.json', 'retrieval-policy.json')


def need(ok, msg):
    if not ok:
        raise ValueError(msg)


def digest(b):
    return hashlib.sha256(b).hexdigest()


def file_digest(p):
    need(p.is_file() and not p.is_symlink(), f'unsafe/missing file: {p}')
    return digest(p.read_bytes())


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def encoded(data):
    return (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')


def write_new(directory, name, content):
    target = directory / name
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'wb') as fp:
        fp.write(content)
        fp.flush()
        os.fsync(fp.fileno())


def pack_zgl(repo, directory):
    need(not directory.exists(), 'release path already exists; will not overwrite')
    base = repo / 'ips/three-kingdoms/zhugeliang/knowledge'
    index_path = base / '.rag/approved-atomic-index.json'
    need(file_digest(index_path) == INDEX_SHA, 'frozen Z3 index SHA256 mismatch')
    need(file_digest(base / 'evaluation/zgl-final-review-packet.json') == PACKET_SHA, 'Z2-H packet SHA mismatch')
    need(file_digest(base / 'evaluation/atomic-review-decisions.json') == DECISIONS_SHA, 'Z2-I decisions SHA mismatch')
    builder = repo / 'zhugeliang_build_z3.py'
    need(file_digest(builder) == '32ea0ac162b83bfb9bc341d3d2866511f4aa15c2a60820068097c4a8b1c61cbc', 'Z3 builder script changed')
    completed = subprocess.run([sys.executable, str(builder), '--mode', 'verify', '--root', str(repo)],
                               capture_output=True, text=True, check=False)
    need(completed.returncode == 0 and 'VERIFY PASS:' in completed.stdout, 'Z3 source verification failed: ' + completed.stderr[-900:])
    idx = read(index_path)
    need(idx.get('schema') == 'zgl-approved-attributed-index-v0.1' and idx.get('ip_id') == 'zhugeliang', 'index schema/IP mismatch')
    need(idx.get('decisions_sha256') == DECISIONS_SHA and idx.get('final_review_packet_sha256') == PACKET_SHA, 'index signoff mismatch')
    docs = idx.get('documents')
    need(isinstance(docs, list) and len(docs) == 10, 'expected 10 approved records')
    records = []
    for i, d in enumerate(docs, 1):
        need(d['id'] == f'ZGL-ATOM-{i:04d}', 'unexpected ID/order')
        need(d.get('source_layer') == 'chen-shou-main-text' and d.get('evidence_limitation'), 'missing source/limit')
        need(isinstance(d.get('vector'), list) and len(d['vector']) == 768, 'invalid index vector')
        records.append({k: d[k] for k in ('id', 'title', 'claim', 'quote', 'quote_span', 'source_layer',
                                           'source_sha256', 'card_sha256', 'evidence_limitation',
                                           'related_annotations', 'review_note')})
    # Topic triggers belong to release data. They're conservative and limited by explicit exclusions.
    policy = {'schema': 'lvrag-policy-v0.1', 'ip_id': 'zhugeliang',
              'blocked_phrases': ['空城计', '草船借箭', '水果', '最喜欢吃', '喜欢吃什么'],
              'topics': [
                  {'id': 'ZGL-ATOM-0001', 'phrases': ['字什么', '哪里人', '籍贯']},
                  {'id': 'ZGL-ATOM-0002', 'phrases': ['躬耕', '梁父吟']},
                  {'id': 'ZGL-ATOM-0003', 'phrases': ['徐庶', '卧龙']},
                  {'id': 'ZGL-ATOM-0004', 'phrases': ['三次拜访', '三顾', '凡三往']},
                  {'id': 'ZGL-ATOM-0005', 'phrases': ['隆中对', '隆中战略']},
                  {'id': 'ZGL-ATOM-0006', 'phrases': ['出使孙权', '求救于孙', '游说孙权']},
                  {'id': 'ZGL-ATOM-0007', 'phrases': ['永安托孤', '托孤时']},
                  {'id': 'ZGL-ATOM-0008', 'phrases': ['出师表', '先帝创业未半']},
                  {'id': 'ZGL-ATOM-0009', 'phrases': ['街亭', '马谡']},
                  {'id': 'ZGL-ATOM-0010', 'phrases': ['在哪里去世', '五丈原', '病逝']},
              ]}
    dirparent = directory.parent
    need(dirparent.is_dir(), 'parent of release path does not exist')
    directory.mkdir(mode=0o700)
    try:
        write_new(directory, FILES[0], index_path.read_bytes())
        write_new(directory, FILES[1], encoded({'schema': 'lvrag-retrieval-records-v0.1', 'ip_id': 'zhugeliang', 'records': records}))
        write_new(directory, FILES[2], encoded(policy))
        manifest = {'schema': SCHEMA, 'ip_id': 'zhugeliang', 'review_scope': 'attributed_historical_record_only',
                    'source_index_sha256': INDEX_SHA, 'source_packet_sha256': PACKET_SHA,
                    'source_decisions_sha256': DECISIONS_SHA,
                    'files': {name: file_digest(directory / name) for name in FILES}}
        write_new(directory, 'release-manifest.json', encoded(manifest))
        checks = [(name, file_digest(directory / name)) for name in (*FILES, 'release-manifest.json')]
        write_new(directory, 'SHA256SUMS', ''.join(f'{h}  {name}\n' for name, h in checks).encode('utf-8'))
        load_release(directory)
    except BaseException:
        print('PACK FAILED: incomplete release directory needs manual inspection; no overwrite performed', file=sys.stderr)
        raise
    print('PACK PASS:', directory)
    for name, h in checks:
        print(h, name)


def load_release(directory):
    need(directory.is_dir() and not directory.is_symlink(), 'unsafe release directory')
    mp = directory / 'release-manifest.json'
    manifest = read(mp)
    need(manifest.get('schema') == SCHEMA, 'manifest schema mismatch')
    ip = manifest.get('ip_id')
    need(isinstance(ip, str) and re.fullmatch(r'[a-z][a-z0-9_-]{1,40}', ip), 'invalid IP identity')
    need(manifest.get('review_scope') == 'attributed_historical_record_only', 'invalid review scope')
    need(set(manifest.get('files', {})) == set(FILES), 'unexpected files manifest')
    for name in FILES:
        need(file_digest(directory / name) == manifest['files'][name], name + ' SHA256 mismatch')
    checksum_lines = (directory / 'SHA256SUMS').read_text(encoding='utf-8').splitlines()
    expected_lines = [f'{file_digest(directory / name)}  {name}' for name in (*FILES, 'release-manifest.json')]
    need(checksum_lines == expected_lines, 'SHA256SUMS mismatch')
    idx, recs, policy = (read(directory / name) for name in FILES)
    need(idx.get('ip_id') == recs.get('ip_id') == policy.get('ip_id') == ip, 'cross-file IP mismatch')
    need(recs.get('schema') == 'lvrag-retrieval-records-v0.1' and policy.get('schema') == 'lvrag-policy-v0.1', 'schema mismatch')
    need(idx.get('decisions_sha256') == manifest.get('source_decisions_sha256'), 'signoff provenance mismatch')
    need(idx.get('final_review_packet_sha256') == manifest.get('source_packet_sha256'), 'source packet mismatch')
    need(file_digest(directory / FILES[0]) == manifest.get('source_index_sha256'), 'source index mismatch')
    ds, rs = idx.get('documents'), recs.get('records')
    need(isinstance(ds, list) and isinstance(rs, list) and len(ds) == len(rs) and len(ds) > 0, 'records missing')
    by_id = {}
    for doc, record in zip(ds, rs):
        need(isinstance(doc, dict) and isinstance(record, dict), 'bad record type')
        stripped = {k: v for k, v in doc.items() if k != 'vector'}
        need(stripped == record, 'record differs from signed index document')
        rid = record.get('id')
        need(isinstance(rid, str) and rid not in by_id, 'duplicate/invalid record ID')
        need(bool(record.get('claim')) and bool(record.get('evidence_limitation')) and bool(record.get('quote')), 'record missing historical limitations')
        by_id[rid] = record
    topics = policy.get('topics')
    blocked = policy.get('blocked_phrases')
    need(isinstance(topics, list) and topics and isinstance(blocked, list) and blocked, 'policy not configured')
    topic_ids = set()
    for item in topics:
        need(isinstance(item, dict), 'invalid topic structure')
        ids = item.get('ids', [item.get('id')])
        need(isinstance(ids, list) and bool(ids) and all(isinstance(rid, str) and rid in by_id for rid in ids), 'invalid topic mapping')
        marker = tuple(ids)
        need(marker not in topic_ids, 'duplicate topic mapping')
        topic_ids.add(marker)
        need(isinstance(item.get('phrases'), list) and item['phrases'] and all(isinstance(x, str) and x.strip() for x in item['phrases']), 'bad trigger')
    need(all(isinstance(x, str) and x.strip() for x in blocked), 'bad exclusion phrase')
    return ip, by_id, policy


def retrieve(ip_requested, question, top_k, release):
    ip, by_id, policy = release
    if ip_requested != ip:
        return {'ip_id': ip, 'status': 'unsupported_ip_id', 'evidence': []}
    if not isinstance(question, str) or not question.strip() or len(question) > 500 or not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= len(by_id):
        raise ValueError('invalid question/top_k')
    if any(x in question for x in policy['blocked_phrases']):
        return {'ip_id': ip, 'status': 'insufficient_evidence', 'evidence': [], 'reason': 'Out of approved topic scope'}
    ids = list(dict.fromkeys(rid for t in policy['topics'] if any(x in question for x in t['phrases']) for rid in (t.get('ids') or [t.get('id')])))
    if not ids or len(ids) > top_k:
        return {'ip_id': ip, 'status': 'insufficient_evidence', 'evidence': [], 'reason': 'No unique supported topic match'}
    return {'ip_id': ip, 'status': 'evidence_found', 'evidence': [{
        'knowledge_id': record['id'], 'claim': record['claim'], 'quote': record['quote'],
        'evidence_limitation': record['evidence_limitation'], 'related_annotations': record['related_annotations'],
        'source_layer': record['source_layer']} for record in (by_id[rid] for rid in ids)],
        'reason': 'Conservative topic match to an approved attributed record; not a generated answer'}


def selftest(release):
    ip, _, _ = release
    cases = [
        ('诸葛亮字什么？是哪里人？', 'evidence_found', 'ZGL-ATOM-0001'),
        ('诸葛亮在隆中对中提出什么战略？', 'evidence_found', 'ZGL-ATOM-0005'),
        ('刘备在永安托孤时对诸葛亮说了什么？', 'evidence_found', 'ZGL-ATOM-0007'),
        ('马谡为什么在街亭战败？', 'evidence_found', 'ZGL-ATOM-0009'),
        ('诸葛亮在哪里去世？', 'evidence_found', 'ZGL-ATOM-0010'),
        ('诸葛亮真的使用过空城计吗？', 'insufficient_evidence', None),
        ('诸葛亮最喜欢吃什么水果？', 'insufficient_evidence', None),
    ]
    need(ip == 'zhugeliang', 'these regression questions require zhugeliang release')
    for q, status, expected_id in cases:
        got = retrieve(ip, q, 4, release)
        actual_id = got['evidence'][0]['knowledge_id'] if got['evidence'] else None
        need(got['status'] == status and actual_id == expected_id, 'regression mismatch: ' + q)
        print('PASS', status, actual_id, q)
    got = retrieve('guangong', '诸葛亮在哪里去世？', 4, release)
    need(got['status'] == 'unsupported_ip_id', 'cross-IP isolation failed')
    print('PASS unsupported_ip_id')
    print('SELFTEST PASS: 8/8')


def serve(release, host, port):
    need(host in ('127.0.0.1', 'localhost'), 'loopback bind only')
    need(1024 <= port <= 65535, 'port out of range')
    ip, by_id, policy = release
    class Handler(BaseHTTPRequestHandler):
        def answer(self, code, body):
            raw = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        def do_GET(self):
            if self.path != '/health':
                return self.answer(404, {'error': 'not_found'})
            return self.answer(200, {'status': 'ok', 'ip_id': ip, 'approved_records': len(by_id), 'schema': SCHEMA})
        def do_POST(self):
            if self.path != '/v1/retrieve':
                return self.answer(404, {'error': 'not_found'})
            try:
                length = int(self.headers.get('Content-Length', '-1'))
                if not 0 < length <= 16384:
                    return self.answer(400, {'error': 'invalid_content_length'})
                data = json.loads(self.rfile.read(length).decode('utf-8'))
                if not isinstance(data, dict) or set(data) - {'ip_id', 'question', 'top_k'}:
                    return self.answer(400, {'error': 'invalid_request'})
                if not isinstance(data.get('ip_id'), str):
                    return self.answer(400, {'error': 'ip_id_required'})
                if data['ip_id'] != ip:
                    return self.answer(400, {'error': 'unsupported_ip_id'})
                return self.answer(200, retrieve(data['ip_id'], data.get('question'), data.get('top_k', 4), release))
            except (ValueError, TypeError, UnicodeError, json.JSONDecodeError):
                return self.answer(400, {'error': 'invalid_request'})
    server = ThreadingHTTPServer((host, port), Handler)
    print(f'SERVE: http://{host}:{port} ip_id={ip} (loopback only)', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=('pack-zgl', 'verify', 'selftest', 'query', 'serve'), required=True)
    p.add_argument('--repo', default=str(Path.home() / 'Programs/esp32/lvrag'))
    p.add_argument('--release', required=True)
    p.add_argument('--ip-id', default='zhugeliang')
    p.add_argument('--question')
    p.add_argument('--top-k', type=int, default=4)
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=8766)
    args = p.parse_args()
    directory = Path(args.release).expanduser().absolute()
    if args.mode == 'pack-zgl':
        pack_zgl(Path(args.repo).expanduser().resolve(strict=True), directory)
    else:
        release = load_release(directory)
        if args.mode == 'verify':
            print('VERIFY PASS:', release[0], len(release[1]), 'approved attributed records')
            print('MANIFEST_SHA256:', file_digest(directory / 'release-manifest.json'))
        elif args.mode == 'selftest':
            selftest(release)
        elif args.mode == 'query':
            need(args.question is not None, '--question required')
            print(json.dumps(retrieve(args.ip_id, args.question, args.top_k, release), ensure_ascii=False, indent=2))
        else:
            serve(release, args.host, args.port)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, AssertionError, json.JSONDecodeError) as exc:
        print('FAIL CLOSED:', exc, file=sys.stderr)
        sys.exit(1)
