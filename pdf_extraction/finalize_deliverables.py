#!/usr/bin/env python3
"""Validate page coverage and references, and package the extracted catalogs."""
import collections
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

from extract_catalogs import ROOT, OUT, save_json, document_list


def indices(values):
    result=[]
    for v in sorted(values):
        if not result or v-result[-1]>.08:result.append(v)
    return result


def source_ref(doc_id,page,bbox,printed=None):
    doc=next(d for d in document_list() if d['document_id']==doc_id)
    return {'document_id':doc_id,'filename':doc['filename'],'sha256':doc['sha256'],
            'pdf_page_1based':page,'printed_page_label_visually_read':printed,
            'bbox_pt':bbox,'coordinate_origin':'top_left','points_per_inch':72}


def examples():
    return {
        'scope':'Four representative records visually compared to rendered source excerpts. This does not validate the remaining OCR records or the correctness of published source data.',
        'examples':[
            {'id':'example_chemical_composition','source':source_ref('pt1_part1',36,[36,142,398,200],'34'),
             'validation_status':'visually_compared_to_source_excerpt','standard':'EN10025','grade':'S235JR',
             'properties':{'carbon_max':{'source_text':'0.17','value':0.17,'unit':'wt%'},
                           'manganese_max':{'source_text':'1.40','value':1.4,'unit':'wt%'}},
             'note':'Header says maximum composition; a dash is preserved as unspecified, never zero.'},
            {'id':'example_plate_cell','source':source_ref('pt1_part2',1,[63,139,500,212]),
             'validation_status':'visually_compared_to_source_excerpt',
             'row_context':{'thickness':{'source_text':'6 ≤ t < 7','lower':6,'lower_inclusive':True,'upper':7,'upper_inclusive':False,'unit':'mm'}},
             'column_context':{'width':{'source_text':'2801 ~ 3000','lower':2801,'upper':3000,'unit':'mm'}},
             'displayed_cell':{'source_text':'22.0','value':22.0,'unit':'m'},
             'note':'The page legend specifies M. This sample does not infer the engineering meaning of every grid cell or availability color.'},
            {'id':'example_h_section','source':source_ref('pt2_part1',26,[36,142,400,220],'24'),
             'validation_status':'visually_compared_to_source_excerpt','series':"Metric Series – JIS '21",
             'nominal_designation':'450 x 300',
             'properties':{'unit_weight':{'value':121,'unit':'kg/m'},'H':{'value':440,'unit':'mm'},
                           'B':{'value':300,'unit':'mm'},'t1':{'value':11,'unit':'mm'},
                           't2':{'value':18,'unit':'mm'},'r':{'value':13,'unit':'mm'},
                           'A':{'value':153.9,'unit':'cm²'},'Ix':{'source_text':'54,700','value':54700,'unit':'cm⁴'},
                           'Iy':{'source_text':'8,110','value':8110,'unit':'cm⁴'}},
             'note':'Nominal designation and actual H dimension differ in this source row; they are kept separate.'},
            {'id':'example_length_conversion','source':source_ref('pt2_part2',121,[36,142,400,264],'242'),
             'validation_status':'visually_compared_to_source_excerpt',
             'from':{'value':1,'unit':'in'},'to':{'source_text':'25.40','value':25.4,'unit':'mm'},
             'note':'Only this record was visually compared. Source consistency issues elsewhere on the same page are listed separately.'}
        ]}


def consistency_findings():
    return {'scope':'Two concrete source consistency findings from a representative conversion table; not an exhaustive audit.',
            'policy':'Preserve published source values in OCR outputs. Expected values are separate derived checks, never silent replacements.',
            'findings':[
                {'id':'source_conversion_m_to_cm','source':source_ref('pt2_part2',121,[36,205,180,218],'242'),
                 'row':'Meter (m)','column':'Centimeter (cm)','source_displayed_value':'10',
                 'expected_value_from_unit_definitions':100,'check':'1 m = 1000 mm; 1 cm = 10 mm; 1000 / 10 = 100',
                 'classification':'apparent_source_table_error','ocr_error':False,'needs_review':True},
                {'id':'source_conversion_in2_to_mm2','source':source_ref('pt2_part2',121,[36,442,180,456],'242'),
                 'row':'Square Inch (in²)','column':'Square Millimeter (mm²)','source_displayed_value':'654.2',
                 'expected_value_from_unit_definitions':645.16,'check':'1 in = 25.4 mm; 25.4² = 645.16 mm²',
                 'classification':'apparent_source_table_error','ocr_error':False,'needs_review':True}
            ]}


