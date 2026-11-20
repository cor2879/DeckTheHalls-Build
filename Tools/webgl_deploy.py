#!/usr/bin/env python3
"""Stage a Unity Web export, then prepare its runtime files for GitHub Pages."""
import argparse
import gzip
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
CHUNK_BYTES = 90 * 1024 * 1024
PAGES_BYTES = 1_000_000_000
FOLDERS = {'Build', 'StreamingAssets', 'TemplateData'}
ROOT_FILES = {'index.html', 'favicon.ico', 'manifest.webmanifest', 'robots.txt'}
PRIVATE_SUFFIXES = {'.cs', '.csproj', '.sln', '.unity', '.asset', '.aseprite', '.psd', '.blend', '.fbx', '.pdb', '.mdb', '.cpp', '.h', '.cc', '.c', '.jslib', '.dll', '.exe', '.so', '.dylib', '.a'}


def safe_relative(value):
    p = PurePosixPath(value)
    if not value or '\\' in value or p.is_absolute() or '..' in p.parts or str(p) != value:
        raise ValueError(f'Unsafe relative path: {value!r}')
    return p


def allowed(value):
    p = safe_relative(value)
    return (len(p.parts) == 1 and p.name in ROOT_FILES) or (len(p.parts) > 1 and p.parts[0] in FOLDERS)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        if stream.read(128).startswith(b'version https://git-lfs.github.com/spec/v1'):
            raise ValueError(f'Git LFS pointer instead of game bytes: {path.name}')
        stream.seek(0)
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def export_files(source):
    if not (source / 'index.html').is_file() or not (source / 'Build').is_dir():
        raise ValueError('Choose the exported Web build folder containing index.html and Build/, not the Unity project.')
    for p in sorted(source.rglob('*')):
        if p.is_symlink():
            raise ValueError(f'Symlinks are not accepted: {p.relative_to(source)}')
        if not p.is_file():
            continue
        rel = p.relative_to(source).as_posix()
        if not allowed(rel) or p.suffix.lower() == '.meta' or any(x.startswith('.') for x in p.relative_to(source).parts):
            continue
        if p.suffix.lower() in PRIVATE_SUFFIXES:
            raise ValueError(f'Unity source/art detected in export: {rel}')
        yield p, rel


def replace_generated(temp, target):
    # Only the generated site/ and _site/ directories can be replaced.
    if target not in (ROOT / 'site', ROOT / '_site') or target.is_symlink():
        raise ValueError('Refusing to replace a non-generated destination.')
    if target.exists():
        shutil.rmtree(target)
    shutil.move(str(temp), str(target))


