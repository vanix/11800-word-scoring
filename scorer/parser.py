import zipfile
import xml.etree.ElementTree as ET
import re

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
WP = 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
PIC = 'http://schemas.openxmlformats.org/drawingml/2006/picture'

def w(tag):
    return f'{{{W}}}{tag}'
def a(tag):
    return f'{{{A}}}{tag}'
def wp(tag):
    return f'{{{WP}}}{tag}'
def pic(tag):
    return f'{{{PIC}}}{tag}'
def rns(tag):
    return f'{{{R}}}{tag}'
def get_attr(elem, attr):
    if elem is not None:
        return elem.get(f'{{{W}}}{attr}')
    return None
def halfpt_to_pt(v):
    return int(v) / 2 if v else None
def text_of_para(p_elem):
    texts = []
    for t in p_elem.findall(f'.//{w("t")}'):
        if t.text:
            texts.append(t.text)
    return ''.join(texts)
def fmt_run_props(rPr):
    if rPr is None:
        return {}
    props = {}
    rFonts = rPr.find(w('rFonts'))
    if rFonts is not None:
        for k in ['ascii', 'hAnsi', 'eastAsia', 'cs']:
            v = rFonts.get(f'{{{W}}}{k}')
            if v:
                props[f'font_{k}'] = v
    sz = rPr.find(w('sz'))
    if sz is not None:
        props['sz'] = sz.get(f'{{{W}}}val')
    szCs = rPr.find(w('szCs'))
    if szCs is not None:
        props['szCs'] = szCs.get(f'{{{W}}}val')
    b = rPr.find(w('b'))
    if b is not None:
        props['b'] = b.get(f'{{{W}}}val', 'true')
    i = rPr.find(w('i'))
    if i is not None:
        props['i'] = i.get(f'{{{W}}}val', 'true')
    u = rPr.find(w('u'))
    if u is not None:
        props['u'] = u.get(f'{{{W}}}val', '')
    color = rPr.find(w('color'))
    if color is not None:
        props['color'] = color.get(f'{{{W}}}val', '')
    shd = rPr.find(w('shd'))
    if shd is not None:
        props['shd'] = {
            'val': shd.get(f'{{{W}}}val', ''),
            'color': shd.get(f'{{{W}}}color', ''),
            'fill': shd.get(f'{{{W}}}fill', ''),
        }
    bdr = rPr.find(w('bdr'))
    if bdr is not None:
        props['bdr'] = {
            'val': bdr.get(f'{{{W}}}val', ''),
            'sz': bdr.get(f'{{{W}}}sz', ''),
            'color': bdr.get(f'{{{W}}}color', ''),
        }
    return props
def fmt_para_props(pPr):
    if pPr is None:
        return {}
    props = {}
    pStyle = pPr.find(w('pStyle'))
    if pStyle is not None:
        props['pStyle'] = pStyle.get(f'{{{W}}}val', '')
    jc = pPr.find(w('jc'))
    if jc is not None:
        props['jc'] = jc.get(f'{{{W}}}val', '')
    ind = pPr.find(w('ind'))
    if ind is not None:
        ind_props = {}
        for k in ['left', 'right', 'firstLine', 'hanging', 'leftChars', 'rightChars', 'firstLineChars', 'hangingChars']:
            v = ind.get(f'{{{W}}}{k}')
            if v:
                ind_props[k] = v
        if ind_props:
            props['ind'] = ind_props
    spacing = pPr.find(w('spacing'))
    if spacing is not None:
        sp_props = {}
        for k in ['before', 'after', 'line', 'lineRule']:
            v = spacing.get(f'{{{W}}}{k}')
            if v:
                sp_props[k] = v
        if sp_props:
            props['spacing'] = sp_props
    pBdr = pPr.find(w('pBdr'))
    if pBdr is not None:
        borders = {}
        for side in ['top', 'left', 'bottom', 'right']:
            side_e = pBdr.find(w(side))
            if side_e is not None:
                sz_v = side_e.get(f'{{{W}}}sz')
                color_v = side_e.get(f'{{{W}}}color')
                borders[side] = {'sz': sz_v, 'color': color_v}
        if borders:
            props['pBdr'] = borders
    shd = pPr.find(w('shd'))
    if shd is not None:
        props['shd'] = {
            'val': shd.get(f'{{{W}}}val', ''),
            'color': shd.get(f'{{{W}}}color', ''),
            'fill': shd.get(f'{{{W}}}fill', ''),
        }
    keepLines = pPr.find(w('keepLines'))
    if keepLines is not None:
        props['keepLines'] = True
    keepNext = pPr.find(w('keepNext'))
    if keepNext is not None:
        props['keepNext'] = True
    return props
