"""
Auralis AI Meeting Agent — Synthetic Training Data Generator
Generates ~65,000 labeled samples for 3 model categories:
  1. Intent Classification (~25,000 samples)
  2. Q&A Detection (~20,000 samples)
  3. Meeting Context / Action Items (~20,000 samples)
"""
import csv
import os
import random
import itertools

SEED = 42
random.seed(SEED)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# VOCABULARY POOLS
# ─────────────────────────────────────────────────────────────────────────────
NAMES = [
    "Alice", "Bob", "Charlie", "Diana", "Ethan", "Fiona", "George", "Hannah",
    "Ian", "Julia", "Kevin", "Laura", "Mike", "Nina", "Oscar", "Priya",
    "Quinn", "Rachel", "Sam", "Tina", "Uma", "Victor", "Wendy", "Xavier",
    "Yara", "Zach", "Amit", "Bella", "Carlos", "Deepa", "Elena", "Farid",
    "Grace", "Hiro", "Isha", "John", "Kira", "Leo", "Maya", "Nate",
]

TOPICS = [
    "Q3 budget", "product launch", "marketing campaign", "hiring plan",
    "sprint review", "client feedback", "infrastructure upgrade", "sales pipeline",
    "UI redesign", "database migration", "API integration", "security audit",
    "performance review", "team standup", "project timeline", "vendor contract",
    "customer onboarding", "training session", "quarterly goals", "feature roadmap",
    "compliance review", "user research", "A/B testing", "deployment strategy",
    "bug triage", "code review", "design sprint", "data pipeline",
    "pricing model", "partnership deal", "investor update", "board meeting",
]

PROJECTS = [
    "Project Alpha", "Project Beta", "Phoenix Initiative", "Titan Build",
    "Operation Mercury", "Horizon 2.0", "Nexus Platform", "CloudFirst",
    "DataVault", "UserInsight", "Pipeline Pro", "MobileEdge",
    "SmartDash", "DevOps Central", "Growth Engine", "AI Core",
]

DOMAINS = [
    "engineering", "marketing", "sales", "finance", "HR", "operations",
    "design", "product", "legal", "customer success", "data science", "security",
]

TIMES = [
    "tomorrow at 10 AM", "next Monday at 2 PM", "Friday at 3:30 PM",
    "today at 4 PM", "tomorrow morning", "next Wednesday at 11 AM",
    "this afternoon at 5 PM", "March 15 at 9 AM", "end of day",
    "next sprint", "the day after tomorrow", "this Thursday at noon",
]

EMAILS = [f"{n.lower()}@company.com" for n in NAMES[:20]]

MEETING_SUBJECTS = [
    "sprint planning", "product demo", "design review", "weekly sync",
    "all-hands", "retrospective", "architecture review", "stakeholder check-in",
    "one-on-one", "brainstorming session", "kickoff meeting", "status update",
    "incident review", "training workshop", "roadmap alignment", "budget review",
]


