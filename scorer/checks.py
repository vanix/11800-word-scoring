import re
from .parser import DocxParser, classify_text, halfpt_to_pt, w, W

PASS = (0, '')

def _body_paras(student, ref=None):
    """Filter non-title, non-empty paragraphs."""
    s = [p for p in student.parse_paragraphs() if p['type'] == 'para' and p.get('text', '').strip() and '題組' not in p.get('text', '')]
    if ref is not None:
        r = [p for p in ref.parse_paragraphs() if p['type'] == 'para' and p.get('text', '').strip() and '題組' not in p.get('text', '')]
        return s, r
    return s

def _find_title(doc):
    for p in doc.parse_paragraphs():
        if p['type'] == 'para' and '題組' in p.get('text', ''):
            return p
    return None

def _find_image_para_idx(doc):
    body = doc.body
    if body is None:
        return None
    for i, child in enumerate(body):
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        if tag == 'p' and child.find(f'.//{w("drawing")}') is not None:
            return i
    return None

# ── ★ 直向列印 ─────────────────────────────────────
def check_orientation(student, ref, cfg):
    layout = student.parse_page_layout()
    w_ = int(layout.get('width', 0))
    h_ = int(layout.get('height', 0))
    expected = cfg.get('expected', 'portrait')
    if expected == 'portrait' and h_ > w_:
        return PASS
    if expected == 'landscape' and w_ > h_:
        return PASS
    return (50, f'方向非{expected}')

# ── ● A4 尺寸 ──────────────────────────────────────
def check_page_size(student, ref, cfg):
    layout = student.parse_page_layout()
    w_ = layout.get('width')
    h_ = layout.get('height')
    e = cfg['expected']
    if w_ == e['w'] and h_ == e['h']:
        return PASS
    return (10, f'尺寸{w_}x{h_}(應為{e["w"]}x{e["h"]})')

# ── ● 邊界 3cm ─────────────────────────────────────
def check_margins(student, ref, cfg):
    layout = student.parse_page_layout()
    e = cfg['expected']
    for k in ['top', 'bottom', 'left', 'right']:
        if layout.get(f'margin_{k}') != e[k]:
            return (10, f'{k}邊界{layout.get(f"margin_{k}")}(應為{e[k]})')
    return PASS

# ── ● 左右對齊 ─────────────────────────────────────
def check_justify(student, ref, cfg):
    bad = []
    for p in student.parse_paragraphs():
        if p['type'] != 'para':
            continue
        text = p.get('text', '').strip()
        if not text or '題組' in text:
            continue
        jc = p.get('pPr', {}).get('jc', '')
        if jc != 'both':
            bad.append(text[:15])
    if bad:
        return (10, f'{len(bad)}段非左右對齊')
    return PASS

# ── ● 頁首字型 ─────────────────────────────────────
def _hf_font_check(student, zone, cfg):
    hf = student.parse_header_footer()
    zone_cn = '頁首' if zone == 'header' else '頁尾'
    el = hf.get(zone)
    if not el:
        return (10, f'無{zone_cn}')
    style_rpr = (hf.get(zone + '_style') or {}).get('rPr') or {}
    expected_en = cfg.get('en_font', 'Times New Roman')
    allowed_cjk = cfg.get('cjk_fonts') or ['新細明體', '細明體']
    if 'size' in cfg:
        expected_half = int(cfg['size']) * 2
    else:
        expected_half = int(cfg.get('font_size', '20'))
    issues = []
    for t, rp in el['runs']:
        if not t.strip():
            continue
        cls = classify_text(t)
        ea = rp.get('font_eastAsia') or style_rpr.get('font_eastAsia')
        af = rp.get('font_ascii') or style_rpr.get('font_ascii')
        sz = rp.get('sz') or style_rpr.get('sz')
        if cls in ('chinese', 'mixed') and ea and ea not in allowed_cjk:
            issues.append(f'中文字型「{ea}」(應{"或".join(allowed_cjk)})')
        if cls in ('english', 'digit', 'mixed') and af and af != expected_en:
            issues.append(f'英數字型「{af}」(應{expected_en})')
        if sz and sz.isdigit() and int(sz) != expected_half:
            issues.append(f'大小{halfpt_to_pt(sz)}pt(應{cfg.get("size") or halfpt_to_pt(str(expected_half))}pt)')
    if issues:
        return (10, f'{zone_cn}字型: ' + '; '.join(dict.fromkeys(issues)))
    return PASS

def check_header_font(student, ref, cfg):
    return _hf_font_check(student, 'header', cfg)

def check_footer_font(student, ref, cfg):
    return _hf_font_check(student, 'footer', cfg)

# ── ● 頁首內容 ─────────────────────────────────────
def check_header_content(student, ref, cfg):
    hf = student.parse_header_footer()
    header = hf.get('header')
    if not header:
        return (10, '無頁首')
    text = header.get('text', '')
    sections = cfg.get('sections', [])
    for sec in sections:
        pos = sec.get('position', 'left')
        kind = sec.get('kind', 'text')
        if pos == 'left':
            if kind == 'date' and not re.search(r'\d', text.split('第')[0] if '第' in text else text):
                return (10, '頁首左側缺少日期')
            elif kind == 'id' and '證' not in text.split('第')[0] if '第' in text else text:
                pass  # Simplified check
    return PASS

# ── ● 頁碼 ──────────────────────────────────────────
def _has_page_number(hf):
    for zone in ('header', 'footer'):
        el = hf.get(zone)
        if el:
            text = el.get('text', '')
            if 'FIELD:PAGE' in text or '第' in text or 'Page' in text or 'page' in text:
                return True
    return False

def check_header_pagenum(student, ref, cfg):
    if ref is None:
        return (10, '無參考答案可比對')
    ref_hf = ref.parse_header_footer()
    stu_hf = student.parse_header_footer()
    for zone in ('header', 'footer'):
        if _ref_has_page_in_zone(ref_hf, zone):
            if not stu_hf.get(zone):
                return (10, f'缺少頁尾' if zone == 'footer' else '缺少頁首')
            stu_el = stu_hf.get(zone)
            stu_text = stu_el.get('text', '')
            if 'FIELD:PAGE' not in stu_text and '第' not in stu_text and 'Page' not in stu_text and 'page' not in stu_text:
                return (10, f'頁尾無頁碼' if zone == 'footer' else '頁首無頁碼')
    return PASS

