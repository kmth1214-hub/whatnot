#!/usr/bin/env python3
"""Add conservative numeric parsing and visual decimal review signals."""
import collections
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re

import fitz
import numpy as np
from scipy import ndimage

from extract_catalogs import OUT, ROOT, DPI, save_json, document_list, assemble_document, bbox_union

TOKEN = re.compile(r'^(?P<op><=|>=|≤|≥|<|>|~|≈)?\s*(?P<n>[+−-]?\d+(?:[.,]\d+)*)(?:\s*(?P<unit>mm|cm|m|MPa|GPa|kg/m|kg|%))?$')
OPERATOR = {'<','>','≤','≥','<=','>='}
VALUE = r'[+−-]?\d+(?:[.,]\d+)?'
PATTERNS = [
    ('symmetric_tolerance', re.compile(r'(?P<value>'+VALUE+r')\s*±\s*(?P<tolerance>'+VALUE+r')')),
    ('dimension_sequence', re.compile(r'(?P<a>'+VALUE+r')\s*[×xX]\s*(?P<b>'+VALUE+r')(?:\s*[×xX]\s*(?P<c>'+VALUE+r'))?')),
    ('range', re.compile(r'(?P<lower>'+VALUE+r')\s*[~～〜–]\s*(?P<upper>'+VALUE+r')')),
    ('bounded_variable', re.compile(r'(?P<lower>'+VALUE+r')\s*(?P<left_op>[<≤])\s*(?P<variable>[tTHBWdhb])\s*(?P<right_op>[<≤])\s*(?P<upper>'+VALUE+r')')),
    ('variable_bound', re.compile(r'(?P<variable>[tTHBWdhb])\s*(?P<operator><=|>=|[<>≤≥])\s*(?P<bound>'+VALUE+r')')),
]


def decimal_signal(rgb, box, digit_text, operator):
    """Detect a small baseline component between digit components.

    This is evidence for review, never an automatic correction or validation.
    It does not guess an absent decimal from engineering plausibility.
    """
    digits=digit_text.lstrip('+−-')
    if not digits.isdigit() or len(digits)<2 or len(digits)>9:
        return None
    scale=DPI/72
    x0,y0,x1,y1=box
    patch=rgb[max(0,int(y0*scale)-3):min(rgb.shape[0],int(y1*scale)+5),
              max(0,int(x0*scale)-3):min(rgb.shape[1],int(x1*scale)+5)]
    if not patch.size:return None
    labels,_=ndimage.label(np.min(patch,axis=2)<150)
    components=[]
    for s in ndimage.find_objects(labels):
        if s is None:continue
        ys,xs=s;w=xs.stop-xs.start;h=ys.stop-ys.start
        if w*h>=3:components.append((xs.start,ys.start,w,h))
    if not components:return None
    tallest=max(c[3] for c in components)
    big=sorted([c for c in components if c[3]>=.6*tallest and c[2]>=.10*tallest])
    # Comparator glyphs can form an extra full-height connected component.
    if operator in {'<','>','≤','≥'} and len(big)==len(digits)+1:
        big=big[1:]
    if len(big)!=len(digits):return None
    height=float(np.median([c[3] for c in big]))
    baseline=float(np.median([c[1]+c[3] for c in big]))
    dots=[c for c in components if .065*height<=c[3]<=.32*height
          and .065*height<=c[2]<=.35*height and .45<=c[2]/c[3]<=2.0
          and baseline-.24*height<=c[1]+c[3]<=baseline+.20*height]
    positions=[]
    for dot in dots:
        cx=dot[0]+dot[2]/2
        for k in range(1,len(big)):
            if big[k-1][0]+big[k-1][2] < cx < big[k][0]:
                positions.append(k)
    if len(set(positions))!=1:return None
    pos=positions[0]
    text=digits[:pos]+'.'+digits[pos:]
    if digit_text.startswith(('-', '−')):text='-'+text
    return {'candidate_text':text,'candidate_value':float(text),
            'method':'small_baseline_component_between_digit_components',
            'status':'unverified_visual_candidate'}