# ─────────────────────────────────────────────────────────────────────────────
# 1. INTENT CLASSIFICATION DATA (~25,000 samples)
# ─────────────────────────────────────────────────────────────────────────────
def _intent_templates():
    """Returns list of (template_string, label) tuples."""
    templates = []

    # schedule (~3000)
    for topic in TOPICS:
        for time in TIMES:
            templates.append((f"Schedule a meeting about {topic} {time}", "schedule"))
        for name in random.sample(NAMES, 8):
            templates.append((f"Set up a call with {name} about {topic}", "schedule"))
    templates += [
        ("Can you book a room for tomorrow?", "schedule"),
        ("I need to set up a meeting", "schedule"),
        ("Let's have a sync this week", "schedule"),
        ("Block my calendar for a design review", "schedule"),
        ("Arrange a team standup next week", "schedule"),
    ]

    # email / draft_email (~3000)
    for name in NAMES:
        templates.append((f"Send an email to {name} about the project update", "email"))
        templates.append((f"Draft a message to {name.lower()}@company.com", "draft_email"))
        templates.append((f"Email {name} the meeting notes", "email"))
    for topic in TOPICS:
        templates.append((f"Draft a recap email about {topic}", "draft_email"))
        templates.append((f"Send a follow-up about {topic}", "email"))
        templates.append((f"Compose a message about the {topic} decisions", "draft_email"))

    # task (~2500)
    for topic in TOPICS:
        templates.append((f"Add a task to follow up on {topic}", "task"))
        templates.append((f"Remind me to check {topic} by end of week", "task"))
        templates.append((f"Create an action item for {topic}", "task"))
    for name in random.sample(NAMES, 15):
        templates.append((f"Assign {name} to review the document", "task"))
        templates.append((f"Set a reminder to call {name}", "task"))

    # question (~3000)
    for topic in TOPICS:
        templates.append((f"What was decided about {topic}?", "question"))
        templates.append((f"Can you summarize the discussion on {topic}?", "question"))
        templates.append((f"Who is responsible for {topic}?", "question"))
    for project in PROJECTS:
        templates.append((f"What's the status of {project}?", "question"))
        templates.append((f"When is {project} launching?", "question"))

    # meeting_query (~2500)
    for subject in MEETING_SUBJECTS:
        templates.append((f"Show me notes from the last {subject}", "meeting_query"))
        templates.append((f"What happened in the {subject}?", "meeting_query"))
        templates.append((f"Pull up the {subject} transcript", "meeting_query"))
    for name in random.sample(NAMES, 10):
        templates.append((f"What did {name} say in the meeting?", "meeting_query"))
        templates.append((f"Did {name} mention anything about the deadline?", "meeting_query"))

    # cancel (~1500)
    for topic in TOPICS:
        templates.append((f"Cancel the meeting about {topic}", "cancel"))
        templates.append((f"Remove the {topic} session from my calendar", "cancel"))
    templates += [
        ("Cancel my next meeting", "cancel"),
        ("Drop the call scheduled for tomorrow", "cancel"),
        ("Please cancel all meetings today", "cancel"),
    ]

    # modify (~1500)
    for topic in TOPICS:
        templates.append((f"Move the {topic} meeting to next week", "modify"))
        templates.append((f"Change the time of {topic} discussion to 3 PM", "modify"))
    for name in random.sample(NAMES, 10):
        templates.append((f"Add {name} to the meeting", "modify"))
        templates.append((f"Remove {name} from the invite list", "modify"))

    # greeting (~2000)
    greetings = [
        "Hi", "Hello", "Hey there", "Good morning", "Good afternoon",
        "Hey", "What's up", "How are you", "Hi Auralis", "Hello AI",
        "Yo", "Greetings", "Hi there", "Good evening", "Hey Auralis",
        "Thanks", "Thank you", "Great job", "Well done", "Appreciate it",
    ]
    for g in greetings:
        templates.append((g, "greeting"))
        for name in random.sample(NAMES, 5):
            templates.append((f"{g}, {name} here", "greeting"))

    # summarize (~2500)
    for topic in TOPICS:
        templates.append((f"Summarize the {topic} meeting", "summarize"))
        templates.append((f"Give me a brief of {topic}", "summarize"))
        templates.append((f"TL;DR of {topic} discussion", "summarize"))
    templates += [
        ("Summarize today's calls", "summarize"),
        ("Give me a summary of all meetings this week", "summarize"),
        ("What are the key takeaways from today?", "summarize"),
        ("Break down the main points", "summarize"),
    ]

    # set_preference (~1500)
    pref_templates = [
        "Set my preferred meeting time to mornings",
        "Change my response style to detailed",
        "Set language to English",
        "Enable daily briefing",
        "Disable email notifications",
        "Set my timezone to IST",
        "Change my tone to professional",
        "Turn on auto follow-ups",
        "Set response length to short",
        "Enable dark mode notifications",
    ]
    for p in pref_templates:
        templates.append((p, "set_preference"))
    for domain in DOMAINS:
        templates.append((f"Set my focus area to {domain}", "set_preference"))
        templates.append((f"Change department to {domain}", "set_preference"))

    return templates


