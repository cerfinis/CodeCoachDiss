# imports
from flask import Flask, render_template, request, session, redirect, url_for
import time
import secrets

import pandas as pd
from adaptation import (DIFFICULTY_ORDER, load_item_bank, normalise_code, select_next_item,
                        apply_difficulty_rules, MASTERY_MIN, MASTERY_MAX, TIME_THRESHOLD,
                        RECENT_WINDOW, MAX_ATTEMPTS)  # variables from adaptation.py

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)  # cryptographically secure secret key

# load item bank once at startup
df = load_item_bank()

@app.route('/')
def home():
    session.clear()
    return render_template('index.html')

@app.route('/pretest', methods=['GET', 'POST'])
def pretest():
    questions = [
        {'id': 'pre1', 'question': 'Print numbers 1 to 3 with a for loop.',
         'correct': 'for i in range(1, 4):\n    print(i)'},
        {'id': 'pre2', 'question': 'Use a while loop to print "Hello" twice.',
         'correct': 'count = 0\nwhile count < 2:\n    print("Hello")\n    count += 1'},
        {'id': 'pre3', 'question': 'Sum numbers from 1 to 5 and print the total.',
         'correct': 'total = 0\nfor i in range(1, 6):\n    total += i\nprint(total)'}
    ]

    if request.method == 'POST':
        score = sum(
            1 for q in questions
            if normalise_code(request.form.get(f'code_{q["id"]}', ''))
               == normalise_code(q['correct'])
        )
        session['pre_score']      = score
        session['difficulty']     = 'medium' if score == 3 else 'easy'
        session['mastery']        = {}
        session['quick_streak']   = 0
        session['consec_wrong']   = 0
        session['hint_count']     = 0
        session['recent_ids']     = []
        session['total_attempts'] = 0
        session['last_seen']      = {}
        return redirect(url_for('pretest_result'))

    return render_template('pretest.html', questions=questions)

@app.route('/pretest_result')
def pretest_result():
    score    = session.get('pre_score', 0)
    first_id = select_next_item(
        df,
        session.get('mastery', {}),
        session.get('difficulty', 'easy'),
        session.get('recent_ids', []),
        last_seen=session.get('last_seen', {}),
        attempt_num=session.get('total_attempts', 0)
    )
    return render_template('pretest_result.html', score=score, first_id=first_id)

@app.route('/exercise/<int:item_id>')
def show_exercise(item_id):
    row = df[df['id'] == item_id]
    if row.empty:
        return f"Exercise {item_id} not found", 404

    hint_val    = row['hint'].values[0] if 'hint' in row.columns else None
    hint        = None if pd.isna(hint_val) else hint_val.replace('\\n', '\n')

    example_val = row['example'].values[0] if 'example' in row.columns else None
    example     = None if pd.isna(example_val) else example_val.replace('\\n', '\n')

    # expected output for Pyodide output based grading
    exp_val         = row['expected_output'].values[0] if 'expected_output' in row.columns else None
    expected_output = None if pd.isna(exp_val) else str(exp_val)

    mastery = session.get('mastery', {})
    session['current_item_start'] = time.time()

    return render_template(
        'exercise.html',
        question=row['question'].values[0],
        hint=hint,
        example=example,
        expected_output=expected_output,
        item_id=item_id,
        difficulty=row['difficulty'].values[0],
        current_mastery=mastery.get(str(item_id), 0),
        mastery_max=MASTERY_MAX,
        attempt_num=session.get('total_attempts', 0) + 1,
        max_attempts=MAX_ATTEMPTS,
    )

