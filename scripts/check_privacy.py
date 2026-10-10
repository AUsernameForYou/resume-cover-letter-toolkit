#!/usr/bin/env python3
"""Check working files and staged blobs; prior Git history needs a separate audit."""
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
PRIVATE_DIRS={'data','inputs','build','state','applications','exports','workspaces','vaults','raw'}
SKIP_DIRS={'.git','__pycache__','.venv','test-results'}
SECRET_PATTERNS=[r'gh[pousr]_[A-Za-z0-9]{20,}',r'github_pat_[A-Za-z0-9_]{20,}',r'sk-(?:(?:proj|ant)-)?[A-Za-z0-9_-]{20,}',r'xai-[A-Za-z0-9_-]{20,}',r'-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----']
BINARY_SUFFIXES={'.sqlite','.db','.doc','.docx','.pdf','.png','.jpg','.jpeg','.zip','.tar','.gz','.7z','.xlsx','.pptx','.rtf'}
EMAIL=re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')


def files():
    run=subprocess.run(['git','ls-files','-z','--cached','--others','--exclude-standard'],cwd=ROOT,capture_output=True)
    if run.returncode==0:
        return [ROOT/name for name in run.stdout.decode().split('\0') if name]
    return [p for p in ROOT.rglob('*') if (p.is_file() or p.is_symlink()) and not SKIP_DIRS.intersection(p.relative_to(ROOT).parts)]


def inspect_name(rel):
    parts=tuple(part.lower() for part in rel.parts)
    if PRIVATE_DIRS.intersection(parts):
        return 'private workspace artifact is included'
    if rel.name.lower()=='profile.json' and parts!=('examples','profile.json'):
        return 'private workspace artifact is included'
    if rel.name.lower()=='.env' or rel.name.lower().startswith('.env.'):
        return 'private workspace artifact is included'
    if rel.suffix.lower() in BINARY_SUFFIXES or re.search(r'\.(?:sqlite|db)-(?:wal|shm|journal)$',rel.name,re.I):
        return 'personal/generated binary artifact is included'
    return None


def inspect_text(text):
    for pattern in SECRET_PATTERNS:
        if re.search(pattern,text):return 'credential-shaped content'
    # Do not print the matching value.
    for email in EMAIL.findall(text):
        domain=email.rsplit('@',1)[1].lower()
        if domain not in {'example.invalid','example.com','example.org','example.net','users.noreply.github.com'}:
            return 'non-example email address'
    user_path = '/' + 'Users' + r'/[^/\s]+/|[A-Za-z]:\\Users\\'
    if re.search(user_path,text):return 'specific local user path'
    return None


def inspect(path):
    # Never follow a source-tree link into a private workspace.
    rel=path.relative_to(ROOT)
    component=ROOT
    for part in rel.parts:
        component=component/part
        if component.is_symlink():return 'symbolic link is included'
    problem=inspect_name(rel)
    if problem:return problem
    try:text=path.read_text(encoding='utf-8')
    except UnicodeError:return 'unexpected binary file'
    except OSError:return 'source file cannot be read'
    return inspect_text(text)


def staged_problems():
    run=subprocess.run(['git','ls-files','--stage','-z'],cwd=ROOT,capture_output=True)
    if run.returncode!=0:return []
    problems=[]
    for entry in run.stdout.decode().split('\0'):
        if not entry:continue
        metadata,name=entry.split('\t',1)
        mode,object_id,stage=metadata.split()
        problem=inspect_name(Path(name))
        if mode not in {'100644','100755'}:
            problem='symbolic link, submodule or unsupported index entry is included'
        if stage!='0':problem='unmerged index entry is included'
        if not problem:
            blob=subprocess.run(['git','cat-file','blob',object_id],cwd=ROOT,capture_output=True)
            if blob.returncode!=0:problem='staged source cannot be read'
            else:
                try:problem=inspect_text(blob.stdout.decode('utf-8'))
                except UnicodeError:problem='unexpected binary file'
        if problem:problems.append((name+' [staged]',problem))
    return problems


def main():
    problems=staged_problems()
    for path in files():
        # A tracked file can be deleted locally while its staged bytes remain.
        if not path.exists() and not path.is_symlink():continue
        problem=inspect(path)
        if problem:problems.append((str(path.relative_to(ROOT)),problem))
    for name,problem in problems:print(name+': '+problem,file=sys.stderr)
    if problems:return 1
    print('Privacy check passed: no private artifacts or likely credentials detected in working files or staged blobs. Prior Git history is not checked.')
    return 0


if __name__=='__main__':raise SystemExit(main())
