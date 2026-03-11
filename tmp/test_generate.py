import os
os.environ['GEMINI_API_KEY'] = 'AIzaSyAt...'
from utils.ai_response import generate_answer
context = [{'content': 'Meeting about budget: total $5000'}]
answers = []
for i in range(5):
    ans = generate_answer(context, 'What is the budget?')
    answers.append(ans)
print('Answers:', answers)
