import threading

import pytest
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList

from neos.services import attachment_blocks
from neos.services.attachment_blocks import (
    AttachmentKind,
    AttachmentNotSupportedError,
    resolve_attachments,
)

OWNER = "u1"
OTHER = "u2"


class _Doc:
    """Document 행의 최소 대역."""

    def __init__(
        self,
        mime_type,
        storage_key="k",
        file_size=10,
        page_count=None,
        user_id=OWNER,
    ):
        self.mime_type = mime_type
        self.storage_key = storage_key
        self.file_size = file_size
        self.page_count = page_count
        self.user_id = user_id


def _message(content, attachments, role="user"):
    return {"role": role, "content": content, "attachments": attachments}


def _attachment(name, mime, document_id=1, url="s3://bucket/k"):
    return {
        "type": "file",
        "url": url,
        "name": name,
        "metadata": {"mediaType": mime, "documentId": document_id},
    }


@pytest.fixture
def stub_io(monkeypatch):
    """DB 와 스토리지를 이음매에서 끊는다.

    `fake_load_document` 는 실제 구현처럼 `owner_user_id` 로 걸러낸다 — 그래야
    Finding 1(소유권 필터)을 이 스텁 위에서도 실제로 검증할 수 있다.
    """
    docs = {}
    downloads = {}

    async def fake_load_document(*, document_id=None, storage_url=None, owner_user_id):
        doc = docs.get(document_id)
        if doc is not None and doc.user_id == owner_user_id:
            return doc
        return None

    async def fake_download(storage_key):
        return downloads.get(storage_key, b"bytes")

    monkeypatch.setattr(attachment_blocks, "_load_document", fake_load_document)
    monkeypatch.setattr(attachment_blocks, "_download", fake_download)
    monkeypatch.setattr(attachment_blocks, "supports_vision", lambda model: True)
    return docs, downloads


@pytest.mark.asyncio
async def test_image_attachment_is_resolved_for_its_message(stub_io) -> None:
    docs, _ = stub_io
    docs[1] = _Doc("image/png")

    plan = await resolve_attachments(
        [_message("이 그림 봐줘", [_attachment("scan.png", "image/png")])],
        model="seeing-model",
        owner_user_id=OWNER,
    )

    resolved = plan.by_index[0][0]
    assert resolved.kind is AttachmentKind.IMAGE
    assert resolved.data == b"bytes"


@pytest.mark.asyncio
async def test_server_mime_wins_over_the_client_supplied_one(stub_io) -> None:
    docs, _ = stub_io
    docs[1] = _Doc("application/pdf")

    plan = await resolve_attachments(
        [_message("봐줘", [_attachment("f.pdf", "image/png")])],
        model="seeing-model",
        owner_user_id=OWNER,
    )

    assert plan.by_index[0][0].mime_type == "application/pdf"


@pytest.mark.asyncio
async def test_docx_is_extracted_to_text(stub_io, monkeypatch) -> None:
    docs, _ = stub_io
    docs[1] = _Doc("application/msword")

    async def fake_parse_word(file_content=None, file_path=None):
        return {"text": "분기 실적 요약"}

    monkeypatch.setattr(attachment_blocks, "parse_word", fake_parse_word)

    plan = await resolve_attachments(
        [_message("요약", [_attachment("memo.docx", "application/msword")])],
        model="seeing-model",
        owner_user_id=OWNER,
    )

    resolved = plan.by_index[0][0]
    assert resolved.kind is AttachmentKind.EXTRACT
    assert resolved.text == "분기 실적 요약"
    assert resolved.data is None


@pytest.mark.asyncio
async def test_gate_refuses_when_the_model_has_no_vision(stub_io, monkeypatch) -> None:
    docs, _ = stub_io
    docs[1] = _Doc("image/png")
    monkeypatch.setattr(attachment_blocks, "supports_vision", lambda model: False)

    with pytest.raises(AttachmentNotSupportedError):
        await resolve_attachments(
            [_message("봐줘", [_attachment("scan.png", "image/png")])],
            model="blind-model",
            owner_user_id=OWNER,
        )

    # 게이트는 스토리지를 열기 전에 선다 — 거부될 턴에서 스토리지 오류가
    # 거부 메시지를 가리면 안 된다 (컨트롤러 판정)
    calls = []

    async def tracking_download(storage_key):
        calls.append(storage_key)
        return b"bytes"

    monkeypatch.setattr(attachment_blocks, "_download", tracking_download)

    with pytest.raises(AttachmentNotSupportedError):
        await resolve_attachments(
            [_message("봐줘", [_attachment("scan.png", "image/png")])],
            model="blind-model",
            owner_user_id=OWNER,
        )

    assert calls == [], "거부될 턴인데 스토리지를 열었다"