@app.route('/attempt', methods=['POST'])
def attempt():
    item_id_str = request.form.get('item_id', '')
    if not item_id_str.isdigit():
        return "<h1>Error</h1><p>Invalid item ID</p><a href='/'>Back</a>", 400

    # limit submission length to prevent oversized payloads
    code_input = request.form.get('code', '')
    if len(code_input) > 5000:
        return "<h1>Error</h1><p>Submission too long.</p><a href='/'>Back</a>", 400

    item_id   = int(item_id_str)
    hint_used = request.form.get('hint_requested', 'false') == 'true'

    # pyodide output based grading result passed from client
    pyodide_graded  = request.form.get('pyodide_graded', 'false') == 'true'
    pyodide_correct = request.form.get('pyodide_correct', 'false') == 'true'

    row = df[df['id'] == item_id]
    if row.empty:
        return "<h1>Error</h1><p>Exercise not found!</p><a href='/'>Back</a>", 404

    correct_answer_raw = row['correct_answer'].values[0]

    # use Pyodide output-based result if available otherwise fall back to string comparison
    if pyodide_graded:
        is_correct = pyodide_correct
    else:
        is_correct = (normalise_code(code_input) == normalise_code(correct_answer_raw))

    time_taken = time.time() - session.get('current_item_start', time.time())

    # update mastery score
    mastery = dict(session.get('mastery', {}))
    key     = str(item_id)
    prev    = mastery.get(key, 0)
    mastery[key] = min(prev + 1, MASTERY_MAX) if is_correct else max(prev - 1, MASTERY_MIN)
    session['mastery'] = mastery

    # update streak counters
    qs = session.get('quick_streak', 0)
    cw = session.get('consec_wrong', 0)
    if is_correct:
        cw = 0
        qs = qs + 1 if time_taken < TIME_THRESHOLD else 0
    else:
        qs = 0
        cw += 1

    # apply difficulty rules
    old_diff         = session.get('difficulty', 'easy')
    new_diff, qs, cw = apply_difficulty_rules(old_diff, qs, cw)

    session['difficulty']     = new_diff
    session['quick_streak']   = qs
    session['consec_wrong']   = cw
    session['total_attempts'] = session.get('total_attempts', 0) + 1
    if hint_used:
        session['hint_count'] = session.get('hint_count', 0) + 1

    # spaced repetition
    last_seen       = dict(session.get('last_seen', {}))
    last_seen[key]  = session.get('total_attempts', 0)
    session['last_seen'] = last_seen

    # recency window
    recent = list(session.get('recent_ids', []))
    recent.append(item_id)
    session['recent_ids'] = recent[-RECENT_WINDOW:]

    total = session.get('total_attempts', 0)
    if total >= MAX_ATTEMPTS:
        return redirect(url_for('posttest'))

    next_id = select_next_item(
        df, mastery, new_diff, session['recent_ids'],
        last_seen=session.get('last_seen', {}),
        attempt_num=session.get('total_attempts', 0)
    )

    diff_message = None
    if new_diff != old_diff:
        if DIFFICULTY_ORDER.index(new_diff) > DIFFICULTY_ORDER.index(old_diff):
            diff_message = f"Great work! Moving up to {new_diff} exercises."
        else:
            diff_message = f"Let's remain at {new_diff} for now."

    return render_template(
        'feedback.html',
        feedback_text="Correct! Well done." if is_correct else "Not quite but keep going!",
        feedback_class='correct' if is_correct else 'incorrect',
        next_id=next_id,
        diff_message=diff_message,
        new_difficulty=new_diff,
        mastery_score=mastery[key],
        mastery_max=MASTERY_MAX,
        is_correct=is_correct,
        attempt_num=total,
        max_attempts=MAX_ATTEMPTS,
        # corrective feedback shows correct answer on incorrect attempts
        correct_answer=normalise_code(correct_answer_raw) if not is_correct else None,
    )

@app.route('/posttest', methods=['GET', 'POST'])
def posttest():
    questions = [
        {'id': 'post1', 'question': 'Print numbers 1 to 3 with a for loop.',
         'correct': 'for i in range(1, 4):\n    print(i)'},
        {'id': 'post2', 'question': 'Use a while loop to print "Hello" twice.',
         'correct': 'count = 0\nwhile count < 2:\n    print("Hello")\n    count += 1'},
        {'id': 'post3', 'question': 'Sum numbers from 1 to 5 and print the total.',
         'correct': 'total = 0\nfor i in range(1, 6):\n    total += i\nprint(total)'}
    ]

    if request.method == 'POST':
        score = sum(
            1 for q in questions
            if normalise_code(request.form.get(f'code_{q["id"]}', ''))
               == normalise_code(q['correct'])
        )
        session['post_score'] = score
        return redirect(url_for('session_complete'))

    return render_template('posttest.html', questions=questions)

@app.route('/complete')
def session_complete():
    return render_template(
        'complete.html',
        pre_score=session.get('pre_score', 0),
        post_score=session.get('post_score', 0),
        total_attempts=session.get('total_attempts', 0),
        hint_count=session.get('hint_count', 0),
        final_difficulty=session.get('difficulty', 'easy'),
    )

if __name__ == '__main__':
    app.run(debug=False)  