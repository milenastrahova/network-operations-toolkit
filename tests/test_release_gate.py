"""Checks integrity gate fails closed when release inputs are changed."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('netops_release_audit',ROOT/'scripts'/'release_audit.py')
audit_module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_module)

class ReleaseGateTests(unittest.TestCase):
    def test_baseline_manifest(self):
        audit_module.audit()

    def test_modified_content_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)
            (base/'README.md').write_text('changed',encoding='utf-8')
            (base/'MANIFEST.json').write_text(json.dumps({
                'version':'1.0.0',
                'files':{'README.md':hashlib.sha256(b'expected').hexdigest()}
            }), encoding='utf-8')
            with mock.patch.object(audit_module,'ROOT',base), mock.patch.object(audit_module,'MANIFEST_PATH',base/'MANIFEST.json'):
                with self.assertRaisesRegex(ValueError,'SHA-256 mismatches'):
                    audit_module.audit()

    def test_untracked_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)
            (base/'safe.txt').write_text('safe',encoding='utf-8')
            (base/'unexpected.txt').write_text('unexpected',encoding='utf-8')
            (base/'MANIFEST.json').write_text(json.dumps({
                'version':'1.0.0',
                'files':{'safe.txt':hashlib.sha256(b'safe').hexdigest()}
            }), encoding='utf-8')
            with mock.patch.object(audit_module,'ROOT',base), mock.patch.object(audit_module,'MANIFEST_PATH',base/'MANIFEST.json'):
                with self.assertRaisesRegex(ValueError,'paths mismatch'):
                    audit_module.audit()

    def test_refuse_local_report_in_release_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)
            (base/'local-reports').mkdir()
            (base/'local-reports'/'secret.json').write_text('{}',encoding='utf-8')
            with mock.patch.object(audit_module,'ROOT',base):
                with self.assertRaisesRegex(ValueError,'Local evidence detected'):
                    audit_module.source_files()
