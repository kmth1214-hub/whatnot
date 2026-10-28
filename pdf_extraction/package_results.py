#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

from jsonschema import Draft202012Validator

from extract_catalogs import ROOT, OUT, save_json


def main():
    schema=json.loads((OUT/'document.schema.json').read_text(encoding='utf-8'))
    validator=Draft202012Validator(schema)
    validator.check_schema(schema)
    for doc_id in ['pt1_part1','pt1_part2','pt2_part1','pt2_part2']:
        data=json.loads((OUT/(doc_id+'.json')).read_text(encoding='utf-8'))
        validator.validate(data)
        print('SCHEMA_VALID',doc_id,len(data['pages']),flush=True)
    jsonl_count=0
    with (OUT/'reference_pages.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            data=json.loads(line);assert data['schema_version']=='1.1.0';jsonl_count+=1
    assert jsonl_count==464
    excerpts=OUT/'source_excerpts';excerpts.mkdir(exist_ok=True)
    for p in (ROOT/'validation_images').glob('*.png'):shutil.copy2(p,excerpts/p.name)
    scripts=OUT/'scripts';scripts.mkdir(exist_ok=True)
    for name in ['extract_catalogs.py','enrich_reference.py','finalize_deliverables.py','package_results.py']:
        shutil.copy2(ROOT/name,scripts/name)
    versions={'tesseract_version':subprocess.check_output(['tesseract','--version'],text=True).splitlines()[0],
              'kor_model_source':'https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/kor.traineddata',
              'kor_model_sha256':hashlib.sha256((ROOT/'tools/tessdata/kor.traineddata').read_bytes()).hexdigest(),
              'eng_model_source':'preinstalled /usr/share/tesseract-ocr/5/tessdata/eng.traineddata',
              'eng_model_sha256':hashlib.sha256((ROOT/'tools/tessdata/eng.traineddata').read_bytes()).hexdigest(),
              'source_pdfs_modified':False,'email_sent':False}
    save_json(OUT/'tool_provenance.json',versions)
    report=json.loads((OUT/'quality_report.json').read_text(encoding='utf-8'))
    report['checks']['json_schema_validation']=True
    report['checks']['jsonl_464_page_records']=True
    save_json(OUT/'quality_report.json',report)
    artifacts=[p for p in OUT.iterdir() if p.is_file() and p.suffix in ['.json','.jsonl','.md','.txt']]
    artifacts+=list(excerpts.glob('*.png'))+list(scripts.glob('*.py'))
    checksums={str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}
    save_json(OUT/'checksums.json',checksums);artifacts.append(OUT/'checksums.json')
    bundle=ROOT/'hyundai_steel_ocr_json.zip'
    with zipfile.ZipFile(bundle,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(artifacts):z.write(p,arcname=p.relative_to(OUT))
    with zipfile.ZipFile(bundle) as z:
        assert z.testzip() is None
        assert all(name+'.json' in z.namelist() for name in ['pt1_part1','pt1_part2','pt2_part1','pt2_part2'])
    print('ZIP_VALID',str(bundle),'bytes',bundle.stat().st_size,'entries',len(artifacts),flush=True)
    print('ZIP_SHA256',hashlib.sha256(bundle.read_bytes()).hexdigest(),flush=True)


if __name__=='__main__':main()
