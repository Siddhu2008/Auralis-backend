import chromadb
import numpy as np

print("Imported chromadb")

class MyFunc(chromadb.EmbeddingFunction):
    def __call__(self, input):
        return [[0.1]*384 for _ in input]

try:
    print("Creating client...")
    client = chromadb.EphemeralClient()
    print("Creating collection...")
    coll = client.create_collection("test", embedding_function=MyFunc())
    print("Adding...")
    coll.add(ids=["1"], documents=["hello"])
    print("Done")
except Exception as e:
    import traceback
    traceback.print_exc()
