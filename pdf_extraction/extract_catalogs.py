#!/usr/bin/env python3
"""Resumable, local OCR reference extraction; no source PDF is modified."""
import argparse
import collections
import concurrent.futures
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time

import fitz
from PIL import Image

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'results'
TESSDATA = ROOT / 'tools' / 'tessdata'
DPI = 350


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    tmp.replace(path)


def bbox_union(rects):
    return [round(min(r[0] for r in rects), 3), round(min(r[1] for r in rects), 3),
            round(max(r[2] for r in rects), 3), round(max(r[3] for r in rects), 3)]


def group_cells(cells):
    """Connected cell groups, including color matrices without native PDF text."""
    parents = list(range(len(cells)))
    def find(a):
        while parents[a] != a:
            parents[a] = parents[parents[a]]
            a = parents[a]
        return a
    corners = {}
    for i, (x0, y0, x1, y1) in enumerate(cells):
        for c in [(x0,y0),(x0,y1),(x1,y0),(x1,y1)]:
            k = tuple(round(v, 3) for v in c)
            if k in corners:
                parents[find(i)] = find(corners[k])
            else:
                corners[k] = i
    groups = collections.defaultdict(list)
    for i, cell in enumerate(cells):
        groups[find(i)].append(cell)
    return sorted([v for v in groups.values() if len(v) >= 4], key=lambda g:(min(c[1] for c in g), min(c[0] for c in g)))


NUMBER = re.compile(r'^(?P<op><=|>=|≤|≥|<|>|~|≈)?\s*(?P<n>[+−-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?:\s*(?P<unit>mm|cm|m|MPa|GPa|kg/m|kg|%))?$')


def parse_number(word):
    text = word['text'].strip()
    m = NUMBER.fullmatch(text)
    if not m:
        return None
    value = m['n'].replace(',', '').replace('−', '-')
    return {'word_id':word['id'], 'original_text':text,
            'parsed_value':float(value) if '.' in value else int(value),
            'operator':m['op'], 'unit_explicit_in_token':m['unit'],
            'verified_value':None, 'bbox_pt':word['bbox_pt'],
            'ocr_confidence':word['confidence'], 'needs_review':True}


