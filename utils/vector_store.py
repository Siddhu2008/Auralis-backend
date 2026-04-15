import os
import json

class VectorStore:
    def __init__(self, collection_name="auralis_memory"):
        self.persist_directory = os.path.join(os.path.dirname(__file__), "..", "chroma_db_native")
        os.makedirs(self.persist_directory, exist_ok=True)
        self.collection_file = os.path.join(self.persist_directory, f"{collection_name}.json")
        self.documents = []
        self._load()
        print("Native Vector Store initialized (No Torch/Chroma)")

    def _load(self):
        if os.path.exists(self.collection_file):
            try:
                with open(self.collection_file, "r") as f:
                    self.documents = json.load(f)
            except Exception:
                self.documents = []

    def _save(self):
        try:
            with open(self.collection_file, "w") as f:
                json.dump(self.documents, f)
        except Exception:
            pass

    def add_meeting(self, meeting_id, text, metadata=None):
        if not text:
            return

        chunk_size = 1000  
        chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size - 100)]
        
        for i, chunk in enumerate(chunks):
            meta = metadata.copy() if metadata else {}
            meta['chunk_index'] = i
            meta['meeting_id'] = str(meeting_id)
            meta['source'] = 'meeting'
            
            self.documents.append({
                "id": f"mtg_{meeting_id}_{i}",
                "content": chunk,
                "metadata": meta
            })
            
        self._save()
        print(f"Added {len(chunks)} chunks for meeting {meeting_id} to Native Vector Store")

    def search(self, query, n_results=5):
        if not self.documents:
            return []
            
        # A very naive search fallback based on simple word matching
        query_words = set(query.lower().split())
        results = []
        
        for doc in self.documents:
            doc_words = set(doc["content"].lower().split())
            overlap = len(query_words.intersection(doc_words))
            
            if overlap > 0:
                results.append({
                    'content': doc["content"],
                    'meeting_id': doc["metadata"].get('meeting_id', 'unknown'),
                    'score': float(overlap)
                })
        
        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:n_results]

# Singleton
vector_store = VectorStore()
