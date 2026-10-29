"""Collect current candidate evidence without promoting or installing a release."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from build_release import validate_archive,validate_evidence,validate_pmx,validate_subjects

parser=argparse.ArgumentParser()
parser.add_argument('--prefix',required=True)
parser.add_argument('--output-dir',type=Path,required=True)
args=parser.parse_args()
project=Path(__file__).resolve().parents[1];out=args.output_dir.resolve()
assert out.is_relative_to(project/'.verification');out.mkdir(parents=True,exist_ok=True)
record=json.loads((project/'.build/candidate/candidate.json').read_text(encoding='utf-8'))
archive=project/'.build/candidate'/record['archive']
assert hashlib.sha256(archive.read_bytes()).hexdigest()==record['sha256']
assert validate_archive(archive)==record['payload']
names={'fbx':'verification.json','pmx':'pmx-verification.json','integration':'integration.json',
       'interface':'interface.json','pmx-interface':'interface.json','formats':'formats.json',
       'subjects':'subjects.json','baseline':'baseline.json'}
paths={key:project/'.verification/development'/f'{args.prefix}-{key}'/file for key,file in names.items()}
parts={key:json.loads(path.read_text(encoding='utf-8')) for key,path in paths.items()}
assert all(p.get('package_sha256')==record['sha256'] for p in parts.values())
for key in ('interface','pmx-interface'):
    assert not parts[key].get('error'),parts[key].get('error')
    expected=('toggle_undo_redo','group_undo_redo','empty_selection_rollback','dialog_cancel')
    assert all(parts[key]['subject_checks'].get(k) is True for k in expected)
    assert all(parts[key]['integration_checks'].values())
evidence=parts['fbx'];evidence.update(scope='01–21',version=record['version'])
evidence['integration_checks']={**parts['integration']['integration_checks'],**parts['interface']['integration_checks']}
hashes=validate_evidence(evidence,integration=True)
assert parts['integration']['source_sha256']==evidence['source_sha256']
assert parts['integration']['resource_sha256']==evidence['resource_sha256']
validate_pmx(parts['pmx'],hashes,integration=True)
validate_subjects(parts['subjects'],hashes,integration=True)
assert all(parts['formats']['checks'].values())
assert parts['baseline']['source_sha256']==evidence['source_sha256']
assert all(parts['baseline']['checks'].values())
assert {m['source_format'] for m in parts['baseline']['comparisons'] if m['unchanged_shading']}=={'fbx','pmx'}
assert all(evidence['resolver_checks'].values())
assert evidence['animation_fixture']['source_actions_preserved']
for key in ('pmx','subjects','baseline'):evidence[key]=parts[key]
evidence['formats']=parts['formats']['checks']
evidence['subject_interface']={key:parts[key]['subject_checks'] for key in ('interface','pmx-interface')}
evidence['evidence_files']={key:str(path.relative_to(project)) for key,path in paths.items()}
evidence['archive']={key:record[key] for key in ('archive','bytes','sha256')}
evidence['acceptance']='待用户操作与外观验收；未发布或更新用户安装'
evidence['published_version']=json.loads((project/'release/index.json').read_text(encoding='utf-8'))['data'][0]['version']
assert evidence['published_version']!=record['version']
file=out/'verification.json';file.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
checkpoint={'git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=project,text=True).strip(),
            'package_sha256':record['sha256'],'payload_sha256':record['payload'],
            'verification_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),
            'working_tree':subprocess.check_output(['git','status','--short'],cwd=project,text=True,encoding='utf-8')}
(out/'checkpoint.json').write_text(json.dumps(checkpoint,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('HGT_CANDIDATE_ACCEPTANCE_READY',record['version'],record['sha256'],len(record['payload']))
