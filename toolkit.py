#!/usr/bin/env python3
"""Prepare a private evidence store and matching resumes and cover letters."""
from __future__ import annotations
import argparse
import datetime as dt
from pathlib import Path
import json
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import career
import documents

PROJECT=Path(__file__).resolve().parent


def require_fts5():
    try:
        with sqlite3.connect(':memory:') as check:
            check.execute('CREATE VIRTUAL TABLE toolkit_capability USING fts5(text)')
    except sqlite3.Error as exc:
        raise career.ValidationError('SQLite FTS5 is required. Use a Python 3.10 or newer installation with FTS5 support, then retry init. No workspace files were created.') from exc


def init(root,example=False):
    root=root.resolve()
    if root.is_relative_to(PROJECT.resolve()) or (root/'.git').exists():
        raise career.ValidationError('Choose a private workspace outside the code checkout')
    if root.exists() and any(root.iterdir()):
        raise career.ValidationError('Initialization requires an empty directory; existing files are preserved')
    require_fts5()
    root.mkdir(parents=True,exist_ok=True)
    (root/'data').mkdir()
    for name in ['inputs','state','applications','exports']:(root/name).mkdir()
    if example:
        shutil.copy2(PROJECT/'examples/career.json',root/'data/base.json')
        shutil.copy2(PROJECT/'examples/profile.json',root/'profile.json')
    else:
        career.atomic_text(root/'data/base.json',career.pretty({e:[] for e in career.ENTITIES}))
        career.atomic_text(root/'profile.json',career.pretty({'name':'Your Name','email':'','phone':'','location':'','links':{},'font':'Georgia','motivation':''}))
    career.atomic_text(root/'.gitignore','data/\nprofile.json\ninputs/\nbuild/\nstate/\napplications/\nexports/\n.env*\n')
    career.atomic_text(root/'README-PRIVATE.txt','This workspace contains your personal information. Keep it private. The toolkit never submits applications or calls an AI provider. Review selected evidence before sharing a prompt with your chosen assistant.\n')
    try:
        built=career.build(root)
    except (career.ValidationError,OSError,sqlite3.Error,ValueError) as exc:
        command='python3 toolkit.py --workspace '+shlex.quote(str(root))+' build'
        raise career.ValidationError('Workspace source files were created and preserved, but the database build failed: '+str(exc)+'. Resolve the cause, then run '+command+'. Do not delete your source files or repeat init.') from exc
    return {'workspace':str(root),'example':example,'counts':built['counts'],'next':'Edit profile.json and add sourced facts, or run the fictional demo job.'}


