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
def check_header_font(student, ref, cfg):
    hf = student.parse_header_footer()
    header = hf.get('header')
    if not header:
        return (10, '無頁首')
    cjk_ok = True
    en_ok = True
    sz_ok = True
    expected_sz = cfg.get('font_size', '20')
    expected_en = cfg.get('en_font', 'Times New Roman')
    for t, rp in header['runs']:
        if not t.strip():
            continue
        eastasia = rp.get('font_eastAsia', '')
        ascii_f = rp.get('font_ascii', '')
        sz = rp.get('sz', '')
        cls = classify_text(t)
        if cls in ('chinese', 'mixed') and eastasia and eastasia not in ('細明體', '新細明體', '標楷體'):
            cjk_ok = False
        if cls in ('english', 'digit', 'mixed') and ascii_f and ascii_f != expected_en:
            en_ok = False
        if sz and sz != expected_sz:
            sz_ok = False
    issues = []
    if not cjk_ok:
        issues.append('中文字型非細明體/新細明體')
    if not en_ok:
        issues.append(f'英數字型非{expected_en}')
    if not sz_ok:
        issues.append(f'字型大小非{halfpt_to_pt(expected_sz)}pt')
    if issues:
        return (10, '; '.join(issues))
    return PASS

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

# ── ● 頁首頁碼 ─────────────────────────────────────
def _has_page_number(hf):
    for zone in ('header', 'footer'):
        el = hf.get(zone)
        if el:
            text = el.get('text', '')
            if 'FIELD:PAGE' in text or '第' in text or 'Page' in text or 'page' in text:
                return True
    return False

def check_header_pagenum(student, ref, cfg):
    hf = student.parse_header_footer()
    if not hf.get('header') and not hf.get('footer'):
        return (10, '無頁首也無頁尾')
    if not _has_page_number(hf):
        return (10, '無頁碼')
    return PASS

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
    if not s_list:
        total_chars = 0
        for row in r_list[0].get('rows', []):
            for cell in row:
                total_chars += len(cell.get('text', '').strip())
        return (total_chars * 3, f'缺少表格(全文共{total_chars}字)')
    s_tbl, r_tbl = s_list[0], r_list[0]
    s_rows, r_rows = s_tbl.get('rows', []), r_tbl.get('rows', [])
    diff = 0
    details = []
    for ri, (sr, rr) in enumerate(zip(s_rows, r_rows)):
        for ci, (sc, rc) in enumerate(zip(sr, rr)):
            st = sc.get('text', '').strip()
            rt = rc.get('text', '').strip()
            if st != rt:
                wd = sum(1 for a, b in zip(st, rt) if a != b) + abs(len(st) - len(rt))
                diff += wd
                details.append(f'({ri+1},{ci+1}):預期「{rt}」\n  實際「{st}」')
            for sp, rp in zip(sc.get('paras', []), rc.get('paras', [])):
                for sr_, rr_ in zip(sp.get('runs', []), rp.get('runs', [])):
                    if sr_[1].get('i') != rr_[1].get('i'): diff += 1; details.append(f'({ri+1},{ci+1}):斜體')
                    if sr_[1].get('u') != rr_[1].get('u'): diff += 1; details.append(f'({ri+1},{ci+1}):底線')
            s_shd = sc.get('tcPr', {}).get('shd', {})
            r_shd = rc.get('tcPr', {}).get('shd', {})
            s_val = s_shd.get('val') if s_shd.get('val') not in (None, 'clear', 'nil') else None
            r_val = r_shd.get('val') if r_shd.get('val') not in (None, 'clear', 'nil') else None
            if s_val != r_val: diff += 1; details.append(f'({ri+1},{ci+1}):網底')
            s_td = sc.get('tcPr', {}).get('textDirection', '')
            r_td = rc.get('tcPr', {}).get('textDirection', '')
            if s_td != r_td: diff += 1; details.append(f'({ri+1},{ci+1}):文字方向')
            s_diag = sc.get('tcPr', {}).get('diag', {})
            r_diag = rc.get('tcPr', {}).get('diag', {})
            if bool(s_diag) != bool(r_diag): diff += 1; details.append(f'({ri+1},{ci+1}):斜線')
    if len(s_rows) != len(r_rows):
        diff += abs(len(s_rows) - len(r_rows)) * 5
    if diff:
        r = '\n'.join(details[:3])
        if len(details) > 3: r += f'\n等{len(details)}處'
        return (min(diff * 3, 999), r)
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

# ── 註冊表 ──────────────────────────────────────────
REGISTRY = {
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
    'body_fonts': check_body_fonts,
    'title_text': check_title_text_same,
    'para_split': check_para_split,
    'brackets': check_brackets,
    'table_content': check_table_content,
    'self_input_font': check_self_input_font,
    'para_formats': check_para_formats,
}