@pytest.mark.asyncio
async def test_history_attachment_needing_vision_is_demoted_not_refused(
    stub_io, monkeypatch
) -> None:
    """Finding 2 — 게이트는 현재 턴만 본다.

    과거 턴에 이미지가 있고, 지금은 vision 없는 모델로 순수 텍스트 턴을
    보내는 대화는 거부되면 안 된다 — 그 이미지는 강등되고 안내만 남는다.
    """
    docs, _ = stub_io
    docs[1] = _Doc("image/png")
    monkeypatch.setattr(attachment_blocks, "supports_vision", lambda model: False)

    plan = await resolve_attachments(
        [
            _message("옛 턴", [_attachment("scan.png", "image/png", document_id=1)]),
            _message("이번엔 텍스트만", []),
        ],
        model="blind-model",
        owner_user_id=OWNER,
    )

    assert plan.by_index[0][0].data is None
    assert "scan.png" in plan.by_index[0][0].text
    assert any("scan.png" in notice for notice in plan.notices)


@pytest.mark.asyncio
async def test_current_turn_attachment_needing_vision_still_refuses(
    stub_io, monkeypatch
) -> None:
    """Finding 2 — 현재 턴의 첨부는 여전히 거부되어야 한다."""
    docs, _ = stub_io
    docs[1] = _Doc("image/png", user_id=OWNER)
    docs[2] = _Doc("image/png", user_id=OWNER)
    monkeypatch.setattr(attachment_blocks, "supports_vision", lambda model: False)

    with pytest.raises(AttachmentNotSupportedError):
        await resolve_attachments(
            [
                _message("옛 턴", [_attachment("old.png", "image/png", document_id=1)]),
                _message("이번 턴", [_attachment("new.png", "image/png", document_id=2)]),
            ],
            model="blind-model",
            owner_user_id=OWNER,
        )


@pytest.mark.asyncio
async def test_budget_fills_newest_first_and_demotes_the_rest(stub_io) -> None:
    docs, downloads = stub_io
    big = attachment_blocks.MAX_ATTACHMENT_BYTES
    docs[1] = _Doc("image/png", storage_key="old", file_size=big)
    docs[2] = _Doc("image/png", storage_key="new", file_size=big)
    downloads["old"] = b"o"
    downloads["new"] = b"n"

    plan = await resolve_attachments(
        [
            _message("옛 턴", [_attachment("old.png", "image/png", document_id=1)]),
            _message("새 턴", [_attachment("new.png", "image/png", document_id=2)]),
        ],
        model="seeing-model",
        owner_user_id=OWNER,
    )

    assert plan.by_index[1][0].data == b"n"          # 최신이 자리를 얻는다
    assert plan.by_index[0][0].data is None          # 오래된 것은 강등된다
    assert "old.png" in plan.by_index[0][0].text
    assert any("old.png" in notice for notice in plan.notices)


@pytest.mark.asyncio
async def test_unresolvable_attachment_is_refused_on_the_current_turn(stub_io) -> None:
    # docs 가 비어 있어 문서를 못 찾는다
    with pytest.raises(AttachmentNotSupportedError) as excinfo:
        await resolve_attachments(
            [_message("봐줘", [_attachment("gone.png", "image/png", document_id=99)])],
            model="seeing-model",
            owner_user_id=OWNER,
        )

    assert excinfo.value.items[0]["reason"] == "unresolved"


@pytest.mark.asyncio
async def test_unresolvable_attachment_is_demoted_on_an_older_turn(stub_io) -> None:
    docs, _ = stub_io
    docs[2] = _Doc("image/png")

    plan = await resolve_attachments(
        [
            _message("옛 턴", [_attachment("gone.png", "image/png", document_id=99)]),
            _message("새 턴", [_attachment("ok.png", "image/png", document_id=2)]),
        ],
        model="seeing-model",
        owner_user_id=OWNER,
    )

    assert plan.by_index[0][0].data is None
    assert "gone.png" in plan.by_index[0][0].text


