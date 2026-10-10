import contextlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import career
import documents
import toolkit


class CliWorkflowTests(unittest.TestCase):
    def invoke(self,args):
        out=io.StringIO();error=io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(error):code=toolkit.main(args)
        return code,json.loads(out.getvalue() or error.getvalue())

    def test_fts5_failure_creates_no_workspace_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'workspace'
            with mock.patch.object(toolkit.sqlite3,'connect',side_effect=sqlite3.OperationalError('no such module: fts5')):
                code,result=self.invoke(['init',str(root),'--example'])
            self.assertEqual(code,2);self.assertIn('FTS5',result['error']);self.assertFalse(root.exists())

    def test_stale_error_names_the_actual_workspace_build_command(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'workspace';toolkit.init(root,True)
            data=json.loads((root/'data/base.json').read_text());data['sources'][0]['notes']='Updated source'
            (root/'data/base.json').write_text(json.dumps(data),encoding='utf-8')
            code,result=self.invoke(['--workspace',str(root),'search','delivery'])
            self.assertEqual(code,2);self.assertIn('toolkit.py --workspace',result['error'])
            self.assertIn(str(root.resolve()),result['error']);self.assertNotIn('python career.py build',result['error'])

    def test_build_failure_preserves_sources_and_gives_recovery_command(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'workspace'
            with mock.patch.object(career,'build',side_effect=sqlite3.OperationalError('injected disk failure')):
                code,result=self.invoke(['init',str(root),'--example'])
            self.assertEqual(code,2);self.assertIn('--workspace',result['error']);self.assertIn('build',result['error'])
            self.assertIn('preserved',result['error']);before=(root/'data/base.json').read_bytes()
            code,result=self.invoke(['--workspace',str(root),'build'])
            self.assertEqual(code,0);self.assertEqual(before,(root/'data/base.json').read_bytes())

    def test_validate_reports_bad_profile_before_drafting(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'workspace';toolkit.init(root,True)
            person=json.loads((root/'profile.json').read_text());person['links']['bad']='javascript:alert(1)'
            (root/'profile.json').write_text(json.dumps(person),encoding='utf-8')
            code,result=self.invoke(['--workspace',str(root),'validate'])
            self.assertEqual(code,2);self.assertIn('http or https',result['error'])

    def test_capture_unicode_job_keeps_description_separate_from_private_notes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'workspace';toolkit.init(root,True)
            posting=root/'inputs/job.txt';text='Résumé – delivery ’reviews’ and team coordination.'
            posting.write_text(text,encoding='utf-8')
            code,result=self.invoke(['--workspace',str(root),'capture-job','unicode-job','--company','Example Employer',
                                     '--title','Delivery Lead','--url','https://example.invalid/job','--description',str(posting)])
            self.assertEqual(code,0)
            data,_,_=career.load_data(root)
            self.assertEqual(data['jobs']['unicode-job']['description'],text)
            self.assertEqual(data['jobs']['unicode-job']['notes'],'')

    def test_refresh_command_preserves_prose_and_requires_new_review(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'workspace';toolkit.init(root,True)
            old=documents.initial_draft(root,'example-job',['fact_education']);value=json.loads(old.read_text())
            value['summary']='Practical delivery experience.';old.write_text(json.dumps(value),encoding='utf-8')
            person=json.loads((root/'profile.json').read_text());person['motivation']='Interested in useful improvements.'
            (root/'profile.json').write_text(json.dumps(person),encoding='utf-8')
            code,result=self.invoke(['--workspace',str(root),'refresh-draft',str(old)])
            self.assertEqual(code,0);self.assertTrue(result['review_required'])
            refreshed=Path(result['path']);self.assertNotEqual(refreshed,old)
            self.assertEqual(json.loads(refreshed.read_text())['summary'],value['summary'])
            self.assertFalse(refreshed.with_suffix('.approval.json').exists())
