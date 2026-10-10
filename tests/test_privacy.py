from pathlib import Path
import importlib.util
import tempfile
import unittest
import subprocess
import contextlib
import io
import json
from unittest import mock

PROJECT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('privacy',PROJECT/'scripts/check_privacy.py')
privacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(privacy)


class PrivacyTests(unittest.TestCase):
    def test_workspace_artifacts_are_rejected_and_fictional_examples_allowed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with mock.patch.object(privacy,'ROOT',root):
                path=root/'profile.json';path.write_text('{}')
                self.assertIsNotNone(privacy.inspect(path))
                example=root/'examples/profile.json';example.parent.mkdir();example.write_text('{"email":"jordan@example.invalid"}')
                self.assertIsNone(privacy.inspect(example))
    def test_credentials_and_nonexample_contact_are_reported_without_values(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'sample.txt'
            with mock.patch.object(privacy,'ROOT',root):
                path.write_text('ghp_'+'x'*30);message=privacy.inspect(path)
                self.assertEqual(message,'credential-shaped content');self.assertNotIn('x'*30,message)
                path.write_text('person'+'@'+'actual-mail.test')
                self.assertEqual(privacy.inspect(path),'non-example email address')
    def test_specific_home_path_is_rejected_but_generic_workspace_docs_allowed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'guide.txt'
            with mock.patch.object(privacy,'ROOT',root):
                path.write_text('/'+'Users'+'/someone/private');self.assertIsNotNone(privacy.inspect(path))
                path.write_text('Use ~/my-career outside the code checkout.');self.assertIsNone(privacy.inspect(path))

    def test_staged_credentials_are_rejected_after_working_copy_is_cleaned(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'guide.txt'
            subprocess.run(['git','init','--quiet'],cwd=root,check=True)
            path.write_text('ghp_'+'x'*30)
            subprocess.run(['git','add','guide.txt'],cwd=root,check=True)
            for working_copy in ['clean','deleted']:
                with self.subTest(working_copy=working_copy):
                    if working_copy=='clean':path.write_text('Clean working copy.')
                    else:path.unlink()
                    output=io.StringIO()
                    with mock.patch.object(privacy,'ROOT',root),contextlib.redirect_stderr(output),contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(privacy.main(),1)
                    self.assertIn('staged',output.getvalue())
                    self.assertNotIn('x'*30,output.getvalue())

    def test_symlinks_are_rejected_without_reading_the_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'link.txt';path.symlink_to(root/'missing-private-file')
            with mock.patch.object(privacy,'ROOT',root):
                self.assertEqual(privacy.inspect(path),'symbolic link is included')
                target=root/'target';target.mkdir();(target/'guide.txt').write_text('')
                (root/'linked-folder').symlink_to(target,target_is_directory=True)
                self.assertEqual(privacy.inspect(root/'linked-folder/guide.txt'),'symbolic link is included')

    def test_private_artifact_variants_and_fine_grained_tokens_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with mock.patch.object(privacy,'ROOT',root):
                for name in ['Examples/raw/source.txt','Data/source.json','backup.sqlite-wal','resume.rtf']:
                    with self.subTest(name=name):
                        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('')
                        self.assertIsNotNone(privacy.inspect(path))
                path=root/'guide.txt';path.write_text('github_pat_'+'x'*40)
                self.assertEqual(privacy.inspect(path),'credential-shaped content')

    def test_linux_home_paths_and_additional_credentials_are_rejected(self):
        cases={
            'linux_home':'/'+'home'+'/someone/private',
            'aws_long_lived':'AK'+'IA'+'A'*16,
            'aws_temporary':'AS'+'IA'+'A'*16,
            'google_api':'AI'+'za'+'x'*35,
            'slack_bot':'xox'+'b-'+'x'*24,
            'stripe_secret':'sk_'+'live_'+'x'*24,
            'stripe_restricted':'rk_'+'live_'+'x'*24,
            'pgp_private':'-----BEGIN '+'PGP PRIVATE KEY BLOCK-----',
        }
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'guide.txt'
            with mock.patch.object(privacy,'ROOT',root):
                for label,value in cases.items():
                    with self.subTest(kind=label):
                        path.write_text(value)
                        self.assertIsNotNone(privacy.inspect(path))

    def test_json_career_artifacts_are_rejected_in_working_and_staged_bytes(self):
        samples={
            'career_pack':{'facts':[{'claim':'Managed a private project.'}]},
            'draft':{'resume_bullets':[{'fact_id':'f','text':'Private career prose.'}],'cover_letter':[]},
            'bundle':{'profile':{'name':'Synthetic Candidate'},'snapshot':{},'selected_fact_ids':['f']},
            'approval':{'draft_sha256':'a'*64,'reviewed_at':'2026-01-01'},
        }
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'arbitrary.json'
            subprocess.run(['git','init','--quiet'],cwd=root,check=True)
            with mock.patch.object(privacy,'ROOT',root):
                for label,value in samples.items():
                    with self.subTest(kind=label,location='working'):
                        path.write_text(json.dumps(value))
                        self.assertEqual(privacy.inspect(path),'potential private career JSON artifact')
                    subprocess.run(['git','add','arbitrary.json'],cwd=root,check=True)
                    path.write_text('{"timeout":5}')
                    with self.subTest(kind=label,location='staged'):
                        self.assertTrue(privacy.staged_problems())
                example=root/'examples/career.json';example.parent.mkdir();example.write_text(json.dumps(samples['career_pack']))
                self.assertIsNone(privacy.inspect(example))
                renamed=root/'examples/other.json';renamed.write_text(example.read_text())
                self.assertIsNotNone(privacy.inspect(renamed))
                self.assertIsNone(privacy.inspect(path))

    def test_generated_format_and_draft_filename_variants_are_rejected(self):
        names=['resume.odt','resume.pages','photo.heic','photo.webp','archive.rar','backup.bz2',
               'reviewed-draft.approval.json','reviewed-draft.json','draft.json','draft-copy.json','resume.draft.json']
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with mock.patch.object(privacy,'ROOT',root):
                for name in names:
                    with self.subTest(name=name):
                        path=root/name;path.write_text('')
                        self.assertIsNotNone(privacy.inspect(path))


if __name__=='__main__':unittest.main()
