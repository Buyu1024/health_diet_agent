"""
向量检索模块 - 混合检索 + 重排序
使用本地 BGE-M3（嵌入）和 BGE-Reranker-Large（重排序）模型
连接 Milvus 向量数据库（health 库 / health_rag 集合）
"""
import os
import hashlib

import torch
import numpy as np
from milvus_model.hybrid import BGEM3EmbeddingFunction
from pymilvus import MilvusClient, DataType, AnnSearchRequest, WeightedRanker
from langchain.docstore.document import Document
from sentence_transformers import CrossEncoder

from config.settings import settings


class VectorStore:
    """混合检索 + 重排序向量存储"""

    def __init__(self):
        # Milvus 配置
        self.collection_name = settings.MILVUS_COLLECTION
        self.uri = settings.MILVUS_URI
        self.database = settings.MILVUS_DATABASE

        # 设备
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[VectorStore] 使用设备: {self.device}")

        # 加载 BGE-M3 嵌入模型
        self.embedding_function = BGEM3EmbeddingFunction(
            model_name_or_path=settings.BGE_M3_PATH,
            use_fp16=(self.device == "cuda"),
            device=self.device,
        )
        self.dense_dim = self.embedding_function.dim["dense"]
        print(f"[VectorStore] BGE-M3 加载成功，稠密维度: {self.dense_dim}")

        # 加载 BGE-Reranker-Large 重排序模型
        self.reranker = CrossEncoder(settings.BGE_RERANKER_PATH, device=self.device)
        print(f"[VectorStore] BGE-Reranker-Large 加载成功")

        # 连接 Milvus
        self.client = MilvusClient(uri=self.uri, db_name=self.database)
        print(f"[VectorStore] Milvus 连接成功: {self.uri} / {self.database}")

        # 加载集合
        self._load_collection()

    def _load_collection(self):
        """加载已有集合（不自动创建，集合应由 health_qa_system 预先建好）"""
        if not self.client.has_collection(self.collection_name):
            raise RuntimeError(
                f"Milvus 集合 '{self.collection_name}' 不存在，"
                f"请先在 health_qa_system 中初始化数据。"
            )
        self.client.load_collection(collection_name=self.collection_name)
        print(f"[VectorStore] 集合 '{self.collection_name}' 已加载")

    # ==================== 混合检索（无重排序） ====================

    def hybrid_search(self, query: str, k: int = 5, source_filter: str = None) -> list:
        """
        混合检索：稠密向量 + 稀疏向量，加权融合
        :param query: 用户查询
        :param k: 返回数量
        :param source_filter: 按 source 字段过滤（如 '高血压'、'糖尿病'）
        :return: Document 列表（父文档去重后）
        """
        query_embeddings = self.embedding_function([query])
        dense_vec = np.array(query_embeddings["dense"][0], dtype=np.float16)
        sparse_vec = self._to_sparse_dict(query_embeddings["sparse"], 0)

        filter_expr = f"source == '{source_filter}'" if source_filter else ""

        dense_req = AnnSearchRequest(
            data=[dense_vec],
            anns_field="dense_vector",
            param={"metric_type": "IP", "params": {"nprobe": 10}},
            limit=k,
            expr=filter_expr,
        )
        sparse_req = AnnSearchRequest(
            data=[sparse_vec],
            anns_field="sparse_vector",
            param={"metric_type": "IP", "params": {}},
            limit=k,
            expr=filter_expr,
        )

        results = self.client.hybrid_search(
            collection_name=self.collection_name,
            reqs=[dense_req, sparse_req],
            ranker=WeightedRanker(0.7, 1.0),
            limit=k,
            output_fields=["text", "parent_id", "parent_content", "source", "timestamp"],
        )

        if not results or len(results) == 0:
            return []

        sub_chunks = [self._doc_from_hit(hit["entity"]) for hit in results[0]]
        return self._get_unique_parent_docs(sub_chunks)[:k]

    # ==================== 混合检索 + 重排序 ====================

    def hybrid_search_with_rerank(
        self, query: str, k: int = 5, source_filter: str = None, candidate_m: int = 2
    ) -> list:
        """
        混合检索 + 重排序：先用混合检索召回 k 条，再用 BGE-Reranker 精排取 candidate_m 条
        :param query: 用户查询
        :param k: 初召回数量
        :param source_filter: 按 source 字段过滤
        :param candidate_m: 重排序后返回数量
        :return: Document 列表
        """
        query_embeddings = self.embedding_function([query])
        dense_vec = np.array(query_embeddings["dense"][0], dtype=np.float16)
        sparse_vec = self._to_sparse_dict(query_embeddings["sparse"], 0)

        filter_expr = f"source == '{source_filter}'" if source_filter else ""

        dense_req = AnnSearchRequest(
            data=[dense_vec],
            anns_field="dense_vector",
            param={"metric_type": "IP", "params": {"nprobe": 10}},
            limit=k,
            expr=filter_expr,
        )
        sparse_req = AnnSearchRequest(
            data=[sparse_vec],
            anns_field="sparse_vector",
            param={"metric_type": "IP", "params": {}},
            limit=k,
            expr=filter_expr,
        )

        results = self.client.hybrid_search(
            collection_name=self.collection_name,
            reqs=[dense_req, sparse_req],
            ranker=WeightedRanker(0.7, 1.0),
            limit=k,
            output_fields=["text", "parent_id", "parent_content", "source", "timestamp"],
        )

        if not results or len(results) == 0:
            return []

        sub_chunks = [self._doc_from_hit(hit["entity"]) for hit in results[0]]
        parent_docs = self._get_unique_parent_docs(sub_chunks)

        # 结果不足 2 条时直接返回，不重排序
        if len(parent_docs) < 2:
            return parent_docs[:candidate_m]

        # BGE-Reranker 精排
        pairs = [[query, doc.page_content] for doc in parent_docs]
        scores = self.reranker.predict(pairs)
        ranked = [doc for _, doc in sorted(zip(scores, parent_docs), reverse=True)]
        return ranked[:candidate_m]

    # ==================== 内部工具方法 ====================

    @staticmethod
    def _to_sparse_dict(sparse_matrix, row_idx: int) -> dict:
        """将 scipy 稀疏矩阵的一行转为 dict {col_idx: value}"""
        # 兼容 csr_matrix 和 csr_array
        if hasattr(sparse_matrix, 'getrow'):
            row = sparse_matrix.getrow(row_idx)
        else:
            # csr_array 直接访问
            start = sparse_matrix.indptr[row_idx]
            end = sparse_matrix.indptr[row_idx + 1]
            indices = sparse_matrix.indices[start:end]
            data = sparse_matrix.data[start:end]
            return {int(idx): float(val) for idx, val in zip(indices, data)}
        return {int(idx): float(val) for idx, val in zip(row.indices, row.data)}

    @staticmethod
    def _doc_from_hit(hit: dict) -> Document:
        """将 Milvus hit 转为 LangChain Document"""
        return Document(
            page_content=hit.get("text", ""),
            metadata={
                "parent_id": hit.get("parent_id", ""),
                "parent_content": hit.get("parent_content", ""),
                "source": hit.get("source", ""),
                "timestamp": hit.get("timestamp", ""),
            },
        )

    @staticmethod
    def _get_unique_parent_docs(sub_chunks: list) -> list:
        """子块列表 → 按 parent_content 去重，返回父文档列表"""
        seen = set()
        unique = []
        for chunk in sub_chunks:
            parent_content = chunk.metadata.get("parent_content", chunk.page_content)
            if parent_content and parent_content not in seen:
                unique.append(Document(page_content=parent_content, metadata=chunk.metadata))
                seen.add(parent_content)
        return unique
