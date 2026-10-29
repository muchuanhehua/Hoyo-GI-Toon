"""Collect matching installed-package checks without promoting a release."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from build_release import validate_archive, validate_evidence, validate_pmx

parser=argparse.ArgumentParser()
parser.add_argument('--prefix',required=True)
parser.add_argument('--output-dir',type=Path,required=True)
args=parser.parse_args()
project=Path(__file__).resolve().parents[1]
out=args.output_dir.resolve()
assert out.is_relative_to(project/'.verification')
out.mkdir(parents=True,exist_ok=True)
record=json.loads((project/'.build/candidate/candidate.json').read_text(encoding='utf-8'))
archive=project/'.build/candidate'/record['archive']
assert hashlib.sha256(archive.read_bytes()).hexdigest()==record['sha256']
assert validate_archive(archive)==record['payload']
paths={key:project/'.verification/development'/f'{args.prefix}-{key}'/filename for key,filename in
       [('fbx','verification.json'),('pmx','pmx-verification.json'),('integration','integration.json'),
        ('interface','interface.json'),('formats','formats.json')]}
parts={key:json.loads(path.read_text(encoding='utf-8')) for key,path in paths.items()}
assert all(item.get('package_sha256')==record['sha256'] for item in parts.values())
assert 'error' not in parts['interface']
evidence=parts['fbx']
evidence.update(scope='01–15',version=record['version'])
evidence['integration_checks']={**parts['integration']['integration_checks'],**parts['interface']['integration_checks']}
hashes=validate_evidence(evidence,integration=True)
validate_pmx(parts['pmx'],hashes,integration=True)
assert all(parts['formats']['checks'].values())
evidence['pmx']=parts['pmx']
evidence['formats']=parts['formats']['checks']
evidence['evidence_files']={key:str(path.relative_to(project)) for key,path in paths.items()}
evidence['archive']={key:record[key] for key in ('archive','bytes','sha256')}
evidence['acceptance']='待用户外观与操作验收；未发布或更新用户安装'
release=json.loads((project/'release/index.json').read_text(encoding='utf-8'))
assert release['data'][0]['version']=='0.2.2'
evidence['published_version']='0.2.2'
(out/'verification.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
checkpoint={'git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=project,text=True).strip(),
            'package_sha256':record['sha256'],'payload_sha256':record['payload'],
            'verification_sha256':hashlib.sha256((out/'verification.json').read_bytes()).hexdigest(),
            'working_tree':subprocess.check_output(['git','status','--short'],cwd=project,text=True,encoding='utf-8')}
(out/'checkpoint.json').write_text(json.dumps(checkpoint,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('HGT_PMX_ACCEPTANCE_READY',record['version'],len(evidence['models']),len(parts['pmx']['models']),record['sha256'])