def extract_page(task):
    source, doc_id, page_index, combined_offset = task
    page_num = page_index + 1
    folder = OUT / doc_id
    page_path = folder / 'pages' / f'{page_num:04}.json'
    if page_path.exists():
        existing = json.loads(page_path.read_text(encoding='utf-8'))
        if existing.get('extraction',{}).get('dpi') == DPI and existing.get('status') == 'ocr_completed':
            return {'page':page_num,'cached':True, 'words':len(existing['words'])}
    started = time.monotonic()
    raw = folder / 'raw_ocr'
    raw.mkdir(parents=True, exist_ok=True)
    base = raw / f'{page_num:04}'
    image_path = raw / f'{page_num:04}.png'
    with fitz.open(source) as pdf:
        page = pdf[page_index]
        pix = page.get_pixmap(dpi=DPI, alpha=False)
        pix.save(image_path)
        image = Image.frombytes('RGB', [pix.width,pix.height],pix.samples)
        size = [round(page.rect.width,3),round(page.rect.height,3)]
        env = dict(os.environ, OMP_THREAD_LIMIT='1')
        cmd = ['tesseract',str(image_path),str(base),'--tessdata-dir',str(TESSDATA),
               '-l','kor+eng','--psm','3','--dpi',str(DPI),
               '-c','tessedit_create_tsv=1','-c','tessedit_create_txt=1']
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=180)
        if proc.returncode:
            raise RuntimeError(f'{doc_id} page {page_num}: {proc.stderr[-1000:]}')
        words=[]
        line_groups=collections.OrderedDict()
        with base.with_suffix('.tsv').open(encoding='utf-8') as stream:
            for r in csv.DictReader(stream, delimiter='\t', quoting=csv.QUOTE_NONE):
                if r['level'] != '5' or not (r.get('text') or '').strip():
                    continue
                x,y,w,h=[int(r[k]) for k in ['left','top','width','height']]
                conf=float(r['conf'])
                word={'id':f'w{len(words)+1:05}', 'text':r['text'], 'confidence':round(conf,2),
                      'bbox_pt':[round(v*72/DPI,3) for v in [x,y,x+w,y+h]],
                      'line_key':'.'.join(r[k] for k in ['block_num','par_num','line_num']),
                      'needs_review':conf<85}
                words.append(word)
                line_groups.setdefault(word['line_key'],[]).append(word)
        lines=[]
        for key, group in line_groups.items():
            lines.append({'id':f'l{len(lines)+1:04}', 'text':' '.join(w['text'] for w in group),
                          'bbox_pt':bbox_union([w['bbox_pt'] for w in group]),
                          'word_ids':[w['id'] for w in group],
                          'needs_review':any(w['needs_review'] for w in group)})
        candidates=[]
        for word in words:
            n=parse_number(word)
            if n is not None:
                n['id']=f'n{len(candidates)+1:05}'
                candidates.append(n)
        vector_error=None
        colored=[]
        tables=[]
        try:
            paths=page.get_drawings()
            for path in paths:
                fill=path.get('fill')
                if not fill or path['rect'].width<4 or path['rect'].height<4:
                    continue
                if max(fill)-min(fill)<0.015 and (min(fill)>.98 or max(fill)<.25):
                    continue
                # Only polygonal backgrounds, excluding outlined text curves.
                if not all(item[0] in ['l','re'] for item in path['items']):
                    continue
                items=[]
                for item in path['items']:
                    if item[0]=='l':items.append({'kind':'line','from':[round(v,3) for v in item[1]],'to':[round(v,3) for v in item[2]]})
                    elif item[0]=='re':items.append({'kind':'rectangle','bbox_pt':[round(v,3) for v in item[1]]})
                colored.append({'id':f'color{len(colored)+1:04}', 'bbox_pt':[round(v,3) for v in path['rect']],
                                'fill_rgb_0_1':[round(v,5) for v in fill], 'path':items,
                                'meaning':None, 'needs_review':True})
            # A PDF with text converted to outlines has no native words; the
            # usual table result drops textless cells. Keep the raw geometry.
            finder=page.find_tables(paths=paths, snap_tolerance=1,join_tolerance=1,intersection_tolerance=1)
            groups=group_cells(finder.cells)
            for group in groups:
                bounds=bbox_union(group)
                if bounds[2]-bounds[0]<35 or bounds[3]-bounds[1]<10:
                    continue
                tid=f't{len(tables)+1:03}'
                cells=[]
                for box in sorted(group,key=lambda b:(b[1],b[0],b[3],b[2])):
                    box=[round(v,3) for v in box]
                    contained=[w for w in words if box[0]-.7 <= (w['bbox_pt'][0]+w['bbox_pt'][2])/2 <= box[2]+.7 and box[1]-.7 <= (w['bbox_pt'][1]+w['bbox_pt'][3])/2 <= box[3]+.7]
                    cell_lines=collections.OrderedDict()
                    for w in contained:cell_lines.setdefault(w['line_key'],[]).append(w['text'])
                    pixels=[]
                    for fx in [.25,.5,.75]:
                        for fy in [.25,.5,.75]:
                            px=min(image.width-1,max(0,round((box[0]+fx*(box[2]-box[0]))*DPI/72)))
                            py=min(image.height-1,max(0,round((box[1]+fy*(box[3]-box[1]))*DPI/72)))
                            pixels.append(image.getpixel((px,py)))
                    rgb=collections.Counter(pixels).most_common(1)[0][0]
                    cells.append({'id':f'{tid}c{len(cells)+1:04}', 'bbox_pt':box,
                                  'ocr_text':'\n'.join(' '.join(g) for g in cell_lines.values()),
                                  'word_ids':[w['id'] for w in contained],
                                  'sampled_background_rgb_0_255':list(rgb),
                                  'needs_review':True})
                nearby=[l for l in lines if bounds[1]-65 <= l['bbox_pt'][1] < bounds[1] and l['bbox_pt'][0]<bounds[2]]
                tables.append({'id':tid,'kind':'grid_candidate', 'bbox_pt':bounds,
                               'preceding_text_candidates':[l['text'] for l in nearby[-5:]],
                               'cells':cells, 'semantic_columns':None, 'units_confirmed':False,
                               'needs_review':True})
        except Exception as exc:
            vector_error=f'{type(exc).__name__}: {exc}'
        footer_words=[w for w in words if w['bbox_pt'][1] > size[1]*.80 and re.fullmatch(r'\d{1,3}',w['text'])]
        footer_words=sorted(footer_words,key=lambda w:w['bbox_pt'][1],reverse=True)
        issues=[]
        if not words:issues.append('NO_WORDS_RECOGNIZED_CHECK_SOURCE_PAGE')
        if vector_error:issues.append('TABLE_GEOMETRY_EXTRACTION_FAILED')
        if any(w['confidence']<60 for w in words):issues.append('LOW_CONFIDENCE_OCR_WORDS')
        if colored:issues.append('COLOR_MEANINGS_REQUIRE_LEGEND_REVIEW')
        if tables:issues.append('TABLE_HEADERS_MERGES_AND_UNITS_REQUIRE_REVIEW')
        data={'schema_version':'1.0.0', 'document_id':doc_id,
              'source':{'filename':Path(source).name,'pdf_page_1based':page_num,
                        'combined_catalog_page_1based':combined_offset+page_num,
                        'printed_page_label_candidate':footer_words[0]['text'] if footer_words else None},
              'status':'ocr_completed', 'coordinate_system':{'unit':'PDF_point','points_per_inch':72,'origin':'top_left','page_size_pt':size},
              'extraction':{'engine':'Tesseract','languages':['kor','eng'],'dpi':DPI,'psm':3,'manual_validation':'not_performed'},
              'raw_text':base.with_suffix('.txt').read_text(encoding='utf-8'),
              'words':words,'lines':lines,'numeric_candidates':candidates,
              'table_grid_candidates':tables, 'colored_vector_regions':colored,
              'review':{'needs_review':True,'issues':issues,'table_geometry_error':vector_error,
                        'notice':'OCR confidence is an engine score, not a correctness guarantee. Numeric candidates, units, table associations and color meanings are not verified for calculations.'}}
        save_json(page_path,data)
        image_path.unlink(missing_ok=True)
    return {'page':page_num,'words':len(words),'numeric_candidates':len(candidates),'grids':len(tables),'seconds':round(time.monotonic()-started,2)}


