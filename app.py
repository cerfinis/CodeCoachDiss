# imports
from flask import Flask, render_template, request, session, redirect, url_for
import pandas as pd
import os, time, random, csv
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'cs-diss-2026' # later change prob

# creating a mastery model for adaptation methods 
MASTERY_MIN      = 0
MASTERY_MAX      = 5
N_PROMOTE        = 2       # quick correct to promote difficulty
N_DEMOTE         = 2       # demote difficulty
TIME_THRESHOLD   = 30      # time threshold for what counts as a fast answer 
RECENT_WINDOW    = 3       # avoid selecting n (recent_window) items immediately
MAX_ATTEMPTS     = 30      # how many attempts before posttest loads 
DIFFICULTY_ORDER = ['easy', 'medium', 'hard']

# load the filed is codecoach/data
LOG_PATH       = os.path.join(os.path.dirname(__file__), 'data', 'attempts_log.csv')
ITEM_BANK_PATH = os.path.join(os.path.dirname(__file__), 'data', 'item_bank.csv')

# loading the item bank from item_bank.csv
df = pd.DataFrame()
try:
    if os.path.exists(ITEM_BANK_PATH):
        df = pd.read_csv(ITEM_BANK_PATH)
        print(f"Loaded {len(df)} items across difficulties: "
              f"{df['difficulty'].value_counts().to_dict()}")
    else:
        print(f"Item bank not found at: {ITEM_BANK_PATH}")
except Exception as e:
    print(f"[Error loading item bank: {e}")


# code normalisation to ensure the answers work either way
def normalise_code(code: str) -> str:
    if not code:
        return ''
    code = code.replace('\\n', '\n').replace('\\r', '').replace('\\t', '    ') # removing whitespacing etc
    code = code.replace('\r\n', '\n')
    lines = [line.rstrip() for line in code.splitlines()]
    while lines and lines[0].strip() == '':
        lines.pop(0)
    while lines and lines[-1].strip() == '':
        lines.pop()
    return '\n'.join(lines).strip()

# selecting the next question in the process 
def select_next_item(mastery: dict, difficulty: str, recent_ids: list):
    # mastery selection process:
    # 1. avoid recently seen items for later (spaced repetition)
    # 2. fall back for recent difficulties
    # 3. fall back to ANY difficulty so 
    # 4. absolute fallback where failure is high
    
    # picking item with the lowest mastery
    def pick_lowest_mastery(subset):
        if subset.empty:
            return None
        ids = subset['id'].tolist()
        scored = [(i, mastery.get(str(i), 0)) for i in ids]
        min_m = min(s for _, s in scored)
        return random.choice([i for i, s in scored if s == min_m])

    pools = [
        df[(df['difficulty'] == difficulty) & (~df['id'].isin(recent_ids))],
        df[df['difficulty'] == difficulty],
        df[~df['id'].isin(recent_ids)],
        df,
    ]
    for pool in pools:
        result = pick_lowest_mastery(pool)
        if result is not None:
            return result
    return None

# applying difficulty for adaptation
def apply_difficulty_rules(current: str, quick_streak: int, consec_wrong: int):
    # difficulty transitions placed by rules:
    # promote: N_PROMOTE continuously correct, rank up to the next difficulty
    # demote:  N_DEMOTE  consecutively wrong, demote difficulty
    # return the difficulty, streak, and consecutive wrongs
    idx = DIFFICULTY_ORDER.index(current)
    new = current

    if quick_streak >= N_PROMOTE and idx < len(DIFFICULTY_ORDER) - 1:
        new = DIFFICULTY_ORDER[idx + 1]
        quick_streak = 0        # reset after promotion

    if consec_wrong >= N_DEMOTE and idx > 0:
        new = DIFFICULTY_ORDER[idx - 1]
        consec_wrong = 0        # reset after demotion

    return new, quick_streak, consec_wrong

# append a row to the attempts csv log
def log_attempt(pid, item_id, difficulty, correct, time_taken, mastery_after, hint_used):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    exists = os.path.exists(LOG_PATH)
    with open(LOG_PATH, 'a', newline='') as f:
        w = csv.writer(f)
        if not exists:
            # data
            w.writerow(['timestamp', 'participant_id', 'item_id', 'difficulty',
                        'correct', 'time_taken_s', 'mastery_after', 'hint_used'])
        w.writerow([
            datetime.utcnow().isoformat(), pid, item_id, difficulty,
            int(correct), round(time_taken, 2), mastery_after, int(hint_used)
        ])

# routes to go 

# homepage route
@app.route('/')
def home():
    session.clear()
    return render_template('index.html')


# route for pretest (load pretest.html)
@app.route('/pretest', methods=['GET', 'POST'])
def pretest():
    # pretest basic questions
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
        session['participant_id'] = os.urandom(4).hex()   # anonymous 8 character hex ID

        # starting difficulty based on pretest performance
        session['difficulty']     = 'medium' if score == 3 else 'easy'

        # initialising our mastery model here with default values
        session['mastery']        = {} 
        session['quick_streak']   = 0  
        session['consec_wrong']   = 0   
        session['hint_count']     = 0
        session['recent_ids']     = [] 
        session['total_attempts'] = 0

        return redirect(url_for('pretest_result'))

    return render_template('pretest.html', questions=questions)


