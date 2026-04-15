import os
from utils.ai_service_unified import ai_service


def summarize_text(text, summary_type='report'):
    """
    Analyzes document/transcript and generates a summary using the unified AI service.
    """
    if not text:
        return "No data available to summarize."

    type_prompts = {
        'report': "Provide a comprehensive technical report with Executive Overview, Key Points, Decisions, and Action Items.",
        'short': "Provide a concise 2-sentence summary of the main points.",
        'bullets': "Provide a bulleted list of the most important information.",
        'insights': "Extract the 5 most critical strategic insights or takeaways.",
        'study': "Create structured study notes with key terms, definitions, and a summary of core concepts."
    }

    selected_prompt = type_prompts.get(summary_type, type_prompts['report'])

    prompt = f"""
    You are an expert AI productivity assistant. Analyze the text below and generate a summary.
    
    INSTRUCTION: {selected_prompt}
    
    SPECIAL INSTRUCTION: Identify the most critical technical or action-oriented sentences. Enclose exactly 3-5 of these critical sections in <high> tags like this: <high>this is an important part</high>.
    
    Text:
    {text[:15000]}
    
    Please provide the output in Markdown format.
    """

    try:
        # Using a model that supports high-quality reasoning
        result = ai_service.generate_content(prompt, model='gemini-2.0-flash')
        if result:
            return result
        return "Summary generation temporarily unavailable."
    except Exception as e:
        print(f"Summarization Error: {e}")
        return f"Error generating summary: {str(e)}"