@pytest.mark.asyncio
async def test_null_file_size_does_not_bypass_the_download_budget(stub_io) -> None:
    # Finding 4 — `Document.file_size or 0` means a NULL row sails through the
    # pre-download check; the actual downloaded byte count must still be
    # checked against the remaining budget before the attachment is included.
    docs, downloads = stub_io
    docs[1] = _Doc("image/png", storage_key="huge", file_size=None)
    downloads["huge"] = b"x" * (attachment_blocks.MAX_ATTACHMENT_BYTES + 1)

    plan = await resolve_attachments(
        [_message("봐줘", [_attachment("huge.png", "image/png", document_id=1)])],
        model="seeing-model",
        owner_user_id=OWNER,
    )

    resolved = plan.by_index[0][0]
    assert resolved.data is None
    assert "huge.png" in resolved.text
    assert any("huge.png" in notice for notice in plan.notices)


@pytest.mark.asyncio
async def test_two_attachments_in_one_message_keep_their_order(stub_io) -> None:
    docs, downloads = stub_io
    docs[1] = _Doc("image/png", storage_key="first")
    docs[2] = _Doc("image/png", storage_key="second")
    downloads["first"] = b"1"
    downloads["second"] = b"2"

    plan = await resolve_attachments(
        [
            _message(
                "둘 다 봐줘",
                [
                    _attachment("first.png", "image/png", document_id=1),
                    _attachment("second.png", "image/png", document_id=2),
                ],
            )
        ],
        model="seeing-model",
        owner_user_id=OWNER,
    )

    assert [a.name for a in plan.by_index[0]] == ["first.png", "second.png"]
    assert [a.data for a in plan.by_index[0]] == [b"1", b"2"]


# ---------------------------------------------------------------------------
# Finding 1 — attachment document lookup must be scoped to its owner.
#
# These tests do NOT stub `_load_document` — `stub_io`'s fake filters by
# owner itself, so it would keep "passing" even if the real ownership filter
# were deleted (Fix round 2, Item 1: a test that cannot fail is not
# coverage). Instead they fake only `get_session`, so the real `select(...)
# .where(...)` construction in `_load_document` runs and is evaluated
# structurally against a tiny in-memory row set.
# ---------------------------------------------------------------------------


def _eq_conditions(clause) -> dict:
    """Column == literal 조건들을 (컬럼명 -> 값) 로 펼친다.

    `_load_document`가 실제로 조립한 SQLAlchemy WHERE 절의 표현식 트리를
    그대로 걷는다 — 문자열 매칭이 아니다. 컬럼 이름이 빠지면(회귀) 이 매핑도
    비어 그 조건 없이 매치되어 버린다.
    """
    conditions: dict = {}

    def walk(node) -> None:
        if node is None:
            return
        if isinstance(node, BooleanClauseList):
            for inner in node.clauses:
                walk(inner)
        elif isinstance(node, BinaryExpression):
            left, right = node.left, node.right
            if hasattr(left, "key") and hasattr(right, "value"):
                conditions[left.key] = right.value

    walk(clause)
    return conditions


class _RealRow:
    """`Document` ORM 행의 최소 대역 — 실제 컬럼 이름으로 걸러진다."""

    def __init__(
        self,
        *,
        id,
        user_id,
        storage_url=None,
        mime_type="image/png",
        file_size=10,
        page_count=None,
        storage_key="k",
    ):
        self.id = id
        self.user_id = user_id
        self.storage_url = storage_url
        self.mime_type = mime_type
        self.file_size = file_size
        self.page_count = page_count
        self.storage_key = storage_key


class _RealResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _RealSession:
    """`_load_document`가 조립한 WHERE 절을 진짜로 평가한다.

    소유권 조건이 where 절에서 빠지면 `_eq_conditions`도 그 조건 없이
    돌려주므로, 다른 사용자의 행이 그냥 매치되어 버린다 — 스텁이 대신
    걸러주는 게 아니라 이 세션이 실제 조건으로 판정한다.
    """

    def __init__(self, rows):
        self._rows = rows
        self.captured_statements: list = []

    async def execute(self, stmt):
        self.captured_statements.append(stmt)
        conditions = _eq_conditions(stmt.whereclause)
        for row in self._rows:
            if all(
                getattr(row, key, object()) == value
                for key, value in conditions.items()
            ):
                return _RealResult(row)
        return _RealResult(None)