def _ref_has_page_in_zone(hf, zone):
    el = hf.get(zone)
    if not el:
        return False
    text = el.get('text', '')
    return 'FIELD:PAGE' in text or '第' in text or 'Page' in text or 'page' in text

# ── ● 標題格式 ─────────────────────────────────────
def check_title_format(student, ref, cfg):
    s_title = _find_title(student)
    if not s_title:
        return (10, '找不到標題')
    issues = []
    runs = s_title.get('runs', [])
    expected_cjk = cfg.get('cjk', '細明體')
    expected_sz = cfg.get('size', '32')
    has_cjk = False
    has_sz = False
    for t, rp in runs:
        if not t.strip():
            continue
        cls = classify_text(t)
        eastasia = rp.get('font_eastAsia', '')
        if cls in ('chinese', 'mixed'):
            if not eastasia or eastasia in (expected_cjk, '新細明體', '標楷體'):
                has_cjk = True
        sz = rp.get('sz', '')
        if sz == expected_sz:
            has_sz = True
    if not has_cjk:
        issues.append(f'字型非{expected_cjk}')
    if not has_sz:
        issues.append(f'大小非{halfpt_to_pt(expected_sz)}pt')
    jc = s_title.get('pPr', {}).get('jc', '')
    if jc != 'center':
        issues.append('未置中')
    if cfg.get('border'):
        pBdr = s_title.get('pPr', {}).get('pBdr', {})
        has_bdr = bool(pBdr)
        if not has_bdr:
            for _, rp in runs:
                if rp.get('bdr'):
                    has_bdr = True
                    break
        if not has_bdr:
            issues.append('無框線')
    if cfg.get('italic'):
        has_i = any(rp.get('i') in ('true', '1') for _, rp in runs)
        if not has_i:
            issues.append('無斜體')
    if cfg.get('shading'):
        shd = s_title.get('pPr', {}).get('shd', {})
        has_shd = bool(shd.get('val'))
        if not has_shd:
            for _, rp in runs:
                rshd = rp.get('shd', {})
                if rshd.get('val'):
                    has_shd = True
                    break
        if not has_shd:
            issues.append('無網底')
    if issues:
        return (10, '; '.join(issues))
    return PASS

# ── ● 標題文字 ─────────────────────────────────────
def check_title_text(student, ref, cfg):
    s_title = _find_title(student)
    r_title = _find_title(ref)
    if not s_title:
        if r_title:
            r_text = r_title.get('text', '').strip()
            return (len(r_text) * 3, f'無標題(全文{r_text}共{len(r_text)}字)')
        return (999, '無標題')
    if not r_title:
        return PASS
    s_text = s_title.get('text', '').strip()
    r_text = r_title.get('text', '').strip()
    diff = sum(1 for a, b in zip(s_text, r_text) if a != b) + abs(len(s_text) - len(r_text))
    if diff > 0:
        return (diff * 3, f'預期「{r_text}」\n  實際「{s_text}」')
    return PASS

# ── ● 分欄 ─────────────────────────────────────────
def check_columns(student, ref, cfg):
    indices = cfg.get('para_indices', [3])
    expected_space = cfg.get('space', '567')
    has_cols = False
    space_ok = True
    if student.body is not None:
        for sp in student.body.findall(f'.//{{{W}}}sectPr'):
            cols = sp.find(f'{{{W}}}cols')
            if cols is not None:
                num = cols.get(f'{{{W}}}num', '1')
                space = cols.get(f'{{{W}}}space', '0')
                if num == '2':
                    has_cols = True
                    if abs(int(space) - int(expected_space)) > 20:
                        space_ok = False
    if not has_cols:
        return (10, '未設定二欄')
    if not space_ok:
        return (10, f'欄距不正確(應為{int(expected_space)//567}cm)')
    return PASS

# ── ● 段落間隔 ─────────────────────────────────────
def _content_blank_pattern(paras):
    """Return list of (content_idx, gap_type) where gap_type is 'blank' or 'adjacent'."""
    content = []
    blanks_between = []
    prev_content = None
    for i, p in enumerate(paras):
        if p['type'] != 'para':
            continue
        text = p.get('text', '').strip()
        if text and '題組' not in text:
            if prev_content is not None:
                gap = i - prev_content - 1
                blanks_between.append(gap)
            prev_content = i
            content.append(i)
    return content, blanks_between

def _blank_spacing_set(paras):
    """Return set of (line, lineRule) tuples used by blank paragraphs with explicit spacing."""
    vals = set()
    for i, p in enumerate(paras):
        if p['type'] != 'para':
            continue
        if p.get('text', '').strip():
            continue
        sp = p.get('pPr', {}).get('spacing', {})
        if sp.get('line'):
            vals.add((sp['line'], sp.get('lineRule', '')))
    return vals

def check_para_spacing(student, ref, cfg):
    s_paras = student.parse_paragraphs()
    r_paras = ref.parse_paragraphs() if ref else s_paras
    _, r_gaps = _content_blank_pattern(r_paras)
    _, s_gaps = _content_blank_pattern(s_paras)
    issues = []
    if s_gaps != r_gaps:
        issues.append('段落間空白列數與參考答案不符')
    r_blank_sp = _blank_spacing_set(r_paras)
    bad_lines = []
    for p in s_paras:
        if p['type'] != 'para' or p.get('text', '').strip():
            continue
        sp = p.get('pPr', {}).get('spacing', {})
        line = sp.get('line', '')
        if line and (line, sp.get('lineRule', '')) not in r_blank_sp:
            bad_lines.append(line)
    if r_blank_sp and bad_lines:
        def fmt_line(v):
            return f'{v}（{int(v)//20}pt）'
        r_display = ', '.join(fmt_line(v[0]) for v in sorted(r_blank_sp))
        s_display = ', '.join(fmt_line(v) for v in sorted(set(bad_lines)))
        issues.append(f'空白列行距{s_display}，應為{r_display}')
    if issues:
        return (10, '; '.join(issues))
    return PASS

