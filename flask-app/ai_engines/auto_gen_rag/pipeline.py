"""RAGPipeline v6.0"""
import sqlite3, json

class RAGPipeline:
    def __init__(self, db_path=None):
        self.db = db_path or "engines/app.db"
        self._ensure_tables()
    def _ensure_tables(self):
        conn = sqlite3.connect(self.db, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_rag_documents (
            doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL, chunk_size INTEGER DEFAULT 512,
            source TEXT, domain TEXT,
            created_at TEXT DEFAULT (datetime('now')))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS mt_rag_queries (
            query_id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT, answer TEXT, retrieved_doc_ids TEXT,
            relevance_score REAL, created_at TEXT DEFAULT (datetime('now')))""")
        conn.commit(); conn.close()
    def chunk_text(self, text, size=512, overlap=64):
        words = text.split()
        return [" ".join(words[i:i+size]) for i in range(0, len(words), size-overlap)]
    def hybrid_search(self, query, top_k=5):
        conn = sqlite3.connect(self.db, timeout=5)
        kw_rows = conn.execute("SELECT doc_id, content FROM mt_rag_documents WHERE content LIKE ? LIMIT ?", (f"%{query[:20]}%", top_k)).fetchall()
        conn.close()
        results = []
        for did, content in kw_rows:
            score = content.count(query[:10]) / max(len(content.split()), 1)
            results.append({"doc_id": did, "content": content[:200], "score": round(score, 3)})
        return sorted(results, key=lambda x: -x["score"])[:top_k]
    def augment(self, query, system_prompt="你是仙女座知识库助手"):
        docs = self.hybrid_search(query)
        context = "\n".join(d["content"] for d in docs)
        return f"[auto_rag] {system_prompt}\n上下文:\n{context[:2000]}\n问题: {query}"

if __name__ == "__main__":
    print(RAGPipeline().augment("仙女座是什么?"))
