import json, os
from .parser import DocxParser
from .checks import REGISTRY

EXAMS_DIR = os.path.join(os.path.dirname(__file__), 'exams')

def load_exam_list():
    """Return list of {id, name} for all available exams."""
    exams = []
    if not os.path.isdir(EXAMS_DIR):
        return exams
    for fname in sorted(os.listdir(EXAMS_DIR)):
        if fname.endswith('.json') and not fname.startswith('._'):
            exam_id = fname[:-5]
            try:
                with open(os.path.join(EXAMS_DIR, fname), encoding='utf-8') as f:
                    cfg = json.load(f)
                exams.append({'id': exam_id, 'name': cfg.get('name', exam_id),
                              'stages': cfg.get('stages', [])})
            except Exception:
                exams.append({'id': exam_id, 'name': exam_id})
    return exams

class ScoreResult:
    def __init__(self, check_id, symbol, points, label):
        self.check_id = check_id
        self.symbol = symbol
        self.max_points = points
        self.label = label
        self.passed = True
        self.deduct = 0
        self.reason = ''

class ScoringEngine:
    def __init__(self, exam_id, student_docx_path):
        self.exam_id = exam_id
        self.config = self._load_config(exam_id)
        self.student = DocxParser(student_docx_path)
        self._ref_cache = {}
        self.ref = self._get_ref(self.config.get('ref_file', ''))
        self.results = []

    def _load_config(self, exam_id):
        path = os.path.join(EXAMS_DIR, f'{exam_id}.json')
        with open(path, encoding='utf-8') as f:
            return json.load(f)

    def _get_ref(self, ref_rel):
        if not ref_rel:
            return None
        if ref_rel in self._ref_cache:
            return self._ref_cache[ref_rel]
        ref_path = os.path.join(EXAMS_DIR, ref_rel)
        ref = DocxParser(ref_path) if os.path.isfile(ref_path) else None
        self._ref_cache[ref_rel] = ref
        return ref

    def run(self, stage=None):
        for item in self.config.get('checks', []):
            stages = item.get('stages') or ([item['stage']] if item.get('stage') else [])
            if stage is not None and stage not in stages:
                continue
            by_stage = item.get('by_stage') or {}
            params = {**self.config, **item, **(by_stage.get(stage) or {})}
            self.results.append(self._run_one(item, params, stage))
        return self.results

    def _run_one(self, item, params, stage):
        cid = item['id']
        result = ScoreResult(cid, params.get('symbol', item.get('symbol', '')),
                             params.get('points', item.get('points', 0)),
                             params.get('label', item['label']))
        if cid in REGISTRY:
            try:
                ref = self._get_ref(params.get('ref_file') or self.config.get('ref_file', ''))
                deduct, reason = REGISTRY[cid](self.student, ref, params)
                if deduct > 0:
                    result.passed = False
                    result.deduct = deduct
                    result.reason = reason
            except Exception as e:
                result.passed = False
                result.deduct = result.max_points
                result.reason = f'錯誤: {e}'
        else:
            result.passed = False
            result.deduct = result.max_points
            result.reason = f'未實裝檢查: {cid}'
        return result

    def summary(self):
        total_deduct = sum(r.deduct for r in self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)
        return {
            'total_deduct': total_deduct,
            'score': max(0, 100 - total_deduct),
            'passed': passed,
            'failed': failed,
            'results': self.results,
        }

    def cleanup(self):
        self.student.zip.close()
        if self.ref:
            self.ref.zip.close()
