"""Verify that a committed release contains exactly the installed payload bytes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--ref',default='HEAD')
args=parser.parse_args()


def committed(path):
    return subprocess.run(['git','show',f'{args.ref}:{path}'],cwd=ROOT,check=True,capture_output=True).stdout


index=json.loads(committed('release/index.json'))['data'][0]
record=json.loads(committed(f"release/build-v{index['version']}.json"))
package=committed('release/'+record['archive'])
assert hashlib.sha256(package).hexdigest()==record['sha256']
import io
with zipfile.ZipFile(io.BytesIO(package)) as archive:
    assert set(archive.namelist())==set(record['payload'])
    assert archive.testzip() is None
    for name,expected in record['payload'].items():
        data=archive.read(name)
        assert hashlib.sha256(data).hexdigest()==expected,name
        assert committed(name)==data, 'Committed source differs from archive: '+name
print('HGT_COMMITTED_RELEASE',args.ref,index['version'],len(record['payload']),record['sha256'])
