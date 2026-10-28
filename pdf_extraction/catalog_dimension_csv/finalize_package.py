#!/usr/bin/env python3

import os
import collections
import csv
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'deliverables'


def read(name):
    with (OUT/name).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def write(name,rows,headers=None):
    headers=headers or list(dict.fromkeys(k for row in rows for k in row))
    with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=headers);w.writeheader();w.writerows(rows)


def inside(v,lower,lower_inclusive,upper,upper_inclusive):
    if v is None or not lower or not upper:return False
    v=D(str(v));lo=D(lower);hi=D(upper)
    return (v>=lo if lower_inclusive=='TRUE' else v>lo) and (v<=hi if upper_inclusive=='TRUE' else v<hi)


def geometric_ranges(rows,thickness,width,length):
    return [r for r in rows if r['PRODUCT_TYPE']=='STEEL_PLATE' and r['ALLOW_DIMENSION_LOOKUP']=='TRUE'
            and inside(thickness,r['THICKNESS_MIN'],r['THICKNESS_MIN_INCLUSIVE'],r['THICKNESS_MAX'],r['THICKNESS_MAX_INCLUSIVE'])
            and inside(width,r['WIDTH_MIN'],r['WIDTH_MIN_INCLUSIVE'],r['WIDTH_MAX'],r['WIDTH_MAX_INCLUSIVE'])
            and inside(length,r['LENGTH_MIN'],r['LENGTH_MIN_INCLUSIVE'],r['LENGTH_MAX'],r['LENGTH_MAX_INCLUSIVE'])]