def capture_job(root,job_id,company,title,url,description):
    career.ensure_string(job_id,'job ID')
    career.ensure_string(company,'company')
    career.ensure_string(title,'title')
    from urllib.parse import urlsplit
    parsed=urlsplit(url)
    if parsed.scheme not in {'http','https'} or not parsed.netloc:
        raise career.ValidationError('Job URL requires http or https')
    text=description.read_text(encoding='utf-8')
    career.ensure_string(text,'job description')
    date=dt.date.today().isoformat()
    key=documents.package_key(job_id)
    source='posting_'+key;org='target_'+key
    pack={'sources':[{'id':source,'title':title+' job description','kind':'job_posting','source_date':None,'retrieved_at':date,'uri':url,'notes':'Saved description supplied by the user; not fetched or independently verified by the toolkit.'}],
          'organizations':[{'id':org,'name':company,'kind':'target_employer','source_ids':[source]}],
          'jobs':[{'id':job_id,'organization_id':org,'title':title,'url':url,'captured_at':date,'source_id':source,'status':'captured','description':text,'notes':''}]}
    with tempfile.TemporaryDirectory(prefix='toolkit-job-') as temp:
        file=Path(temp)/'posting.json';file.write_text(career.pretty(pack),encoding='utf-8')
        result=career.add_pack(root,file,key)
    result['next']='Run build, then choose relevant evidence with bundle or draft --fact FACT_ID. Curated requirements/matches can be added as normal evidence packs.'
    return result


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',type=Path,help='Your private workspace; required except for init')
    sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('init',help='Create a separate private workspace')
    q.add_argument('directory',type=Path);q.add_argument('--example',action='store_true')
    for command in ['build','validate','stats','search','show','match','export','validate-exports','add','capture-job','bundle','draft','refresh-draft','check-draft','approve','render','history','status']:
        q=sub.add_parser(command)
        if command=='search':
            q.add_argument('query',nargs='+');q.add_argument('--include-context',action='store_true');q.add_argument('--include-unconfirmed',action='store_true');q.add_argument('--limit',type=int,default=20)
        if command=='show':q.add_argument('fact_id')
        if command in ['match','bundle','draft']:q.add_argument('job_id')
        if command in ['bundle','draft']:q.add_argument('--fact',action='append',default=[],help='Extra eligible evidence ID, for breadth beyond direct requirements')
        if command in ['export','validate-exports']:q.add_argument('--output-dir',type=Path)
        if command=='add':q.add_argument('pack',type=Path);q.add_argument('--name')
        if command=='capture-job':
            q.add_argument('job_id');q.add_argument('--company',required=True);q.add_argument('--title',required=True);q.add_argument('--url',required=True);q.add_argument('--description',type=Path,required=True)
        if command in ['refresh-draft','check-draft','approve','render']:q.add_argument('draft',type=Path)
        if command=='render':
            q.add_argument('--format',action='append',choices=['html','docx','pdf']);q.add_argument('--final',action='store_true',help='Require an exact human-review receipt');q.add_argument('--soffice',type=Path)
        if command=='status':q.add_argument('version');q.add_argument('status',choices=['applied','interview','closed','declined'])
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    try:
        if args.command=='init':result=init(args.directory,args.example)
        else:
            if args.workspace is None:raise career.ValidationError('Pass --workspace PATH to your private workspace')
            root=args.workspace.resolve()
            if args.command=='build':result=career.build(root)
            elif args.command=='validate':
                data,origins,packs=career.load_data(root);documents.profile(root);result={'valid':True,'profile_valid':True,'counts':career.data_counts(data),'packs':packs,'data_sha256':career.data_digest(data),'provenance_sha256':career.provenance_digest(origins)}
            elif args.command=='add':result=career.add_pack(root,args.pack.resolve(),args.name)
            elif args.command=='capture-job':result=capture_job(root,args.job_id,args.company,args.title,args.url,args.description.resolve())
            elif args.command=='bundle':
                _,path=documents.bundle(root,args.job_id,args.fact);result={'bundle':str(path),'resume_prompt':str(path/'resume-prompt.txt'),'cover_letter_prompt':str(path/'cover-letter-prompt.txt')}
            elif args.command=='draft':result={'draft':str(documents.initial_draft(root,args.job_id,args.fact)),'next':'Edit the paired draft yourself or with your chosen assistant; check, preview, then approve only after human review.'}
            elif args.command=='refresh-draft':result=documents.refresh_draft(root,args.draft.resolve())
            elif args.command=='check-draft':
                draft,_,_=documents.check_draft(root,args.draft.resolve());result={'valid':True,'semantic_review_required':True,'letter_date':draft['letter_date']}
            elif args.command=='approve':result={'approval':str(documents.approve(root,args.draft.resolve()))}
            elif args.command=='render':result=documents.render(root,args.draft.resolve(),args.format or ['html'],args.final,args.soffice)
            elif args.command=='history':result=documents.history(root)
            elif args.command=='status':result=documents.history(root,args.status,args.version)
            else:
                with career.open_database(root) as db:
                    if args.command=='search':
                        if not 1<=args.limit<=1000:raise career.ValidationError('Search limit is 1–1000')
                        result=career.search(db,' '.join(args.query),args.include_context,args.include_unconfirmed,args.limit)
                    elif args.command=='export':result=career.export_data(root,db,args.output_dir)
                    elif args.command=='validate-exports':result=career.validate_exports(root,db,args.output_dir)
                    else:
                        data,origins=career.database_data(db)
                        if args.command=='stats':result={'counts':career.data_counts(data),'metadata':dict(db.execute('SELECT key,value FROM metadata'))}
                        elif args.command=='show':result=career.fact_details(data,origins,args.fact_id)
                        elif args.command=='match':result=career.match_job(data,args.job_id)
        print(career.pretty(result),end='');return 0
    except (career.ValidationError,OSError,sqlite3.Error,ValueError,UnicodeError,RecursionError,subprocess.SubprocessError) as exc:
        message=str(exc)
        if args.command!='init' and args.workspace is not None and ('run build' in message.lower() or 'database not found' in message.lower()):
            launcher='py -3' if sys.platform=='win32' else 'python3'
            message+=' Run: '+launcher+' toolkit.py --workspace '+shlex.quote(str(args.workspace.resolve()))+' build'
        print(career.pretty({'error':message}),file=sys.stderr,end='');return 2


if __name__=='__main__':raise SystemExit(main())
