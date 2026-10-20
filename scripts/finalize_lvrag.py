#!/usr/bin/env python3
"""Prepare LVRAG public repository for a safe, reviewed commit. No commits/pushes."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

PUBLIC_DIRS = (
    'ips/three-kingdoms',
    'ips/three-kingdoms/guangong/docs/assets',
    'ips/journey-to-the-west',
    'ips/water-margin',
    'core/ingestion',
    'core/retrieval',
    'core/generation',
    'core/agent',
    'devices/esp32s3',
    'backend/api',
    'tools',
    'docs/architecture',
)
PRIVATE_DIRS = (
    'ips/three-kingdoms/guangong/knowledge/history',
    'ips/three-kingdoms/guangong/knowledge/literature',
    'ips/three-kingdoms/guangong/knowledge/culture',
    'ips/three-kingdoms/guangong/knowledge/original',
    'ips/three-kingdoms/guangong/private',
    'ips/three-kingdoms/guangong/persona-private',
)
RULES = (
    'confidential.md',
    '/ips/**/knowledge/',
    '/ips/**/private/',
    '/ips/**/persona-private/',
    '/lvrag-local-rag-starter/',
    '**/.local/',
    '**/vectorstore/',
    '**/__pycache__/',
    '*.pyc',
    '.env',
    '.env.*',
    '!.env.example',
)
PRIVATE_TOKENS = {'knowledge', 'private', 'persona-private', '.local', 'vectorstore', '__pycache__'}

def run(root, *args, check=True):
    return subprocess.run(args, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=check)

def fail(msg):
    print('FAIL:', msg, file=sys.stderr)
    sys.exit(2)

def is_private(path):
    parts = Path(path).parts
    return (Path(path).name == 'confidential.md'
            or any(p in PRIVATE_TOKENS for p in parts)
            or (len(parts)>0 and parts[0] == 'lvrag-local-rag-starter')
            or Path(path).name == '.env'
            or Path(path).name.startswith('.env.'))

def main():
    p=argparse.ArgumentParser(description='LVRAG public structure + private ignore audit; never commits or pushes.')
    p.add_argument('--root', type=Path, default=Path.cwd())
    p.add_argument('--apply', action='store_true', help='create directories/ignore entries (without staging)')
    p.add_argument('--stage', action='store_true', help='stage only audited public changes; requires --apply')
    a=p.parse_args()
    if a.stage and not a.apply: fail('--stage requires --apply')
    root=a.root.resolve()
    if not (root/'.git').exists(): fail('Not the Git worktree root (.git missing)')
    detected=run(root,'git','rev-parse','--show-toplevel').stdout.strip()
    if Path(detected).resolve()!=root: fail('Not Git root')
    if (root/'guangong').exists(): fail('Old guangong/ still present; migration state requires manual review')
    if not (root/'ips/three-kingdoms/guangong/README.md').exists(): fail('Missing migrated public guangong README')
    if not (root/'ips/three-kingdoms/README.md').exists(): fail('Missing three-kingdoms README')
    for ignorefile in [root/'.gitignore',root/'ips/three-kingdoms/guangong/.gitignore']:
        if ignorefile.exists() and (not ignorefile.is_file() or ignorefile.is_symlink()): fail(f'Unusual ignore path: {ignorefile}')
    tracked=run(root,'git','ls-files','--cached').stdout.splitlines()
    leaks=[x for x in tracked if is_private(x)]
    if leaks: fail('Private files tracked already (cannot fix with .gitignore): '+', '.join(leaks))
    staged=run(root,'git','diff','--cached','--name-only').stdout.splitlines()
    if staged: fail('Already staged changes; do not mix commits: '+', '.join(staged))
    for name in PUBLIC_DIRS + PRIVATE_DIRS:
        dest=root/name
        if dest.is_symlink(): fail(f'Symlink directory forbidden: {name}')
    rootignore=root/'.gitignore'
    text=rootignore.read_text(encoding='utf-8') if rootignore.exists() else ''
    extra=[r for r in RULES if r not in text.splitlines()]
    print('ROOT:',root)
    print('PUBLIC EMPTY DIRS:',len(PUBLIC_DIRS))
    print('PRIVATE DIRS:',len(PRIVATE_DIRS))
    print('MISSING IGNORE ENTRIES:',extra)
    print('EXISTING TRACKED PRIVATE FILES: none')
    print('PRESERVE: lvrag-local-rag-starter/ unchanged')
    if not a.apply:
        print('DRY RUN PASS; no changes made. Use --apply then audit, optionally --apply --stage.')
        return
    if extra:
        prefix='' if not text or text.endswith('\n') else '\n'
        rootignore.write_text(text+prefix+'\n# LVRAG private knowledge and local development\n'+'\n'.join(extra)+'\n',encoding='utf-8')
    for name in PUBLIC_DIRS:
        dest=root/name
        dest.mkdir(parents=True, exist_ok=True)
        if not any(dest.iterdir()):
            (dest/'.gitkeep').touch(exist_ok=True)
    for name in PRIVATE_DIRS:
        (root/name).mkdir(parents=True,exist_ok=True)
    for rel in [
       'ips/three-kingdoms/guangong/confidential.md',
       'ips/three-kingdoms/guangong/knowledge/README.md',
       'ips/three-kingdoms/guangong/private/keep.txt',
       'ips/three-kingdoms/guangong/persona-private/keep.txt',
       'lvrag-local-rag-starter/.local/index.json',
    ]:
        ret=run(root,'git','check-ignore','--no-index','-q','--',rel,check=False)
        if ret.returncode!=0: fail(f'Ignore rule does not cover: {rel}')
    # Double-check no private files are tracked, and stage only approved public files.
    if a.stage:
        public_paths=['.gitignore','ips/three-kingdoms/README.md',
                      'ips/three-kingdoms/guangong/.gitignore',
                      'ips/three-kingdoms/guangong/README.md',
                      'ips/three-kingdoms/guangong/docs/assets/guangong-hero.png',
                      'ips/three-kingdoms/guangong/docs/assets/guangong_profile.jpg',
                      'scripts/organize_lvrag.py','scripts/finalize_lvrag.py']
        public_paths += [str(Path(name)/'.gitkeep') for name in PUBLIC_DIRS]
        public_paths=[r for r in public_paths if (root/r).exists()]
        run(root,'git','add','--',*public_paths)
        # Explicit old tracked path removals (only old Guan Gong public paths)
        old=[x for x in tracked if x.startswith('guangong/')]
        if old:
            run(root,'git','add','-u','--','guangong/')
        staged=run(root,'git','diff','--cached','--name-only').stdout.splitlines()
        bad=[x for x in staged if is_private(x)]
        if bad: fail('Sensitive paths staged: '+', '.join(bad))
        run(root,'git','diff','--cached','--check')
        print('\nSTAGED PUBLIC PATHS:')
        print('\n'.join(staged) or '(none)')
        print('\nDo not commit until you review the public README/images and staged paths.')
    print('\nAPPLY PASS — no commit or push performed.')

if __name__=='__main__':
    main()
