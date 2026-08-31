import os, re, csv, datetime
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory

from scorer.engine import load_exam_list, ScoringEngine

app = Flask(__name__)
app.secret_key = 'odt-scorer-secret-key'
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), 'uploads')
LOG_FILE = os.path.join(UPLOAD_DIR, 'submissions.csv')
ALLOWED_EXT = {'.docx'}

os.makedirs(UPLOAD_DIR, exist_ok=True)

def allowed_file(fname):
    return os.path.splitext(fname)[1].lower() in ALLOWED_EXT

def sanitize(s):
    s = re.sub(r'[^\w.\u4e00-\u9fff-]', '', s)
    return s.strip('._') or 'unknown'

def log_submission(client_ip, student_name, class_id, seat_no, saved_name, exam_name, score):
    is_new = not os.path.isfile(LOG_FILE)
    with open(LOG_FILE, 'a', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(['時間', 'IP', '班級', '座號', '姓名', '檔案', '題組', '分數'])
        w.writerow([datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    client_ip, class_id, seat_no, student_name, saved_name, exam_name, score])

@app.route('/')
def index():
    exams = load_exam_list()
    client_ip = request.remote_addr or 'unknown'
    return render_template('index.html', exams=exams, client_ip=client_ip)

@app.route('/data/<path:filename>')
def serve_data(filename):
    return send_from_directory('data', filename)

@app.route('/score', methods=['POST'])
def score():
    exam_id = request.form.get('exam_id', '')
    if not exam_id:
        flash('請選擇題組')
        return redirect(url_for('index'))

    stage = request.form.get('stage', '').strip()

    student_name = request.form.get('student_name', '').strip()
    if not student_name:
        flash('請輸入姓名')
        return redirect(url_for('index'))

    class_id = request.form.get('class_id', '').strip()
    if not class_id:
        flash('請選擇班級')
        return redirect(url_for('index'))

    seat_no = request.form.get('seat_no', '').strip()
    if not seat_no:
        flash('請輸入座號')
        return redirect(url_for('index'))

    file = request.files.get('file')
    if not file or file.filename == '':
        flash('請選擇檔案')
        return redirect(url_for('index'))
    if not allowed_file(file.filename):
        flash('請上傳 .docx 檔案')
        return redirect(url_for('index'))

    client_ip = request.remote_addr or '0.0.0.0'
    safe_ip = sanitize(client_ip)
    safe_name = sanitize(student_name)

    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    base, ext = os.path.splitext(file.filename)
    safe_base = re.sub(r'\W+', '_', base).strip('_') or 'file'
    tmp_name = f'{safe_name}_{safe_ip}_{ts}_{safe_base}_tmp{ext}'
    tmp_path = os.path.join(UPLOAD_DIR, tmp_name)
    file.save(tmp_path)

    try:
        engine = ScoringEngine(exam_id, tmp_path)
        engine.run(stage=stage)
        summary = engine.summary()
        engine.cleanup()
        score = summary['score']
        saved_name = f'{safe_name}_{safe_ip}_{ts}_{safe_base}_{score}{ext}'
        saved_path = os.path.join(UPLOAD_DIR, saved_name)
        os.rename(tmp_path, saved_path)
        log_submission(client_ip, student_name, class_id, seat_no, saved_name,
                       engine.config.get('name', exam_id), score)
        return render_template('result.html', summary=summary,
                               exam_name=engine.config.get('name', exam_id),
                               saved_name=saved_name)
    except Exception as e:
        try: os.remove(tmp_path)
        except: pass
        flash(f'評分過程發生錯誤: {e}')
        return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
