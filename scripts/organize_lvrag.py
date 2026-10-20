#!/usr/bin/env python3
"""Guarded LVRAG directory organizer; dry-run by default. Python standard library only."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

RULES = '''\n# LVRAG private assets - never commit to public GitHub\nconfidential.md\n/ips/**/knowledge/\n/ips/**/private/\n/ips/**/persona-private/\n**/.local/\n**/vectorstore/\n**/__pycache__/\n*.pyc\n.env\n.env.*\n!.env.example\n/lvrag-local-rag-starter/\n'''
SERIES_README = '''# Three Kingdoms · 三国人物\n\nLVRAG 文化人物系列：三国人物（Three Kingdoms Characters）。\n\n首个角色：**Guan Gong（关公）**，位于 [`guangong/`](guangong/)。\n\n本目录仅包含经批准的公开说明；专属知识库、原始资料与内部研发文档保留在本地。\n'''

def git(root, *args):
    return subprocess.run(['git', *args], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout

def abort(message):
    print('ABORT:', message, file=sys.stderr)
    raise SystemExit(2)

def check(root):
    if not (root / '.git').exists():
        abort(f'{root} 不是具有 .git 目录的仓库根目录')
    try:
        detected = Path(os.fsdecode(git(root, 'rev-parse', '--show-toplevel')).strip()).resolve()
    except subprocess.CalledProcessError:
        abort('git rev-parse 失败')
    if detected != root:
        abort('工作目录不是仓库根目录')
    src = root / 'guangong'
    dst = root / 'ips' / 'three-kingdoms' / 'guangong'
    if not src.is_dir() or src.is_symlink():
        abort('源 guangong/ 不存在，或是符号链接；拒绝操作')
    if dst.exists() or dst.is_symlink():
        abort('目标 ips/three-kingdoms/guangong/ 已存在；拒绝覆盖')
    if (src / '.git').exists():
        abort('guangong/ 内含单独 Git 仓库；拒绝迁移')
    tracked = [os.fsdecode(x) for x in git(root, 'ls-files', '-z', '--cached', '--', 'guangong').split(b'\0') if x]
    private = [p for p in tracked if Path(p).name == 'confidential.md' or '/knowledge/' in ('/' + p + '/') or '/private/' in ('/' + p + '/')]
    if private:
        abort('私有文件已被 Git 跟踪，必须先人工处理：\n' + '\n'.join(private))
    # Check all cached paths in repo, including previously staged sensitive files elsewhere.
    all_tracked = [os.fsdecode(x) for x in git(root, 'ls-files', '-z', '--cached').split(b'\0') if x]
    globally_private = [p for p in all_tracked if Path(p).name == 'confidential.md' or (p.startswith('ips/') and any('/'+name+'/' in '/'+p+'/' for name in ('knowledge','private','persona-private')))]
    if globally_private:
        abort('仓库内已有跟踪的机密文件：\n' + '\n'.join(globally_private))
    # Ensure no link pointing outside repo in the moved tree.
    for p in src.rglob('*'):
        if p.is_symlink():
            abort(f'源目录包含符号链接，人工确认后再迁移：{p}')
    return src, dst, tracked

def main():
    parser = argparse.ArgumentParser(description='LVRAG 安全迁移：默认只预览，不写入。')
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='LVRAG Git 仓库根目录')
    parser.add_argument('--apply', action='store_true', help='确认后执行迁移（不提交 Git）')
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    src, dst, tracked = check(root)
    print('ROOT:', root)
    print('MOVE:', src.relative_to(root), '=>', dst.relative_to(root))
    print('TRACKED PUBLIC CANDIDATES:', len(tracked))
    print('KEEP UNCHANGED: lvrag-local-rag-starter/')
    print('UPDATE: root .gitignore (append private patterns only)')
    print('CREATE: ips/three-kingdoms/README.md (if missing)')
    if not args.apply:
        print('\nDRY RUN PASS：未修改任何文件。执行 --apply 才会迁移。')
        return
    series = dst.parent
    series_readme = series / 'README.md'
    if series_readme.exists():
        abort('系列 README 已存在，停止以避免覆盖')
    ignore_path = root / '.gitignore'
    if ignore_path.exists() and (not ignore_path.is_file() or ignore_path.is_symlink()):
        abort('根 .gitignore 不是普通文件，停止')
    original = ignore_path.read_bytes() if ignore_path.exists() else None
    if original is not None:
        try:
            existing = original.decode('utf-8')
        except UnicodeDecodeError:
            abort('根 .gitignore 不是 UTF-8，停止')
    else:
        existing = ''
    # Preserve existing contents; only append unique entries.
    added = [line for line in RULES.splitlines() if line.strip() and line not in existing.splitlines()]
    new_ignore = existing + ('' if not existing or existing.endswith('\n') else '\n') + ('\n'.join(added) + '\n' if added else '')
    if new_ignore == existing and original is not None:
        new_ignore = None
    moved = False
    created_readme = False
    try:
        series.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        moved = True
        series_readme.write_text(SERIES_README, encoding='utf-8')
        created_readme = True
        if new_ignore is not None:
            fd, temp = tempfile.mkstemp(prefix='.lvrag-gitignore-', dir=root)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    f.write(new_ignore)
                if ignore_path.exists():
                    os.chmod(temp, ignore_path.stat().st_mode & 0o777)
                os.replace(temp, ignore_path)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
    except Exception:
        # Best effort rollback for filesystem failure.
        if created_readme and series_readme.exists():
            series_readme.unlink()
        if moved and dst.exists() and not src.exists():
            shutil.move(str(dst), str(src))
        abort('操作中断，已尝试回滚。请人工检查 git status 和目录。')
    print('\nAPPLY COMPLETE (NOT COMMITTED).')
    for path in ['ips/three-kingdoms/guangong/confidential.md', 'ips/three-kingdoms/guangong/knowledge/README.md', 'lvrag-local-rag-starter/.local/index.json']:
        result = subprocess.run(['git','check-ignore','-v','--no-index', path],cwd=root,text=True,capture_output=True)
        print(('IGNORE PASS' if result.returncode == 0 else 'NOT FOUND / NOT IGNORED'), path)
    print('\n===== GIT STATUS (NOT STAGED) =====')
    subprocess.run(['git','status','--short','--untracked-files=all'],cwd=root,check=False)
    print('\n下一步：人工审核，再选择性 git add；不要 git add -A。')

if __name__ == '__main__':
    main()
