import pandas as pd
import os
import random

# constants
MASTERY_MIN = 0
MASTERY_MAX = 5
N_PROMOTE = 2  # quick correct to promote difficulty
N_DEMOTE = 2  # demote difficulty
TIME_THRESHOLD = 30  # time threshold for what counts as a fast answer
RECENT_WINDOW = 3  # avoid selecting n items immediately
MAX_ATTEMPTS = 30  # how many attempts before posttest
DIFFICULTY_ORDER = ['easy', 'medium', 'hard']


# creating a spaced repetition system here

# spaced repetition intervals maps mastery level to the minimum attempts before showing again
# low mastery items are reviewed sooner and high mastery items are spaced further apart
SR_INTERVALS = {
    0: 1,   # unseen: show very soon
    1: 2,   # low mastery: short gap
    2: 4,   # building mastery: moderate gap
    3: 6,   # consolidating: space out further
    4: 9,   # almost mastery: longer interval
    5: 12,  # full mastery: long interval, prioritise less
}

# loading the item bank
def load_item_bank():
    ITEM_BANK_PATH = os.path.join(os.path.dirname(__file__), 'data', 'item_bank.csv')
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
    return df

# code normalisation to ensure answer works either way
def normalise_code(code: str) -> str:
    if not code:
        return ''
    code = code.replace('\\n', '\n').replace('\\r', '').replace('\\t', '    ')  # removing whitespacing etc
    code = code.replace('\r\n', '\n')
    lines = [line.rstrip() for line in code.splitlines()]
    while lines and lines[0].strip() == '':
        lines.pop(0)
    while lines and lines[-1].strip() == '':
        lines.pop()
    return '\n'.join(lines).strip()

# returns ids that are due for review 
# an item is due depending on this: current_attempt-last_seen_attempt>= SR_INTERVALS[mastery_level]
# items never seen before are always considered due
def get_due_items(df: pd.DataFrame, mastery: dict, last_seen: dict, attempt_num: int):
    due = []
    for item_id in df['id'].tolist():
        key = str(item_id)
        m = mastery.get(key, 0)
        interval = SR_INTERVALS.get(m, 1)
        seen_at = last_seen.get(key)  # attempt number when last attempted

        if seen_at is None:
            due.append(item_id)  # never seen is always due
        elif (attempt_num - seen_at) >= interval:
            due.append(item_id)  # enough attempts have passed so due for review

    return due

# selecting the next question in the process
# last_seen: dict of {str(item_id): attempt_num_when_last_seen} for spaced repetition
# attempt_num: current total attempt count, used to compute spacing intervals
def select_next_item(df: pd.DataFrame, mastery: dict, difficulty: str, recent_ids: list,
                     last_seen: dict | None = None, attempt_num: int = 0):
    # mastery and spaced repetition selection process:
    # 1. prefer due items at target difficulty excluding recent
    # 2. fall back to any due items at target difficulty
    # 3. fall back to due items at any difficulty excluding recent
    # 4. fall back to target difficulty, excluding recent
    # 5. fall back to target difficulty regardless
    # 6. fall back to ANY item 

    if last_seen is None:
        last_seen = {}

    # picking item with the lowest mastery from a subset
    def pick_lowest_mastery(subset):
        if subset.empty:
            return None
        ids = subset['id'].tolist()
        scored = [(i, mastery.get(str(i), 0)) for i in ids]
        min_m = min(s for _, s in scored)
        return random.choice([i for i, s in scored if s == min_m])

    # items whose spaced repetition interval has elapsed
    due_ids = get_due_items(df, mastery, last_seen, attempt_num)
    due_mask = df['id'].isin(due_ids)
    recent_mask = ~df['id'].isin(recent_ids)
    diff_mask = df['difficulty'] == difficulty

    pools = [
        df[diff_mask & due_mask & recent_mask],   # due + target difficulty + not recent
        df[diff_mask & due_mask],                  # due + target difficulty
        df[due_mask & recent_mask],                # due + any difficulty + not recent
        df[diff_mask & recent_mask],               # target difficulty + not recent
        df[diff_mask],                             # target difficulty regardless
        df,                                        # absolute fallback
    ]
    for pool in pools:
        result = pick_lowest_mastery(pool)
        if result is not None:
            print(f"[SR] attempt={attempt_num} | due_ids={due_ids} | selected={result} | last_seen={last_seen}")
            return result

    print(f"[SR] attempt={attempt_num} | due_ids={due_ids} | selected=None | last_seen={last_seen}")
    return None

# applying difficulty for adaptation
def apply_difficulty_rules(current: str, quick_streak: int, consec_wrong: int):
    # difficulty transitions placed by rules:
    # promote: N_PROMOTE continuously correct, rank up to the next difficulty
    # demote: N_DEMOTE consecutively wrong, demote difficulty
    # return the difficulty, streak, and consecutive wrongs
    idx = DIFFICULTY_ORDER.index(current)
    new = current

    if quick_streak >= N_PROMOTE and idx < len(DIFFICULTY_ORDER) - 1:
        new = DIFFICULTY_ORDER[idx + 1]
        quick_streak = 0  # reset after promotion

    if consec_wrong >= N_DEMOTE and idx > 0:
        new = DIFFICULTY_ORDER[idx - 1]
        consec_wrong = 0  # reset after demotion

    return new, quick_streak, consec_wrong