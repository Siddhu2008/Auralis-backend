import os, sys, random
# Ensure project root is in PYTHONPATH
sys.path.append(os.path.abspath('.'))
# Set API key (replace with actual key if needed)
os.environ['GEMINI_API_KEY'] = 'AIzaSyAt...'
from utils.ai_response import generate_answer

context = [{'content': 'Meeting about budget: total $5000'}]
answers = []
for i in range(5):
    ans = generate_answer(context, 'What is the budget?')
    answers.append(ans)
print('Generated answers:')
for idx, a in enumerate(answers, 1):
    print(f"{idx}: {a}")
