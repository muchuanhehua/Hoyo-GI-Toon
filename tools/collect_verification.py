"""Collect exact installed PMX candidate evidence without publishing it."""
import argparse,json,hashlib,subprocess
from pathlib import Path
from build_release import validate_archive,validate_evidence
parser=argparse.ArgumentParser()
parser.add_argument('--verification',type=Path,required=True)
parser.add_argument('--interface-verification',type=Path,required=True)
parser.add_argument('--output-dir',type=Path,required=True)
args=parser.parse_args()
root=Path(__file__).resolve().parents[1];out=args.output_dir.resolve()
assert out.is_relative_to(root/'.verification');out.mkdir(parents=True,exist_ok=True)
evidence=json.loads(args.verification.read_text(encoding='utf-8'))
interface=json.loads(args.interface_verification.read_text(encoding='utf-8'))
validate_evidence(evidence,interface,integration=True)
record=json.loads((root/'.build/candidate/candidate.json').read_text(encoding='utf-8'))
archive=root/'.build/candidate'/record['archive']
assert hashlib.sha256(archive.read_bytes()).hexdigest()==record['sha256']==evidence['package_sha256']
assert validate_archive(archive)==record['payload']
report={'scope':evidence['scope'],'version':record['version'],'candidate':{k:record[k] for k in ('archive','bytes','sha256')},
        'payload_files':len(record['payload']),'models':evidence['models'],'checks':evidence['checks'],
        'interface_checks':interface['checks'],'native_cancel_input':interface['native_cancel_input'],
        'acceptance':'pending_user_review','published_version':json.loads((root/'release/index.json').read_text(encoding='utf-8'))['data'][0]['version']}
path=out/'verification.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
checkpoint={'git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
            'working_tree':subprocess.check_output(['git','status','--short'],cwd=root,text=True,encoding='utf-8'),
            'package_sha256':record['sha256'],'payload_sha256':record['payload'],
            'verification_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
(out/'checkpoint.json').write_text(json.dumps(checkpoint,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print('HGT_PMX_CANDIDATE_READY',record['version'],record['sha256'])
