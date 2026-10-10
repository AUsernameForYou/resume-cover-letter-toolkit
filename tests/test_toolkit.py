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
        self.assertEqual(context['job']['description'],text.read_text())
        self.assertEqual(context['job']['notes'],'')
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
        with self.assertRaisesRegex(career.ValidationError,'another application'):documents.history(self.root,'applied','x')
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

    def test_selected_roles_render_newest_first_with_semantic_lists(self):
        path=self.draft();result=documents.render(self.root,path)
        text=(Path(result['directory'])/'resume.html').read_text()
        self.assertLess(text.index('Product Developer'),text.index('Construction Coordinator'))
        self.assertIn('<ul>',text);self.assertIn('<li>',text);self.assertIn('<h3>Product Developer</h3>',text)
        self.assertNotIn('Present',text)

    def test_refresh_after_engine_upgrade_preserves_edits_but_requires_new_review(self):
        path=self.draft();draft=json.loads(path.read_text());draft['summary']='Practical engineering experience.';path.write_text(json.dumps(draft));documents.approve(self.root,path)
        with mock.patch.object(career,'engine_digest',return_value='a'*64):
            career.build(self.root)
            result=documents.refresh_draft(self.root,path)
            new=Path(result['path']);updated,_,_=documents.check_draft(self.root,new)
            self.assertEqual(updated['summary'],draft['summary'])
            self.assertIn('engine_sha256',result['changes']['snapshot_changed_fields'])
            self.assertFalse(new.with_suffix('.approval.json').exists())
            self.assertEqual(result['changes']['facts_changed'],[])

    def test_recorded_numbers_ignore_sentence_and_clause_punctuation(self):
        pack=self.read();pack['facts'][0]['claim']='Managed a team of 12.';self.write(pack);career.build(self.root)
        path=self.draft();original=json.loads(path.read_text())
        for text in ['Managed 12 engineers', 'Managed 12 engineers.', 'Managed 12, across teams']:
            with self.subTest(text=text):
                draft=copy.deepcopy(original);draft['resume_bullets'][0]['text']=text;path.write_text(json.dumps(draft))
                documents.check_draft(self.root,path)
        original['resume_bullets'][0]['text']='Managed 999 engineers';path.write_text(json.dumps(original))
        with self.assertRaisesRegex(career.ValidationError,'numeric'):documents.check_draft(self.root,path)
        for claim, text in [('Negotiated $25,000, in credits.', 'Negotiated $25,000 in credits'),
                            ('Reduced cost by 1.5%.', 'Reduced cost by 1.5% across the project')]:
            with self.subTest(claim=claim):
                pack['facts'][0]['claim']=claim;self.write(pack);career.build(self.root)
                path=self.draft();draft=json.loads(path.read_text());draft['resume_bullets'][0]['text']=text;path.write_text(json.dumps(draft))
                documents.check_draft(self.root,path)

    def test_prompt_sharing_allowlist_omits_private_fields_but_keeps_scope(self):
        pack=self.read();sentinel='INTERNAL_ONLY_SENTINEL'
        pack['sources'][0].update(notes=sentinel,local_path='private/sensitive.txt',uri='https://example.invalid/'+sentinel)
        pack['facts'][0]['usage_notes']=sentinel;pack['facts'][0]['evidence'][0].update(locator=sentinel,excerpt=sentinel)
        pack['roles'][0]['notes']=sentinel;pack['organizations'][0]['description']=sentinel
        pack['jobs'][0]['notes']=sentinel;pack['jobs'][0]['description']='PUBLIC_POSTING_DESCRIPTION'
        self.write(pack);career.build(self.root)
        person=json.loads((self.root/'profile.json').read_text());person.update(name=sentinel,email=sentinel+'@example.invalid',phone=sentinel,location=sentinel,links={'Private':'https://example.invalid/'+sentinel})
        (self.root/'profile.json').write_text(json.dumps(person))
        context,directory=documents.bundle(self.root,'example-job')
        self.assertIn(sentinel,(directory/'bundle.json').read_text())
        for kind in ['resume','cover-letter']:
            with self.subTest(prompt=kind):
                text=(directory/(kind+'-prompt.txt')).read_text()
                self.assertNotIn(sentinel,text);self.assertNotIn('base.json',text)
                self.assertIn('PUBLIC_POSTING_DESCRIPTION',text)
                self.assertNotIn('profile_sha256',text);self.assertNotIn('snapshot',text)
                self.assertIn('Approximately; shared contribution',text)
                self.assertIn('Project or organization scope never implies personal',text)
        shared=documents.prompt_context(context)
        self.assertEqual(set(shared['sources'][0]),{'id','title','kind','source_date'})
        self.assertNotIn('profile',shared);self.assertEqual(shared['facts'][0]['scope'],'personal')

    def test_explicit_letter_date_is_hash_bound_and_not_replaced_by_render_day(self):
        path=self.draft();draft=json.loads(path.read_text());draft['letter_date']='2026-10-01';path.write_text(json.dumps(draft))
        preview=documents.render(self.root,path);documents.approve(self.root,path)
        class Later(__import__('datetime').date):
            @classmethod
            def today(cls):return cls(2026,10,10)
        with mock.patch.object(documents.dt,'date',Later):final=documents.render(self.root,path,final=True)
        self.assertEqual(final['version'],preview['version']);self.assertEqual(final['letter_date'],'2026-10-01')
        self.assertIn('October 1, 2026',(Path(final['directory'])/'cover-letter.html').read_text())
        draft['letter_date']='2026-10-10';path.write_text(json.dumps(draft))
        with self.assertRaisesRegex(career.ValidationError,'changed after review'):documents.render(self.root,path,final=True)
        documents.approve(self.root,path);changed=documents.render(self.root,path,final=True)
        self.assertNotEqual(changed['version'],final['version']);self.assertEqual(changed['letter_date'],'2026-10-10')
        for date in ['2026-02-30','2026-1-1','20261010',True]:
            with self.subTest(date=date):
                draft['letter_date']=date;path.write_text(json.dumps(draft))
                with self.assertRaises(career.ValidationError):documents.check_draft(self.root,path)

    def test_draft_and_receipt_paths_cannot_escape_private_applications(self):
        path=self.draft();outside=self.root.parent/'outside.json';outside.write_bytes(path.read_bytes())
        for action in [documents.check_draft,documents.approve,documents.refresh_draft,documents.render]:
            with self.subTest(action=action.__name__):
                with self.assertRaisesRegex(career.ValidationError,'inside the private workspace'):action(self.root,outside)
        self.assertFalse(outside.with_suffix('.approval.json').exists())
        alias=path.parent/'alias.json';alias.symlink_to(outside)
        with self.assertRaises(career.ValidationError):documents.approve(self.root,alias)
        receipt=path.with_suffix('.approval.json');receipt.symlink_to(self.root.parent/'external-receipt.json')
        with self.assertRaises(career.ValidationError):documents.approve(self.root,path)
        self.assertFalse((self.root.parent/'external-receipt.json').exists())

    def test_refresh_preserves_edited_prose_and_old_files_without_approval(self):
        path=self.draft();edited=json.loads(path.read_text());edited['summary']='Practical construction and software experience.'
        edited['letter_date']='2026-10-01';path.write_text(json.dumps(edited));documents.approve(self.root,path)
        before=path.read_bytes();approval=path.with_suffix('.approval.json').read_bytes()
        pack=self.read();pack['sources'][0]['notes']='New source description';self.write(pack);career.build(self.root)
        person=json.loads((self.root/'profile.json').read_text());person['motivation']='Interested in useful public infrastructure.';(self.root/'profile.json').write_text(json.dumps(person))
        result=documents.refresh_draft(self.root,path);new=Path(result['path']);draft,_,_=documents.check_draft(self.root,new)
        self.assertNotEqual(new,path);self.assertEqual(path.read_bytes(),before);self.assertEqual(path.with_suffix('.approval.json').read_bytes(),approval)
        for field in ['summary','resume_bullets','cover_letter','selected_fact_ids','letter_date']:self.assertEqual(draft[field],edited[field])
        self.assertFalse(new.with_suffix('.approval.json').exists());self.assertTrue(result['review_required'])
        self.assertTrue(result['changes']['profile_changed']);self.assertIn('src_profile',result['changes']['sources_changed'])
        with self.assertRaisesRegex(career.ValidationError,'approve this exact'):documents.render(self.root,new,final=True)

    def test_refresh_upgrades_legacy_and_rejects_ineligible_or_changed_numeric_evidence(self):
        path=self.draft();original=json.loads(path.read_text());legacy=copy.deepcopy(original);legacy['format_version']=1;legacy.pop('letter_date');path.write_text(json.dumps(legacy))
        result=documents.refresh_draft(self.root,path);updated=json.loads(Path(result['path']).read_text())
        self.assertEqual(updated['format_version'],documents.FORMAT_VERSION);self.assertIn('letter_date',updated)
        self.assertTrue(result['changes']['legacy_format_upgraded']);self.assertTrue(result['changes']['letter_date_added'])
        pack=self.read();fact=next(f for f in pack['facts'] if f['id']==original['selected_fact_ids'][0]);fact['application_eligible']=False;self.write(pack);career.build(self.root)
        with self.assertRaisesRegex(career.ValidationError,'eligible'):documents.refresh_draft(self.root,path)
        fact['application_eligible']=True;fact['claim']='Managed 14 coordinators.';self.write(pack);career.build(self.root)
        # An edited claim's numeric support must still be checked; refresh cannot grandfather unsupported metrics.
        legacy['resume_bullets'][0]['text']='Managed 12 coordinators';path.write_text(json.dumps(legacy))
        with self.assertRaisesRegex(career.ValidationError,'numeric'):documents.refresh_draft(self.root,path)

    def test_future_plan_numbers_are_allowed_only_as_explicit_future_paragraph(self):
        path=self.draft();draft=json.loads(path.read_text());draft['cover_letter'].append({'kind':'future_plan','text':'In my first 90 days I would map the delivery workflow.','fact_ids':[]});path.write_text(json.dumps(draft));documents.check_draft(self.root,path)
        draft['cover_letter'][-1]['kind']='supported_claim';draft['cover_letter'][-1]['fact_ids']=[draft['selected_fact_ids'][0]];path.write_text(json.dumps(draft))
        with self.assertRaisesRegex(career.ValidationError,'numeric'):documents.check_draft(self.root,path)

    def test_bundle_interruption_is_retryable_and_foreign_or_changed_cache_is_preserved(self):
        original=career.atomic_text;calls=[]
        def fail_second(path,text):
            calls.append(path)
            if len(calls)==2:raise OSError('injected bundle interruption')
            original(path,text)
        with mock.patch.object(career,'atomic_text',side_effect=fail_second):
            with self.assertRaises(OSError):documents.bundle(self.root,'example-job')
        evidence=self.root/'applications'/documents.package_key('example-job')/'evidence'
        self.assertEqual(list(evidence.iterdir()),[])
        _,directory=documents.bundle(self.root,'example-job');prompt=directory/'resume-prompt.txt';prompt.write_text('foreign content')
        with self.assertRaisesRegex(career.ValidationError,'changed or incomplete'):documents.bundle(self.root,'example-job')
        self.assertEqual(prompt.read_text(),'foreign content');(directory/'manifest.json').unlink()
        with self.assertRaisesRegex(career.ValidationError,'changed or incomplete'):documents.bundle(self.root,'example-job')
        self.assertEqual(prompt.read_text(),'foreign content')

    def test_history_version_and_table_contract_are_checked_without_mutation(self):
        documents.render(self.root,self.draft());path=self.root/'state/application_history.sqlite'
        with sqlite3.connect(path) as db:db.execute('PRAGMA user_version=99');db.commit()
        before=path.read_bytes()
        with self.assertRaisesRegex(career.ValidationError,'schema version'):documents.history(self.root)
        self.assertEqual(before,path.read_bytes())
        with sqlite3.connect(path) as db:db.execute('PRAGMA user_version=1');db.execute('ALTER TABLE versions ADD COLUMN unknown TEXT');db.commit()
        before=path.read_bytes()
        with self.assertRaisesRegex(career.ValidationError,'table contract'):documents.history(self.root)
        self.assertEqual(before,path.read_bytes())

    def test_manual_ready_does_not_bypass_review_but_external_status_is_recorded(self):
        path=self.draft();result=documents.render(self.root,path)
        with self.assertRaisesRegex(career.ValidationError,'render --final'):documents.history(self.root,'ready',result['version'])
        self.assertEqual(documents.history(self.root)[0]['status'],'draft')
        documents.history(self.root,'applied',result['version'])
        self.assertEqual(documents.history(self.root)[0]['status'],'applied')
        self.assertTrue(json.loads((Path(result['directory'])/'manifest.json').read_text())['review_required'])


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
