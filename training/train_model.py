"""
Auralis AI Meeting Agent — Model Training Pipeline
Trains 3 lightweight scikit-learn models on the synthetic data:
  1. Intent Classifier        → TF-IDF + SGDClassifier
  2. Q&A Detector             → TF-IDF + LogisticRegression
  3. Meeting Context Classifier → TF-IDF + LogisticRegression

Models are saved as .pkl files in training/models/ using joblib.
Inference speed: < 5ms per prediction (no GPU required).
"""
import os
import csv
import time
import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import SGDClassifier, LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score
from sklearn.pipeline import Pipeline

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
MODEL_DIR = os.path.join(os.path.dirname(__file__), 'models')
os.makedirs(MODEL_DIR, exist_ok=True)


def load_csv(filename):
    """Load a CSV file and return (texts, labels)."""
    filepath = os.path.join(DATA_DIR, filename)
    texts, labels = [], []
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            texts.append(row['text'])
            labels.append(row['label'])
    return texts, labels


def train_and_save(name, texts, labels, classifier_cls, classifier_kwargs=None):
    """Train a TF-IDF + classifier pipeline and save to disk."""
    print(f"\n{'─' * 50}")
    print(f"Training: {name}")
    print(f"{'─' * 50}")

    if classifier_kwargs is None:
        classifier_kwargs = {}

    X_train, X_test, y_train, y_test = train_test_split(
        texts, labels, test_size=0.15, random_state=42, stratify=labels
    )

    pipeline = Pipeline([
        ('tfidf', TfidfVectorizer(
            max_features=30000,
            ngram_range=(1, 3),
            sublinear_tf=True,
            min_df=2,
        )),
        ('classifier', classifier_cls(**classifier_kwargs)),
    ])

    print(f"  Training on {len(X_train):,} samples...")
    start = time.time()
    pipeline.fit(X_train, y_train)
    train_time = time.time() - start
    print(f"  Training time: {train_time:.2f}s")

    # Evaluate
    print(f"  Evaluating on {len(X_test):,} samples...")
    y_pred = pipeline.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    print(f"  Accuracy: {accuracy:.4f} ({accuracy * 100:.1f}%)")
    print()
    print(classification_report(y_test, y_pred, zero_division=0))

    # Measure inference speed
    single_sample = [X_test[0]]
    start = time.time()
    for _ in range(1000):
        pipeline.predict(single_sample)
    avg_ms = (time.time() - start) / 1000 * 1000
    print(f"  Avg inference: {avg_ms:.2f}ms per prediction")

    # Save
    model_path = os.path.join(MODEL_DIR, f'{name}.pkl')
    joblib.dump(pipeline, model_path)
    file_size = os.path.getsize(model_path) / (1024 * 1024)
    print(f"  Saved: {model_path} ({file_size:.1f} MB)")

    return accuracy


def main():
    print("=" * 60)
    print("AURALIS AI — Model Training Pipeline")
    print("=" * 60)

    results = {}

    # 1. Intent Classifier
    print("\n[1/3] Loading intent_classification.csv...")
    texts, labels = load_csv('intent_classification.csv')
    print(f"  Loaded {len(texts):,} samples, {len(set(labels))} classes: {sorted(set(labels))}")
    results['intent_classifier'] = train_and_save(
        'intent_classifier',
        texts, labels,
        SGDClassifier,
        {'loss': 'modified_huber', 'max_iter': 1000, 'random_state': 42, 'class_weight': 'balanced'}
    )

    # 2. QA Detector
    print("\n[2/3] Loading qa_detection.csv...")
    texts, labels = load_csv('qa_detection.csv')
    print(f"  Loaded {len(texts):,} samples, {len(set(labels))} classes: {sorted(set(labels))}")
    results['qa_detector'] = train_and_save(
        'qa_detector',
        texts, labels,
        LogisticRegression,
        {'max_iter': 1000, 'random_state': 42, 'class_weight': 'balanced', 'solver': 'lbfgs'}
    )

    # 3. Meeting Context Classifier
    print("\n[3/3] Loading meeting_context.csv...")
    texts, labels = load_csv('meeting_context.csv')
    print(f"  Loaded {len(texts):,} samples, {len(set(labels))} classes: {sorted(set(labels))}")
    results['context_classifier'] = train_and_save(
        'context_classifier',
        texts, labels,
        LogisticRegression,
        {'max_iter': 1000, 'random_state': 42, 'class_weight': 'balanced', 'solver': 'lbfgs'}
    )

    # Summary
    print(f"\n{'=' * 60}")
    print("TRAINING COMPLETE — SUMMARY")
    print(f"{'=' * 60}")
    for name, acc in results.items():
        print(f"  {name:30s} → {acc * 100:.1f}% accuracy")
    print(f"\nModels saved in: {MODEL_DIR}")


if __name__ == '__main__':
    main()