def generate_intent_data(target_count=25000):
    templates = _intent_templates()
    # Augment with minor variations to reach target
    augmented = list(templates)

    augmentations = [
        lambda t: t.lower(),
        lambda t: t.upper(),
        lambda t: f"Hey, {t}",
        lambda t: f"Could you {t.lower()}?",
        lambda t: f"Please {t.lower()}",
        lambda t: f"I want to {t.lower()}",
        lambda t: f"Can you {t.lower()}",
        lambda t: f"{t} please",
        lambda t: f"Urgently {t.lower()}",
        lambda t: f"{t}!",
    ]

    while len(augmented) < target_count:
        text, label = random.choice(templates)
        aug_fn = random.choice(augmentations)
        augmented.append((aug_fn(text), label))

    random.shuffle(augmented)
    return augmented[:target_count]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Q&A DETECTION DATA (~20,000 samples)
# ─────────────────────────────────────────────────────────────────────────────
def _qa_templates():
    templates = []

    # Questions
    q_patterns = [
        "What is the timeline for {}?",
        "Who is handling {}?",
        "When do we need to finish {}?",
        "Can someone explain {}?",
        "Why did we choose {}?",
        "How much will {} cost?",
        "Is {} on track?",
        "Have we started {}?",
        "What blockers are there for {}?",
        "Did anyone follow up on {}?",
        "Should we prioritize {}?",
        "Are there risks with {}?",
        "What do you think about {}?",
        "Has {} been approved?",
        "Who approved {}?",
        "When was {} last updated?",
        "What's the next step for {}?",
        "Do we have metrics for {}?",
        "Is the client happy with {}?",
        "Can we demo {}?",
    ]
    for pattern in q_patterns:
        for topic in TOPICS:
            templates.append((pattern.format(topic), "question"))
        for project in random.sample(PROJECTS, 8):
            templates.append((pattern.format(project), "question"))

    # Answers
    a_patterns = [
        "The deadline for {} is next Friday.",
        "{name} is leading {} this quarter.",
        "We decided to go with option A for {}.",
        "The budget for {} is $50,000.",
        "Yes, {} has been approved by management.",
        "We'll complete {} by end of March.",
        "{} is currently in the testing phase.",
        "No, {} hasn't started yet.",
        "The team agreed to postpone {} to next sprint.",
        "We're on track with {}, no blockers.",
        "{name} will present {} at the next review.",
        "The cost estimate for {} is $30,000.",
        "We've allocated three engineers to {}.",
        "The client signed off on {} yesterday.",
        "{} is 80% complete as of today.",
    ]
    for pattern in a_patterns:
        for topic in TOPICS:
            name = random.choice(NAMES)
            templates.append((pattern.format(topic, name=name), "answer"))

    # Statements (neutral, not Q&A)
    s_patterns = [
        "Let's move on to the next topic.",
        "I think we've covered {} sufficiently.",
        "Good point about {}.",
        "That's an interesting perspective on {}.",
        "Let me share my screen for {}.",
        "We should table {} for now.",
        "Moving on from {}.",
        "Thanks for that update on {}.",
        "Noted on {}.",
        "I agree with the approach for {}.",
        "Let me pull up the data for {}.",
        "That makes sense for {}.",
        "We can discuss {} offline.",
        "The recording is on for this session.",
        "Let's keep this meeting focused.",
    ]
    for pattern in s_patterns:
        for topic in TOPICS:
            templates.append((pattern.format(topic), "statement"))

    return templates


def generate_qa_data(target_count=20000):
    templates = _qa_templates()
    augmented = list(templates)

    augmentations = [
        lambda t: t,
        lambda t: f"So, {t.lower()}",
        lambda t: f"Actually, {t.lower()}",
        lambda t: f"I think {t.lower()}",
        lambda t: f"Just to clarify, {t.lower()}",
        lambda t: f"To answer that, {t.lower()}",
        lambda t: f"Well, {t.lower()}",
        lambda t: t.rstrip('.') + ', right?',
    ]

    while len(augmented) < target_count:
        text, label = random.choice(templates)
        aug_fn = random.choice(augmentations)
        augmented.append((aug_fn(text), label))

    random.shuffle(augmented)
    return augmented[:target_count]


