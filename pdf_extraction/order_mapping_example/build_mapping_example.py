#!/usr/bin/env python3
"""Worked example for PO DEMO001; not a general PDF parser or deployed PA flow.

Runtime payloads intentionally contain no page numbers or PDF coordinates.
Evidence is kept in audit_evidence.json. No original document is edited.
"""

import os
from decimal import Decimal as D
import copy
import csv
import hashlib
import json
from pathlib import Path
import re
import zipfile

import fitz

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'deliverables'
OUT.mkdir(exist_ok=True)


def save(name,data):
    (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def number(x):
    value=D(str(x));return int(value) if value==value.to_integral_value() else float(value)


def contains(value,bounds):
    v=D(str(value));low=D(str(bounds['lower']));high=D(str(bounds['upper']))
    return (v>=low if bounds['lower_inclusive'] else v>low) and (v<=high if bounds['upper_inclusive'] else v<high)


def evaluate_dimensions(item,rules):
    result=[]
    t=D(str(item['thickness_mm']));w=D(str(item['width_mm']))
    upper=t+D(str(item['thickness_tolerance']['plus_mm']))
    lower=t-D(str(item['thickness_tolerance']['minus_mm']))
    for rule in rules['dimension_windows']:
        if item['product_family']!=rule['product_family']:continue
        nominal=contains(t,rule['thickness_mm']) and contains(w,rule['width_mm'])
        span=contains(lower,rule['thickness_mm']) and contains(upper,rule['thickness_mm']) and contains(w,rule['width_mm'])
        if nominal:
            result.append({'rule_id':rule['rule_id'],'plant':rule['plant'],'catalog_grade_group':rule['catalog_grade_group'],
                           'nominal_dimension_in_selected_window':True,'po_thickness_span_in_selected_window':span,
                           'source_grade_matches_catalog_group':None,'width_tolerance_checked':False,
                           'status':'conditional_dimension_match',
                           'note':'A geometric match under this catalog grade group; grade equivalence, thickness basis and supplier acceptance are not established.'})
    return result


def final_decision(grade_target,coating_target,dimensions,capabilities):
    complete=bool(grade_target and coating_target and dimensions and all(capabilities.values()))
    return {'status':'ready_for_review' if complete else 'needs_confirmation',
            'auto_replace':False,
            'note':'This example produces a proposal only. Procurement spec changes require a separately defined accepted mapping.'}


def main():
    po=next(Path(os.environ.get('WHATNOT_INPUT_DIR', 'private/inputs')).rglob('*DEMO001*FINAL.pdf'))
    catalog=next(Path(os.environ.get('WHATNOT_INPUT_DIR', 'private/inputs')).rglob('*pt1(*PART 1.pdf'))
    with fitz.open(po) as pdf:
        assert len(pdf)==1
        page=pdf[0];text=page.get_text(sort=True)
        def evidence(needle):
            hits=page.search_for(needle)
            return {'document_id':'order_demo','pdf_page_1based':1,'text':needle,
                    'bbox_pt':[[round(v,3) for v in b] for b in hits]}
        m=re.search(r'C-20\s*\(\s*(\.\d+|\d+(?:\.\d+)?)\s*mm\s*X\s*(\d+(?:\.\d+)?)\s*mm\s*\)',text)
        assert m
        thickness=D(m[1]);width=D(m[2])
        assert thickness==D('.85') and width==D('1219')
        assert 'GRADE SS37' in text and 'ASTM A653 G-60' in text
        assert 'NON SKIN PASSED' in text and 'TENSION LEVELED' in text and '(CR6+)' in text
        assert '4 A 5 TON.' in text and 'COIL WEIGHT MAX 5 TONS' in text
        assert '60.00' in text and '1,000.00' in text and '60,000.00' in text
        assert '+.005"' in text and 'FEBRERO/MARZO-2025' in text
        po_evidence={
            'product':evidence('LAMINA GALVANIZADA'), 'dimensions':evidence('.85 mm X 1219 mm'),
            'standard_and_coating':evidence('ASTM A653 G-60'), 'grade':evidence('GRADE SS37'),
            'standard_expanded':evidence('ASTM A653/653M'), 'surface':evidence('CROMATED (CR6+) NON SKIN PASSED , TENSION LEVELED'),
            'coil_id':evidence('COIL ID 508 MM'), 'coil_max':evidence('COIL WEIGHT MAX 5 TONS'),
            'coil_weight':evidence('PESOS DE ROLLOS DE 4 A 5 TON.'), 'thickness_tolerance':evidence('+.005"'),
            'quantity':evidence('60.00'),'price':evidence('1,000.00'),'total':evidence('60,000.00'),
            'shipping':evidence('FEBRERO/MARZO-2025'), 'payment':evidence('O/A 120 DAYS FROM BL'),
            'delivery':evidence('CIF LO EXAMPLE PORT PORT, EXAMPLE COUNTRY'), 'metric_ton_context':evidence('USD/Mt')}
    plus_mm=D('.005')*D('25.4')
    item={
        'product_family':'GI','product_name':'용융아연도금 강판 코일',
        'source_product_text':'LAMINA GALVANIZADA EN ROLLO / PRIME GALVANISED STEEL SHEET IN COILS',
        'standard':'ASTM A653/A653M','standard_edition':None,
        'source_standard_text':['ASTM A653','ASTM A653/653M'],
        'grade':'SS37','coating_designation':'G60','source_coating_text':'G-60','source_gauge_text':'C-20',
        'thickness_mm':number(thickness),'width_mm':number(width),'thickness_measurement_basis':None,
        'thickness_tolerance':{'minus_mm':0,'plus_mm':number(plus_mm),'minimum_mm':number(thickness),
                               'maximum_mm':number(thickness+plus_mm),'source_plus_inch':0.005,
                               'interpretation':'PO states minimum thickness and upward variation no more than +.005 inch'},
        'width_tolerance_mm':None,'coil_inner_diameter_mm':508,
        'coil_weight':{'min_t':4,'max_t':5,'min_kg':4000,'max_kg':5000},
        'surface':{'chromated':True,'chromium_valence':6,'skin_passed':False,'tension_leveled':True},
        'quantity':{'value':60,'unit':'t','kg':60000,'unit_basis':'PO delivery note says USD/Mt; metric-ton interpretation'},
        'unit_price':{'value':1000,'currency':'USD','per_unit':'t'},'total':{'value':60000,'currency':'USD'},
        'delivery':{'incoterm':'CIF','additional_term_raw':'LO','port':'Example Port','country':'Example Country'},
        'payment':{'headline_text':'O/A 120 DAYS FROM BL','days_from_bill_of_lading':120,
                   'additional_text':'100% O/A OR T/T O BALANCE 120 DESPUES DE LA FECHA DEL B/L'},
        'shipping':{'document_months':['2025-02','2025-03'],'filename_months':['2025-03','2025-04'],'status':'conflict_needs_confirmation'}
    }
    input_data={'schema_version':'1.0.0','purchase_order':'DEMO001','order_date':'2025-01-01','items':[item]}
    rules={
        'schema_version':'1.0.0','reference_set_id':'hyundai_catalog_250116_reviewed_subset',
        'scope':'Verified source excerpts for one worked example; incomplete coverage of the 464-page catalog.',
        'product_mappings':[{'rule_id':'product_gi','source_product_family':'galvanized_steel_sheet_in_coils','hyundai_product_family':'GI'}],
        'accepted_grade_mappings':[], 'accepted_coating_mappings':[],
        'published_gi_grade_list':{'rule_id':'gi_grade_list','JIS':['SGCC','SGCD','SGC340','SGC400','SGC440','SGC490','SGC570'],
                                   'KS':['SGCC','SGCD','SGC245Y','SGC295Y','SGC335Y','SGC365Y','SGC560Y'],
                                   'ASTM_in_reviewed_GI_table':['CS TYPE A','CS TYPE B','CS TYPE C','DDS TYPE A','DDS TYPE C'],
                                   'cross_standard_equivalence_confirmed':False},
        'coating_measurement_reference':{'rule_id':'gi_coating_measurements','unit':'g/m²','basis':'both_sides_total',
                                        'three_spot_average_to_single_spot_minimum':[
                                            {'three_spot_average':100,'single_spot_minimum':85},
                                            {'three_spot_average':140,'single_spot_minimum':120},
                                            {'three_spot_average':200,'single_spot_minimum':170},
                                            {'three_spot_average':225,'single_spot_minimum':195},
                                            {'three_spot_average':275,'single_spot_minimum':235},
                                            {'three_spot_average':350,'single_spot_minimum':300},
                                            {'three_spot_average':450,'single_spot_minimum':385},
                                            {'three_spot_average':600,'single_spot_minimum':510}],
                                        'note':'This is a measurement table, not proof each coating is available for ASTM SS37. No G60 mapping is accepted.'},
        'dimension_windows':[
            {'rule_id':'gi_suncheon_s310_s570m_selected_band','product_family':'GI','plant':'순천공장',
             'catalog_grade_group':'S310~S570M','thickness_mm':{'lower':0.8,'lower_inclusive':True,'upper':2.3,'upper_inclusive':False},
             'width_mm':{'lower':1040,'lower_inclusive':False,'upper':1250,'upper_inclusive':True},
             'source_color':'blue','legend_grey_means':'Please consult us in advance',
             'note':'Selected interior blue band only; not a full digitization of the chart. This does not map SS37 to this grade group.'},
            {'rule_id':'gi_dangjin_cgl2_s330_s440_selected_band','product_family':'GI','plant':'당진 1공장 #2 CGL',
             'catalog_grade_group':'S330~S440','thickness_mm':{'lower':0.35,'lower_inclusive':True,'upper':1.3,'upper_inclusive':False},
             'width_mm':{'lower':775,'lower_inclusive':True,'upper':1275,'upper_inclusive':False},
             'source_color':'blue','legend_grey_means':'Not Available',
             'note':'Selected interior blue band only; not a full digitization of the chart. This does not map SS37 to this grade group.'}
        ]}
    dimensions=evaluate_dimensions(item,rules)
    assert len(dimensions)==2 and all(x['po_thickness_span_in_selected_window'] for x in dimensions)
    g60_conversion=D('.60')*D('28.349523125')/(D('.3048')**2)
    fields=[]
    def field(key,raw,normalized,status,target,reason,rule_ids=None):
        fields.append({'field':key,'source_value':raw,'normalized_value':normalized,
                       'status':status,'hyundai_value':target,'reason':reason,'rule_ids':rule_ids or []})
    field('product','PRIME GALVANISED STEEL SHEET IN COILS','용융아연도금 강판 코일','catalog_product_family_match','GI','GI product family is present in the catalog; exact grade/coating acceptance remains open.',['product_gi'])
    field('standard','ASTM A653 / ASTM A653/653M','ASTM A653/A653M','preserve_source_standard',None,'The catalog GI tables mention ASTM 653M; the SS37 grade and applicable edition are not established.',['gi_grade_list'])
    field('grade','GRADE SS37','SS37','needs_confirmation',None,'No explicit SS37-to-Hyundai equivalence was found in the reviewed GI tables. No JIS, KS or internal grade is selected.',['gi_grade_list'])
    field('coating','G-60','G60','needs_confirmation',None,'Preserve G60. Coating mass conversion alone does not establish a Hyundai coating designation or an accepted test basis.',['gi_coating_measurements'])
    field('gauge','C-20','C-20','preserve_source_label',None,'Gauge label is retained; the PO explicitly specifies 0.85 mm, so no gauge-table substitution is performed.')
    field('thickness','.85 mm',0.85,'conditional_dimension_match',0.85,'Preserve the ordered thickness; two selected GI chart windows contain it, conditional on grade and thickness basis.',['gi_suncheon_s310_s570m_selected_band','gi_dangjin_cgl2_s330_s440_selected_band'])
    field('width','1219 mm',1219,'conditional_dimension_match',1219,'Preserve the ordered width; nominal-width fit only. Width tolerance is not specified.',['gi_suncheon_s310_s570m_selected_band','gi_dangjin_cgl2_s330_s440_selected_band'])
    field('thickness_tolerance','minimum thickness; +.005 inch',{'minus_mm':0,'plus_mm':0.127,'minimum_mm':0.85,'maximum_mm':0.977},'unit_normalization_only',None,'Exact unit conversion: 0.005 × 25.4 = 0.127 mm. Supplier acceptance and coated/base thickness basis need confirmation.')
    field('coil_inner_diameter','508 MM',{'mm':508,'inch':20},'unit_normalization_only',None,'Exact unit conversion; this example has no catalog-backed coil-inner-diameter capability match.')
    field('coil_weight','4 A 5 TON; MAX 5 TONS',{'min_kg':4000,'max_kg':5000},'needs_confirmation',None,'The PO weight notes agree. The selected catalog excerpts do not establish the supplier coil-weight capability.')
    field('chromate','CROMATED (CR6+)',{'chromated':True,'chromium_valence':6},'needs_confirmation',None,'Preserve the requested treatment; no matching Hyundai process capability has been established.')
    field('skin_pass','NON SKIN PASSED',False,'needs_confirmation',None,'Preserve the requested process condition; no matching Hyundai capability has been established.')
    field('tension_leveling','TENSION LEVELED',True,'needs_confirmation',None,'Preserve the requested process condition; no matching Hyundai capability has been established.')
    field('quantity','60.00 TON',{'t':60,'kg':60000},'preserve_commercial_value',None,'Metric-ton interpretation follows the PO USD/Mt note. Quantity is an order requirement, not a manufacturer replacement value.')
    field('unit_price','USD 1,000.00',{'USD_per_t':1000},'preserve_commercial_value',None,'No Hyundai quotation was provided, so no replacement price is inferred.')
    field('total','USD 60,000.00',{'USD':60000},'preserve_commercial_value',None,'60 × 1000 = 60000; arithmetic verified.')
    field('delivery','CIF LO EXAMPLE PORT PORT, EXAMPLE COUNTRY',item['delivery'],'preserve_commercial_value',None,'Delivery terms are retained as PO terms.')
    field('payment','O/A 120 DAYS FROM BL',item['payment'],'preserve_commercial_value',None,'Headline and additional printed terms are both retained; no replacement financing term is inferred.')
    field('shipment_months','document February/March 2025; filename March/April 2025',item['shipping'],'conflict_needs_confirmation',None,'Document contents and filename disagree; neither is silently overwritten.')
    capabilities={k:None for k in ['grade_equivalence','coating_acceptance','thickness_basis_and_tolerance','width_tolerance','coil_inner_diameter','coil_weight','surface_chromate','non_skin_pass','tension_leveling','standard_edition']}
    decision=final_decision(None,None,dimensions,capabilities)
    result={'schema_version':'1.0.0','purchase_order':'DEMO001','reference_set_id':rules['reference_set_id'],
            'decision':decision,'proposed_hyundai_values':{'product_family':'GI','standard':'ASTM A653/A653M',
                'grade':None,'coating_designation':None,'thickness_mm':0.85,'width_mm':1219,
                'note':'Proposal retains ordered numeric dimensions; grade/coating and supply capability are not confirmed.'},
            'fields':fields,'conditional_dimension_matches':dimensions,
            'coating_unit_conversion_illustration':{'source_designation':'G60',
                'assumption_to_verify':'If the applicable ASTM G60 requirement is interpreted as 0.60 avoirdupois oz/ft² total both sides,',
                'calculation':'0.60 × 28.349523125 / 0.3048²','calculated_g_per_m2':number(g60_conversion),
                'status':'unverified_designation_interpretation_unit_conversion_only',
                'hyundai_designation':None,'used_for_automatic_matching':False,
                'note':'183.091... is a unit conversion, not an approved nominal coating-class substitution. No Z180 or 200 g/m² replacement is applied.'},
            'commercial_check':{'quantity_times_price_matches_total':D(60)*D(1000)==D(60000)},
            'capability_checks':capabilities,'document_modified':False,'power_automate_flow_deployed':False}
    # Tests focus on preventing incorrect matches and destructive substitutions.
    checks=[]
    assert plus_mm==D('.127') and thickness+plus_mm==D('.977');checks.append('exact_inch_to_mm_and_thickness_span')
    sun=rules['dimension_windows'][0];dang=rules['dimension_windows'][1]
    assert contains(1250,sun['width_mm']) and not contains(1040,sun['width_mm']);checks.append('suncheon_width_boundary_operators')
    assert contains(.35,dang['thickness_mm']) and not contains(1.3,dang['thickness_mm']);checks.append('dangjin_thickness_boundary_operators')
    wrong=copy.deepcopy(item);wrong['product_family']='CR';assert not evaluate_dimensions(wrong,rules);checks.append('CR_does_not_match_GI_rules')
    wide=copy.deepcopy(item);wide['width_mm']=1400;assert not evaluate_dimensions(wide,rules);checks.append('out_of_selected_window_not_accepted')
    edge=copy.deepcopy(item);edge['thickness_mm']=2.25
    edge_results=evaluate_dimensions(edge,rules)
    assert edge_results and not edge_results[0]['po_thickness_span_in_selected_window'];checks.append('nominal_fit_is_not_tolerance_span_fit')
    assert decision['status']=='needs_confirmation' and not decision['auto_replace'];checks.append('unknown_grade_and_coating_block_complete_match')
    assert result['proposed_hyundai_values']['grade'] is None and result['proposed_hyundai_values']['coating_designation'] is None;checks.append('no_fabricated_grade_or_coating')
    assert result['commercial_check']['quantity_times_price_matches_total'];checks.append('PO_amount_arithmetic')
    save('order_demo_input.json',input_data);save('hyundai_lookup_rules.json',rules);save('order_demo_result.json',result)
    save('validation_results.json',{'passed':checks,'count':len(checks),'source_PDF_unchanged':True})
    audit={
        'scope':'Separate provenance. The runtime input, lookup rules and result contain no page numbers or PDF coordinates.',
        'documents':{'order_demo':{'filename':po.name,'sha256':hashlib.sha256(po.read_bytes()).hexdigest()},
                     'hyundai_pt1_part1':{'filename':catalog.name,'sha256':hashlib.sha256(catalog.read_bytes()).hexdigest()}},
        'purchase_order_evidence':po_evidence,
        'rule_evidence':{
            'product_gi':{'document_id':'hyundai_pt1_part1','pdf_page_1based':62,'printed_page':'60','bbox_pt':[36,380,420,560]},
            'gi_grade_list':{'document_id':'hyundai_pt1_part1','pdf_pages_1based':[62,68,69,70,71],'printed_pages':['60','66','67','68','69'],
                             'note':'Visual review of GI listing and mechanical/chemical tables; no explicit ASTM SS37 equivalence confirmed.'},
            'gi_coating_measurements':{'document_id':'hyundai_pt1_part1','pdf_page_1based':71,'printed_page':'69','bbox_pt':[253,110,400,352]},
            'gi_suncheon_s310_s570m_selected_band':{'document_id':'hyundai_pt1_part1','pdf_page_1based':90,'printed_page':'88','bbox_pt':[36,480,400,605]},
            'gi_dangjin_cgl2_s330_s440_selected_band':{'document_id':'hyundai_pt1_part1','pdf_page_1based':105,'printed_page':'103','plant_header_reference_pdf_page_1based':104,'bbox_pt':[70,140,420,340]}
        },
        'additional_review':[
            {'kind':'reference_edition','note':'PO is dated March 2025; reference catalog filename is dated January 2025. Applicable ASTM edition and contemporaneous supply capability are unconfirmed.'},
            {'kind':'external_standard_reference','url':'https://www.galvinfo.com/wp-content/uploads/sites/8/2017/05/GalvInfoNote_1_1.pdf',
             'retrieval_result':'HTTP 403; document not read or used as verified evidence. G60 interpretation remains explicitly conditional.'}
        ]}
    save('audit_evidence.json',audit)
    # Runtime files should not force Power Automate to handle provenance.
    for name in ['order_demo_input.json','hyundai_lookup_rules.json','order_demo_result.json']:
        obj=json.loads((OUT/name).read_text(encoding='utf-8'))
        def check_keys(value):
            if isinstance(value,dict):
                for k,v in value.items():
                    assert not ('page' in k.lower() or 'bbox' in k.lower()),(name,k)
                    check_keys(v)
            elif isinstance(value,list):
                for v in value:check_keys(v)
        check_keys(obj)
    with (OUT/'order_demo_comparison.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['항목','발주서 값','정규화 값','현대제철 대응값','상태','판단 근거'])
        for row in fields:writer.writerow([row['field'],json.dumps(row['source_value'],ensure_ascii=False),json.dumps(row['normalized_value'],ensure_ascii=False),json.dumps(row['hyundai_value'],ensure_ascii=False),row['status'],row['reason']])
    print('SOURCE_PARSED',po.name)
    print('FIELDS_EVALUATED',len(fields),'CONDITIONAL_DIMENSION_MATCHES',len(dimensions))
    print('DECISION',decision['status'],'AUTO_REPLACE',decision['auto_replace'])
    print('CHECKS_PASSED',len(checks),'RUNTIME_PAYLOADS_HAVE_NO_PAGE_OR_BBOX_KEYS')


if __name__=='__main__':main()