def improve_page(task):
    source,doc_id,index=task
    path=OUT/doc_id/'pages'/f'{index+1:04}.json'
    data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('enrichment_version')=='1.1.0':
        return {'page':index+1,'cached':True}
    with fitz.open(source) as pdf:
        pix=pdf[index].get_pixmap(dpi=DPI,alpha=False)
    rgb=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,3)
    line_words=collections.OrderedDict()
    for w in data['words']:line_words.setdefault(w['line_key'],[]).append(w)
    word_to_line={wid:line['id'] for line in data['lines'] for wid in line['word_ids']}
    word_to_cells=collections.defaultdict(list)
    for table in data['table_grid_candidates']:
        for cell in table['cells']:
            for wid in cell['word_ids']:word_to_cells[wid].append({'grid_id':table['id'],'cell_id':cell['id']})
    numbers=[]
    for words in line_words.values():
        for i,w in enumerate(words):
            m=TOKEN.fullmatch(w['text'].strip())
            if not m:continue
            sign=m['op'];ids=[w['id']];ocr=w['text'];box=w['bbox_pt'];issues=[]
            if not sign and i and words[i-1]['text'].strip() in OPERATOR:
                prev=words[i-1]
                gap=box[0]-prev['bbox_pt'][2]
                if -.5<=gap<=10:
                    sign=prev['text'].strip();ids.insert(0,prev['id'])
                    ocr=prev['text']+' '+ocr;box=bbox_union([box,prev['bbox_pt']])
            lexeme=m['n'];value=None
            if ',' in lexeme:
                issues.append('AMBIGUOUS_COMMA_SEPARATOR')
            elif lexeme.count('.')>1:
                issues.append('MULTIPLE_DECIMAL_POINTS')
            else:
                plain=lexeme.replace('−','-')
                value=float(plain) if '.' in plain else int(plain)
            signal=decimal_signal(rgb,w['bbox_pt'],lexeme,m['op']) if '.' not in lexeme and ',' not in lexeme else None
            ocr_value=value
            if signal:
                value=None;issues.append('POSSIBLE_DECIMAL_POINT_MISSED_BY_OCR')
            if w['confidence']<85:issues.append('LOW_OCR_CONFIDENCE')
            numbers.append({'id':f'n{len(numbers)+1:05}', 'ocr_text':ocr,
                            'numeric_lexeme':lexeme,'parsed_value':value,
                            'ocr_parsed_value_before_visual_check':ocr_value,
                            'operator':sign, 'unit_explicit_in_token':m['unit'],
                            'verified_value':None,'source_word_ids':ids,
                            'source_line_id':word_to_line.get(w['id']),
                            'grid_cell_candidates':word_to_cells.get(w['id'],[]),
                            'bbox_pt':box,'ocr_confidence':w['confidence'],
                            'visual_decimal_candidate':signal,
                            'review_reasons':issues,'needs_review':True})
    expressions=[]
    for line in data['lines']:
        for kind,pattern in PATTERNS:
            for match in pattern.finditer(line['text']):
                expressions.append({'id':f'e{len(expressions)+1:04}', 'kind':kind,
                                    'ocr_text':match.group(0), 'components_as_ocr_strings':match.groupdict(),
                                    'source_line_id':line['id'],'line_bbox_pt':line['bbox_pt'],
                                    'needs_review':True,'semantic_assignment':None})
    unit_lines=[]
    for line in data['lines']:
        matches=re.findall(r'(?<![A-Za-z])(?:N/mm[²2?]?|kg/m[²2³3]?|mm[²2³3⁴4]?|cm[²2³3⁴4]?|MPa|GPa|kN|kg|%)(?![A-Za-z])',line['text'])
        if matches:unit_lines.append({'line_id':line['id'],'ocr_unit_tokens':matches,'text':line['text'],'bbox_pt':line['bbox_pt'],'needs_review':True})
    data['numeric_candidates']=numbers
    data['expression_candidates']=expressions
    data['unit_context_candidates']=unit_lines
    data['enrichment_version']='1.1.0'
    data['extraction']['manual_validation']='not_performed_except_separate_verified_examples'
    data['review']['numeric_candidate_count']=len(numbers)
    data['review']['possible_missing_decimal_count']=sum(bool(n['visual_decimal_candidate']) for n in numbers)
    data['review']['ambiguous_comma_count']=sum('AMBIGUOUS_COMMA_SEPARATOR' in n['review_reasons'] for n in numbers)
    if data['review']['possible_missing_decimal_count']:
        data['review']['issues'].append('POSSIBLE_DECIMAL_POINTS_MISSED_BY_OCR')
    if data['review']['ambiguous_comma_count']:
        data['review']['issues'].append('AMBIGUOUS_COMMA_SEPARATORS')
    # Preserve OCR word order and geometry; no missing headers or units inferred.
    for table in data['table_grid_candidates']:
        table['numeric_candidate_ids']=[n['id'] for n in numbers if any(c['grid_id']==table['id'] for c in n['grid_cell_candidates'])]
        table['context_note']='Grid candidates can omit borderless columns, merged regions or a disconnected header. Refer to all page words and the source PDF.'
    save_json(path,data)
    return {'page':index+1,'numbers':len(numbers),'decimal_flags':data['review']['possible_missing_decimal_count']}


def main():
    docs=document_list();summary={}
    for doc in docs:
        print('ENRICH_START',doc['document_id'],flush=True)
        tasks=[(doc['path'],doc['document_id'],i) for i in range(doc['page_count'])]
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
            for count,result in enumerate(pool.map(improve_page,tasks),1):
                if count%15==0 or count==doc['page_count']:print('ENRICH_PAGE',doc['document_id'],count,'/',doc['page_count'],json.dumps(result),flush=True)
        summary[doc['document_id']]=assemble_document(doc)
    save_json(OUT/'processing_summary.json',summary)


if __name__=='__main__':main()