def stage(source):
    source = Path(source).expanduser().resolve()
    target = ROOT / 'site'
    if source == target.resolve() or target.resolve() in source.parents or source in target.resolve().parents:
        raise ValueError('The export must be separate from this repository and its generated site/ folder.')
    files = list(export_files(source))
    index = (source / 'index.html').read_text(encoding='utf-8')
    if '{{{' in index:
        raise ValueError('This is a Unity HTML template, not a completed export.')
    names = [rel for _, rel in files if rel.startswith('Build/')]
    if not any('.loader.js' in n for n in names) or not any('.wasm' in n for n in names) or not any('.data' in n for n in names):
        raise ValueError('The export is missing its loader, WebAssembly or data file.')
    with tempfile.TemporaryDirectory(prefix='.webgl-stage-', dir=ROOT) as temporary:
        temp = Path(temporary) / 'site'
        temp.mkdir()
        manifest = {'format': 1, 'files': []}
        for path, rel in files:
            sha = digest(path)
            entry = {'path': rel, 'size': path.stat().st_size, 'sha256': sha, 'storage': []}
            if entry['size'] > CHUNK_BYTES:
                with path.open('rb') as stream:
                    i = 0
                    while True:
                        block = stream.read(CHUNK_BYTES)
                        if not block:
                            break
                        stored = f'.parts/{sha}/{i:04d}.part'
                        out = temp / stored
                        out.parent.mkdir(parents=True, exist_ok=True)
                        out.write_bytes(block)
                        entry['storage'].append(stored)
                        i += 1
            else:
                out = temp / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, out)
                entry['storage'].append(rel)
            manifest['files'].append(entry)
        (temp / 'build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        validate(temp)
        replace_generated(temp, target)
    size = sum(e['size'] for e in manifest['files'])
    print(f'Staged {len(files)} runtime files ({size / 1024 / 1024:.1f} MiB). Original export unchanged.')
    print('Next: git add site && git commit -m "Upload tested WebGL build" && git push')


def manifest_entries(site):
    if site.is_symlink():
        raise ValueError('site/ must not be a symlink.')
    manifest = json.loads((site / 'build-manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 1 or not isinstance(manifest.get('files'), list):
        raise ValueError('Unsupported build manifest.')
    seen = set()
    for entry in manifest['files']:
        rel = entry['path']
        if not allowed(rel) or Path(rel).suffix.lower() in PRIVATE_SUFFIXES or rel in seen:
            raise ValueError(f'Invalid/duplicate runtime path: {rel}')
        seen.add(rel)
        if not isinstance(entry.get('size'), int) or entry['size'] < 0 or not entry.get('storage'):
            raise ValueError(f'Invalid size/storage for {rel}')
        for stored in entry['storage']:
            safe_relative(stored)
            if stored != rel and not stored.startswith('.parts/'):
                raise ValueError(f'Invalid stored chunk for {rel}')
            path = site / stored
            if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(site.resolve()):
                raise ValueError(f'Missing/unsafe stored payload: {stored}')
        yield entry
    if 'index.html' not in seen or not any(p.startswith('Build/') for p in seen):
        raise ValueError('Manifest is missing the game entry point or Build payload.')


def join_entry(site, entry, output=None):
    h = hashlib.sha256()
    size = 0
    first = True
    for stored in entry['storage']:
        with (site / stored).open('rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                if first and block.startswith(b'version https://git-lfs.github.com/spec/v1'):
                    raise ValueError('Git LFS pointer detected; actual exported bytes are required.')
                first = False
                h.update(block)
                size += len(block)
                if output is not None:
                    output.write(block)
    if size != entry['size'] or h.hexdigest() != entry['sha256']:
        raise ValueError(f'Incomplete or modified build payload: {entry["path"]}')


def validate(site=None):
    site = site or ROOT / 'site'
    entries = list(manifest_entries(site))
    for entry in entries:
        join_entry(site, entry)
    print(f'PASS: {len(entries)} payload checksums and runtime paths.')
    return entries


def decompress_build(path):
    if path.suffix not in {'.gz', '.br'}:
        return path
    output = path.with_suffix('')
    if output.exists():
        raise ValueError(f'Compressed/uncompressed name collision: {output.name}')
    if path.suffix == '.gz':
        with gzip.open(path, 'rb') as source, output.open('wb') as dest:
            shutil.copyfileobj(source, dest)
    else:
        try:
            import brotli
        except ImportError as exc:
            raise ValueError('Brotli export: install Tools/requirements-deploy.txt before preparing Pages.') from exc
        decoder = brotli.Decompressor()
        with path.open('rb') as source, output.open('wb') as dest:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                dest.write(decoder.process(block))
        if not decoder.is_finished():
            raise ValueError(f'Truncated Brotli stream: {path.name}')
    path.unlink()
    return output


def apply_host_layout(index):
    css = (ROOT / 'Web' / 'game-viewport.css').read_text(encoding='utf-8')
    # Replace our earlier override when preparing an export made with the new template.
    index = re.sub(r'<style\b[^>]*\bid=[\"\']dth-viewport[\"\'][^>]*>.*?</style\s*>',
                   '', index, flags=re.IGNORECASE | re.DOTALL)
    override = '<style id="dth-viewport">\n' + css + '</style>\n'
    if re.search(r'</head\s*>', index, flags=re.IGNORECASE):
        return re.sub(r'</head\s*>', lambda match: override + match.group(), index,
                      count=1, flags=re.IGNORECASE)
    return override + index


def prepare():
    site = ROOT / 'site'
    entries = validate(site)
    with tempfile.TemporaryDirectory(prefix='.webgl-pages-', dir=ROOT) as temporary:
        temp = Path(temporary) / 'output'
        temp.mkdir()
        for entry in entries:
            out = temp / entry['path']
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open('wb') as dest:
                join_entry(site, entry, dest)
        index_path = temp / 'index.html'
        index = index_path.read_text(encoding='utf-8')
        mapping = []
        for path in sorted((temp / 'Build').rglob('*')):
            if not path.is_file():
                continue
            before = path.relative_to(temp).as_posix()
            after = decompress_build(path).relative_to(temp).as_posix()
            if before != after:
                mapping.extend([(before, after), (Path(before).name, Path(after).name)])
        for before, after in sorted(set(mapping), key=lambda pair: len(pair[0]), reverse=True):
            index = index.replace(before, after).replace(quote(before), quote(after))
        index_path.write_text(apply_host_layout(index), encoding='utf-8')
        (temp / '.nojekyll').touch()
        (temp / 'robots.txt').write_text('User-agent: *\nDisallow: /\n', encoding='utf-8')
        size = sum(p.stat().st_size for p in temp.rglob('*') if p.is_file())
        if size > PAGES_BYTES:
            raise ValueError(f'Published files total {size:,} bytes, exceeding the 1 GB Pages site limit.')
        replace_generated(temp, ROOT / '_site')
    print(f'Prepared _site/ ({size / 1024 / 1024:.1f} MiB), with no Unity source or deployment tools.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    subs.add_parser('stage').add_argument('export', help='Completed Unity Web export folder')
    subs.add_parser('validate')
    subs.add_parser('prepare')
    args = parser.parse_args()
    try:
        if args.command == 'stage':
            stage(args.export)
        elif args.command == 'validate':
            validate()
        else:
            prepare()
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, f'ERROR: {exc}\n')


if __name__ == '__main__':
    main()