@pytest.fixture
def real_db_io(monkeypatch):
    """`_load_document`는 스텁하지 않고 `get_session`만 가짜로 바꾼다."""
    rows: list[_RealRow] = []
    session = _RealSession(rows)

    async def fake_get_session():
        yield session

    monkeypatch.setattr(attachment_blocks, "get_session", fake_get_session)
    return rows, session


@pytest.mark.asyncio
async def test_other_users_document_is_refused_like_a_missing_one_on_current_turn(
    real_db_io, monkeypatch
) -> None:
    rows, _ = real_db_io
    rows.append(_RealRow(id=1, user_id=OTHER))
    monkeypatch.setattr(attachment_blocks, "supports_vision", lambda model: True)

    with pytest.raises(AttachmentNotSupportedError) as excinfo:
        await resolve_attachments(
            [_message("봐줘", [_attachment("secret.png", "image/png", document_id=1)])],
            model="seeing-model",
            owner_user_id=OWNER,
        )

    # 존재하지만 소유가 아닌 문서는 "찾을 수 없음"과 구별되지 않아야 한다 —
    # 별도 사유는 그 자체로 문서 존재를 확인해 주는 신호가 된다.
    assert excinfo.value.items[0]["reason"] == "unresolved"


@pytest.mark.asyncio
async def test_other_users_document_is_demoted_like_a_missing_one_on_an_older_turn(
    real_db_io, monkeypatch
) -> None:
    rows, _ = real_db_io
    rows.append(_RealRow(id=1, user_id=OTHER, storage_key="secret-key"))
    rows.append(_RealRow(id=2, user_id=OWNER, storage_key="ok-key"))
    monkeypatch.setattr(attachment_blocks, "supports_vision", lambda model: True)

    async def fake_download(storage_key):
        return b"bytes"

    monkeypatch.setattr(attachment_blocks, "_download", fake_download)

    plan = await resolve_attachments(
        [
            _message("옛 턴", [_attachment("secret.png", "image/png", document_id=1)]),
            _message("새 턴", [_attachment("ok.png", "image/png", document_id=2)]),
        ],
        model="seeing-model",
        owner_user_id=OWNER,
    )

    assert plan.by_index[0][0].data is None
    assert "secret.png" in plan.by_index[0][0].text
    # 진짜 소유자의 문서(id=2)는 정상적으로 해석된다 — 필터가 전부를
    # 막아버린 게 아니라 소유권만 가려낸다는 걸 함께 보인다.
    assert plan.by_index[1][0].data == b"bytes"


@pytest.mark.asyncio
async def test_load_document_filters_by_owner_on_both_lookup_paths(real_db_io) -> None:
    """`_load_document` 자체가 documentId 경로와 storage_url 경로 둘 다에
    소유권 조건을 건다 — 진짜 세션 위에서 동작(다른 소유자는 못 찾고, 진짜
    소유자는 찾는다)과 조립된 WHERE 절의 구조를 함께 확인한다."""
    rows, session = real_db_io
    rows.append(_RealRow(id=1, user_id=OTHER, storage_url="s3://bucket/secret"))

    # documentId 경로: 다른 소유자로는 못 찾고, 진짜 소유자로는 찾는다.
    assert (
        await attachment_blocks._load_document(
            document_id=1, storage_url=None, owner_user_id=OWNER
        )
        is None
    )
    assert (
        await attachment_blocks._load_document(
            document_id=1, storage_url=None, owner_user_id=OTHER
        )
        is not None
    )

    # storage_url 경로도 마찬가지다.
    assert (
        await attachment_blocks._load_document(
            document_id=None, storage_url="s3://bucket/secret", owner_user_id=OWNER
        )
        is None
    )
    assert (
        await attachment_blocks._load_document(
            document_id=None, storage_url="s3://bucket/secret", owner_user_id=OTHER
        )
        is not None
    )

    # 구조 확인: 두 경로 모두 실제로 조립한 WHERE 절이 `documents.user_id`를
    # 그 호출의 owner_user_id 리터럴로 건다 — 컬럼 목록이 아니라 조건이다.
    assert len(session.captured_statements) == 4
    for stmt, expected_owner in zip(
        session.captured_statements, [OWNER, OTHER, OWNER, OTHER]
    ):
        compiled = str(
            stmt.compile(compile_kwargs={"literal_binds": True})
        )
        assert f"documents.user_id = '{expected_owner}'" in compiled, compiled


