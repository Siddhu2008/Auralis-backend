
import os
import json
import numpy as np
import hashlib

class SimpleEmbeddingFunction:
    def __init__(self, dim=384):
        self.dim = dim

    def __call__(self, texts):
        embeddings = []
        for text in texts:
            words = text.lower().split()
            vec = np.zeros(self.dim, dtype=np.float32)
            for word in words:
                word_hash = int(hashlib.md5(word.encode()).hexdigest(), 16)
                idx = word_hash % self.dim
                sign = 1.0 if (word_hash // self.dim) % 2 == 0 else -1.0
                vec[idx] += sign
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            embeddings.append(vec.tolist())
        return embeddings

class VectorStore:
    def __init__(self, persistence_path="vector_store.json"):
        self.path = persistence_path
        self.embedding_fn = SimpleEmbeddingFunction()
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path, 'r') as f:
                return json.load(f)
        return {"ids": [], "documents": [], "metadatas": [], "embeddings": []}

    def _save(self):
        with open(self.path, 'w') as f:
            json.dump(self.data, f)

    def add_meeting(self, meeting_id, text, metadata=None):
        if not text:
            return

        chunk_size = 1000  
        chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
        
        # Embed
        embeddings = self.embedding_fn(chunks)
        
        for i, chunk in enumerate(chunks):
            chunk_id = f"{meeting_id}_{i}"
            meta = metadata.copy() if metadata else {}
            meta['chunk_index'] = i
            meta['meeting_id'] = str(meeting_id)
            meta['text_content'] = chunk
            
            # Append
            self.data['ids'].append(chunk_id)
            self.data['documents'].append(chunk)
            self.data['metadatas'].append(meta)
            self.data['embeddings'].append(embeddings[i])
            
        self._save()
        print(f"Added {len(chunks)} chunks for meeting {meeting_id}")

    def search(self, query, n_results=5):
        if not self.data['embeddings']:
            return []
            
        query_embedding = self.embedding_fn([query])[0]
        query_vec = np.array(query_embedding, dtype=np.float32)
        
        doc_vecs = np.array(self.data['embeddings'], dtype=np.float32)
        
        # Cosine similarity: dot product (since normalized)
        scores = np.dot(doc_vecs, query_vec)
        
        # Top K
        top_k_indices = np.argsort(scores)[::-1][:n_results]
        
        results = []
        for idx in top_k_indices:
            results.append({
                'content': self.data['documents'][idx],
                'meeting_id': self.data['metadatas'][idx]['meeting_id'],
                'score': float(scores[idx])
            })
            
        return results

vector_store = VectorStore()
