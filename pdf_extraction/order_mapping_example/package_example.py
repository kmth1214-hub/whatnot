#!/usr/bin/env python3

import os
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import fitz
from jsonschema import Draft7Validator

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'deliverables'


def save(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    data=json.loads((OUT/'order_demo_input.json').read_text(encoding='utf-8'))
    result=json.loads((OUT/'order_demo_result.json').read_text(encoding='utf-8'))
    item=data['items'][0]
    runtime={
        'purchase_order':'DEMO001','reference_set_id':result['reference_set_id'],
        'requested_specification':{k:item[k] for k in ['product_family','standard','grade','coating_designation',
            'thickness_mm','width_mm','thickness_tolerance','coil_inner_diameter_mm','coil_weight','surface']},
        'hyundai_proposal':{'product_family':'GI','grade':None,'coating_designation':None,'thickness_mm':0.85,'width_mm':1219},
        'dimension_check':'conditional_match_in_two_catalog_grade_groups',
        'status':'needs_confirmation','auto_replace':False,
        'unresolved':['grade_equivalence','coating_designation_and_test_basis','coated_or_base_thickness_and_tolerance',
                      'width_tolerance','coil_inner_diameter_and_weight_capability','chromate_non_skin_pass_and_leveling_capability',
                      'applicable_standard_edition','shipment_month_conflict'],
        'commercial_values':{'quantity_t':60,'unit_price_usd_per_t':1000,'total_usd':60000,'action':'preserve'}
    }
    save('pa_runtime_payload.json',runtime)
    number={'type':'number'}
    nullable_string={'type':['string','null']}
    schema={
        'type':'object','required':['purchase_order','reference_set_id','requested_specification','hyundai_proposal','status','auto_replace','unresolved'],
        'properties':{
            'purchase_order':{'type':'string'},'reference_set_id':{'type':'string'},
            'requested_specification':{'type':'object','required':['product_family','standard','grade','coating_designation','thickness_mm','width_mm'],
                'properties':{'product_family':{'type':'string'},'standard':{'type':'string'},'grade':{'type':'string'},
                              'coating_designation':{'type':'string'},'thickness_mm':number,'width_mm':number,
                              'thickness_tolerance':{'type':'object'},'coil_inner_diameter_mm':number,'coil_weight':{'type':'object'},'surface':{'type':'object'}}},
            'hyundai_proposal':{'type':'object','required':['product_family','grade','coating_designation','thickness_mm','width_mm'],
                'properties':{'product_family':{'type':'string'},'grade':nullable_string,'coating_designation':nullable_string,
                              'thickness_mm':number,'width_mm':number}},
            'dimension_check':{'type':'string'},'status':{'type':'string'},'auto_replace':{'type':'boolean'},
            'unresolved':{'type':'array','items':{'type':'string'}},'commercial_values':{'type':'object'}}}
    Draft7Validator.check_schema(schema);Draft7Validator(schema).validate(runtime)
    save('PA_Parse_JSON_schema.json',schema)
    report='''# 발주서 DEMO001 — 현대제철 대응 예시

업로드한 1페이지 발주서의 19개 항목을 확인하고, 현대제철 카탈로그의 GI 관련 표·공급 범위와 대조했습니다.
원본 발주서와 기존 카탈로그 OCR JSON은 수정하지 않았습니다. PA 흐름을 실제로 연결하거나 배포하지 않았습니다.

## 페이지 정보는 PA 실행용에 없어도 됩니다

`pa_runtime_payload.json`은 PA에서 사용할 작은 결과 데이터입니다. 페이지·좌표가 없습니다.
`order_demo_input.json`, `hyundai_lookup_rules.json`, `order_demo_result.json`에도 페이지·좌표를 넣지 않았습니다.
추출값을 다시 확인할 때 쓸 원본 파일명·해시·페이지·좌표는 `audit_evidence.json`에 별도로 보관했습니다.
PA는 품목·규격·치수·단위·대응값과 상태를 비교하면 됩니다. 원본 PDF를 매번 읽을 필요는 없습니다.

## 주요 결과

| 항목 | 발주서 요구 | 처리 결과 |
|---|---|---|
| 제품 | 아연도금 강판 코일 | 현대제철 제품군 GI로 분류 |
| 적용 규격 | ASTM A653 / A653/653M | ASTM A653/A653M로 표기 정리. 적용 판본은 미기재 |
| 강종 | SS37 | 확인한 GI 표에서 명시적 대응 강종을 찾지 못해 미확정 |
| 도금 | G-60 | G60로 표기 정리. 현대제철 도금 코드 미확정 |
| 게이지 | C-20 | 원문 유지. 별도 게이지표로 0.85mm를 바꾸지 않음 |
| 두께 | 0.85mm | 요청값 유지. 일부 GI 공급 차트 범위와 조건부 일치 |
| 폭 | 1219mm | 요청값 유지. 폭 공차는 미기재 |
| 두께 공차 | 최소 두께, 상향 +.005인치 이하 | +0.127mm로 정확히 환산. 해석상 0.85~0.977mm |
| 코일 내경 | 508mm | 20인치와 같은 길이. 해당 내경 공급 능력은 미확인 |
| 코일 중량 | 4~5TON, 최대 5TON | 4,000~5,000kg. 공급 능력은 미확인 |
| 표면 처리 | CROMATED (CR6+) | 요구 그대로 구조화. 현대제철 대응 공정은 미확인 |
| 스킨패스 | NON SKIN PASSED | false로 구조화. 대응 가능 여부는 미확인 |
| 레벨링 | TENSION LEVELED | true로 구조화. 대응 가능 여부는 미확인 |
| 수량 | 60TON | USD/Mt 표기를 근거로 미터톤 해석. 60,000kg |
| 단가 | USD 1,120/톤 | 원문 유지. 현대제철 견적 미제공 |
| 총액 | USD 67,200 | 60 × 1,120 = 67,200 검산 완료 |
| 인도 조건 | CIF LO Example Port, Example Country | 원문 조건 유지 |
| 결제 | O/A 120 DAYS FROM BL | 본문과 하단의 추가 결제 문구를 모두 보존 |
| 선적월 | 본문 2025년 2·3월 / 파일명 3·4월 | 불일치로 기록하고 미확정 처리 |

## 치수 범위 판정의 의미

확인한 차트 중 다음 두 부분 범위에 0.85 × 1219mm가 들어갑니다.
이 예시는 차트의 일부 내부 구간만 정리했으며 전체 공급표를 수치화한 것은 아닙니다.

- 순천공장 GI, `S310~S570M` 그룹: 선택 구간 0.8 ≤ 두께 < 2.3mm, 1040 < 폭 ≤ 1250mm.
- 당진 1공장 #2 CGL GI, `S330~S440` 그룹: 선택 구간 0.35 ≤ 두께 < 1.3mm, 775 ≤ 폭 < 1275mm.

두 구간에는 두께 허용범위 0.85~0.977mm도 들어갑니다. 폭은 명목값만 비교했습니다.
SS37이 이 카탈로그 그룹과 동등하다는 근거는 확보하지 않았습니다. 따라서 전체 제품의 공급 가능 확정으로 해석하면 안 됩니다.
`SS37 → SGCC`, `SS37 → SGC400`, `SS37 → S370` 같은 치환은 적용하지 않았습니다.

## G60 환산과 도금 등급은 구분합니다

적용 ASTM의 G60 요구를 양면합계 0.60 oz/ft²로 해석한다는 가정에서는, 질량/면적 단위 환산값이 약 183.091 g/m²입니다.
계산식은 `0.60 × 28.349523125 / 0.3048²`입니다. 이 단위 환산값을 현대제철 도금 코드나 규격상의 명목 등급과 같다고 확정하지 않았습니다.
적용 표준 원문과 도금 시험 조건을 검증하지 못했기 때문에 자동 판정에는 사용하지 않습니다.
카탈로그의 양면합계 도금량 측정 표에 200 g/m² 등이 있다고 해서 G60을 200이나 Z180으로 바꾸지 않았습니다.
강종별 적용 여부, 3점 평균/1점 최소값, 발주 요구 조건을 확인해 수용된 대응 규칙으로 등록해야 합니다.

## 실행 결과와 파일

최종 상태는 `needs_confirmation`, `auto_replace`는 false입니다.
제품군 분류와 단위 정리는 수행했지만, 강종·도금·공정 조건의 대응 근거가 없어 완성된 현대제철 주문 사양으로 자동 치환하지 않았습니다.
미확정은 공급 불가능을 뜻하지 않습니다. 현재 근거만으로 확정할 수 없다는 뜻입니다.
수량·가격·금액·인도·결제 조건은 고객 주문 조건으로 보존했습니다.

- `pa_runtime_payload.json`: 페이지 없는 PA 실행용 요약 JSON.
- `PA_Parse_JSON_schema.json`: 위 파일을 PA Parse JSON 작업에서 읽을 기본 스키마.
- `order_demo_input.json`: 발주서의 구조화된 입력값.
- `hyundai_lookup_rules.json`: 시각적으로 확인한 GI 기준 일부. 미확인 강종·도금 대응표는 비워 두었습니다.
- `order_demo_result.json`: 19개 항목의 상세 대조와 판단 사유.
- `order_demo_comparison.csv`: Excel에서 열 수 있는 UTF-8 BOM 대조표.
- `audit_evidence.json`: 별도 출처와 검토 기록.
- `validation_results.json`: 실제 실행한 9개 계산·경계·오류 방지 검사 결과.
- `pa_flow_spec.md`: PA 연결 방법 설계. 실제 배포 결과가 아닙니다.
- `catalog_reference_extracts.pdf`: 확인에 사용한 카탈로그 원본 페이지 발췌.
- `scripts/`: 이번 예시 생성 코드. 이 발주서 전용 파서이며 범용 운영 시스템은 아닙니다.
'''
    (OUT/'README_ko.md').write_text(report,encoding='utf-8')
    flow='''# PA 연결 설계 예시

Power Automate를 가정한 설계이며, 이 세션에서 실제 흐름을 생성·연결·배포하지 않았습니다.

1. 기존 업무의 파일 도착 이벤트로 PDF를 받습니다.
2. 텍스트 PDF는 텍스트 추출을 사용하고, 스캔본은 OCR 경로로 분기합니다. 이번 PO는 텍스트 추출이 가능합니다.
3. 추출 서비스에서 `order_demo_input.json` 같은 필드 구조로 정규화합니다.
4. 확정된 기준표를 JSON, SharePoint 목록, Dataverse 또는 SQL 등 업무에 맞는 저장소에서 조회합니다.
5. 제품군·표준·강종·도금·공정·치수 범위가 맞는지 평가합니다. 치수만 맞는 결과는 conditional_match로 둡니다.
6. 결과 서비스가 `pa_runtime_payload.json` 형식의 출력을 반환합니다.
7. PA의 Parse JSON 작업에 `PA_Parse_JSON_schema.json`을 사용합니다.
8. 다음 조건을 평가해 처리 경로를 나눕니다.

```
@and(
  equals(body('Parse_JSON')?['auto_replace'], true),
  equals(length(body('Parse_JSON')?['unresolved']), 0),
  not(empty(body('Parse_JSON')?['hyundai_proposal']?['grade'])),
  not(empty(body('Parse_JSON')?['hyundai_proposal']?['coating_designation']))
)
```

이 예시에서는 auto_replace=false이므로 확인 필요 목록에 기록하는 경로로 갑니다.
제품군과 단위 정리 결과는 사용할 수 있고, 미확정 강종·도금은 null로 유지합니다.
향후 수용된 대응표가 추가되고 필수 조건이 모두 확인되면, 그 정책에 따라 자동 치환 여부를 평가하도록 구현할 수 있습니다.
원래 발주값과 최종 적용값을 별도 필드로 저장합니다.

페이지 정보는 PA 실행 페이로드에 없습니다. 조회 규칙의 버전과 rule_id를 통해 필요할 때만 별도 검토 기록을 찾습니다.
현재 JSON의 일부 규칙은 예시용으로 확인한 구간입니다. 운영에서는 필요한 제품군의 확정 기준표를 정리하고,
이번 발주서에 맞춘 텍스트 파서도 여러 문서 형식에 맞는 추출기로 대체해야 합니다.
'''
    (OUT/'pa_flow_spec.md').write_text(flow,encoding='utf-8')
    scripts=OUT/'scripts';scripts.mkdir(exist_ok=True)
    for name in ['build_mapping_example.py','package_example.py']:shutil.copy2(ROOT/name,scripts/name)
    catalog=next(Path(os.environ.get('WHATNOT_INPUT_DIR', 'private/inputs')).rglob('*pt1(*PART 1.pdf'))
    with fitz.open(catalog) as original:
        with fitz.open() as excerpt:
            for n in [62,68,69,70,71,90,104,105]:excerpt.insert_pdf(original,from_page=n-1,to_page=n-1)
            excerpt.save(OUT/'catalog_reference_extracts.pdf')
    po=next(Path(os.environ.get('WHATNOT_INPUT_DIR', 'private/inputs')).rglob('*DEMO001*FINAL.pdf'))
    audit=json.loads((OUT/'audit_evidence.json').read_text(encoding='utf-8'))
    assert hashlib.sha256(po.read_bytes()).hexdigest()==audit['documents']['order_demo']['sha256']
    assert hashlib.sha256(catalog.read_bytes()).hexdigest()==audit['documents']['hyundai_pt1_part1']['sha256']
    artifacts=[p for p in OUT.rglob('*') if p.is_file() and p.name!='checksums.json']
    checksums={str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}
    save('checksums.json',checksums);artifacts.append(OUT/'checksums.json')
    bundle=ROOT/'order_demo_hyundai_mapping_example.zip'
    with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(artifacts):z.write(p,arcname=p.relative_to(OUT))
    with zipfile.ZipFile(bundle) as z:assert z.testzip() is None
    print('PARSE_JSON_SCHEMA_VALID; ORIGINAL_FILES_UNCHANGED; ZIP_VALID')
    print('BUNDLE',bundle,'BYTES',bundle.stat().st_size)
    print('RUNTIME_JSON_BYTES',(OUT/'pa_runtime_payload.json').stat().st_size)


if __name__=='__main__':main()
