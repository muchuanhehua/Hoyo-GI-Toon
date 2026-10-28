"""Join current installed-package evidence into the candidate acceptance record."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

parser=argparse.ArgumentParser()
parser.add_argument('--modules',type=Path,required=True)
parser.add_argument('--integration',type=Path,required=True)
parser.add_argument('--interface',type=Path,required=True)
parser.add_argument('--candidate',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
modules,integration,interface=[json.loads(path.read_text(encoding='utf-8')) for path in (args.modules,args.integration,args.interface)]
archive_hash=hashlib.sha256(args.candidate.read_bytes()).hexdigest()
for record in (modules,integration,interface):
    assert record.get('package_sha256')==archive_hash,'Evidence did not execute this candidate package'
assert not interface.get('error'),interface.get('error')
for key in ('source_sha256','resource_sha256'):
    assert modules[key]==integration[key],'Module and integration sources differ'
with zipfile.ZipFile(args.candidate) as package:
    assert package.testzip() is None
    for key in ('source_sha256','resource_sha256'):
        for name,digest in modules[key].items():
            assert hashlib.sha256(package.read(name)).hexdigest()==digest,name
    payload_count=len(package.namelist())
checks={**integration['integration_checks'],**interface['integration_checks']}
assert checks and all(checks.values()),checks
assert len(modules['models'])==4 and all(modules['lifecycle'].values())
assert all(modules['resolver_checks'].values())
assert modules['animation_fixture']['source_actions_preserved']
record={**modules,'scope':'01–08','integration_checks':checks,'package_sha256':archive_hash,
        'archive':args.candidate.name,'payload_files':payload_count,'crc_verified':True,
        'framing':integration['framing'],'post_rgb_response_max':integration['post_rgb_response_max'],
        'ui_screenshots':interface['screenshots'],'ui_render_seconds':interface['render_seconds'],
        'user_acceptance':'pending'}
args.output.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('HGT_ACCEPTANCE_RECORD',archive_hash,payload_count)