# ─────────────────────────────────────────────────────────────────────────────
# 3. MEETING CONTEXT DATA (~20,000 samples)
# ─────────────────────────────────────────────────────────────────────────────
def _context_templates():
    templates = []

    # action_item
    for name in NAMES:
        for topic in TOPICS:
            templates.append((
                f"{name} will follow up on {topic} by end of week.",
                "action_item"
            ))
        for project in random.sample(PROJECTS, 6):
            templates.append((
                f"{name} needs to prepare a report for {project}.",
                "action_item"
            ))

    # decision
    for topic in TOPICS:
        templates.append((f"We decided to proceed with {topic}.", "decision"))
        templates.append((f"The team voted to approve {topic}.", "decision"))
        templates.append((f"It was agreed that {topic} takes priority.", "decision"))
        templates.append((f"Management approved the {topic} proposal.", "decision"))

    # follow_up
    for name in random.sample(NAMES, 20):
        for topic in random.sample(TOPICS, 10):
            templates.append((
                f"Follow up with {name} regarding {topic} after the meeting.",
                "follow_up"
            ))

    # Key insight
    for topic in TOPICS:
        templates.append((f"Key takeaway: {topic} is now the top priority.", "key_insight"))
        templates.append((f"Important: {topic} deadline moved to next quarter.", "key_insight"))
        templates.append((f"Critical finding: {topic} needs additional resources.", "key_insight"))

    # fillers / neutral (not actionable)
    filler_patterns = [
        "Let's start the meeting.",
        "Can everyone hear me?",
        "I'll share my screen now.",
        "Let me unmute.",
        "Sorry, I was on mute.",
        "Go ahead, {name}.",
        "Thanks {name} for joining.",
        "Let's take a 5-minute break.",
        "We're running short on time.",
        "Let's wrap up.",
        "Any other topics?",
        "I think that covers everything.",
        "See you all next week.",
    ]
    for pattern in filler_patterns:
        for name in random.sample(NAMES, 10):
            templates.append((pattern.format(name=name), "filler"))

    return templates


def generate_context_data(target_count=20000):
    templates = _context_templates()
    augmented = list(templates)

    while len(augmented) < target_count:
        text, label = random.choice(templates)
        # Small random prefix/suffix variations
        prefixes = ["", "So, ", "Also, ", "In addition, ", "Furthermore, "]
        augmented.append((random.choice(prefixes) + text, label))

    random.shuffle(augmented)
    return augmented[:target_count]


# ─────────────────────────────────────────────────────────────────────────────
# MAIN — Generate and save all datasets
# ─────────────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("AURALIS AI — Synthetic Data Generator")
    print("=" * 60)

    # 1. Intent Classification
    print("\n[1/3] Generating Intent Classification data...")
    intent_data = generate_intent_data(25000)
    intent_path = os.path.join(DATA_DIR, 'intent_classification.csv')
    with open(intent_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['text', 'label'])
        writer.writerows(intent_data)
    labels = set(l for _, l in intent_data)
    print(f"   ✓ {len(intent_data):,} samples | {len(labels)} classes | {intent_path}")

    # 2. Q&A Detection
    print("\n[2/3] Generating Q&A Detection data...")
    qa_data = generate_qa_data(20000)
    qa_path = os.path.join(DATA_DIR, 'qa_detection.csv')
    with open(qa_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['text', 'label'])
        writer.writerows(qa_data)
    labels = set(l for _, l in qa_data)
    print(f"   ✓ {len(qa_data):,} samples | {len(labels)} classes | {qa_path}")

    # 3. Meeting Context
    print("\n[3/3] Generating Meeting Context data...")
    ctx_data = generate_context_data(20000)
    ctx_path = os.path.join(DATA_DIR, 'meeting_context.csv')
    with open(ctx_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['text', 'label'])
        writer.writerows(ctx_data)
    labels = set(l for _, l in ctx_data)
    print(f"   ✓ {len(ctx_data):,} samples | {len(labels)} classes | {ctx_path}")

    total = len(intent_data) + len(qa_data) + len(ctx_data)
    print(f"\n{'=' * 60}")
    print(f"TOTAL: {total:,} synthetic training samples generated.")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    main()
