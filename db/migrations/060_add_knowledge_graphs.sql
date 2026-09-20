-- 060: ORM 의 `knowledge_graphs` 를 정본 스키마에 들인다
--
-- 왜 필요한가
--   `neos/database/models.py:237` 의 `KnowledgeGraph` 를 문서 파이프라인이 쓴다 --
--   `pipelines/document/document_processor.py:432` 가 쓰고,
--   `api/services/document_service.py:197` 이 읽는다. 그런데 `db/**/*.sql` 중
--   이 테이블을 만드는 파일이 **하나도 없었다**. BOOTSTRAP_ORDER 로 배포한 DB 에
--   WAS 를 올리면 문서 업로드가 KG 단계에서 `relation "knowledge_graphs" does not
--   exist` 로 죽는다. 여태 안 드러난 이유는 테스트가 ORM `create_all()` 로 이
--   테이블을 따로 만들어 주기 때문이다 -- 테스트 경로와 배포 경로가 서로 다른
--   방법으로 스키마를 세우는 한, 한쪽에만 있는 테이블은 보이지 않는다.
--
-- 015 와의 관계 (같은 것이 아니다)
--   015 는 정규화된 `kg_entities` / `kg_relations` / `kg_entity_occurrences` 를
--   만들고 `services/kg_population_service.py` 와 `services/kg_search_strategy.py`
--   가 그쪽을 쓴다. 이 테이블은 문서 단위로 엔티티·관계·출현을 JSONB 에 통째로
--   담는 **비정규화 사본**이고 소비자가 다르다. 둘을 합치는 것은 별개의 결정이라
--   여기서 하지 않는다 -- 지금은 배포에서 빠진 것을 채운다.

CREATE TABLE IF NOT EXISTS knowledge_graphs (
    id                  SERIAL PRIMARY KEY,
    document_id         INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,

    -- 엔티티 정보
    entity_id           VARCHAR(255) NOT NULL,   -- 문서 내 고유 ID
    entity_type         VARCHAR(100) NOT NULL,   -- person / organization / concept / event ...
    entity_name         VARCHAR(500) NOT NULL,
    entity_description  TEXT,

    -- 임베딩 (Gemini Embedding 2 — 3072차원)
    entity_embedding    VECTOR(3072),

    -- 028 이 `document_chunks` 에 대해 하는 것과 같다: 007 이 이 두 컬럼을
    -- `ADD COLUMN IF NOT EXISTS` 로 넣어주지만, 만드는 쪽에서도 선언해 둔다.
    -- 그래야 007 을 빼고 이 파일만 읽어도 테이블의 완전한 모양이 보인다.
    -- 007 쪽은 무해한 no-op 이 된다.
    embedding_provider  VARCHAR(50) DEFAULT 'openai',
    embedding_model     VARCHAR(100),

    -- 관계·속성·출현을 JSONB 로 (015 의 정규화 테이블과 대비되는 지점)
    relations           JSONB DEFAULT '[]'::jsonb,
    properties          JSONB DEFAULT '{}'::jsonb,
    occurrences         JSONB DEFAULT '[]'::jsonb,

    confidence_score    DOUBLE PRECISION DEFAULT 0.0,
    importance_score    DOUBLE PRECISION DEFAULT 0.0,

    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 이 테이블의 **유일한** 접근 경로다 (`document_service.get_document_knowledge_graph`).
CREATE INDEX IF NOT EXISTS idx_knowledge_graphs_document
    ON knowledge_graphs(document_id);

-- 엔티티 조회용 보조 경로. 쓰는 쿼리는 아직 없지만 ORM 이 컬럼을 들고 있고
-- 카디널리티가 낮아 비용이 싸다.
CREATE INDEX IF NOT EXISTS idx_knowledge_graphs_entity_type
    ON knowledge_graphs(entity_type);

-- 007 도 같은 인덱스를 만들지만 (`IF NOT EXISTS`), 컬럼과 마찬가지로 만드는
-- 쪽에 둔다. 028 이 `idx_document_chunks_provider` 를 직접 만드는 것과 같다.
CREATE INDEX IF NOT EXISTS idx_knowledge_graphs_provider
    ON knowledge_graphs(embedding_provider);

-- `entity_embedding` 의 HNSW 인덱스는 여기서 만들지 않는다 -- **027 이 만든다**
-- (`idx_knowledge_graphs_entity_embedding`, halfvec(3072) 캐스팅). 그래서 이
-- 파일은 BOOTSTRAP_ORDER 에서 027 **앞**으로 당겨져 있다. 뒤에 있으면 027 의
-- `IF EXISTS (... 'knowledge_graphs')` 가드가 거짓이 되어 인덱스가 조용히
-- 안 생긴다 -- 에러 없이. 자세한 것은 BOOTSTRAP_ORDER.txt 의 예외 주석.

COMMENT ON TABLE knowledge_graphs IS
    '문서 단위 지식그래프 비정규화 사본. 정규화 버전은 015 의 kg_entities/kg_relations.';