def main():
    exact=read('CatalogExactDimensions.csv');ranges=read('CatalogSupplyRanges.csv')
    tests=[]
    h=[r for r in exact if r['PRODUCT_TYPE']=='H_SECTION' and r['DIMENSION_SERIES']=='METRIC_JIS_2021'
       and r['SIZE_RAW']=='450x300']
    assert len(h)==1 and h[0]['SECTION_HEIGHT_MM']=='440' and h[0]['WIDTH']=='300' and h[0]['WEB_THICKNESS_MM']=='11' and h[0]['FLANGE_THICKNESS_MM']=='18'
    tests.append('H_section_nominal_450x300_is_kept_separate_from_actual_440x300x11x18')
    assert h[0]['LENGTH']=='' and h[0]['THICKNESS']=='';tests.append('H_height_is_not_product_length_and_web_flange_not_collapsed')
    bar=[r for r in exact if r['PRODUCT_TYPE']=='REBAR' and r['DIMENSION_SERIES']=='KS_JIS' and r['SIZE_RAW']=='D10'][0]
    assert bar['NOMINAL_DIAMETER_MM']=='9.53' and bar['OUTSIDE_DIAMETER']=='';tests.append('rebar_nominal_diameter_not_used_as_outer_rib_diameter')
    wire=[r for r in exact if r['PRODUCT_TYPE']=='WIRE_ROD' and r['OUTSIDE_DIAMETER']=='10']
    assert len(wire)==1 and wire[0]['SOURCE_OCCURRENCES']=='2';tests.append('identical_printed_wire_duplicate_merged')
    assert len(exact)==498 and len({r['MATCH_KEY'] for r in exact})==498;tests.append('498_unique_exact_match_keys')
    assert all(not r['TARGET_ITEM_CODE'] and not r['TARGET_ITEM_NAME'] and not r['MATERIAL_CODE'] for r in exact);tests.append('no_invented_company_or_manufacturer_codes')
    assert all(r['ALLOW_MATERIAL_CODE_REPLACEMENT']=='FALSE' for r in exact+ranges);tests.append('unapproved_material_replacement_disabled')
    assert len(geometric_ranges(ranges,6.5,1300,22000))==1;tests.append('plate_example_6_5x1300x22000_has_one_geometric_range')
    assert not geometric_ranges(ranges,6.5,1300,22001);tests.append('plate_length_above_maximum_rejected')
    assert len(geometric_ranges(ranges,7,1300,22000))==1;tests.append('thickness_boundary_7_belongs_to_next_band_only')
    assert not geometric_ranges(ranges,6.5,1200.5,22000);tests.append('fractional_width_gap_not_silently_filled')
    assert not geometric_ranges(ranges,72,1100,13500) and len(geometric_ranges(ranges,72,1100,13000))==1;tests.append('source_T_ge_70_general_13m_cap_applied')
    assert not geometric_ranges(ranges,6.5,4700,3000);tests.append('source_unavailable_cell_not_matched')
    assert all(not r['WALL_THICKNESS'] and not r['SCHEDULE'] for r in exact);tests.append('no_pipe_wall_or_schedule_data_invented')
    assert read('CurrentOCRInputReview.csv')[0]['THICKNESS']=='';tests.append('current_missing_OCR_dimensions_not_inferred_from_ambiguous_raw_size')
    assert not any('PAGE' in key or 'BBOX' in key for key in exact[0]);tests.append('runtime_exact_and_range_lists_exclude_page_coordinates')
    assert not any('PAGE' in key or 'BBOX' in key for key in ranges[0])
    definitions={r['Title']:r for r in read('OCR_FieldDefinitions.csv')}
    boolean_fields={'THICKNESS_MIN_INCLUSIVE','THICKNESS_MAX_INCLUSIVE','WIDTH_MIN_INCLUSIVE','WIDTH_MAX_INCLUSIVE',
                    'LENGTH_MIN_INCLUSIVE','LENGTH_MAX_INCLUSIVE','CONDITIONS_TRANSCRIBED','ALLOW_DIMENSION_LOOKUP',
                    'ALLOW_MATERIAL_CODE_REPLACEMENT','ROUND_FOR_MATCH','REQUIRES_EXPLICIT_SOURCE_UNIT','IS_CONFIRMED_PRODUCT_FAMILY_ALIAS'}
    text_fields={'Title','MATCH_KEY','MATCH_FIELDS','RECORD_VERSION','DIMENSION_SERIES','DIMENSION_STANDARD',
                 'DIMENSION_UNIT','MATCH_MODE','PRODUCT_TYPE','PROCESS','CATALOG_GRADE_GROUP','GRADE','MATERIAL_CODE','SCHEDULE',
                 'SIZE_RAW','CATALOG_ITEM_NAME','TARGET_ITEM_NAME','TARGET_ITEM_CODE','SUPPLY_NOTE','TRANSCRIPTION_STATUS',
                 'DIAMETER_BASIS','SOURCE_CELL_STATUS','NOTES','NORMALIZED_UNIT','CATEGORY','SHAREPOINT_TYPE','NULL_POLICY',
                 'DISPLAY_NAME','SOURCE_PRODUCT_TYPE','CANONICAL_PRODUCT_TYPE','SOURCE_UNIT','TARGET_UNIT','QUANTITY_KIND',
                 'PURCHASE_ORDER','STANDARD_SPEC','MATCH_STATUS'}
    schemas=[]
    for name in ['CatalogExactDimensions.csv','CatalogSupplyRanges.csv','CatalogMatchProfiles.csv','UnitNormalization.csv','ProductTypeAliases.csv','CurrentOCRInputReview.csv']:
        rows=read(name)
        for field in rows[0]:
            vals=[r[field] for r in rows if r[field]]
            if field in boolean_fields:kind='Yes/No'
            elif field in definitions:kind=definitions[field]['SHAREPOINT_TYPE']
            elif field in text_fields or not vals:kind='Text'
            else:
                try:
                    for value in vals:D(value)
                    kind='Number'
                except Exception:kind='Text'
            if field in ['NOTES','SUPPLY_NOTE','TARGET_POLICY','NOTE']:kind='Multiple lines of text'
            schemas.append({'Title':name[:-4]+'_'+field,'LIST_NAME':name[:-4],'COLUMN_INTERNAL_NAME':field,
                            'SHAREPOINT_TYPE':kind,'RECOMMENDED_INDEX':field in ['Title','MATCH_KEY','PRODUCT_TYPE','DIMENSION_SERIES'],
                            'UNIQUE_VALUES':field in ['Title','MATCH_KEY'],
                            'NUMBER_DECIMAL_PLACES':'5' if kind=='Number' else '',
                            'NOTE':definitions.get(field,{}).get('NOTES','')})
    write('SharePointColumnDefinitions.csv',schemas)
    source_checks=[]
    manifest=json.loads((ROOT.parent/'results/manifest.json').read_text())
    for meta in manifest['documents']:
        p=next(p for p in Path(os.environ.get('WHATNOT_INPUT_DIR', 'private/inputs')).rglob('*.pdf') if p.name==meta['filename'])
        assert hashlib.sha256(p.read_bytes()).hexdigest()==meta['sha256'];source_checks.append(meta['document_id'])
    tests.append('all_4_source_PDF_hashes_unchanged')
    old_checksums=json.loads((ROOT.parent/'results/checksums.json').read_text())
    for name in ['pt1_part1.json','pt1_part2.json','pt2_part1.json','pt2_part2.json']:
        assert hashlib.sha256((ROOT.parent/'results'/name).read_bytes()).hexdigest()==old_checksums[name]
    tests.append('existing_4_complete_OCR_JSON_outputs_unchanged')
    readme=f'''# SharePoint용 카탈로그 치수 기준 CSV

사용자가 제공한 OCR 필드명 36개를 분류하고, 카탈로그 원본 이미지와 대조한 치수 데이터를 일괄 입력용 표로 정리했습니다.
실제 SharePoint나 PA에는 등록·배포하지 않았습니다. 원본 PDF와 기존 OCR 결과는 변경하지 않았습니다.

## 먼저 사용할 파일

| 파일 | 역할 | 행 수 |
|---|---|---:|
| CatalogExactDimensions.csv | 단면·봉강 등의 정확 규격 기준 | 498 |
| CatalogSupplyRanges.csv | TMCP 후판의 두께·폭별 길이 상한과 GI 선택 구간 | 562 |
| OCR_FieldDefinitions.csv | 화면에 있는 36개 필드의 치수 관련 분류와 추가 권장 열 | 55 |
| SharePointColumnDefinitions.csv | 목록별 열 이름·자료형·권장 인덱스 | {len(schemas)} |
| CatalogMatchProfiles.csv | 제품·치수 시리즈별 필수 조회 조건 | {len(read('CatalogMatchProfiles.csv'))} |
| UnitNormalization.csv | 명시된 원본 단위의 mm/kg 환산 | 10 |
| ProductTypeAliases.csv | 제품명 표준화와 HR 미확정 처리 | {len(read('ProductTypeAliases.csv'))} |
| CurrentOCRInputReview.csv | 실제 제공 JSON DEMO002에서 부족한 치수 확인 | 1 |

`SharePoint_CatalogDimensions.xlsx`에는 정확규격·공급범위·OCR열정의 등 7개의 Excel 표가 있습니다.
CSV 가져오기를 지원하는 SharePoint/Lists 화면에서는 CSV를 사용하고, Excel 가져오기에서는 원하는 표를 선택할 수 있습니다.
모든 CSV는 UTF-8 BOM, 쉼표 구분, 소수점 '.', 빈 값은 빈칸, 논리값은 TRUE/FALSE입니다.
가져온 뒤 열 자료형을 확인하세요. Number와 Yes/No가 텍스트로 들어왔다면 열 정의대로 설정합니다.

## SharePoint 목록 구성

1. `CatalogExactDimensions` 목록: CatalogExactDimensions.csv를 가져옵니다.
2. `CatalogSupplyRanges` 목록: CatalogSupplyRanges.csv를 별도 목록으로 가져옵니다.
3. 필요하면 단위 환산·제품명 별칭·매칭 조건 표도 별도 설정 목록으로 만듭니다.
4. Title은 데이터 내부 고유키입니다. MATCH_KEY는 제품·치수 시리즈·실치수의 조합 키이며 정확규격 목록에서 고유합니다.
5. 필요한 회사 항목명과 코드를 TARGET_ITEM_NAME, TARGET_ITEM_CODE에 등록합니다. 예를 들어 회사에서 쓰는 '123'은 이 열에 확정해서 입력합니다.
6. 회사 코드와 모든 필수 조건을 확인한 행만 별도 운영 정책에 따라 코드 치환 대상으로 사용합니다.

## 제품 매칭 시 주의할 의미

- PRODUCT_TYPE, DIMENSION_SERIES 및 MATCH_FIELDS에 선언된 조건이 모두 있어야 정확 규격을 조회합니다.
- SIZE_RAW는 원문 호칭을 보존합니다. H형강 450x300은 길이가 아니며 실제 H가 440인 행이 존재합니다.
- H/I형강 t1/t2는 WEB_THICKNESS_MM, FLANGE_THICKNESS_MM로 분리했습니다. THICKNESS 한 칸으로 합치지 않았습니다.
- ㄱ형강은 LEG_A_MM, LEG_B_MM, THICKNESS를 사용합니다. 부등두께 ㄱ형강은 LEG_A_THICKNESS_MM/LEG_B_THICKNESS_MM로 구분합니다.
- 철근의 공칭직경은 NOMINAL_DIAMETER_MM입니다. 리브 포함 외경 OUTSIDE_DIAMETER와 같다고 처리하지 않았습니다.
- 원형 봉·선재는 OUTSIDE_DIAMETER에 카탈로그의 공칭 원형 치수를 넣고 DIAMETER_BASIS를 명시했습니다.
- SCHEDULE은 SCH40 같은 범주형입니다. 숫자 40을 두께(mm)로 취급하면 안 됩니다.
- 현재 정확규격 표의 LENGTH는 모두 비어 있습니다. 단면 치수표에는 축방향 절단 길이가 지정되지 않았으므로 임의 길이를 추가하지 않았습니다.
- 재질 규격 STANDARD_SPEC과 치수 규격 DIMENSION_STANDARD를 구분합니다. ASTM A6를 ASTM A36과 같다고 매핑하지 않습니다.
- 미기재 값은 0이 아닙니다. 필수값이 없거나 여러 행이 맞으면 확인 필요로 분기합니다.

## 회사 코드와 카탈로그 항목명

CATALOG_ITEM_NAME은 제품 형태·실치수·시리즈로 생성한 설명용 이름입니다. 현대제철 공식 자재번호가 아닙니다.
SIZE_RAW에는 원문 호칭을 보존하고, 회사의 대응 이름·코드는 TARGET_ITEM_NAME/TARGET_ITEM_CODE에 따로 입력하게 했습니다.
회사 코드가 제공되지 않았으므로 두 열 및 MATERIAL_CODE는 비워 두었습니다.
ALLOW_DIMENSION_LOOKUP=TRUE는 확인한 기하 치수를 조회할 수 있다는 뜻입니다.
ALLOW_MATERIAL_CODE_REPLACEMENT는 모든 행에서 FALSE이며, 공급·재질·도금 동등성이 승인되었다는 의미를 부여하지 않았습니다.

## 후판·코일 범위 표 사용

CatalogSupplyRanges는 정확 규격 표와 다른 방식으로 비교합니다.
두께·폭은 MIN/MAX와 포함 여부를 함께 사용하고, 길이가 있는 후판은 LENGTH_MIN/MAX 조건까지 확인합니다.
TMCP 후판 원본의 최대 길이 표 560셀을 전사했고, 숫자 최대값이 있는 셀은 469개입니다.
숫자가 없는 셀은 NOT_AVAILABLE, CONSULTATION_REQUIRED_300MM 또는 NO_NUMERIC_MAXIMUM_REQUIRES_CONFIRMATION으로 남겼습니다.
빈 셀을 무제한 공급이나 길이 0으로 바꾸지 않았습니다.
최소 길이 3m는 3000mm로 변환했습니다. 원문 TABLE_LENGTH_MAX_M과 환산 mm, 적용 LENGTH_MAX를 함께 보관했습니다.
원문 일반 주석 T>=70mm에서 최대 13m 조건은 LENGTH_MAX에 반영했습니다. 인쇄 셀 숫자는 그대로 별도 열에 남겼습니다.
열처리 제품의 에지별 폭 제한(밀에지 4700mm, 슬릿 4750mm), 육상운송 21.5m, 고강도·해양구조용 특정 조건의 협의 필요도 NOTES와 전용 열에 보관했습니다.
이 조건들은 해당 주문의 재질·에지·운송 조건과 함께 적용해야 합니다. 치수 범위 일치만으로 주문 전체 공급 가능을 확정하지 않습니다.
폭 표기는 정수 mm 구간입니다. 예를 들어 1200과 1201 사이의 소수 폭이 있다고 임의로 구간을 이어 붙이지 않습니다.
GI 2행은 확인한 두 차트의 일부 내부 구간입니다. SS37→카탈로그 강종 그룹의 동등성은 확정하지 않았습니다.

예시: TMCP, 두께 6.5mm, 폭 1300mm, 길이 22000mm는 기하 범위 한 행에 맞습니다.
같은 조건에서 길이 22001mm는 길이 상한을 넘습니다. 재질·공정·공급 조건 검토는 별도로 필요합니다.

## 현재 제공된 OCR JSON에서 필요한 보완

발주번호 DEMO002의 PO_ITEM.value[0]에는 THICKNESS와 WIDTH 필드가 없고 SIZE_RAW='10 x 200 x 3000'만 있습니다.
단위와 구분 문자가 확인되지 않아 인치·곱셈으로 추정해 숫자를 채우지 않았습니다.
지금 JSON 그대로는 두께·폭 조합 조회를 확정할 수 없습니다. 원문 또는 OCR 설정에서 치수와 단위를 확인해 분리해야 합니다.
PRODUCT_TYPE='HR'만으로 코일인지 판재인지도 확정하지 않았습니다.

## 제공 범위와 검토 자료

정확규격은 21쪽의 15개 제품군에서 치수·단위중량 500행을 원본 이미지와 대조해 전사했고, 동일한 선재 중복 2행을 병합해 498행입니다.
선택 제품군: H형강, H형강 말뚝, 경량 H형강, I형강, 등변/부등변/부등두께 ㄱ형강, 채널, 평행 채널, 강널말뚝, 철근, 나사형 철근, 원형 봉강, 선재, 각봉.
별도 공급범위는 후판 TMCP 2쪽의 560셀과 GI 2개 선택 구간입니다.
카탈로그 전체 464쪽의 모든 규격·공차를 검수한 데이터베이스는 아닙니다.
남은 치수·공급·공차 관련 OCR 셀 {len(read('CatalogReviewCells_DO_NOT_AUTOMATCH.csv')):,}건은 CatalogReviewCells_DO_NOT_AUTOMATCH.csv에 검토 전용으로 분리했습니다.
이 검토 파일을 실행용 기준 목록에 섞거나 자동 매칭에 사용하지 마세요. OCR 단어·머리글·단위·색 범례가 아직 미확정입니다.
관벽·관 스케줄·관 내외경에 해당하는 규격표는 제공 자료에서 확정하지 못해 생성하지 않았습니다.
별표의 별도주문·규격 미포함 제한은 SUPPLY_NOTE와 별도 출처 기록에 보존했습니다.

## 출처와 검증

실행용 정확규격/공급범위 CSV에는 페이지·좌표를 넣지 않았습니다.
CatalogSourceAudit.csv에서 Title 키로 원본 파일명·분할 PDF 페이지·행·좌표를 추적할 수 있습니다.
CatalogCoverage.csv는 464쪽 전체 분류와 확인 범위를 표시합니다.
CSV 열 수·행 수·UTF-8 BOM, 조합 키 중복, 길이 범위 경계, 철근 직경 의미, TMCP 주석 적용 등을 검사했습니다.
기하 치수와 단위중량을 독립 계산한 점검에서 설정 허용차를 넘은 전사 경고는 없었습니다. 이는 재질이나 공급 조건의 전문 검증을 의미하지 않습니다.
원본 PDF 4개와 기존 OCR JSON 4개의 SHA-256이 기존 기록과 동일함도 확인했습니다.
'''
    (OUT/'README_ko.md').write_text(readme,encoding='utf-8')
    summary=json.loads((OUT/'validation_summary.json').read_text())
    summary['data_tests_passed']=tests;summary['data_test_count']=len(tests)
    (OUT/'validation_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    scripts=OUT/'scripts';scripts.mkdir(exist_ok=True)
    for name in ['curated_tables.py','plate_ranges.py','build_csv.py','finalize_package.py']:shutil.copy2(ROOT/name,scripts/name)
    artifacts=[p for p in OUT.rglob('*') if p.is_file() and p.name!='checksums.json']
    hashes={str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}
    (OUT/'checksums.json').write_text(json.dumps(hashes,ensure_ascii=False,indent=2),encoding='utf-8')
    artifacts.append(OUT/'checksums.json')
    bundle=ROOT/'SharePoint_CatalogDimensions_CSV.zip'
    with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(artifacts):z.write(p,arcname=p.relative_to(OUT))
    with zipfile.ZipFile(bundle) as z:assert z.testzip() is None
    print('CHECKS_PASSED',len(tests),'EXACT_ROWS',len(exact),'RANGE_ROWS',len(ranges),'COLUMN_DEFINITIONS',len(schemas))
    print('BUNDLE',bundle,'BYTES',bundle.stat().st_size)
    print('MAIN_CSVS','CatalogExactDimensions.csv','CatalogSupplyRanges.csv')


if __name__=='__main__':main()
