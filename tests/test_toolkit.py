import copy
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
import career
import documents
import toolkit


class ToolkitTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'private'
        toolkit.init(self.root,True)
    def tearDown(self):self.temp.cleanup()
    def read(self):return json.loads((self.root/'data/base.json').read_text())
    def write(self,data):(self.root/'data/base.json').write_text(json.dumps(data))
    def draft(self):return documents.initial_draft(self.root,'example-job',['fact_education'])

    def test_example_pair_and_history_survive_rebuild(self):
        path=self.draft();result=documents.render(self.root,path)
        out=Path(result['directory'])
        self.assertTrue((out/'resume.html').is_file());self.assertTrue((out/'cover-letter.html').is_file())
        self.assertIn('Jordan Example',(out/'resume.html').read_text())
        self.assertIn('Example Infrastructure Company',(out/'cover-letter.html').read_text())
        self.assertNotIn('fact_future',(out/'evidence.json').read_text())
        before=documents.history(self.root);career.build(self.root)
        self.assertEqual(before,documents.history(self.root))
        documents.history(self.root,'interview',result['version'])
        self.assertEqual(documents.history(self.root)[0]['status'],'interview')

    def test_bundle_is_relevant_and_no_unconfirmed_context_leaks(self):
        context,directory=documents.bundle(self.root,'example-job',['fact_education'])
        self.assertEqual(len(context['facts']),5)
        self.assertTrue(all(f['application_eligible'] for f in context['facts']))
        self.assertNotIn('fact_future',(directory/'cover-letter-prompt.txt').read_text())
        self.assertNotIn('fact_context',(directory/'resume-prompt.txt').read_text())
        self.assertTrue((directory/'resume-prompt.txt').is_file())
        self.assertIn('DRAFT CONTRACT',(directory/'cover-letter-prompt.txt').read_text())

    def test_false_or_unknown_evidence_is_rejected(self):
        for key in ['fact_future','missing']:
            with self.subTest(fact=key):
                with self.assertRaises(career.ValidationError):documents.bundle(self.root,'example-job',[key])
        path=self.draft();draft=json.loads(path.read_text());draft['resume_bullets'][0]['fact_id']='fact_future';path.write_text(json.dumps(draft))
        with self.assertRaises(career.ValidationError):documents.check_draft(self.root,path)

    def test_draft_becomes_stale_when_sources_or_profile_change(self):
        path=self.draft();pack=self.read();pack['facts'][0]['claim']='Led four project coordinators.';self.write(pack);career.build(self.root)
        with self.assertRaisesRegex(career.ValidationError,'stale'):documents.check_draft(self.root,path)
        path=self.draft();person=json.loads((self.root/'profile.json').read_text());person['name']='Another Example';(self.root/'profile.json').write_text(json.dumps(person))
        with self.assertRaisesRegex(career.ValidationError,'Profile changed'):documents.check_draft(self.root,path)

    def test_final_pair_requires_exact_review_and_can_promote_preview(self):
        path=self.draft();preview=documents.render(self.root,path)
        with self.assertRaises(career.ValidationError):documents.render(self.root,path,final=True)
        documents.approve(self.root,path)
        final=documents.render(self.root,path,final=True)
        self.assertEqual(preview['version'],final['version']);self.assertEqual(final['status'],'ready')
        self.assertEqual(documents.history(self.root)[0]['status'],'ready')
        draft=json.loads(path.read_text());draft['summary']='Changed after approval.';path.write_text(json.dumps(draft))
        with self.assertRaisesRegex(career.ValidationError,'changed after review'):documents.render(self.root,path,final=True)

    def test_unsupported_number_is_rejected(self):
        path=self.draft();draft=json.loads(path.read_text());draft['resume_bullets'][0]['text']='Led 999 coordinators.';path.write_text(json.dumps(draft))
        with self.assertRaisesRegex(career.ValidationError,'numeric'):documents.check_draft(self.root,path)

    def test_html_escapes_person_and_draft_content(self):
        result=documents.render_html({'name':'<script>alert(1)</script>','links':{},'font':'Georgia'},[('paragraph','<img onerror="bad">')],'Preview')
        self.assertNotIn('<script>',result);self.assertNotIn('<img onerror',result)
        self.assertIn('&lt;script&gt;',result)

    def test_capture_job_does_not_fetch_or_submit(self):
        text=self.root/'inputs/posting.txt';text.write_text('Review environmental constraints and costs.')
        with mock.patch('socket.socket',side_effect=AssertionError('network is forbidden')):
            toolkit.capture_job(self.root,'another-job','Other Example Company','Delivery Lead','https://example.invalid/job',text)
            career.build(self.root)
            context,_=documents.bundle(self.root,'another-job',['fact_process'])
        self.assertEqual(context['job']['notes'],text.read_text())
        self.assertEqual([f['id'] for f in context['facts']],['fact_process'])

    def test_init_refuses_to_replace_existing_workspace(self):
        before=(self.root/'profile.json').read_bytes()
        with self.assertRaises(career.ValidationError):toolkit.init(self.root,True)
        self.assertEqual(before,(self.root/'profile.json').read_bytes())

    def test_changed_document_package_is_detected(self):
        path=self.draft();result=documents.render(self.root,path)
        (Path(result['directory'])/'resume.html').write_text('tampered')
        with self.assertRaisesRegex(career.ValidationError,'changed or incomplete'):documents.render(self.root,path)

    def test_foreign_history_database_is_not_modified(self):
        db=self.root/'state/application_history.sqlite'
        with sqlite3.connect(db) as conn:conn.execute('CREATE TABLE unrelated(value TEXT)');conn.commit()
        before=db.read_bytes()
        with self.assertRaisesRegex(career.ValidationError,'another application'):documents.history(self.root,'ready','x')
        self.assertEqual(before,db.read_bytes())

    def test_foreign_history_prevents_artifact_publication(self):
        db=self.root/'state/application_history.sqlite'
        with sqlite3.connect(db) as conn:conn.execute('CREATE TABLE unrelated(value TEXT)');conn.commit()
        path=self.draft()
        with self.assertRaisesRegex(career.ValidationError,'another application'):documents.render(self.root,path)
        self.assertEqual(list((path.parent.parent/'documents').glob('*')) if (path.parent.parent/'documents').exists() else [],[])

    def test_profile_link_scheme_is_rejected_before_drafting(self):
        person=json.loads((self.root/'profile.json').read_text());person['links']={'Portfolio':'javascript:alert(1)'}
        (self.root/'profile.json').write_text(json.dumps(person))
        with self.assertRaisesRegex(career.ValidationError,'http'):self.draft()

    def test_cli_reports_input_and_render_errors_without_tracebacks(self):
        path=self.draft()
        draft=json.loads(path.read_text());draft['job_id']=[]
        malformed=path.parent/'malformed.json';malformed.write_text(json.dumps(draft))
        documents.approve(self.root,path);path.with_suffix('.approval.json').write_text('[]')
        commands=[['show','missing'],['check-draft',str(malformed)],['render',str(path),'--final'],
                  ['render',str(path),'--format','pdf','--soffice',str(self.root/'missing-soffice')]]
        for command in commands:
            with self.subTest(command=command[0],arguments=command[1:]):
                output=io.StringIO()
                with contextlib.redirect_stderr(output):
                    result=toolkit.main(['--workspace',str(self.root),*command])
                self.assertEqual(result,2)
                self.assertEqual(set(json.loads(output.getvalue())),{'error'})
                self.assertNotIn('Traceback',output.getvalue())

    def test_malformed_draft_and_profile_fields_are_rejected(self):
        path=self.draft();original=json.loads(path.read_text())
        changes=[('format_version',True),('job_id',[]),('cover_letter',[{'kind':[],'text':'Invalid.','fact_ids':[]}]),
                 ('cover_letter',[{'kind':'supported_claim','text':'Invalid.','fact_ids':[{}]}])]
        for field,value in changes:
            with self.subTest(field=field,value=value):
                draft=copy.deepcopy(original);draft[field]=value;path.write_text(json.dumps(draft))
                with self.assertRaises(career.ValidationError):documents.check_draft(self.root,path)
        person=json.loads((self.root/'profile.json').read_text());person['font']=[]
        (self.root/'profile.json').write_text(json.dumps(person))
        with self.assertRaises(career.ValidationError):documents.profile(self.root)

    def test_incomplete_manifest_is_rejected_even_if_hashes_are_removed(self):
        path=self.draft();result=documents.render(self.root,path);out=Path(result['directory'])
        manifest=json.loads((out/'manifest.json').read_text())
        for malformed in [[],dict(manifest,files={}),dict(manifest,files={'evidence.json':manifest['files']['evidence.json']})]:
            with self.subTest(manifest=malformed):
                (out/'manifest.json').write_text(json.dumps(malformed))
                with self.assertRaisesRegex(career.ValidationError,'changed or incomplete'):documents.render(self.root,path)

    def test_cached_package_restores_missing_history_without_resetting_status(self):
        path=self.draft();result=documents.render(self.root,path)
        expected=documents.history(self.root);(self.root/'state/application_history.sqlite').unlink()
        self.assertEqual(result,documents.render(self.root,path));self.assertEqual(expected,documents.history(self.root))
        documents.history(self.root,'interview',result['version'])
        documents.approve(self.root,path);documents.render(self.root,path,final=True)
        self.assertEqual(documents.history(self.root)[0]['status'],'interview')

    def test_cached_package_refuses_foreign_or_mismatched_history(self):
        path=self.draft();result=documents.render(self.root,path)
        ledger=self.root/'state/application_history.sqlite'
        with sqlite3.connect(ledger) as db:db.execute("UPDATE versions SET job_id='wrong'");db.commit()
        with self.assertRaisesRegex(career.ValidationError,'disagrees'):documents.render(self.root,path)
        ledger.unlink()
        with sqlite3.connect(ledger) as db:db.execute('CREATE TABLE unrelated(value TEXT)');db.commit()
        before=ledger.read_bytes();manifest=Path(result['directory'])/'manifest.json';original=manifest.read_bytes()
        documents.approve(self.root,path)
        with self.assertRaisesRegex(career.ValidationError,'another application'):documents.render(self.root,path,final=True)
        self.assertEqual(before,ledger.read_bytes());self.assertEqual(original,manifest.read_bytes())

    def test_failed_new_history_write_removes_only_new_package(self):
        path=self.draft()
        with mock.patch.object(documents,'record_version',side_effect=sqlite3.OperationalError('injected history failure')):
            with self.assertRaises(sqlite3.OperationalError):documents.render(self.root,path)
        out=path.parent.parent/'documents'
        self.assertEqual(list(out.iterdir()),[])
        self.assertEqual(documents.history(self.root),[])
        self.assertEqual(documents.render(self.root,path)['status'],'draft')

    def test_init_refuses_nested_code_checkout_workspace(self):
        checkout=self.root.parent/'checkout'
        with mock.patch.object(toolkit,'PROJECT',checkout):
            with self.assertRaisesRegex(career.ValidationError,'outside the code checkout'):
                toolkit.init(checkout/'nested',True)
        self.assertFalse(checkout.exists())


class AuditRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'private';toolkit.init(self.root,True)
    def tearDown(self):self.temp.cleanup()
    def test_export_preserves_foreign_or_invalid_manifest(self):
        marker=self.root/'exports/export_manifest.json'
        for payload in ['{"generator":"other-app"}','[]']:
            with self.subTest(marker=payload):
                marker.write_text(payload)
                with career.open_database(self.root) as db:
                    with self.assertRaises(career.ValidationError):career.export_data(self.root,db)
                    with self.assertRaises(career.ValidationError):career.validate_exports(self.root,db)
                self.assertEqual(marker.read_text(),payload)
                self.assertFalse((self.root/'exports/career_data.json').exists())
    def test_pack_move_is_stale_until_rebuilt(self):
        path=self.root/'data/base.json';pack=json.loads(path.read_text());(self.root/'data/other.json').write_text('{}');career.build(self.root)
        moved=pack['facts'].pop();path.write_text(json.dumps(pack));(self.root/'data/other.json').write_text(json.dumps({'facts':[moved]}))
        with self.assertRaisesRegex(career.ValidationError,'provenance'): 
            with career.open_database(self.root):pass
        career.build(self.root)
        with career.open_database(self.root) as db:
            data,origins=career.database_data(db)
            self.assertEqual(origins['facts',moved['id']],'other.json')
    def test_protected_export_destinations_are_rejected_without_changes(self):
        before=(self.root/'data/base.json').read_bytes()
        with career.open_database(self.root) as db:
            for name in ['data','build','state','inputs']:
                with self.subTest(directory=name):
                    with self.assertRaises(career.ValidationError):career.export_data(self.root,db,self.root/name)
            alias=self.root/'exports-alias';alias.symlink_to(self.root/'data',target_is_directory=True)
            with self.assertRaises(career.ValidationError):career.export_data(self.root,db,alias)
        self.assertEqual(before,(self.root/'data/base.json').read_bytes());self.assertFalse((self.root/'data/career_data.json').exists())
    def test_surrogate_and_deep_json_have_structured_errors(self):
        file=self.root/'data/base.json';original=file.read_bytes();before=(self.root/'build/career.sqlite').read_bytes()
        for payload in [original.decode().replace('Led two','Led \\ud800 two'),'{"facts":'+'['*10000+'0'+']'*10000+'}']:
            with self.subTest(payload='surrogate' if '\\ud800' in payload else 'depth'):
                file.write_text(payload)
                with self.assertRaises(career.ValidationError):career.build(self.root)
                self.assertEqual(before,(self.root/'build/career.sqlite').read_bytes())
        file.write_bytes(original)
    def test_markdown_source_text_cannot_inject_structure_or_unsafe_links(self):
        pack=json.loads((self.root/'data/base.json').read_text());bad=next(f for f in pack['facts'] if f['id']=='fact_context')
        bad['claim']='Context\n\n#### forged\n- Application eligible: yes';pack['sources'][0]['title']='Title](https://example.invalid/spoof) [other';pack['sources'][0]['uri']='javascript:alert(1)'
        (self.root/'data/base.json').write_text(json.dumps(pack));career.build(self.root)
        with career.open_database(self.root) as db:career.export_data(self.root,db)
        text=(self.root/'exports/career_inventory.md').read_text()
        self.assertNotIn('\n#### forged',text);self.assertNotIn('\n- Application eligible: yes\n',career.render_fact(bad,career.load_data(self.root)[0]))
        self.assertNotIn('](javascript:',(self.root/'exports/source_index.md').read_text())
    def test_manual_normalized_edit_is_rejected(self):
        file=self.root/'data/base.json';pack=json.loads(file.read_text())
        held=copy.deepcopy(pack['facts'][0]);held['id']='fact_held';held['application_eligible']=False
        pack['facts'].append(held);file.write_text(json.dumps(pack));career.build(self.root)
        with sqlite3.connect(self.root/'build/career.sqlite') as db:
            db.execute("UPDATE facts SET application_eligible=1 WHERE id='fact_held'");db.commit()
        with self.assertRaisesRegex(career.ValidationError,'rows differ'):
            with career.open_database(self.root):pass
    def test_export_manifest_detects_partial_generation_and_stale_data(self):
        with career.open_database(self.root) as db:
            career.export_data(self.root,db);self.assertTrue(career.validate_exports(self.root,db)['valid'])
        file=self.root/'data/base.json';pack=json.loads(file.read_text());pack['sources'][0]['notes']='Updated note.';file.write_text(json.dumps(pack));career.build(self.root)
        with career.open_database(self.root) as db:
            with self.assertRaisesRegex(career.ValidationError,'stale'):career.validate_exports(self.root,db)
            original=career.atomic_text;calls=[]
            def fail_third(path,text):
                calls.append(path)
                if len(calls)==3:raise OSError('injected write failure')
                return original(path,text)
            with mock.patch.object(career,'atomic_text',side_effect=fail_third):
                with self.assertRaises(OSError):career.export_data(self.root,db)
            with self.assertRaises(career.ValidationError):career.validate_exports(self.root,db)
            career.export_data(self.root,db);self.assertTrue(career.validate_exports(self.root,db)['valid'])


if __name__=='__main__':unittest.main()