# ── ● 圖形格式 ─────────────────────────────────────
def check_image(student, ref, cfg):
    s_imgs = student.parse_images()
    r_imgs = ref.parse_images() if ref else []
    if not s_imgs:
        return (10, '無圖片')
    issues = []
    img = s_imgs[0]
    if img.get('mode') != 'anchor':
        issues.append('非文繞圖模式')
    has_border = any(img.get('line') for img in s_imgs)
    has_shadow = any(img.get('shadow') for img in s_imgs)
    if not has_border:
        issues.append('無框線')
    cx = int(img.get('cx', 0))
    cy = int(img.get('cy', 0))
    TOL_EMU = 95250
    ref_img = r_imgs[0] if r_imgs else None
    if ref_img and cx > 0 and cy > 0:
        r_cx = int(ref_img.get('cx', 0))
        r_cy = int(ref_img.get('cy', 0))
        if r_cx > 0 and r_cy > 0:
            if abs(cx - r_cx) > TOL_EMU or abs(cy - r_cy) > TOL_EMU:
                issues.append(f'尺寸{cx}x{cy}EMU(參考{r_cx}x{r_cy})')
    if ref_img and 'posH' in img and 'posV' in img and 'posH' in ref_img and 'posV' in ref_img:
        tol = 100
        if abs(img['posH'] - ref_img['posH']) > tol or abs(img['posV'] - ref_img['posV']) > tol:
            issues.append(f'位置({img["posH"]},{img["posV"]})EMU(參考({ref_img["posH"]},{ref_img["posV"]}))')
    if not issues:
        return PASS
    return (10, '; '.join(issues))

# ── ● 表格位置 ─────────────────────────────────────
def check_table_position(student, ref, cfg):
    s_paras = student.parse_paragraphs(include_tables=True)
    if student.body is None:
        return (10, '無內容')
    first_para_end = None
    for i, el in enumerate(student.body):
        tag = el.tag.split('}')[-1] if '}' in el.tag else el.tag
        if tag == 'p':
            txt = ''.join(t.text or '' for t in el.findall(f'.//{w("t")}'))
            if txt.strip() and first_para_end is None:
                first_para_end = i
            if first_para_end is not None:
                break
    tbl_idx = None
    for i, el in enumerate(student.body):
        tag = el.tag.split('}')[-1] if '}' in el.tag else el.tag
        if tag == 'tbl':
            tbl_idx = i
            break
    if tbl_idx is None:
        return (10, '無表格')
    if first_para_end is not None and tbl_idx > first_para_end:
        return PASS
    return (10, '表格位置不正確')

# ── ● 全型括號 ─────────────────────────────────────
def check_fullwidth_parens(student, ref, cfg):
    full = '\n'.join(p.get('text', '') for p in student.parse_paragraphs())
    half = full.count('(') + full.count(')')
    if half > 0:
        return (10, f'尚有{half}個半型括號')
    return PASS

# ── ● 半型逗號轉全型， ─────────────────────────────
def check_fullwidth_commas(student, ref, cfg):
    full = '\n'.join(p.get('text', '') for p in student.parse_paragraphs())
    half = full.count(',')
    if half > 0:
        return (10, f'尚有{half}個半型逗號')
    return PASS

# ── △ 本文字型 ─────────────────────────────────────
def check_body_fonts(student, ref, cfg):
    s_paras, r_paras = _body_paras(student, ref)
    if not r_paras:
        return PASS
    cjk_issues = {}
    en_issues = {}
    sz_issues = {}
    for i, (sp, rp) in enumerate(zip(s_paras, r_paras)):
        r_cjk = set(); r_en = set(); r_sz = set()
        for t, fp in rp.get('runs', []):
            cls = classify_text(t)
            ea = fp.get('font_eastAsia', '')
            af = fp.get('font_ascii', '')
            sz = fp.get('sz', '')
            if cls in ('chinese', 'mixed') and ea: r_cjk.add(ea)
            if cls in ('english', 'digit') and af: r_en.add(af)
            if sz: r_sz.add(sz)
        if not r_cjk: r_cjk.add('新細明體')
        if not r_en: r_en.add('Arial')
        if not r_sz: r_sz.add('24')
        s_cjk = set(); s_en = set(); s_sz = set()
        for t, fp in sp.get('runs', []):
            cls = classify_text(t)
            ea = fp.get('font_eastAsia', '')
            af = fp.get('font_ascii', '')
            sz = fp.get('sz', '')
            if cls in ('chinese', 'mixed') and ea: s_cjk.add(ea)
            if cls in ('english', 'digit') and af: s_en.add(af)
            if sz: s_sz.add(sz)
        for f in s_cjk:
            if f not in r_cjk: cjk_issues[i] = f'中文用「{f}」'
        for f in s_en:
            if f not in r_en: en_issues[i] = f'英文用「{f}」'
        for sz in s_sz:
            if sz not in r_sz: sz_issues[i] = f'大小{halfpt_to_pt(sz)}pt'
    total = len(cjk_issues) + len(en_issues) + len(sz_issues)
    if total == 0:
        return PASS
    reasons = []
    for pi in sorted(cjk_issues): reasons.append(f'第{pi+1}段{cjk_issues[pi]}')
    for pi in sorted(en_issues): reasons.append(f'第{pi+1}段{en_issues[pi]}')
    for pi in sorted(sz_issues): reasons.append(f'第{pi+1}段{sz_issues[pi]}')
    return (total * 5, '; '.join(reasons[:3]))

# ── △ 段落格式 ─────────────────────────────────────
def check_para_formats(student, ref, cfg):
    s_paras, r_paras = _body_paras(student, ref)
    if not r_paras:
        return PASS
    total = 0
    details = []
    for i, (sp, rp) in enumerate(zip(s_paras, r_paras)):
        s_pp = sp.get('pPr', {})
        r_pp = rp.get('pPr', {})
        for k in ('jc',):
            if s_pp.get(k) != r_pp.get(k):
                total += 1
                details.append(f'第{i+1}段對齊{s_pp.get(k,"")}(應為{r_pp.get(k,"")})')
        for k in ('left', 'right', 'firstLine', 'hanging'):
            sv = (s_pp.get('ind') or {}).get(k)
            rv = (r_pp.get('ind') or {}).get(k)
            if sv != rv:
                total += 1
                details.append(f'第{i+1}段縮排{k}不一致')
        for k in ('before', 'after', 'line', 'lineRule'):
            sv = (s_pp.get('spacing') or {}).get(k)
            rv = (r_pp.get('spacing') or {}).get(k)
            if sv != rv:
                total += 1
                details.append(f'第{i+1}段間距{k}不一致')
        s_bdr = s_pp.get('pBdr', {})
        r_bdr = r_pp.get('pBdr', {})
        if bool(s_bdr) != bool(r_bdr):
            total += 1
            details.append(f'第{i+1}段框線不一致')
        s_shd = s_pp.get('shd', {})
        r_shd = r_pp.get('shd', {})
        if (s_shd.get('val') or '') != (r_shd.get('val') or ''):
            total += 1
            details.append(f'第{i+1}段網底不一致')
    if total:
        return (total * 5, '; '.join(details[:3]))
    return PASS