def document_list():
    files=list(Path(os.environ.get('WHATNOT_INPUT_DIR', 'private/inputs')).rglob('*.pdf'))
    specs=[('pt1_part1','pt1(', 'PART 1',0),('pt1_part2','pt1(', 'PART 2',120),
           ('pt2_part1','pt2(', 'PART 1',0),('pt2_part2','pt2(', 'PART 2',123)]
    docs=[]
    for doc_id,needle,part,offset in specs:
        matches=[p for p in files if needle in p.name and part in p.name]
        if len(matches)!=1:raise RuntimeError(f'Ambiguous input: {doc_id}: {matches}')
        path=matches[0]
        with fitz.open(path) as pdf:count=len(pdf)
        docs.append({'document_id':doc_id,'path':str(path),'filename':path.name,'page_count':count,
                     'combined_offset':offset,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    return docs


def assemble_document(doc):
    folder=OUT/doc['document_id']
    pages=[json.loads((folder/'pages'/f'{i:04}.json').read_text(encoding='utf-8')) for i in range(1,doc['page_count']+1)]
    summary={'page_count':len(pages), 'ocr_completed_pages':sum(p['status']=='ocr_completed' for p in pages),
             'word_count':sum(len(p['words']) for p in pages),
             'numeric_candidate_count':sum(len(p['numeric_candidates']) for p in pages),
             'grid_candidate_count':sum(len(p['table_grid_candidates']) for p in pages),
             'zero_word_pages':[p['source']['pdf_page_1based'] for p in pages if not p['words']],
             'geometry_error_pages':[p['source']['pdf_page_1based'] for p in pages if p['review']['table_geometry_error']],
             'manual_validation':'not_performed', 'ready_for_automatic_numeric_conversion':False}
    result={'schema_version':'1.0.0','document':{k:v for k,v in doc.items() if k!='path'},
            'summary':summary,'pages':pages}
    save_json(OUT/(doc['document_id']+'.json'),result)
    (OUT/(doc['document_id']+'.txt')).write_text('\n\n'.join(f"=== PDF PAGE {p['source']['pdf_page_1based']} ===\n{p['raw_text']}" for p in pages),encoding='utf-8')
    print('DOCUMENT_COMPLETE',doc['document_id'],json.dumps(summary,ensure_ascii=False),flush=True)
    return summary


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--only',choices=['pt1_part1','pt1_part2','pt2_part1','pt2_part2'])
    args=parser.parse_args();OUT.mkdir(parents=True,exist_ok=True)
    docs=document_list();save_json(OUT/'manifest.json',{'documents':docs,'total_pages':sum(d['page_count'] for d in docs)})
    summaries={}
    for doc in docs:
        if args.only and args.only!=doc['document_id']:continue
        print('DOCUMENT_START',doc['document_id'],doc['page_count'],flush=True)
        tasks=[(doc['path'],doc['document_id'],i,doc['combined_offset']) for i in range(doc['page_count'])]
        errors=[]
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures={pool.submit(extract_page,t):t for t in tasks}
            for completed,future in enumerate(concurrent.futures.as_completed(futures),start=1):
                try:res=future.result();print('PAGE_COMPLETE',doc['document_id'],completed,'/',doc['page_count'],json.dumps(res),flush=True)
                except Exception as exc:
                    err={'document':doc['document_id'],'page':futures[future][2]+1,'error':str(exc)};errors.append(err);print('PAGE_ERROR',json.dumps(err),flush=True)
        if errors:
            save_json(OUT/(doc['document_id']+'_errors.json'),errors)
            raise RuntimeError(f'{len(errors)} page failures; resumable outputs preserved')
        summaries[doc['document_id']]=assemble_document(doc)
    save_json(OUT/'processing_summary.json',summaries)


if __name__=='__main__':main()
