"""Python helper scripts executed at `/workspace` inside a coding sandbox.

Pure strings used by the helper-script session (Docker).
"""

from __future__ import annotations

from neos.coding.sandbox.ignore import IGNORE_RUNTIME

_GIT_SAFE = ("git", "--no-pager", "-c", "core.pager=cat")


_READ_FILE_HELPER = """\
from pathlib import Path
import sys
rel, offset_s, limit_s, max_s = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
p = Path('/workspace') / rel
if not p.is_file() or p.is_symlink(): raise SystemExit(2)
offset = int(offset_s)
max_bytes = int(max_s)
if limit_s == '':
    if p.stat().st_size > max_bytes:
        raise SystemExit(3)
    sys.stdout.buffer.write(p.read_bytes())
else:
    limit = int(limit_s)
    start = max(1, offset)
    end = start + limit - 1
    remaining = max_bytes
    with p.open('rb') as handle:
        for index, line in enumerate(handle, 1):
            if index < start: continue
            if index > end: break
            if len(line) >= remaining:
                sys.stdout.buffer.write(line[:remaining])
                break
            sys.stdout.buffer.write(line)
            remaining -= len(line)
"""
_WRITE_FILE_HELPER = """\
import os, sys, tempfile
from pathlib import Path
rel, make_parents = sys.argv[1], sys.argv[2] == '1'
root = Path('/workspace')
parts = Path(rel).parts
p = root.joinpath(*parts)
cur = root
for part in parts[:-1]:
    cur = cur / part
    if cur.is_symlink():
        raise SystemExit(3)
    if cur.exists():
        if not cur.is_dir():
            raise SystemExit(2)
        continue
    if not make_parents:
        raise SystemExit(2)
    cur.mkdir(exist_ok=True)
    if cur.is_symlink() or not cur.is_dir():
        raise SystemExit(3 if cur.is_symlink() else 2)
if p.is_symlink():
    raise SystemExit(4)
fd, tmp = tempfile.mkstemp(prefix='.neos-write-', dir=str(p.parent))
try:
    with os.fdopen(fd, 'wb') as handle:
        handle.write(sys.stdin.buffer.read())
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, p)
except Exception:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise
"""
_MKDIR_HELPER = """\
from pathlib import Path
import sys
rel, parents = sys.argv[1], sys.argv[2] == '1'
root = Path('/workspace')
parts = Path(rel).parts
p = root.joinpath(*parts)
cur = root
for part in parts[:-1]:
    cur = cur / part
    if cur.is_symlink():
        raise SystemExit(3)
    if not cur.exists():
        if not parents:
            raise SystemExit(2)
        cur.mkdir(exist_ok=True)
    elif not cur.is_dir():
        raise SystemExit(2)
if p.exists() and not parents:
    raise SystemExit(5)
if parents:
    p.mkdir(parents=True, exist_ok=True)
else:
    p.mkdir()
"""
_REFUSE_SYMLINK_PARENTS = """\
def _join_refusing_symlink_parents(root, rel):
    parts = Path(rel).parts
    cur = root
    for part in parts[:-1]:
        cur = cur / part
        if cur.is_symlink():
            raise SystemExit(3)
    return root.joinpath(*parts)
"""
_RM_HELPER = (
    _REFUSE_SYMLINK_PARENTS
    + """\
import shutil
from pathlib import Path
import sys
rel, recursive = sys.argv[1], sys.argv[2] == '1'
root = Path('/workspace')
p = _join_refusing_symlink_parents(root, rel)
if p.is_symlink():
    p.unlink()
elif p.is_dir():
    if any(p.iterdir()) and not recursive:
        raise SystemExit(6)
    shutil.rmtree(p) if recursive else p.rmdir()
elif p.exists():
    p.unlink()
else:
    raise SystemExit(2)
"""
)
_MV_HELPER = (
    _REFUSE_SYMLINK_PARENTS
    + """\
import shutil
from pathlib import Path
import sys
src, dest, overwrite = sys.argv[1], sys.argv[2], sys.argv[3] == '1'
root = Path('/workspace')
s = _join_refusing_symlink_parents(root, src)
d = _join_refusing_symlink_parents(root, dest)
if not s.exists() and not s.is_symlink():
    raise SystemExit(2)
if not d.parent.exists():
    raise SystemExit(2)
if (d.exists() or d.is_symlink()) and not overwrite:
    raise SystemExit(5)
if d.exists() or d.is_symlink():
    if d.is_dir() and not d.is_symlink():
        shutil.rmtree(d)
    else:
        d.unlink()
s.rename(d)
"""
)
_CHMOD_HELPER = (
    _REFUSE_SYMLINK_PARENTS
    + """\
import os
from pathlib import Path
import sys
rel, mode = sys.argv[1], int(sys.argv[2])
root = Path('/workspace')
p = _join_refusing_symlink_parents(root, rel)
if not p.exists() and not p.is_symlink():
    raise SystemExit(2)
try:
    os.chmod(p, mode, follow_symlinks=False)
except NotImplementedError:
    os.chmod(p, mode)
"""
)
_SEARCH_TEXT_HELPER = (
    IGNORE_RUNTIME
    + """
import json, re, sys
from pathlib import Path
query, regex, limit, before, after, output_mode, ignore_case, multiline, max_columns, search_path, exclude_json, *patterns = sys.argv[1:]
flags = 0
if ignore_case == '1':
    flags |= re.IGNORECASE
if multiline == '1':
    flags |= re.DOTALL
expression = re.compile(query if regex == '1' else re.escape(query), flags)
before = max(0, min(int(before), 20))
after = max(0, min(int(after), 20))
max_columns = int(max_columns)
try:
    excludes = json.loads(exclude_json)
    if not isinstance(excludes, list):
        excludes = []
except (TypeError, ValueError):
    excludes = []
excludes = [str(item) for item in excludes]
if output_mode not in {'files', 'content', 'count'}:
    output_mode = 'content'
root = Path('/workspace')
start = root / search_path if search_path else root
rules = load_ignore_rules('/workspace')
matches = []

def is_binary(item):
    try:
        with item.open('rb') as handle:
            return b'\\x00' in handle.read(8192)
    except OSError:
        return True

def matches_glob(relative, pattern):
    if pattern.endswith('/**'):
        return relative.startswith(pattern[:-3].rstrip('/') + '/')
    try:
        if Path(relative).match(pattern):
            return True
    except (ValueError, OSError):
        return False
    return pattern.startswith('**/') and Path(relative).match(pattern[3:])

def clip(line):
    if max_columns <= 0:
        return line
    data = line.encode('utf-8')
    if len(data) <= max_columns:
        return line
    return data[:max_columns].decode('utf-8', errors='ignore')

def emit_content(relative, number, column, line, lines):
    ctx = max(0, number - 1 - before)
    matches.append({'path': relative, 'line': number, 'column': column,
                    'text': clip(line),
                    'before': [clip(item) for item in lines[ctx:number - 1]],
                    'after': [clip(item) for item in lines[number:number + after]]})

def consider_file(item, relative):
    if not any(matches_glob(relative, pattern) for pattern in patterns):
        return False
    if excludes and any(matches_glob(relative, pattern) for pattern in excludes):
        return False
    if is_binary(item):
        return False
    max_file_bytes = 1024 * 1024
    try:
        if item.stat().st_size > max_file_bytes:
            return False
        with item.open('rb') as handle:
            data = handle.read(max_file_bytes + 1)
    except OSError:
        return False
    if len(data) > max_file_bytes or b'\\x00' in data[:8192]:
        return False
    text = data.decode('utf-8', errors='replace')
    lines = text.splitlines()
    if multiline == '1':
        file_hits = 0
        for match in expression.finditer(text):
            file_hits += 1
            if output_mode != 'content':
                continue
            number = text.count('\\n', 0, match.start()) + 1
            line_start = text.rfind('\\n', 0, match.start()) + 1
            line_end = text.find('\\n', match.start())
            if line_end < 0:
                line_end = len(text)
            line = text[line_start:line_end].rstrip('\\r')
            emit_content(relative, number, match.start() - line_start + 1, line, lines)
            if len(matches) >= int(limit):
                return True
        if output_mode == 'content' or file_hits == 0:
            return False
    else:
        file_hits = 0
        for number, line in enumerate(lines, 1):
            match = expression.search(line)
            if not match:
                continue
            file_hits += 1
            if output_mode != 'content':
                continue
            emit_content(relative, number, match.start() + 1, line, lines)
            if len(matches) >= int(limit):
                return True
        if output_mode == 'content' or file_hits == 0:
            return False
    if output_mode == 'files':
        matches.append({'path': relative, 'line': 0, 'column': 0, 'text': ''})
    else:
        matches.append({'path': relative, 'line': 0, 'column': 0, 'text': '',
                        'count': file_hits})
    return len(matches) >= int(limit)

done = False
if start.is_symlink():
    pass
elif start.is_file():
    relative = start.relative_to(root).as_posix()
    if not should_skip(relative, rules, is_dir=False):
        consider_file(start, relative)
elif start.is_dir():
    for dirpath, dirnames, filenames in os.walk(start, followlinks=False):
        current = Path(dirpath)
        dirnames.sort(); filenames.sort()
        kept = []
        for name in dirnames:
            item = current / name
            if item.is_symlink():
                continue
            relative = item.relative_to(root).as_posix()
            if should_skip(relative, rules, is_dir=True):
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            item = current / name
            if item.is_symlink() or not item.is_file():
                continue
            relative = item.relative_to(root).as_posix()
            if should_skip(relative, rules, is_dir=False):
                continue
            if consider_file(item, relative):
                done = True
                break
        if done:
            break
sys.stdout.write(json.dumps(matches))
"""
)
_GLOB_FILES_HELPER = (
    IGNORE_RUNTIME
    + """
import fnmatch, json, sys
from pathlib import Path
pattern, limit = sys.argv[1], int(sys.argv[2])
start = sys.argv[3] if len(sys.argv) > 3 else ''
if '..' in Path(pattern).parts or (start and '..' in Path(start).parts):
    raise SystemExit(2)
limit = max(1, min(limit, 500))
root = Path('/workspace')
base = (root / start) if start else root
if not base.exists():
    sys.stdout.write(json.dumps([]))
    raise SystemExit(0)
rules = load_ignore_rules('/workspace')
found = []
def matches(relative, from_start):
    for candidate in (relative, from_start):
        if fnmatch.fnmatch(candidate, pattern) or (
            pattern.startswith('**/') and fnmatch.fnmatch(candidate, pattern[3:])
        ):
            return True
    return False
for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
    current = Path(dirpath)
    dirnames.sort(); filenames.sort()
    kept = []
    for name in dirnames:
        item = current / name
        if item.is_symlink():
            continue
        relative = item.relative_to(root).as_posix()
        if should_skip(relative, rules, is_dir=True):
            continue
        kept.append(name)
    dirnames[:] = kept
    for name in filenames:
        item = current / name
        if item.is_symlink() or not item.is_file():
            continue
        relative = item.relative_to(root).as_posix()
        if should_skip(relative, rules, is_dir=False):
            continue
        from_start = item.relative_to(base).as_posix()
        if matches(relative, from_start):
            found.append((item.stat().st_mtime, relative))
found.sort(key=lambda pair: (-pair[0], pair[1]))
sys.stdout.write(json.dumps([path for _mtime, path in found[:limit]]))
"""
)
_FILE_METADATA_HELPER = (
    IGNORE_RUNTIME
    + """
import json, os, sys
from datetime import UTC, datetime
from pathlib import Path
root = Path('/workspace')
p = root / sys.argv[1]
def encode(item):
    value = item.lstat()
    kind = 'symlink' if item.is_symlink() else ('directory' if item.is_dir() else 'file')
    return {'path': item.relative_to(root).as_posix(), 'kind': kind,
            'size': value.st_size,
            'modified_at': datetime.fromtimestamp(value.st_mtime, UTC).isoformat()}
if sys.argv[2] == 'tree':
    rules = load_ignore_rules('/workspace')
    result = []
    if p.is_dir() and not p.is_symlink():
        for dirpath, dirnames, filenames in os.walk(p, followlinks=False):
            current = Path(dirpath)
            kept = []
            for name in dirnames:
                item = current / name
                relative = item.relative_to(root).as_posix()
                if should_skip(relative, rules, is_dir=True):
                    continue
                kept.append(name)
                result.append(encode(item))
            dirnames[:] = kept
            for name in filenames:
                item = current / name
                relative = item.relative_to(root).as_posix()
                if should_skip(relative, rules, is_dir=False):
                    continue
                result.append(encode(item))
    result.sort(key=lambda row: row['path'])
else:
    if not p.exists() and not p.is_symlink():
        raise SystemExit(2)
    result = encode(p)
sys.stdout.write(json.dumps(result))
"""
)
_SNAPSHOT_HELPER = """\
import os, sys, tarfile
from pathlib import Path

def is_secret(rel):
    if rel in {'.env', '.git/credentials', '.neos/secrets'} or rel.startswith('.neos/secrets/'):
        return True
    parts = tuple(p for p in rel.replace('\\\\', '/').split('/') if p not in {'', '.'})
    if not parts:
        return False
    folded = tuple(p.casefold() for p in parts)
    name = folded[-1]
    if name == '.env' or name.startswith('.env.'):
        return True
    if '.git' in folded or '.ssh' in folded:
        return True
    if name == 'id_rsa':
        return True
    return any(part == '.aws' and folded[i + 1] == 'credentials' for i, part in enumerate(folded[:-1]))

root = Path('/workspace')
with tarfile.open(fileobj=sys.stdout.buffer, mode='w|') as archive:
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        kept = []
        for name in sorted(dirnames):
            item = current / name
            relative = item.relative_to(root).as_posix()
            if item.is_symlink() or is_secret(relative):
                continue
            kept.append(name)
            archive.add(item, arcname=relative, recursive=False)
        dirnames[:] = kept
        for name in sorted(filenames):
            item = current / name
            relative = item.relative_to(root).as_posix()
            if item.is_symlink() or is_secret(relative):
                continue
            if item.is_socket() or item.is_block_device() or item.is_char_device() or item.is_fifo():
                continue
            archive.add(item, arcname=relative, recursive=False)
"""
_RESTORE_HELPER = """\
import sys, tarfile
with tarfile.open(fileobj=sys.stdin.buffer, mode='r|*') as archive:
    archive.extractall('/workspace', filter='data')
"""
_SCAN_HELPER = """\
import json, os
from pathlib import Path

def is_secret(rel):
    parts = tuple(p for p in rel.replace('\\\\', '/').split('/') if p not in {'', '.'})
    if not parts:
        return False
    folded = tuple(p.casefold() for p in parts)
    name = folded[-1]
    if name == '.env' or name.startswith('.env.'):
        return True
    if '.git' in folded or '.ssh' in folded:
        return True
    if name == 'id_rsa':
        return True
    return any(part == '.aws' and folded[i + 1] == 'credentials' for i, part in enumerate(folded[:-1]))

root = Path('/workspace')
result = {}
for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
    current = Path(dirpath)
    kept = []
    for name in dirnames:
        item = current / name
        if item.is_symlink():
            continue
        relative = item.relative_to(root).as_posix()
        if is_secret(relative) or relative.startswith('.git/') or relative.endswith(('.swp', '~')):
            continue
        kept.append(name)
    dirnames[:] = kept
    for name in filenames:
        item = current / name
        if item.is_symlink() or not item.is_file():
            continue
        relative = item.relative_to(root).as_posix()
        if is_secret(relative) or relative.startswith('.git/') or relative.endswith(('.swp', '~')):
            continue
        value = item.lstat()
        result[relative] = [value.st_size, value.st_mtime_ns]
print(json.dumps(result, sort_keys=True))
"""
