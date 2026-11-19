import gzip
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('webgl_deploy', Path(__file__).with_name('webgl_deploy.py'))
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.previous = d.ROOT, d.CHUNK_BYTES, d.PAGES_BYTES
        d.ROOT = self.base / 'repo'
        d.ROOT.mkdir()
        self.export = self.base / 'export'
        (self.export / 'Build').mkdir(parents=True)
        (self.export / 'index.html').write_text('<script>var dataUrl="Build/t.data"; var codeUrl="Build/t.wasm";</script>')
        for name, data in [('t.loader.js', b'loader'), ('t.framework.js', b'framework'), ('t.wasm', b'wasm'), ('t.data', b'game-data')]:
            (self.export / 'Build' / name).write_bytes(data)

    def tearDown(self):
        d.ROOT, d.CHUNK_BYTES, d.PAGES_BYTES = self.previous
        self.temp.cleanup()

    def test_round_trip_includes_runtime_only(self):
        (self.export / 'Assets').mkdir()
        (self.export / 'Assets' / 'Private.cs').write_text('private')
        (self.export / 'README.txt').write_text('not runtime')
        (self.export / 'StreamingAssets').mkdir()
        (self.export / 'StreamingAssets' / 'movie.mp4').write_bytes(b'media')
        (self.export / 'StreamingAssets' / 'movie.mp4.meta').write_text('guid')
        d.stage(self.export)
        d.prepare()
        output = d.ROOT / '_site'
        self.assertEqual((output / 'StreamingAssets' / 'movie.mp4').read_bytes(), b'media')
        self.assertFalse((output / 'Assets').exists())
        self.assertFalse((output / 'README.txt').exists())
        self.assertFalse((output / 'build-manifest.json').exists())
        self.assertTrue((output / '.nojekyll').exists())

    def test_gzip_is_prepared_without_changing_original(self):
        (self.export / 'Build' / 't.data').unlink()
        data = b'UnityWebData1.0\x00game payload'
        compressed = gzip.compress(data)
        (self.export / 'Build' / 't.data.gz').write_bytes(compressed)
        (self.export / 'index.html').write_text('var buildUrl="Build"; var dataUrl=buildUrl+"/t.data.gz";')
        d.stage(self.export)
        d.prepare()
        self.assertEqual((self.export / 'Build' / 't.data.gz').read_bytes(), compressed)
        self.assertEqual((d.ROOT / '_site' / 'Build' / 't.data').read_bytes(), data)
        self.assertIn('/t.data"', (d.ROOT / '_site' / 'index.html').read_text())
        self.assertFalse((d.ROOT / '_site' / 'Build' / 't.data.gz').exists())

    def test_brotli_is_prepared_when_dependency_is_available(self):
        try:
            import brotli
        except ImportError:
            self.skipTest('Optional Brotli package is not installed')
        data = b'WebAssembly payload'
        (self.export / 'Build' / 't.wasm').unlink()
        (self.export / 'Build' / 't.wasm.br').write_bytes(brotli.compress(data))
        (self.export / 'index.html').write_text('var codeUrl="Build/t.wasm.br";')
        d.stage(self.export)
        d.prepare()
        self.assertEqual((d.ROOT / '_site' / 'Build' / 't.wasm').read_bytes(), data)
        self.assertIn('Build/t.wasm"', (d.ROOT / '_site' / 'index.html').read_text())

    def test_chunks_reassemble_exactly_and_are_not_published(self):
        d.CHUNK_BYTES = 16
        data = bytes(range(100))
        (self.export / 'Build' / 't.data').write_bytes(data)
        d.stage(self.export)
        manifest = json.loads((d.ROOT / 'site' / 'build-manifest.json').read_text())
        entry = next(e for e in manifest['files'] if e['path'] == 'Build/t.data')
        self.assertGreater(len(entry['storage']), 1)
        self.assertTrue(all((d.ROOT / 'site' / n).stat().st_size <= 16 for n in entry['storage']))
        d.prepare()
        self.assertEqual((d.ROOT / '_site' / 'Build' / 't.data').read_bytes(), data)
        self.assertFalse((d.ROOT / '_site' / '.parts').exists())

    def test_tampered_payload_is_rejected(self):
        d.stage(self.export)
        (d.ROOT / 'site' / 'Build' / 't.data').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Incomplete or modified'):
            d.prepare()

    def test_source_files_in_runtime_are_rejected(self):
        (self.export / 'StreamingAssets').mkdir()
        (self.export / 'StreamingAssets' / 'Private.cs').write_text('private')
        with self.assertRaisesRegex(ValueError, 'source/art'):
            d.stage(self.export)
        self.assertFalse((d.ROOT / 'site').exists())

    def test_unity_template_is_not_an_export(self):
        (self.export / 'index.html').write_text('{{{ LOADER_FILENAME }}}')
        with self.assertRaisesRegex(ValueError, 'template'):
            d.stage(self.export)

    def test_manifest_cannot_escape_site(self):
        d.stage(self.export)
        p = d.ROOT / 'site' / 'build-manifest.json'
        manifest = json.loads(p.read_text())
        manifest['files'][0]['storage'] = ['../private.txt']
        p.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            d.prepare()

    def test_lfs_pointer_is_not_game_payload(self):
        (self.export / 'Build' / 't.data').write_text('version https://git-lfs.github.com/spec/v1\noid sha256:fake\n')
        with self.assertRaisesRegex(ValueError, 'LFS'):
            d.stage(self.export)

    def test_failed_prepare_keeps_previous_prepared_site(self):
        d.stage(self.export)
        d.prepare()
        before = (d.ROOT / '_site' / 'Build' / 't.data').read_bytes()
        d.PAGES_BYTES = 1
        with self.assertRaisesRegex(ValueError, '1 GB'):
            d.prepare()
        self.assertEqual((d.ROOT / '_site' / 'Build' / 't.data').read_bytes(), before)

    def test_restage_removes_stale_export_files(self):
        (self.export / 'TemplateData').mkdir()
        (self.export / 'TemplateData' / 'old.png').write_bytes(b'old')
        d.stage(self.export)
        (self.export / 'TemplateData' / 'old.png').unlink()
        d.stage(self.export)
        self.assertFalse((d.ROOT / 'site' / 'TemplateData' / 'old.png').exists())


if __name__ == '__main__':
    unittest.main()
