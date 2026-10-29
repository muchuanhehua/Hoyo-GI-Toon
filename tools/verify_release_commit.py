"""Compare a frozen candidate or published release with committed payload bytes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tomllib
import zipfile

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--ref',default='HEAD')
parser.add_argument('--candidate',type=Path)
args=parser.parse_args()


def committed(path):
    return subprocess.run(['git','show',f'{args.ref}:{path}'],cwd=ROOT,check=True,capture_output=True).stdout


if args.candidate:
    package=args.candidate.read_bytes()
    manifest=tomllib.loads(committed('blender_manifest.toml').decode('utf-8'))
    version=manifest['version']
    record=None
else:
    index=json.loads(committed('release/index.json'))['data'][0]
    version=index['version']
    record=json.loads(committed(f"release/build-v{version}.json"))
    package=committed('release/'+record['archive'])
    assert hashlib.sha256(package).hexdigest()==record['sha256']
import io
with zipfile.ZipFile(io.BytesIO(package)) as archive:
    if record:
        assert set(archive.namelist())==set(record['payload'])
    else:
        from build_release import PAYLOAD
        assert set(archive.namelist())==PAYLOAD
        assert archive.read('blender_manifest.toml')==committed('blender_manifest.toml')
    assert archive.testzip() is None
    for name in archive.namelist():
        data=archive.read(name)
        if record:
            assert hashlib.sha256(data).hexdigest()==record['payload'][name],name
        assert committed(name)==data, 'Committed source differs from archive: '+name
    count=len(archive.namelist())
print('HGT_COMMITTED_PAYLOAD',args.ref,version,count,hashlib.sha256(package).hexdigest())