# ── ※ 標題文字 ─────────────────────────────────────
def check_title_text_same(student, ref, cfg):
    return check_title_text(student, ref, cfg)

# ── △ 段落分行 ─────────────────────────────────────
def check_para_split(student, ref, cfg):
    s_paras, r_paras = _body_paras(student, ref)
    if not r_paras:
        return PASS
    s_texts = [p.get('text', '') for p in s_paras]
    r_texts = [p.get('text', '') for p in r_paras]
    s_full = ''.join(s_texts)
    r_full = ''.join(r_texts)
    if s_full == r_full:
        if len(s_paras) == len(r_paras):
            return PASS
        return (10, f'段落數{len(s_paras)}(應為{len(r_paras)})')
    diff = sum(1 for a, b in zip(s_full, r_full) if a != b) + abs(len(s_full) - len(r_full))
    return (min(diff * 3, 999), '段落分行有誤')

# ── ※ 【】未刪除 ───────────────────────────────────
def check_brackets(student, ref, cfg):
    full = '\n'.join(p.get('text', '') for p in student.parse_paragraphs())
    count = full.count('【') + full.count('】')
    if count > 0:
        return (min(count * 3, 999), f'尚有{count}個【】')
    return PASS

# ── ※ 表格內容 ─────────────────────────────────────
def check_table_content(student, ref, cfg):
    s_list = [p.get('table', {}) for p in student.parse_paragraphs(include_tables=True) if p['type'] == 'table']
    r_list = [p.get('table', {}) for p in ref.parse_paragraphs(include_tables=True) if p['type'] == 'table']
    if not r_list:
        return PASS
    per_char = cfg.get('per_char', 3)
    if not s_list:
        total_chars = 0
        for row in r_list[0].get('rows', []):
            for cell in row:
                total_chars += len(cell.get('text', '').strip())
        return (total_chars * per_char, f'缺少表格(全文共{total_chars}字)')
    s_tbl, r_tbl = s_list[0], r_list[0]
    s_rows, r_rows = s_tbl.get('rows', []), r_tbl.get('rows', [])
    text_diff = 0
    fmt_diff = 0
    details = []
    for ri, (sr, rr) in enumerate(zip(s_rows, r_rows)):
        for ci, (sc, rc) in enumerate(zip(sr, rr)):
            st = sc.get('text', '').strip()
            rt = rc.get('text', '').strip()
            if st != rt:
                td = sum(1 for a, b in zip(st, rt) if a != b) + abs(len(st) - len(rt))
                text_diff += td
                details.append(f'({ri+1},{ci+1}):預期「{rt}」\n  實際「{st}」')
            for sp, rp in zip(sc.get('paras', []), rc.get('paras', [])):
                for sr_, rr_ in zip(sp.get('runs', []), rp.get('runs', [])):
                    if sr_[1].get('i') != rr_[1].get('i'): fmt_diff += 1; details.append(f'({ri+1},{ci+1}):斜體')
                    if sr_[1].get('u') != rr_[1].get('u'): fmt_diff += 1; details.append(f'({ri+1},{ci+1}):底線')
            s_shd = sc.get('tcPr', {}).get('shd', {})
            r_shd = rc.get('tcPr', {}).get('shd', {})
            s_val = s_shd.get('val') if s_shd.get('val') not in (None, 'clear', 'nil') else None
            r_val = r_shd.get('val') if r_shd.get('val') not in (None, 'clear', 'nil') else None
            if s_val != r_val: fmt_diff += 1; details.append(f'({ri+1},{ci+1}):網底')
            s_td = sc.get('tcPr', {}).get('textDirection', '')
            r_td = rc.get('tcPr', {}).get('textDirection', '')
            if s_td != r_td: fmt_diff += 1; details.append(f'({ri+1},{ci+1}):文字方向')
            s_diag = sc.get('tcPr', {}).get('diag', {})
            r_diag = rc.get('tcPr', {}).get('diag', {})
            if bool(s_diag) != bool(r_diag): fmt_diff += 1; details.append(f'({ri+1},{ci+1}):斜線')
    if len(s_rows) != len(r_rows):
        missing = abs(len(s_rows) - len(r_rows))
        add = 0
        for row in r_rows[len(s_rows):] if len(s_rows) < len(r_rows) else r_rows[len(r_rows):]:
            for cell in row:
                add += len(cell.get('text', '').strip())
        text_diff += add
    total = text_diff * per_char + fmt_diff
    if total:
        r = '\n'.join(details[:3])
        if len(details) > 3: r += f'\n等{len(details)}處'
        return (min(total, 999), r)
    return PASS

# ── △ 自行輸入字型 ─────────────────────────────────
def check_self_input_font(student, ref, cfg):
    text_cfg = cfg.get('self_input', '')
    if not text_cfg:
        return PASS
    match_key = text_cfg[:20] if len(text_cfg) > 20 else text_cfg
    for p in student.parse_paragraphs():
        if p['type'] != 'para':
            continue
        if match_key not in p.get('text', ''):
            continue
        issues = []
        for t, rp in p.get('runs', []):
            if not t.strip():
                continue
            cls = classify_text(t)
            ea = rp.get('font_eastAsia', '')
            af = rp.get('font_ascii', '')
            if cls in ('chinese', 'mixed') and ea != '標楷體':
                issues.append(f'中文用{ea or "未設定"}(應標楷體)')
            if cls in ('english', 'digit') and af not in ('Arial', ''):
                issues.append(f'英數用{af}(應Arial)')
        if issues:
            return (5, '; '.join(issues[:2]))
        return PASS
    return (5, '找不到自行輸入段落')

# ── ● 取代文字 ─────────────────────────────────────
def check_replacement(student, ref, cfg):
    old = cfg.get('old', '')
    new = cfg.get('new', '')
    require_underline = cfg.get('underline', False)
    issues = []
    for p in student.parse_paragraphs():
        if p['type'] != 'para':
            continue
        text = p.get('text', '')
        if old and old in text:
            issues.append(f'尚有「{old}」未取代')
        if new and new in text:
            if require_underline:
                found_underline = False
                for t, rp in p.get('runs', []):
                    if new in t and rp.get('u', '') not in ('', 'none'):
                        found_underline = True
                        break
                if not found_underline:
                    issues.append(f'「{new}」無底線')
    if issues:
        return (10, '; '.join(issues))
    return PASS

