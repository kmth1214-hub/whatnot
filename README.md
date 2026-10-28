# whatnot

PDF 카탈로그의 OCR 참조 데이터와 SharePoint 입력용 치수 기준표를 준비하는 Python 도구 모음입니다.
현재 대화에서 작성한 오프라인 처리 코드와 Power Automate 연계 설계 문서를 보관합니다.
실제 OCR HTTP API, Power Automate 흐름, SharePoint 사이트는 이 저장소에서 배포하지 않았습니다.

## 소스 구성

```text
pdf_extraction/
  extract_catalogs.py                  # 한국어/영어 OCR, 단어 좌표, 표 격자, 색상 추출
  enrich_reference.py                  # 숫자·공차 후보와 소수점 누락 검토 정보
  finalize_deliverables.py             # JSON 조립, 출처 및 검토 자료 생성
  package_results.py                   # JSON 스키마 검사와 결과 패키징
  catalog_dimension_csv/
    curated_tables.py                 # 카탈로그와 대조한 치수·중량 전사 자료
    plate_ranges.py                   # 후판 TMCP 공급 범위 전사 자료
    build_csv.py                      # SharePoint 입력용 CSV/Excel 생성
    finalize_package.py               # 데이터 검증과 결과 패키징
  order_mapping_example/
    build_mapping_example.py           # 익명화된 발주서 대응 예시
    package_example.py                 # PA 입력 예시와 관련 문서 생성
  sharepoint_example/
    create_examples.py                # SharePoint 목록 구성 예시
docs/architecture/
  department_excel_automation.mmd      # Mermaid 아키텍처 원본
  department_excel_automation.dot      # Graphviz 아키텍처 원본
```

## 의존성

이 작업 환경에서 사용한 Python 3.12와 패키지 버전을 `requirements.txt`에 기록했습니다.
Tesseract는 별도 시스템 의존성이며, 처리 당시에는 Tesseract 5.5.0을 사용했습니다.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

Debian/Ubuntu 계열에서는 Tesseract와 언어 데이터를 다음 패키지로 설치할 수 있습니다.

```bash
sudo apt-get install tesseract-ocr tesseract-ocr-eng tesseract-ocr-kor
mkdir -p pdf_extraction/tools/tessdata
ln -s /usr/share/tesseract-ocr/5/tessdata/eng.traineddata pdf_extraction/tools/tessdata/eng.traineddata
ln -s /usr/share/tesseract-ocr/5/tessdata/kor.traineddata pdf_extraction/tools/tessdata/kor.traineddata
```

설치 경로가 다른 시스템에서는 해당 시스템의 언어 데이터 경로를 사용합니다.
모델 바이너리나 인증서·인증정보를 이 저장소에 복사해 커밋하지 않습니다.

## 비공개 입력 준비

프로젝트 루트에서 실행합니다. 원본 PDF는 기본적으로 `private/inputs/`에서 읽습니다.
입력 폴더를 바꾸려면 실행 환경에서 `WHATNOT_INPUT_DIR`을 지정할 수 있습니다.
고객 발주 추출 JSON은 `private/ocr_input.json`으로 준비하거나 `WHATNOT_OCR_INPUT`으로 경로를 지정합니다.
이 이름들은 입력 경로를 선택하는 옵션이며, 실제 환경변수 값이나 `.env` 파일은 저장하지 않습니다.

카탈로그 처리기는 `pt1(` / `pt2(`, `PART 1` / `PART 2`가 포함된 네 분할 PDF를 대상으로 작성했습니다.
문서 수·페이지 수·테이블 형식 등 해당 카탈로그의 전제가 코드에 포함되어 있으므로 다른 문서에는 조정이 필요합니다.
비공개 입력과 생성 결과는 `.gitignore`로 제외합니다.

## 카탈로그 처리 순서

```bash
python pdf_extraction/extract_catalogs.py --workers 4
python pdf_extraction/enrich_reference.py
python pdf_extraction/finalize_deliverables.py
python pdf_extraction/package_results.py
python pdf_extraction/catalog_dimension_csv/build_csv.py
python pdf_extraction/catalog_dimension_csv/finalize_package.py
```

치수 CSV 생성·검사 단계는 앞 단계의 OCR 결과, 원본 카탈로그와 비공개 OCR 입력 JSON을 사용합니다.
필요한 비공개 입력을 준비해야 전체 파이프라인을 실행할 수 있습니다.

`order_mapping_example`과 `sharepoint_example`은 데이터 형태와 처리 분기를 설명하는 예시입니다.
해당 예시의 발주 식별자·가격·선적 정보는 익명화·가상화했습니다.
예시 문서 검색 조건과 명시적 검증이 포함되어 있어 임의의 발주서를 그대로 처리하는 범용 추출기는 아닙니다.

## 데이터 해석

- OCR의 숫자·단위·표 연결은 별도 검토가 필요합니다.
- 치수 범위 일치는 재질·강종·도금 동등성이나 주문 전체의 공급 가능 승인을 의미하지 않습니다.
- 카탈로그 치수 데이터의 내부 참조키는 제조사 공식 품목번호가 아닙니다.
- 회사 대응 항목명·코드는 별도로 확정하며, 미확정 치환은 비활성 상태로 유지합니다.
- 일부 치수표 전사 자료와 검토 전용 OCR 후보를 구분합니다. 전체 카탈로그의 전문 검수본은 아닙니다.

원본 파일명·페이지·좌표는 별도 출처 기록에 두고, PA 실행용 JSON에는 필요한 업무값과 처리 상태를 전달하는 구조입니다.

## 카탈로그 기준표 다운로드

클라우드 아티팩트 다운로드가 실패하면 [다운로드 안내](downloads/README.md)에서 GitHub 파일을 받을 수 있습니다.
검사한 카탈로그 배포 파일만 `downloads/`에 두며, 비공개 발주 추출 결과는 포함하지 않습니다.

## 보존 및 공개 범위

기존 작업 폴더의 파일은 유지하고 소스의 복사본만 이 저장소에 모았습니다.
원본 PDF, 고객 발주 데이터, OCR 결과 JSON, CSV/Excel 생성물, 모델 파일, API 키, 계정 키와 환경변수 값은 포함하지 않았습니다.
카탈로그 기준표 다운로드를 위한 명시적 예외 파일은 `downloads/`에 별도로 관리합니다.
환경에 종속된 절대 입력 경로는 로컬 입력 경로 옵션으로 바꿨습니다.

자세한 소스 반입 범위는 [docs/SOURCE_IMPORT.md](docs/SOURCE_IMPORT.md)를 참고하세요.
