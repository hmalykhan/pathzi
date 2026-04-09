from careers.services.embeddings import embed_text
import numpy as np

def cosine_sim(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

v1 = embed_text("I love AI")
v2 = embed_text("I enjoy machine learning")
v3 = embed_text("I like cooking food")

print("AI vs ML:", cosine_sim(v1, v2))
print("AI vs Cooking:", cosine_sim(v1, v3))