def _edit_distance(a, b):
    """Levenshtein distance: 1 deletion/insertion/substitution = 1."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[lb]

def _para_text_diff(st, rt):
    """Per-character difference between two paragraph texts (Levenshtein)."""
    return _edit_distance(st, rt)

# ── ● 段落總數 ──────────────────────────────────────
def check_para_count(student, ref, cfg):
    paras = student.parse_paragraphs()
    expected = cfg.get('expected')
    if expected is None:
        if ref is None:
            return (10, '未知段落數')
        expected = len(ref.parse_paragraphs())
    count = len(paras)
    if count == expected:
        return PASS
    return (cfg.get('points', 10), f'段落數{count}(應為{expected})')

# ── ● 匯入文字並分段（段落數＋段落文字與參考答案完全一致）─
def check_import_split(student, ref, cfg):
    if ref is None:
        return (999, '缺少此階段參考答案')
    s_paras = student.parse_paragraphs()
    r_paras = ref.parse_paragraphs()
    s_texts = [p.get('text', '') for p in s_paras]
    r_texts = [p.get('text', '') for p in r_paras]
    indices = cfg.get('p_indices')
    if indices is not None:
        diff = 0
        issues = []
        for i in indices:
            if i >= len(r_paras):
                continue
            rt = r_texts[i]
            st = s_texts[i] if i < len(s_paras) else ''
            d = _para_text_diff(st, rt)
            diff += d
            if d:
                issues.append(f'第{i+1}段：\n  預期「{rt[:30]}{"…" if len(rt)>30 else ""}」\n  實際「{st[:30]}{"…" if len(st)>30 else ""}」')
        if diff == 0:
            return PASS
        per = cfg.get('per_char')
        if per:
            return (min(diff * per, 999), '; '.join(issues[:5]))
        return (cfg.get('points', 20), '; '.join(issues[:5]))
    issues = []
    if s_texts == r_texts:
        return PASS
    if len(s_paras) != len(r_paras):
        issues.append(f'段落數{len(s_paras)}(應為{len(r_paras)})')
    diff = sum(1 for a, b in zip(s_texts, r_texts) if a != b) + abs(len(s_texts) - len(r_texts))
    for i, (st, rt) in enumerate(zip(s_texts, r_texts)):
        if st != rt:
            issues.append(f'第{i+1}段：\n  預期「{rt[:30]}{"…" if len(rt)>30 else ""}」\n  實際「{st[:30]}{"…" if len(st)>30 else ""}」')
    if len(s_paras) > len(r_paras):
        for i in range(len(r_paras), len(s_paras)):
            issues.append(f'第{i+1}段：多出的段落「{s_texts[i][:30]}{"…" if s_texts[i] else ""}」')
    elif len(s_paras) < len(r_paras):
        for i in range(len(s_paras), len(r_paras)):
            issues.append(f'第{i+1}段：缺少段落「{r_texts[i][:30]}{"…" if r_texts[i] else ""}」')
    return (cfg.get('points', 20), '; '.join(issues[:20]))

# ── 頁首/頁尾 三欄分段 ──────────────────────────────
def _hf_segments(runs):
    """Split header/footer runs into columns by paragraph tabs (w:ptab).
    Returns list of (preceding_tab_alignment_or_None, text)."""
    segs = []
    cur_align = None
    cur = ''
    for t, rp in runs:
        if rp.get('ptab'):
            segs.append((cur_align, cur))
            cur_align = rp['ptab']
            cur = ''
        else:
            cur += t
    segs.append((cur_align, cur))
    return segs

# ── ● 頁首：三欄（學號 / 姓名 / 座號）──────────────
def check_header_format(student, ref, cfg):
    el = student.parse_header_footer().get('header')
    if not el:
        return (10, '無頁首')
    segs = _hf_segments(el.get('runs', []))
    texts = [t for _, t in segs]
    aligns = [a for a, _ in segs]
    issues = []
    if len(segs) != 3:
        issues.append(f'欄數{len(segs)}(應為3欄)')
    if aligns != [None, 'center', 'right']:
        issues.append('三欄定位錯誤(應為置中、靠右)')
    for i, lbl in ((0, '左側學號'), (1, '中間姓名'), (2, '右側座號')):
        if i < len(texts) and not texts[i].strip():
            issues.append(f'{lbl}無資料')
    if not issues:
        return PASS
    return (10, '; '.join(issues))

# ── ● 頁尾：三欄（日期 / 第X頁 / 空白）──────────────
def check_footer_format(student, ref, cfg):
    el = student.parse_header_footer().get('footer')
    if not el:
        return (10, '無頁尾')
    segs = _hf_segments(el.get('runs', []))
    texts = [t for _, t in segs]
    aligns = [a for a, _ in segs]
    issues = []
    if len(segs) != 3:
        issues.append(f'欄數{len(segs)}(應為3欄)')
    if aligns != [None, 'center', 'right']:
        issues.append('三欄定位錯誤(應為置中、靠右)')
    if len(texts) >= 1 and not re.fullmatch(r'\d{4}/\d{2}/\d{2}', texts[0].strip()):
        issues.append(f'左側日期「{texts[0].strip()[:15]}」非YYYY/MM/DD')
    center = texts[1] if len(texts) >= 2 else ''
    if ('FIELD:PAGE' not in center) and ('INSTR:PAGE' not in center):
        issues.append('中間無頁碼欄位')
    if '第' not in center or '頁' not in center:
        issues.append('中間非「第X頁」格式')
    if len(texts) >= 3 and texts[2].strip():
        issues.append('右側應無資料')
    if not issues:
        return PASS
    return (10, '; '.join(issues))

# ── ● 所有段落左右對齊 ──────────────────────────────
def check_justify_all(student, ref, cfg):
    bad = []
    for p in student.parse_paragraphs():
        if p['type'] != 'para':
            continue
        if cfg.get('skip_title') and '題組' in p.get('text', ''):
            continue
        if p.get('pPr', {}).get('jc') != 'both':
            t = p.get('text', '').strip()
            bad.append(t[:15] if t else '(空白段)')
    if bad:
        return (cfg.get('points', 10), f'{len(bad)}段非左右對齊: ' + ', '.join(bad[:5]))
    return PASS

# ── ● 段落規格（逐段字型/格式設定）───────────────────
def check_para_spec(student, ref, cfg):
    """按 JSON spec 逐段檢查字型與格式。
    cfg.default: 套用到所有內容段 (cjk/ascii/size/jc/italic/underline/indent_first/border/shading)
    cfg.spec: [{para_no:int[, index:int], 覆寫...}]  用內容段落序號(1-based)或絕對index定位
    內容段落 = 非空白、非表格段落（不含標題）
    """
    default = cfg.get('default', {})
    skip_title = cfg.get('skip_title', True)
    paras = student.parse_paragraphs()
    content_idx = []
    for idx, p in enumerate(paras):
        if p['type'] != 'para':
            continue
        text = p.get('text', '').strip()
        if not text:
            continue
        if skip_title and '題組' in text:
            continue
        content_idx.append(idx)
    # para_no -> 絕對 index
    spec_map = {}
    for sp in cfg.get('spec', []):
        target = None
        if 'para_no' in sp and 1 <= sp['para_no'] <= len(content_idx):
            target = content_idx[sp['para_no'] - 1]
        elif 'index' in sp:
            target = sp['index']
        elif 'indices' in sp:
            for i in sp['indices']:
                spec_map[i] = sp
            continue
        if target is not None:
            spec_map[target] = sp
    skip = set(cfg.get('skip_indices', []) or [])
    issues = []
    for idx in content_idx:
        if idx in skip:
            continue
        p = paras[idx]
        exp = {**default, **spec_map.get(idx, {})}
        if not exp:
            continue
        _check_para_spec_one(p, idx, p.get('text', '').strip(), exp, issues)
    if issues:
        return (cfg.get('points', 5), '; '.join(dict.fromkeys(issues[:8])))
    return PASS

def _check_para_spec_one(p, idx, text, exp, issues):
    runs = p.get('runs', [])
    rp_list = [rp for _, rp in runs]
    def any_run(pred):
        return any(pred(rp) for rp in rp_list) if rp_list else False
    def all_nonempty_runs(pred):
        nonempty = [rp for (t, rp) in runs if t.strip()]
        return bool(nonempty) and all(pred(rp) for rp in nonempty)

    # 字型：中文字型 (只檢查含中文的 run)
    if 'cjk' in exp:
        wrong = {}
        for t, rp in runs:
            if not t.strip():
                continue
            if classify_text(t) not in ('chinese', 'mixed'):
                continue
            ea = rp.get('font_eastAsia', '')
            if ea and ea != exp['cjk']:
                if ea not in wrong: wrong[ea] = 0
                wrong[ea] += len(t)
        if wrong:
            for ea, n in wrong.items():
                issues.append(f'第{idx+1}段中文字型「{ea}」(應{exp["cjk"]}, {n}字)')
    if 'ascii' in exp:
        wrong = {}
        for t, rp in runs:
            if not t.strip():
                continue
            if classify_text(t) not in ('english', 'digit', 'mixed'):
                continue
            af = rp.get('font_ascii', '')
            if af and af != exp['ascii']:
                if af not in wrong: wrong[af] = 0
                wrong[af] += len(t)
        if wrong:
            for af, n in wrong.items():
                issues.append(f'第{idx+1}段英數字型「{af}」(應{exp["ascii"]}, {n}字)')
    if 'size' in exp:
        wrong_sz = []
        for _, rp in runs:
            sz = rp.get('sz', '')
            if sz and sz.isdigit() and int(sz) != int(exp['size']):
                wrong_sz.append(halfpt_to_pt(sz))
        if wrong_sz:
            pts = sorted({halfpt_to_pt(sz) for sz in wrong_sz})
            issues.append(f'第{idx+1}段大小{'/'.join(str(p) for p in pts)}pt(應{halfpt_to_pt(str(exp["size"]))}pt)')
    if 'jc' in exp:
        if p.get('pPr', {}).get('jc', '') != exp['jc']:
            issues.append(f'第{idx+1}段未置中' if exp['jc'] == 'center' else f'第{idx+1}段對齊錯誤')
    if 'italic' in exp:
        if not any_run(lambda rp: rp.get('i') in ('true', '1')):
            issues.append(f'第{idx+1}段無斜體')
    if 'underline' in exp:
        if not any_run(lambda rp: rp.get('u') not in (None, '', 'none')):
            issues.append(f'第{idx+1}段無底線')
    if 'indent_first' in exp:
        ind = p.get('pPr', {}).get('ind', {})
        if str(ind.get('firstLine', '')) != str(exp['indent_first']):
            if exp['indent_first'] is False:
                if ind.get('firstLine'):
                    issues.append(f'第{idx+1}段不應有首行縮排')
            else:
                issues.append(f'第{idx+1}段首行縮排{ind.get("firstLine","無")}(應{exp["indent_first"]})')
    if 'border' in exp:
        has = bool(p.get('pPr', {}).get('pBdr')) or any_run(lambda rp: rp.get('bdr'))
        if exp['border'] and not has:
            issues.append(f'第{idx+1}段無框線')
        if exp['border'] is False and has:
            issues.append(f'第{idx+1}段不應有框線')
    if 'shading' in exp:
        pshd = (p.get('pPr', {}).get('shd') or {}).get('val')
        has = pshd in ('clear', 'solid') or bool(pshd) or any_run(lambda rp: (rp.get('shd') or {}).get('val'))
        if exp['shading'] and not has:
            issues.append(f'第{idx+1}段無網底')

# ── ● 圖片規格（文繞圖/細框線/尺寸/對齊段落）───────
def check_image_spec(student, ref, cfg):
    s_imgs = student.parse_images()
    r_imgs = ref.parse_images() if ref else []
    if not s_imgs:
        return (cfg.get('points', 10), '無圖片')
    img = s_imgs[0]
    issues = []
    if img.get('mode') != 'anchor':
        issues.append('非文繞圖(浮動)模式')
    if cfg.get('tight') and img.get('wrap') != 'wrapTight':
        issues.append('未設定文繞圖「緊密」')
    if cfg.get('border'):
        has_line = bool(img.get('line'))
        if not has_line:
            issues.append('無框線')
        elif cfg.get('border_thin'):
            line_w = (img.get('line') or {}).get('w', '')
            if line_w and line_w.isdigit() and int(line_w) > int(cfg.get('border_thin')):
                issues.append(f'框線過粗({int(line_w)//12700}pt)')
    if cfg.get('shadow') and not img.get('shadow'):
        issues.append('無陰影(需右下陰影)')
    if img.get('posHRel') != cfg.get('posH_rel', 'margin'):
        issues.append(f'水平對齊{img.get("posHRel","無")}(應{cfg.get("posH_rel","margin")}=左邊界)')
    if img.get('posVRel') != cfg.get('posV_rel', 'paragraph'):
        issues.append(f'垂直對齊{img.get("posVRel","無")}(應{cfg.get("posV_rel","paragraph")}=段落頂端)')
    expected_p = cfg.get('anchor_p_idx')
    if expected_p is not None and img.get('anchor_p_idx') != expected_p:
        issues.append(f'圖片綁定第{img.get("anchor_p_idx","?")}段(應第{expected_p+1}段)')
    tol = cfg.get('size_tol', 0.10)
    if r_imgs:
        rc = int(r_imgs[0].get('cx', 0)); rg = int(r_imgs[0].get('cy', 0))
        sc = int(img.get('cx', 0)); sg = int(img.get('cy', 0))
        if rc > 0 and sc > 0 and abs(sc - rc) / rc > tol:
            issues.append(f'寬度{sc}(參考{rc}, 差{abs(sc-rc)/rc*100:.1f}%)')
        if rg > 0 and sg > 0 and abs(sg - rg) / rg > tol:
            issues.append(f'高度{sg}(參考{rg}, 差{abs(sg-rg)/rg*100:.1f}%)')
    if issues:
        return (cfg.get('points', 10), '; '.join(issues))
    return PASS

# ── ● 表格欄列規格 ─────────────────────────────────
def check_table_spec(student, ref, cfg):
    s_tbls = [p for p in student.parse_paragraphs(include_tables=True) if p['type'] == 'table']
    if not s_tbls:
        return (cfg.get('points', 10), '無表格')
    rows = s_tbls[0].get('table', {}).get('rows', [])
    exp_r = cfg.get('rows', 6); exp_c = cfg.get('cols', 4)
    issues = []
    if len(rows) != exp_r:
        issues.append(f'列數{len(rows)}(應{exp_r})')
    max_c = max((len(r) for r in rows), default=0)
    if max_c != exp_c:
        issues.append(f'欄數{max_c}(應{exp_c})')
    if issues:
        return (cfg.get('points', 10), '; '.join(issues))
    return PASS

# ── ● 表格合併儲存格 ───────────────────────────────
def check_table_merge(student, ref, cfg):
    s_tbls = [p for p in student.parse_paragraphs(include_tables=True) if p['type'] == 'table']
    r_tbls = [p for p in ref.parse_paragraphs(include_tables=True) if p['type'] == 'table'] if ref else []
    if not s_tbls or not r_tbls:
        return (cfg.get('points', 10), '缺少表格或參考')
    def merge_pattern(tbl):
        pat = []
        for row in tbl.get('rows', []):
            rp = []
            for cell in row:
                tc = cell.get('tcPr', {})
                if tc.get('gridSpan'):
                    rp.append(f's{tc["gridSpan"]}')
                elif tc.get('vMerge'):
                    rp.append('v' if tc['vMerge'] == 'restart' else 'vc')
                else:
                    rp.append('.')
            pat.append(rp)
        return pat
    sp = merge_pattern(s_tbls[0]); rp = merge_pattern(r_tbls[0])
    if sp != rp:
        return (cfg.get('points', 10), '合併儲存格配置與參考不符')
    return PASS

# ── ● 表格欄位寬度 ─────────────────────────────────
def check_table_width(student, ref, cfg):
    s_tbls = [p for p in student.parse_paragraphs(include_tables=True) if p['type'] == 'table']
    r_tbls = [p for p in ref.parse_paragraphs(include_tables=True) if p['type'] == 'table'] if ref else []
    if not s_tbls or not r_tbls:
        return (cfg.get('points', 10), '缺少表格或參考')
    sw = s_tbls[0].get('table', {}).get('widths', [])
    rw = r_tbls[0].get('table', {}).get('widths', [])
    if not rw:
        return PASS
    if len(sw) != len(rw):
        return (cfg.get('points', 10), f'欄寬數{len(sw)}(應{len(rw)})')
    tol = cfg.get('tolerance', 0.08)
    diffs = []
    for i, (a, b) in enumerate(zip(sw, rw)):
        if b == 0:
            continue
        if abs(a - b) / b > tol:
            diffs.append(f'欄{i+1}:{a}(參考{b})')
    if diffs:
        return (cfg.get('points', 10), '欄寬不符; ' + ', '.join(diffs[:3]))
    return PASS

# ── ● 首列首欄網底 ─────────────────────────────────
def check_table_shading(student, ref, cfg):
    s_tbls = [p for p in student.parse_paragraphs(include_tables=True) if p['type'] == 'table']
    if not s_tbls:
        return (cfg.get('points', 10), '無表格')
    tbl = s_tbls[0].get('table', {})
    rows = tbl.get('rows', [])
    if not rows:
        return (cfg.get('points', 10), '無列')
    cols = max((len(r) for r in rows), default=0)
    def has_shade(cell):
        shd = cell.get('tcPr', {}).get('shd', {})
        fill = shd.get('fill', '')
        val = shd.get('val', '')
        if val in ('nil',):
            return False
        if fill and fill.lower() != 'auto':
            return True
        return False
    issues = []
    expected = set()
    for ci in range(cols):
        expected.add((0, ci))
    for ri in range(len(rows)):
        expected.add((ri, 0))
    for ri in range(len(rows)):
        for ci in range(min(len(rows[ri]), cols)):
            if (ri, ci) in expected and not has_shade(rows[ri][ci]):
                issues.append(f'({ri+1},{ci+1})無網底')
    if issues:
        return (cfg.get('points', 10), '首列/首欄網底; ' + ', '.join(issues[:3]))
    return PASS

# ── ● 表格文字對齊（置中/分散）──────────────────────
def check_table_align(student, ref, cfg):
    s_tbls = [p for p in student.parse_paragraphs(include_tables=True) if p['type'] == 'table']
    r_tbls = [p for p in ref.parse_paragraphs(include_tables=True) if p['type'] == 'table'] if ref else []
    if not s_tbls or not r_tbls:
        return (cfg.get('points', 10), '缺少表格或參考')
    s_tbl, r_tbl = s_tbls[0].get('table', {}), r_tbls[0].get('table', {})
    s_rows, r_rows = s_tbl.get('rows', []), r_tbl.get('rows', [])
    if len(s_rows) != len(r_rows):
        return (cfg.get('points', 10), f'列數{len(s_rows)}(應{len(r_rows)})')
    issues = []
    for ri, (sr, rr) in enumerate(zip(s_rows, r_rows)):
        for ci in range(min(len(sr), len(rr))):
            sp = sr[ci].get('paras', [])[0].get('pPr', {}).get('jc')
            rp_ = rr[ci].get('paras', [])[0].get('pPr', {}).get('jc')
            if sp != rp_:
                issues.append(f'({ri+1},{ci+1}):對齊{sp or "無"}(應{rp_ or "無"})')
    if issues:
        return (cfg.get('points', 10), '; '.join(issues[:3]))
    return PASS

# ── ● 表格字型（中=新細明體, 英=Arial）─────────────
def check_table_font(student, ref, cfg):
    s_tbls = [p for p in student.parse_paragraphs(include_tables=True) if p['type'] == 'table']
    if not s_tbls:
        return (cfg.get('points', 10), '無表格')
    rows = s_tbls[0].get('table', {}).get('rows', [])
    cjk_want = cfg.get('cjk', '新細明體')
    en_want = cfg.get('en', 'Arial')
    issues = []
    for ri, row in enumerate(rows):
        for ci, cell in enumerate(row):
            for para in cell.get('paras', []):
                for t, rp in para.get('runs', []):
                    if not t.strip():
                        continue
                    cls = classify_text(t)
                    if cls in ('chinese', 'mixed'):
                        ea = rp.get('font_eastAsia', '')
                        if ea and ea != cjk_want:
                            issues.append(f'({ri+1},{ci+1})中文用「{ea}」')
                    if cls in ('english', 'digit'):
                        af = rp.get('font_ascii', '') or rp.get('font_hAnsi', '')
                        if af and af != en_want:
                            issues.append(f'({ri+1},{ci+1})英文用「{af}」')
    if issues:
        return (cfg.get('points', 10), '; '.join(set(issues))[:200])
    return PASS

# ── ● 表格全形括號 ─────────────────────────────────
def check_table_fullwidth(student, ref, cfg):
    s_tbls = [p for p in student.parse_paragraphs(include_tables=True) if p['type'] == 'table']
    if not s_tbls:
        return (cfg.get('points', 10), '無表格')
    tbl = s_tbls[0].get('table', {})
    total = 0
    for row in tbl.get('rows', []):
        for cell in row:
            total += cell.get('text', '').count('(') + cell.get('text', '').count(')')
    if total > 0:
        return (10, f'表格內尚有{total}個半型括號')
    return PASS

# ── ● 頁首：三欄（中文西元年 / 空白 / 第X頁）────────
def check_tz02_header_format(student, ref, cfg):
    el = student.parse_header_footer().get('header')
    if not el:
        return (10, '無頁首')
    segs = _hf_segments(el.get('runs', []))
    texts = [t for _, t in segs]
    aligns = [a for a, _ in segs]
    issues = []
    if len(segs) != 3:
        issues.append(f'欄數{len(segs)}(應為3欄)')
    else:
        if not texts[0].strip():
            issues.append('左側(中文西元年)無資料')
        if texts[1].strip():
            issues.append('中間應為空白')
        right = texts[2]
        if ('FIELD:PAGE' not in right) and ('INSTR:PAGE' not in right) and ('第' not in right or '頁' not in right):
            issues.append('右側非「第X頁」格式(含頁碼)')
    if aligns != [None, 'center', 'right']:
        issues.append('三欄定位錯誤(應為置中、靠右)')
    if not issues:
        return PASS
    return (10, '; '.join(issues))

# ── ● 頁尾：三欄（學號 / 姓名 / 座號）──────────────
def check_tz02_footer_format(student, ref, cfg):
    el = student.parse_header_footer().get('footer')
    if not el:
        return (10, '無頁尾')
    segs = _hf_segments(el.get('runs', []))
    texts = [t for _, t in segs]
    aligns = [a for a, _ in segs]
    issues = []
    if len(segs) != 3:
        issues.append(f'欄數{len(segs)}(應為3欄)')
    else:
        for i, lbl in ((0, '左側學號'), (1, '中間姓名'), (2, '右側座號')):
            if not texts[i].strip():
                issues.append(f'{lbl}無資料')
    if aligns != [None, 'center', 'right']:
        issues.append('三欄定位錯誤(應為置中、靠右)')
    if not issues:
        return PASS
    return (10, '; '.join(issues))

# ── 註冊表 ──────────────────────────────────────────
REGISTRY = {
    'justify_all': check_justify_all,
    'para_count': check_para_count,
    'para_spec': check_para_spec,
    'image_spec': check_image_spec,
    'table_spec': check_table_spec,
    'table_merge': check_table_merge,
    'table_width': check_table_width,
    'table_shading': check_table_shading,
    'table_align': check_table_align,
    'table_font': check_table_font,
    'table_fullwidth': check_table_fullwidth,
    'import_split': check_import_split,
    'paragraph_text': check_import_split,
    'title_para': check_import_split,
    'typing_text': check_import_split,
    'header_format': check_header_format,
    'footer_format': check_footer_format,
    'tz02_header_format': check_tz02_header_format,
    'tz02_footer_format': check_tz02_footer_format,
    'footer_font': check_footer_font,
    'orientation': check_orientation,
    'page_size': check_page_size,
    'margins': check_margins,
    'justify': check_justify,
    'header_font': check_header_font,
    'header_content': check_header_content,
    'header_pagenum': check_header_pagenum,
    'title_format': check_title_format,
    'columns': check_columns,
    'para_spacing': check_para_spacing,
    'image': check_image,
    'table_position': check_table_position,
    'fullwidth_parens': check_fullwidth_parens,
    'fullwidth_commas': check_fullwidth_commas,
    'body_fonts': check_body_fonts,
    'title_text': check_title_text_same,
    'para_split': check_para_split,
    'brackets': check_brackets,
    'table_content': check_table_content,
    'self_input_font': check_self_input_font,
    'para_formats': check_para_formats,
    'replacement': check_replacement,
}
