"""Create a new local presentation candidate, preserving the reviewed baseline."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.tnved_presentation import build

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for name in ('base', 'sources', 'spacing', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--base-sha256', required=True)
    p.add_argument('--manifest-sha256', required=True)
    p.add_argument('--pdftotext', required=True)
    a = p.parse_args()
    print(json.dumps(build(a.base, a.base_sha256, a.sources, a.manifest_sha256, a.spacing, a.output, a.pdftotext), ensure_ascii=False))