def main():
    docs=document_list()
    report={'total_documents':len(docs),'total_pages':0,'documents':[],
            'checks':{'json_parse':True,'consecutive_page_coverage':True,'word_references':True,'numeric_ambiguity_guard':True,'coordinates_in_page':True},
            'manual_validation':'four representative records only; no full transcription audit',
            'ready_for_automatic_numeric_conversion':False}
    review_pages=[]
    numerical_review=[]
    compact=OUT/'reference_pages.jsonl'
    with compact.open('w',encoding='utf-8') as stream:
        for doc in docs:
            pages=[]
            stats=collections.Counter()
            for i in range(1,doc['page_count']+1):
                path=OUT/doc['document_id']/'pages'/f'{i:04}.json'
                data=json.loads(path.read_text(encoding='utf-8'))
                assert data['status']=='ocr_completed' and data['enrichment_version']=='1.1.0'
                assert data['source']['pdf_page_1based']==i
                words={w['id']:w for w in data['words']}
                width,height=data['coordinate_system']['page_size_pt']
                for w in words.values():
                    x0,y0,x1,y1=w['bbox_pt']
                    assert -.3<=x0<=x1<=width+.3 and -.3<=y0<=y1<=height+.3,(doc['document_id'],i,w)
                for line in data['lines']:assert set(line['word_ids'])<=words.keys()
                footer=[w for w in words.values() if w['bbox_pt'][1]>height*.70
                        and (w['bbox_pt'][0]<width*.15 or w['bbox_pt'][2]>width*.85)
                        and re.fullmatch(r'\d{1,3}',w['text'])]
                footer.sort(key=lambda w:w['bbox_pt'][1],reverse=True)
                data['source']['printed_page_label_candidate']=footer[0]['text'] if footer else None
                data['source']['printed_page_label_status']='unverified_ocr_candidate'
                data['source']['combined_catalog_page_note']='Concatenated uploaded parts in filename order; not a verified printed page number.'
                data['schema_version']='1.1.0'
                data['review']['source_consistency_finding_ids']=['source_conversion_m_to_cm','source_conversion_in2_to_mm2'] if doc['document_id']=='pt2_part2' and i==121 else []
                for table in data['table_grid_candidates']:
                    xs=indices([v for c in table['cells'] for v in [c['bbox_pt'][0],c['bbox_pt'][2]]])
                    ys=indices([v for c in table['cells'] for v in [c['bbox_pt'][1],c['bbox_pt'][3]]])
                    table['grid_column_boundaries_pt']=xs;table['grid_row_boundaries_pt']=ys
                    for cell in table['cells']:
                        b=cell['bbox_pt']
                        c0=min(range(len(xs)),key=lambda j:abs(xs[j]-b[0]));c1=min(range(len(xs)),key=lambda j:abs(xs[j]-b[2]))
                        r0=min(range(len(ys)),key=lambda j:abs(ys[j]-b[1]));r1=min(range(len(ys)),key=lambda j:abs(ys[j]-b[3]))
                        cell['grid_row_start_1based']=r0+1;cell['grid_row_span']=r1-r0
                        cell['grid_column_start_1based']=c0+1;cell['grid_column_span']=c1-c0
                        assert set(cell['word_ids'])<=words.keys()
                for n in data['numeric_candidates']:
                    assert set(n['source_word_ids'])<=words.keys()
                    assert n['verified_value'] is None and n['needs_review']
                    if ',' in n['numeric_lexeme'] or n['visual_decimal_candidate']:
                        assert n['parsed_value'] is None
                    if n['review_reasons']:
                        numerical_review.append({'document_id':doc['document_id'],'pdf_page_1based':i,**n})
                low=sum(w['confidence']<60 for w in words.values())
                flags=data['review']['possible_missing_decimal_count']
                commas=data['review']['ambiguous_comma_count']
                review_pages.append({'document_id':doc['document_id'],'pdf_page_1based':i,
                                     'printed_page_label_candidate':data['source']['printed_page_label_candidate'],
                                     'low_confidence_word_count_under_60':low,
                                     'possible_missing_decimal_count':flags,'ambiguous_comma_count':commas,
                                     'issues':data['review']['issues'],'source_consistency_finding_ids':data['review']['source_consistency_finding_ids'],
                                     'needs_review':True})
                stats.update({'pages':1,'words':len(words),'lines':len(data['lines']),
                              'numeric_candidates':len(data['numeric_candidates']),
                              'expression_candidates':len(data['expression_candidates']),
                              'grid_candidates':len(data['table_grid_candidates']),
                              'possible_missing_decimals':flags,'ambiguous_commas':commas,
                              'low_confidence_words_under_60':low,
                              'zero_word_pages':not bool(words),
                              'geometry_error_pages':bool(data['review']['table_geometry_error'])})
                save_json(path,data);pages.append(data)
                record={k:data[k] for k in ['schema_version','document_id','source','coordinate_system','raw_text','lines','numeric_candidates','expression_candidates','unit_context_candidates','table_grid_candidates','colored_vector_regions','review']}
                stream.write(json.dumps(record,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n')
            summary=dict(stats);summary['ready_for_automatic_numeric_conversion']=False
            result={'schema_version':'1.1.0','document':{k:v for k,v in doc.items() if k!='path'},'summary':summary,'pages':pages}
            save_json(OUT/(doc['document_id']+'.json'),result)
            report['total_pages']+=len(pages);report['documents'].append({'document_id':doc['document_id'],'filename':doc['filename'],**summary})
            print('VALIDATED',doc['document_id'],dict(stats),flush=True)
    assert report['total_pages']==464
    save_json(OUT/'quality_report.json',report)
    save_json(OUT/'review_pages.json',review_pages)
    save_json(OUT/'numeric_review_queue.json',{'scope':'Numeric OCR candidates with explicit ambiguity or confidence flags; absence from this queue does not mean verified.','records':numerical_review})
    save_json(OUT/'verified_examples.json',examples())
    save_json(OUT/'source_consistency_findings.json',consistency_findings())
    manifest={'schema_version':'1.1.0','documents':[{k:v for k,v in d.items() if k!='path'} for d in docs],
              'total_pages':464,'processing_order':[d['document_id'] for d in docs],
              'ocr':{'engine':'Tesseract 5','languages':['kor','eng'],'dpi':350,'psm':3},
              'coordinate_system':'PDF points; 72 per inch; origin top left',
              'limitations':['OCR transcription is unverified except for the four separate examples.',
                             'Numeric candidates can be labels, years, grades or page numbers, not only dimensions.',
                             'Grid candidates do not guarantee complete tables or correct headers, merged cells, units or color meanings.',
                             'All proposed decimal reconstructions and comma separators require review.',
                             'Published conversion tables contain at least two apparent source errors.']}
    save_json(OUT/'manifest.json',manifest)
    save_json(OUT/'processing_summary.json',{d['document_id']:{k:v for k,v in d.items() if k not in ['document_id','filename']} for d in report['documents']})
    number_schema={'type':'object','required':['ocr_text','parsed_value','verified_value','needs_review'],
                   'properties':{'parsed_value':{'type':['number','null']},'verified_value':{'type':'null'},'needs_review':{'const':True}}}
    page_schema={'type':'object','required':['document_id','source','raw_text','words','numeric_candidates','table_grid_candidates','review'],
                 'properties':{'source':{'type':'object','required':['filename','pdf_page_1based']},
                               'numeric_candidates':{'type':'array','items':number_schema}}}
    schema={'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'urn:hyundai-steel-ocr-reference:1.1',
            'title':'OCR reference document','type':'object','required':['schema_version','document','summary','pages'],
            'properties':{'schema_version':{'const':'1.1.0'},'document':{'type':'object','required':['document_id','filename','page_count','sha256']},
                          'summary':{'type':'object'},'pages':{'type':'array','items':page_schema}}}
    save_json(OUT/'document.schema.json',schema)
    readme='''# 현대제철 카탈로그 OCR 참조 데이터

업로드한 네 PDF, 총 464페이지를 파일 순서대로 전부 OCR 처리했습니다.
pt1 PART 1: 120페이지 / pt1 PART 2: 88페이지 / pt2 PART 1: 123페이지 / pt2 PART 2: 133페이지.

## 파일

- `pt1_part1.json`, `pt1_part2.json`, `pt2_part1.json`, `pt2_part2.json`: 파일별 전체 데이터. UTF-8 JSON.
- `reference_pages.jsonl`: 한 줄에 한 페이지. 큰 파일을 순차적으로 읽을 때 사용합니다. word ID 원본은 전체 JSON에 있습니다.
- `quality_report.json`: 페이지 누락·참조·좌표·숫자 모호성 검사 결과와 파일별 통계.
- `review_pages.json`: 페이지별 검토 우선순위를 정할 수 있는 오류 신호와 개수.
- `numeric_review_queue.json`: 모호성 또는 낮은 인식 점수가 있는 숫자 후보. 이 목록에 없다고 검증된 숫자는 아닙니다.
- `verified_examples.json`: 네 대표 항목을 원본 이미지와 시각적으로 비교해 정리한 예시. 전체 데이터 검증을 의미하지 않습니다.
- `source_consistency_findings.json`: 원본 환산표에서 발견한 오류 의심 두 항목.
- `manifest.json`: 원본 파일명, SHA-256, 처리 순서, OCR 설정.
- `document.schema.json`: 전체 JSON 문서의 기본 구조를 검사하는 JSON Schema.
- `*.txt`: 페이지 구분이 있는 OCR 텍스트.
- `source_excerpts/`: 대표 항목과 원본 환산표 오류 의심 부분의 렌더링 이미지.
- `scripts/`: 실제 사용한 로컬 추출·후처리·검사 스크립트.

## 구조와 값의 의미

`pages[].source.pdf_page_1based`는 분할 PDF 안의 1부터 시작하는 페이지입니다.
`combined_catalog_page_1based`는 같은 pt의 업로드 파트를 파일명 순서로 연결한 페이지이며 인쇄된 쪽수가 아닙니다.
`printed_page_label_candidate`는 OCR로 찾은 인쇄 쪽수 후보이며 틀리거나 없을 수 있습니다.
좌표는 좌상단을 원점으로 하는 PDF 포인트입니다. 72포인트가 1인치입니다.
단어·줄·숫자·표·셀 ID의 유효 범위는 각 페이지 안입니다. 전체 식별 키는 document_id + pdf_page_1based + ID입니다.

`raw_text`, `words`, `lines`는 OCR 결과입니다. 원문을 완벽히 옮겼다는 뜻이 아닙니다.
`numeric_candidates`는 숫자로 읽힌 후보로, 치수 외에도 날짜·등급·페이지 번호가 포함될 수 있습니다.
`numeric_lexeme`와 `ocr_text`는 인식된 표기를 보존합니다.
`parsed_value`는 기계적으로 읽은 잠정 값입니다. `verified_value`는 전체 추출 데이터에서 모두 null입니다.
쉼표가 있거나 누락된 소수점이 의심되면 parsed_value를 null로 남겼습니다.
`visual_decimal_candidate`는 숫자 사이의 작은 기준선 점을 이미지에서 찾은 검토 후보이며 자동 교정값이 아닙니다.
OCR 신뢰도는 Tesseract 점수이며 정확할 확률이 아닙니다. 높은 점수에서도 소수점 누락이 관찰되었습니다.

`expression_candidates`는 치수 곱·범위·부등식·공차로 보이는 문자열입니다. 변수와 의미는 확정하지 않았습니다.
`unit_explicit_in_token`은 해당 숫자 토큰에 실제 인식된 단위만 담습니다.
`unit_context_candidates`는 주변 단위 표기 후보이며 개별 값에 자동 배정하지 않았습니다.
`table_grid_candidates`는 선으로 검출된 셀 집합입니다. 행·열 인덱스와 span은 기하 정보이며 의미 열 이름이 아닙니다.
선이 없는 열, 분리된 머리글, 병합 셀, 색으로 표시된 공급 범위는 누락되거나 분리될 수 있습니다.
`colored_vector_regions`는 원본 PDF의 색·도형 좌표를 보존합니다. 공급 가능/불가 등의 의미는 자동 판정하지 않았습니다.

## 검토와 후속 변환

이 결과는 출처를 추적할 수 있는 OCR 참조 데이터입니다. 464페이지의 치수·등급·단위·공차를 모두 검수한 계산용 데이터베이스는 아닙니다.
숫자와 표의 관계를 확인한 다음 별도의 승인 값이나 변환 결과를 기록하세요. OCR 원문과 잠정 값을 덮어쓰지 마세요.
특히 H형강의 호칭 치수와 실제 단면 치수를 분리하세요. 시각적으로 비교한 예시의 호칭은 450 x 300이지만 H 열은 440 mm입니다.
대시는 0이 아닙니다. 부등호의 포함 여부, 지수 단위, 하첨자, 각주와 색 범례를 원문과 함께 확인하세요.
원본 환산표 pt2 PART 2의 PDF 121페이지(인쇄 242쪽)에 1 m → 10 cm, 1 in² → 654.2 mm² 표기가 보입니다.
단위 정의에 따른 값은 각각 100 cm, 645.16 mm²입니다. 추출 원문을 바꾸지 않고 별도 오류 의심 기록으로 남겼습니다.

이메일은 발송하지 않았습니다. 현재 세션에는 이메일 발송 도구가 없습니다.
'''
    (OUT/'README_ko.md').write_text(readme,encoding='utf-8')
    print('DELIVERABLE_METADATA_COMPLETE',flush=True)


if __name__=='__main__':main()