def para_runs(p_elem):
    result = []
    for r in p_elem.findall(w('r')):
        rPr = r.find(w('rPr'))
        t_el = r.find(w('t'))
        t = t_el.text if t_el is not None and t_el.text else ''
        props = fmt_run_props(rPr)
        fldChar = r.find(w('fldChar'))
        if fldChar is not None:
            t = f'{{FIELD:{fldChar.get(f"{{{W}}}fldCharType", "")}}}'
        instrText = r.find(w('instrText'))
        if instrText is not None and instrText.text:
            t = f'{{INSTR:{instrText.text}}}'
        ptab = r.find(w('ptab'))
        if ptab is not None:
            props['ptab'] = ptab.get(f'{{{W}}}alignment', '')
            props['ptab_rel'] = ptab.get(f'{{{W}}}relativeTo', '')
        result.append((t, props))
    return result
def classify_text(text):
    if not text.strip():
        return 'whitespace'
    has_cjk = bool(re.search(r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]', text))
    has_en = bool(re.search(r'[a-zA-Z]', text))
    has_digit = bool(re.search(r'[0-9]', text))
    if has_cjk and not has_en and not has_digit:
        return 'chinese'
    if has_en and not has_cjk and not has_digit:
        return 'english'
    if has_digit and not has_cjk and not has_en:
        return 'digit'
    return 'mixed'

class DocxParser:
    def __init__(self, path):
        self.path = path
        self.zip = zipfile.ZipFile(path)
        self.doc_xml = self._read_xml('word/document.xml')
        self.styles_xml = self._read_xml('word/styles.xml')
        self._rels = self._read_rels()
        self.header_xml = self._read_default_hf('header')
        self.footer_xml = self._read_default_hf('footer')
        self.footnotes_xml = self._read_xml('word/footnotes.xml')
        self.body = self.doc_xml.find(f'.//{w("body")}')

    def _read_rels(self):
        rels = {}
        el = self._read_xml('word/_rels/document.xml.rels')
        if el is None:
            return rels
        for rel in el:
            id_ = rel.get('Id')
            target = rel.get('Target', '')
            if id_ and ('header' in target or 'footer' in target):
                if target.startswith('/'):
                    target = target.lstrip('/')
                else:
                    target = 'word/' + target
                rels[id_] = target
        return rels

    def _read_default_hf(self, kind, fallback_tpl='word/{kind}1.xml'):
        target = None
        if self.doc_xml is not None:
            sectPrs = self.doc_xml.findall(f'.//{w("sectPr")}')
            for sectPr in reversed(sectPrs):
                for ref in sectPr.findall(w(f'{kind}Reference')):
                    if ref.get(f'{{{W}}}type', '') in ('default', '', None):
                        rid = ref.get(f'{{{R}}}id')
                        target = self._rels.get(rid)
                        if target:
                            break
                if target:
                    break
        if not target:
            target = f'word/{kind}1.xml'
        return self._read_xml(target)

    def _read_xml(self, fname):
        try:
            data = self.zip.read(fname)
            return ET.fromstring(data)
        except (KeyError, ET.ParseError):
            return None

    def parse_page_layout(self):
        result = {}
        if self.body is None:
            return result
        sectPrs = self.body.findall(w('sectPr'))
        if not sectPrs:
            return result
        sectPr = sectPrs[-1]
        pgSz = sectPr.find(w('pgSz'))
        if pgSz is not None:
            result['width'] = pgSz.get(f'{{{W}}}w')
            result['height'] = pgSz.get(f'{{{W}}}h')
        pgMar = sectPr.find(w('pgMar'))
        if pgMar is not None:
            for k in ['top', 'right', 'bottom', 'left', 'header', 'footer']:
                v = pgMar.get(f'{{{W}}}{k}')
                if v:
                    result[f'margin_{k}'] = v
        cols = sectPr.find(w('cols'))
        if cols is not None:
            result['col_count'] = cols.get(f'{{{W}}}num', '1')
            result['col_space'] = cols.get(f'{{{W}}}space', '0')
        return result

    def parse_header_footer(self):
        result = {'header': None, 'footer': None}
        if self.header_xml is not None:
            para = self.header_xml.find(f'.//{w("p")}')
            if para is not None:
                pPr = para.find(w('pPr'))
                pStyle = get_attr(pPr.find(w('pStyle')) if pPr is not None else None, 'val')
                runs = para_runs(para)
                full_text = ''.join(t for t, _ in runs)
                result['header'] = {
                    'pStyle': pStyle, 'text': full_text,
                    'runs': runs, 'pPr': fmt_para_props(pPr),
                }
        if self.styles_xml is not None:
            for s in self.styles_xml.findall(w('style')):
                sid = s.get(f'{{{W}}}styleId', '')
                if sid == 'a6':
                    result['header_style'] = self._style_to_dict(s)
                elif sid == 'a8':
                    result['footer_style'] = self._style_to_dict(s)
        if self.footer_xml is not None:
            para = self.footer_xml.find(f'.//{w("p")}')
            if para is not None:
                pPr = para.find(w('pPr'))
                pStyle = get_attr(pPr.find(w('pStyle')) if pPr is not None else None, 'val')
                runs = para_runs(para)
                full_text = ''.join(t for t, _ in runs)
                result['footer'] = {
                    'pStyle': pStyle, 'text': full_text,
                    'runs': runs, 'pPr': fmt_para_props(pPr),
                }
        return result

    def _style_to_dict(self, s_elem):
        d = {}
        d['name'] = get_attr(s_elem.find(w('name')), 'val')
        d['basedOn'] = get_attr(s_elem.find(w('basedOn')), 'val')
        pPr = s_elem.find(w('pPr'))
        if pPr is not None:
            d['pPr'] = fmt_para_props(pPr)
        rPr = s_elem.find(w('rPr'))
        if rPr is not None:
            d['rPr'] = fmt_run_props(rPr)
        return d

    def parse_paragraphs(self, include_tables=False):
        paras = []
        if self.body is None:
            return paras
        for child in self.body:
            tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
            if tag == 'p':
                pPr = child.find(w('pPr'))
                runs = para_runs(child)
                full_text = ''.join(t for t, _ in runs)
                paras.append({
                    'type': 'para', 'pPr': fmt_para_props(pPr),
                    'runs': runs, 'text': full_text, 'element': child,
                })
            elif tag == 'tbl' and include_tables:
                tbl_info = self._parse_table(child)
                paras.append({'type': 'table', 'table': tbl_info, 'text': tbl_info.get('text', '')})
        return paras

    def _parse_table(self, tbl_elem):
        info = {'rows': [], 'cols': 0, 'text': '', 'widths': []}
        grid = tbl_elem.find(f'.//{w("tblGrid")}')
        if grid is not None:
            for gc in grid.findall(w('gridCol')):
                wv = gc.get(f'{{{W}}}w')
                if wv is not None:
                    info['widths'].append(int(wv))
        rows = tbl_elem.findall(f'.//{w("tr")}')
        full_texts = []
        for row in rows:
            cells = row.findall(f'.//{w("tc")}')
            row_data = []
            for cell in cells:
                cell_text = ''
                cell_paras = []
                tcPr = cell.find(w('tcPr'))
                tc_props = {}
                if tcPr is not None:
                    vMerge = tcPr.find(w('vMerge'))
                    if vMerge is not None:
                        tc_props['vMerge'] = vMerge.get(f'{{{W}}}val', 'continue')
                    gridSpan = tcPr.find(w('gridSpan'))
                    if gridSpan is not None:
                        tc_props['gridSpan'] = gridSpan.get(f'{{{W}}}val', '')
                    shd = tcPr.find(w('shd'))
                    if shd is not None:
                        tc_props['shd'] = {'val': shd.get(f'{{{W}}}val', ''), 'fill': shd.get(f'{{{W}}}fill', '')}
                    textDir = tcPr.find(w('textDirection'))
                    if textDir is not None:
                        tc_props['textDirection'] = textDir.get(f'{{{W}}}val', '')
                    tcBorders = tcPr.find(w('tcBorders'))
                    if tcBorders is not None:
                        diag = {}
                        for side in ('tl2br', 'tr2bl'):
                            b = tcBorders.find(w(side))
                            if b is not None:
                                diag[side] = b.get(f'{{{W}}}val', '')
                        if diag:
                            tc_props['diag'] = diag
                for p in cell.findall(w('p')):
                    pt = text_of_para(p)
                    pPr = fmt_para_props(p.find(w('pPr')))
                    runs = para_runs(p)
                    cell_paras.append({'text': pt, 'pPr': pPr, 'runs': runs})
                    cell_text += pt
                row_data.append({'text': cell_text, 'paras': cell_paras, 'tcPr': tc_props})
                full_texts.append(cell_text)
            info['rows'].append(row_data)
            info['cols'] = max(info['cols'], len(row_data))
        info['text'] = '\n'.join(full_texts)
        return info

    def parse_images(self):
        images = []
        if self.body is None:
            return images
        # 先建立 anchor -> 所在段落索引 的對應
        anchor_para = {}
        p_idx = 0
        for child in self.body:
            tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
            if tag == 'p':
                for draw in child.findall(f'.//{{{WP}}}anchor'):
                    anchor_para[id(draw)] = p_idx
                p_idx += 1
        for draw in self.body.iter(f'{{{WP}}}inline'):
            img_info = self._parse_one_image(draw, 'inline')
            if img_info:
                images.append(img_info)
        for draw in self.body.iter(f'{{{WP}}}anchor'):
            img_info = self._parse_one_image(draw, 'anchor')
            if img_info:
                img_info['anchor_p_idx'] = anchor_para.get(id(draw))
                images.append(img_info)
        return images

    def _parse_one_image(self, draw_elem, mode):
        info = {'mode': mode}
        extent = draw_elem.find(f'.//{{{WP}}}extent')
        if extent is not None:
            info['cx'] = extent.get('cx')
            info['cy'] = extent.get('cy')
        simplePos = draw_elem.find(f'.//{{{WP}}}simplePos')
        if simplePos is not None:
            info['simplePos'] = (simplePos.get('x'), simplePos.get('y'))
        if mode == 'anchor':
            posH = draw_elem.find(f'{{{WP}}}positionH')
            posV = draw_elem.find(f'{{{WP}}}positionV')
            if posH is not None:
                info['posHRel'] = posH.get('relativeFrom', '')
                offset = posH.find(f'{{{WP}}}posOffset')
                if offset is not None and offset.text:
                    info['posH'] = int(offset.text)
            if posV is not None:
                info['posVRel'] = posV.get('relativeFrom', '')
                offset = posV.find(f'{{{WP}}}posOffset')
                if offset is not None and offset.text:
                    info['posV'] = int(offset.text)
        wrap = draw_elem.find(f'.//{{{WP}}}wrapTight') or draw_elem.find(f'.//{{{WP}}}wrapSquare') or draw_elem.find(f'.//{{{WP}}}wrapNone') or draw_elem.find(f'.//{{{WP}}}wrapThrough')
        if wrap is not None:
            info['wrap'] = wrap.tag.split('}')[-1]
        blip = draw_elem.find(f'.//{a("blip")}')
        if blip is not None:
            info['embed'] = blip.get(f'{{{R}}}embed', '')
        spPr = draw_elem.find(f'.//{pic("spPr")}')
        if spPr is not None:
            ln = spPr.find(f'.//{a("ln")}')
            if ln is not None:
                info['line'] = {'w': ln.get('w', ''), 'cap': ln.get('cap', '')}
            effectLst = spPr.find(f'.//{a("effectLst")}')
            if effectLst is not None:
                outerShdw = effectLst.find(f'.//{a("outerShdw")}')
                if outerShdw is not None:
                    info['shadow'] = {'dir': outerShdw.get('dir', ''), 'dist': outerShdw.get('dist', ''), 'algn': outerShdw.get('algn', '')}
        if not info.get('line') and not info.get('shadow'):
            spPr2 = draw_elem.find(f'.//{a("spPr")}')
            if spPr2 is not None:
                ln = spPr2.find(f'.//{a("ln")}')
                if ln is not None:
                    info['line'] = {'w': ln.get('w', ''), 'cap': ln.get('cap', '')}
                effectLst = spPr2.find(f'.//{a("effectLst")}')
                if effectLst is not None:
                    outerShdw = effectLst.find(f'.//{a("outerShdw")}')
                    if outerShdw is not None:
                        info['shadow'] = {'dir': outerShdw.get('dir', ''), 'dist': outerShdw.get('dist', ''), 'algn': outerShdw.get('algn', '')}
        return info
