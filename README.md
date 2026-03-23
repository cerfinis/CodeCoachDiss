# CodeCoach

A Python programming tutor that uses adaptation systems to help you master the language; built with Flask, Pandas, and CodeMirror 5.

## Requirements

- Python 3.10+
- Install the below dependencies:

pip install Flask pandas

## Running the app

1. Unzip the project folder.
2. Navigate to the project directory.
3. Run:

python app.py

4. Open your browser at http://127.0.0.1:5000 or localhost

## Project structure

CodeCoachDiss/
├── app.py              # main application
├── adaptation.py       # adaptation system
├── data/
│   └── item_bank.csv   # Exercise bank (50 Python loop questions)
├── templates/          # HTML layouts with Jinja2
│   ├── index.html
│   ├── pretest.html
│   ├── pretest_result.html
│   ├── exercise.html
│   ├── feedback.html
│   ├── posttest.html
│   └── complete.html
└── requirements.txt

## Usage

- Complete the 3 pretest questions to set your starting difficulty.
- Work through the adaptive exercises where difficulty adjusts automatically.
- Complete the 3 posttest questions to see your learning gain.

## Notes

- All session state is held in memory.
- Sessions reset automatically when returning to the home page.