# ---------------------------------------------------------------------------
# Finding 7 — empty EXTRACT text must not vanish silently.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_docx_with_no_extractable_text_is_demoted_with_a_notice(
    stub_io, monkeypatch
) -> None:
    docs, _ = stub_io
    docs[1] = _Doc("application/msword")

    async def fake_parse_word(file_content=None, file_path=None):
        return {"text": ""}

    monkeypatch.setattr(attachment_blocks, "parse_word", fake_parse_word)

    plan = await resolve_attachments(
        [_message("요약", [_attachment("empty.docx", "application/msword")])],
        model="seeing-model",
        owner_user_id=OWNER,
    )

    resolved = plan.by_index[0][0]
    assert resolved.data is None
    assert "empty.docx" in resolved.text
    assert any("empty.docx" in notice for notice in plan.notices)


# ---------------------------------------------------------------------------
# Finding 8 — extracted text must count against the byte budget.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oversized_extracted_text_is_demoted_not_included(
    stub_io, monkeypatch
) -> None:
    docs, _ = stub_io
    docs[1] = _Doc("application/msword", file_size=10)  # tiny original file size

    huge_text = "x" * (attachment_blocks.MAX_ATTACHMENT_BYTES + 1)

    async def fake_parse_word(file_content=None, file_path=None):
        return {"text": huge_text}

    monkeypatch.setattr(attachment_blocks, "parse_word", fake_parse_word)

    plan = await resolve_attachments(
        [_message("요약", [_attachment("huge.docx", "application/msword")])],
        model="seeing-model",
        owner_user_id=OWNER,
    )

    resolved = plan.by_index[0][0]
    assert resolved.data is None
    assert resolved.text != huge_text
    assert "huge.docx" in resolved.text
    assert any("huge.docx" in notice for notice in plan.notices)


@pytest.mark.asyncio
async def test_extracted_text_within_budget_is_included_and_consumes_it(
    stub_io, monkeypatch
) -> None:
    docs, _ = stub_io
    docs[1] = _Doc("application/msword", file_size=10)

    async def fake_parse_word(file_content=None, file_path=None):
        return {"text": "짧은 요약"}

    monkeypatch.setattr(attachment_blocks, "parse_word", fake_parse_word)

    plan = await resolve_attachments(
        [_message("요약", [_attachment("small.docx", "application/msword")])],
        model="seeing-model",
        owner_user_id=OWNER,
    )

    resolved = plan.by_index[0][0]
    assert resolved.text == "짧은 요약"
    assert resolved.data is None


# ---------------------------------------------------------------------------
# Finding 3 — the download must not build a fresh provider every call, and
# must not block the event loop.
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_provider_cache():
    """`_get_provider` 는 모듈 전역 lru_cache 다 — 시작과 끝 모두 비워야

    한 테스트가 "s3" 밑에 스텁을 캐시해 두면, 그 뒤로 실행되는 아무 테스트나
    pytest 프로세스가 끝날 때까지 진짜 프로바이더 대신 그 스텁을 받는다
    (순서 의존 실패, N8 리뷰 Finding 6).
    """
    attachment_blocks._get_provider.cache_clear()
    yield
    attachment_blocks._get_provider.cache_clear()


def test_get_provider_is_cached_across_calls(monkeypatch, clean_provider_cache) -> None:
    calls: list[str] = []

    def fake_create_provider(provider_type: str, **kwargs):
        calls.append(provider_type)
        return object()

    monkeypatch.setattr(
        attachment_blocks.StorageService, "create_provider", staticmethod(fake_create_provider)
    )

    first = attachment_blocks._get_provider("s3")
    second = attachment_blocks._get_provider("s3")

    assert first is second
    assert calls == ["s3"], "provider was rebuilt on the second call"


@pytest.mark.asyncio
async def test_download_runs_the_blocking_call_off_the_event_loop(monkeypatch) -> None:
    main_thread_id = threading.get_ident()
    seen: dict[str, int] = {}

    class FakeProvider:
        async def download(self, key: str) -> bytes:
            seen["thread_id"] = threading.get_ident()
            return b"payload"

    monkeypatch.setattr(attachment_blocks, "_get_provider", lambda name: FakeProvider())

    data = await attachment_blocks._download("some-key")

    assert data == b"payload"
    assert seen["thread_id"] != main_thread_id, "download ran on the event loop thread"
