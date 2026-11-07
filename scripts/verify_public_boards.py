#!/usr/bin/env python3
"""Read-only P2-A verification; no state writes, webhooks, credentials or POSTs.

Example (output must not already exist):
python scripts/verify_public_boards.py --allow-network --output /tmp/p2a-smoke.json

Writes metadata-only receipts, not copyrighted job-description datasets. A
successful read is not evidence that any posting suits the candidate or that
an application/Discord notification was sent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml

from src.adapters import ADAPTER_REGISTRY
from src.adapters.public_board import validate_public_board_config
from src.eligibility import classify_eligibility
from src.http import HTTPClient
from src.notifier import build_job_embed


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def source_sha() -> str:
    try:
        return subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return os.getenv('GITHUB_SHA', 'unknown')


def verify(manifest: Path) -> tuple[dict, int]:
    """Only invoke the new public adapters; intentionally never call main.do_run."""
    targets = yaml.safe_load(manifest.read_text()).get('companies')
    if not isinstance(targets,list) or not 1 <= len(targets) <= 2:
        raise ValueError('read-only smoke manifest must contain 1–2 explicit targets')
    before = {p: digest(ROOT/p) for p in ('companies.yaml','state/seen_jobs.json')}
    receipts = []
    result = {'kind':'P2-A_READ_ONLY_RECEIPT','source_sha':source_sha(),
              'started_at':datetime.now(timezone.utc).isoformat(),
              'manifest_sha256':digest(manifest), 'network_methods':['GET'],
              'state_and_config_before':before, 'boards':receipts,
              'discord_sent':False, 'production_enabled':False}
    exit_code = 0
    try:
        for target in targets:
            if not isinstance(target,dict) or target.get('adapter') not in ('greenhouse','ashby'):
                raise ValueError('only Greenhouse/Ashby public sources are accepted')
            if target.get('enabled') is not False or target.get('network_priority') is not False:
                raise ValueError('smoke entries must be disabled and explicitly non-network-priority')
            platform = target['adapter']
            cfg = validate_public_board_config(platform, target.get('config',{}))
            receipt = {'platform':platform,'board':cfg.slug,'board_url':cfg.board_url,
                       'employer_careers_url':cfg.employer_careers_url}
            receipts.append(receipt)
            client = HTTPClient('jobbie-p2a-readonly-verification/1', timeout=15, max_retries=1)
            try:
                jobs = list(ADAPTER_REGISTRY[platform](target['name'],target['config'],client).fetch())
                verdicts = Counter(classify_eligibility(j).status for j in jobs)
                # Rendering an embed is local; never instantiate or call Notifier.
                sample = jobs[0] if jobs else None
                if sample:
                    embed = build_job_embed(sample)
                    assert embed['title'].startswith('DISCOVERED')
                    assert not sample.network_priority
                receipt.update(status='observed_nonempty' if jobs else 'observed_empty',
                               count=len(jobs), eligibility_counts=dict(verdicts),
                               missing_description=sum(j.description_complete is False for j in jobs),
                               missing_posted_at=sum(j.posted_at is None for j in jobs),
                               samples=[{'source_job_id':j.source_job_id,'job_url':j.url,
                                         'date_kind':j.posted_at_kind} for j in jobs[:3]])
            except Exception as exc:
                exit_code = 1
                receipt.update(status='failed',error_type=type(exc).__name__)
                logging.error('%s read-only validation failed (%s)', platform,type(exc).__name__)
            finally:
                client.session.close()
    finally:
        after = {p:digest(ROOT/p) for p in before}
        result['state_and_config_after'] = after
        result['state_and_config_unchanged'] = before == after
        result['finished_at'] = datetime.now(timezone.utc).isoformat()
        if before != after:
            exit_code = 1
            result['error'] = 'PRODUCTION_STATE_OR_CONFIG_MUTATED'
    result['result'] = 'passed' if not exit_code else 'failed'
    return result,exit_code


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-network',action='store_true',help='explicitly permit public read-only GETs')
    parser.add_argument('--manifest',type=Path,default=ROOT/'examples/p2a-public-boards.yaml')
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args(argv)
    if not args.allow_network:
        parser.error('--allow-network is required; no implicit network probe')
    output=args.output.resolve()
    if output.exists() or output.is_relative_to((ROOT/'state').resolve()):
        parser.error('output must be a new non-state file; existing files cannot be overwritten')
    # Never import .env or consume/send a webhook configured in the environment.
    result,code=verify(args.manifest)
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x') as f:
        json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps({'result':result['result'],'counts':[
        {'platform':b['platform'],'status':b['status'],'count':b.get('count')}
        for b in result['boards']], 'state_and_config_unchanged':result['state_and_config_unchanged']}))
    return code


if __name__=='__main__':
    raise SystemExit(main())