# show the results of the pretest
@app.route('/pretest_result')
def pretest_result():
    score    = session.get('pre_score', 0)
    first_id = select_next_item(
        session.get('mastery', {}),
        session.get('difficulty', 'easy'),
        session.get('recent_ids', [])
    )
    return render_template('pretest_result.html', score=score, first_id=first_id)

# loading exercises from item_bank
@app.route('/exercise/<int:item_id>')
def show_exercise(item_id):
    row = df[df['id'] == item_id]
    if row.empty:
        return f"Exercise {item_id} not found", 404 # in case of error

    hint_val = row['hint'].values[0] if 'hint' in row.columns else None
    hint     = None if pd.isna(hint_val) else hint_val
    mastery  = session.get('mastery', {})

    # current item
    session['current_item_start'] = time.time()

    # rendering
    return render_template(
        'exercise.html',
        question=row['question'].values[0],
        hint=hint,
        item_id=item_id,
        difficulty=row['difficulty'].values[0],
        current_mastery=mastery.get(str(item_id), 0),
        mastery_max=MASTERY_MAX,
        attempt_num=session.get('total_attempts', 0) + 1,
        max_attempts=MAX_ATTEMPTS,
    )

# attempt route
@app.route('/attempt', methods=['POST'])
def attempt():
    # establishing errors in case
    item_id_str = request.form.get('item_id', '')
    if not item_id_str.isdigit():
        return "<h1>Error</h1><p>Invalid item ID</p><a href='/'>Back</a>", 400

    item_id   = int(item_id_str)
    hint_used = request.form.get('hint_requested', 'false') == 'true'

    row = df[df['id'] == item_id]
    if row.empty:
        return "<h1>Error</h1><p>Exercise not found!</p><a href='/'>Back</a>", 404

    item_diff  = row['difficulty'].values[0]
    is_correct = (normalise_code(request.form.get('code', ''))
                  == normalise_code(row['correct_answer'].values[0]))
    time_taken = time.time() - session.get('current_item_start', time.time())

    # updating mastery score per question
    mastery = dict(session.get('mastery', {}))
    key  = str(item_id)
    prev = mastery.get(key, 0)
    mastery[key] = min(prev + 1, MASTERY_MAX) if is_correct else max(prev - 1, MASTERY_MIN) # rise in mastery if correct
    session['mastery'] = mastery

    # updating/incrementing/decrementing streak counter
    qs = session.get('quick_streak', 0)
    cw = session.get('consec_wrong', 0)

    if is_correct:
        cw = 0
        qs = qs + 1 if time_taken < TIME_THRESHOLD else 0   # only quick corrects count
    else:
        qs = 0
        cw += 1

    # applying difficulty rules; initially easy to hard depending on stats
    old_diff          = session.get('difficulty', 'easy')
    new_diff, qs, cw  = apply_difficulty_rules(old_diff, qs, cw)

    session['difficulty']     = new_diff
    session['quick_streak']   = qs
    session['consec_wrong']   = cw
    session['total_attempts'] = session.get('total_attempts', 0) + 1
    if hint_used:
        session['hint_count'] = session.get('hint_count', 0) + 1

    # updating recent times window for spaced repetition
    recent = list(session.get('recent_ids', []))
    recent.append(item_id)
    session['recent_ids'] = recent[-RECENT_WINDOW:]

    # logging the attempt
    log_attempt(
        session.get('participant_id', 'unknown'),
        item_id, item_diff, is_correct, time_taken,
        mastery[key], hint_used
    )

    # ending the session after max attempts; pushing to posttest
    total = session.get('total_attempts', 0)
    if total >= MAX_ATTEMPTS:
        return redirect(url_for('posttest'))

    # selecting the next question
    next_id = select_next_item(mastery, new_diff, session['recent_ids'])

    # estabslishing a difficulty change
    diff_message = None
    if new_diff != old_diff:
        if DIFFICULTY_ORDER.index(new_diff) > DIFFICULTY_ORDER.index(old_diff):
            # moves if questions are correct
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
    )


@app.route('/posttest', methods=['GET', 'POST'])
def posttest():
    # pretest mirror to measure how much the user has learned, same questions
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

        # log the final session
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        summary_path = os.path.join(os.path.dirname(LOG_PATH), 'session_summary.csv')
        exists = os.path.exists(summary_path)
        with open(summary_path, 'a', newline='') as f:
            w = csv.writer(f)
            if not exists:
                w.writerow(['timestamp', 'participant_id', 'pre_score', 'post_score',
                            'total_attempts', 'hint_count', 'final_difficulty'])
            w.writerow([
                datetime.utcnow().isoformat(),
                session.get('participant_id', 'unknown'),
                session.get('pre_score', 0), score,
                session.get('total_attempts', 0),
                session.get('hint_count', 0),
                session.get('difficulty', 'easy'),
            ])

        return redirect(url_for('session_complete'))

    return render_template('posttest.html', questions=questions)

# establishing a complete screen
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
    app.run(debug=True)