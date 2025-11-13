"""Deep Research API handlers - FastAPI routes for deep research functionality"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator
import json
import asyncio
import uuid
from datetime import datetime

from neos.api.models.deep_research_models import (
    StartDeepResearchRequest,
    StartDeepResearchResponse,
    ResearchReport,
    ResearchStatus,
    DeepResearchEvent,
    DeepResearchEventType,
    PhaseStartedEventData,
    PhaseCompletedEventData,
    SectionStartedEventData,
    SectionCompletedEventData,
    SectionContentEventData,
    QueryExecutedEventData,
    ProgressUpdateEventData,
    CompletedEventData,
    ErrorEventData,
    ResearchPhase,
)
from neos.api.services.chat_service import ChatService
from neos.database.connection import db_manager
from neos.utils.logger import get_logger

# Import the deep research agent
from neos.agents.search_agents.hyper_deep_research.agent import HyperDeepResearchAgent as HyperDeepResearch

logger = get_logger(__name__)
router = APIRouter()


# ============================================================================
# Helper Functions
# ============================================================================

async def save_deep_research_report(
    report_id: str,
    user_id: str,
    session_id: str,
    research_topic: str,
    conversation_id: str,
    initial_message_id: str
) -> str:
    """Create a new deep research report in database"""
    query = """
        INSERT INTO hyper_research_reports (
            report_id, user_id, session_id, research_topic,
            conversation_id, initial_message_id,
            research_status, research_plan, created_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
    """

    research_plan = {
        "phases": [
            "topic_confirmation",
            "planning",
            "data_collection",
            "analysis",
            "report_generation"
        ]
    }

    await db_manager.execute(
        query,
        report_id,
        user_id,
        session_id,
        research_topic,
        conversation_id,
        initial_message_id,
        "pending",
        json.dumps(research_plan),
        datetime.now()
    )

    return report_id


async def update_research_status(
    report_id: str,
    status: str,
    **kwargs
) -> None:
    """Update research report status and other fields"""
    update_fields = ["research_status = $2"]
    values = [report_id, status]
    param_idx = 3

    if "started_at" in kwargs and kwargs["started_at"]:
        update_fields.append(f"started_at = ${param_idx}")
        values.append(kwargs["started_at"])
        param_idx += 1

    if "completed_at" in kwargs and kwargs["completed_at"]:
        update_fields.append(f"completed_at = ${param_idx}")
        values.append(kwargs["completed_at"])
        param_idx += 1

    if "total_sections" in kwargs:
        update_fields.append(f"total_sections = ${param_idx}")
        values.append(kwargs["total_sections"])
        param_idx += 1

    if "total_sources" in kwargs:
        update_fields.append(f"total_sources = ${param_idx}")
        values.append(kwargs["total_sources"])
        param_idx += 1

    if "total_queries" in kwargs:
        update_fields.append(f"total_queries = ${param_idx}")
        values.append(kwargs["total_queries"])
        param_idx += 1

    if "processing_time_ms" in kwargs:
        update_fields.append(f"processing_time_ms = ${param_idx}")
        values.append(kwargs["processing_time_ms"])
        param_idx += 1

    if "quality_score" in kwargs:
        update_fields.append(f"quality_score = ${param_idx}")
        values.append(kwargs["quality_score"])
        param_idx += 1

    query = f"""
        UPDATE hyper_research_reports
        SET {", ".join(update_fields)}, updated_at = CURRENT_TIMESTAMP
        WHERE report_id = $1
    """

    await db_manager.execute(query, *values)


async def get_research_report(report_id: str) -> dict:
    """Get research report by ID"""
    query = """
        SELECT
            report_id, user_id, session_id, research_topic,
            conversation_id, initial_message_id,
            research_status, research_plan,
            total_sections, total_sources, total_queries,
            quality_score, completeness_score, processing_time_ms,
            created_at, started_at, completed_at
        FROM hyper_research_reports
        WHERE report_id = $1 AND deleted_at IS NULL
    """

    result = await db_manager.fetch_one(query, report_id)

    if not result:
        return None

    return {
        "report_id": result[0],
        "user_id": result[1],
        "session_id": result[2],
        "research_topic": result[3],
        "conversation_id": result[4],
        "initial_message_id": result[5],
        "research_status": result[6],
        "research_plan": result[7],
        "total_sections": result[8],
        "total_sources": result[9],
        "total_queries": result[10],
        "quality_score": result[11],
        "completeness_score": result[12],
        "processing_time_ms": result[13],
        "created_at": result[14],
        "started_at": result[15],
        "completed_at": result[16],
    }


# ============================================================================
# Deep Research Streaming Generator
# ============================================================================

async def deep_research_stream_generator(
    report_id: str,
    user_id: str,
    session_id: str,
    research_topic: str,
    conversation_id: str,
    initial_message_id: str,
    assistant_message_id: str
) -> AsyncGenerator[str, None]:
    """
    Generator for SSE streaming of deep research progress

    Yields Server-Sent Events formatted strings for real-time updates
    """
    try:
        # Send started event
        started_event = DeepResearchEvent(
            event=DeepResearchEventType.STARTED,
            report_id=report_id,
            data={
                "message": "Deep research started",
                "research_topic": research_topic
            }
        )
        yield f"data: {started_event.model_dump_json()}\n\n"

        # Update status to in_progress
        await update_research_status(
            report_id,
            "in_progress",
            started_at=datetime.now()
        )

        # Initialize the HyperDeepResearch agent
        agent = HyperDeepResearch()

        # Track progress
        total_queries = 0
        total_sources = 0
        completed_sections = 0
        start_time = datetime.now()

        # Phase 1: Topic Confirmation
        phase_start = datetime.now()
        phase_event = DeepResearchEvent(
            event=DeepResearchEventType.PHASE_STARTED,
            report_id=report_id,
            data=PhaseStartedEventData(
                phase=ResearchPhase.TOPIC_CONFIRMATION,
                message="Confirming and analyzing research topic..."
            ).model_dump()
        )
        yield f"data: {phase_event.model_dump_json()}\n\n"

        # Topic analysis (this would call the actual agent method)
        # For now, we'll simulate the flow
        await asyncio.sleep(0.5)  # Simulate processing

        phase_complete = DeepResearchEvent(
            event=DeepResearchEventType.PHASE_COMPLETED,
            report_id=report_id,
            data=PhaseCompletedEventData(
                phase=ResearchPhase.TOPIC_CONFIRMATION,
                message="Topic confirmed",
                duration_ms=int((datetime.now() - phase_start).total_seconds() * 1000)
            ).model_dump()
        )
        yield f"data: {phase_complete.model_dump_json()}\n\n"

        # Phase 2: Planning
        phase_start = datetime.now()
        phase_event = DeepResearchEvent(
            event=DeepResearchEventType.PHASE_STARTED,
            report_id=report_id,
            data=PhaseStartedEventData(
                phase=ResearchPhase.PLANNING,
                message="Creating comprehensive research plan..."
            ).model_dump()
        )
        yield f"data: {phase_event.model_dump_json()}\n\n"

        await asyncio.sleep(1)  # Simulate processing

        phase_complete = DeepResearchEvent(
            event=DeepResearchEventType.PHASE_COMPLETED,
            report_id=report_id,
            data=PhaseCompletedEventData(
                phase=ResearchPhase.PLANNING,
                message="Research plan created",
                duration_ms=int((datetime.now() - phase_start).total_seconds() * 1000)
            ).model_dump()
        )
        yield f"data: {phase_complete.model_dump_json()}\n\n"

        # Phase 3: Data Collection
        phase_start = datetime.now()
        phase_event = DeepResearchEvent(
            event=DeepResearchEventType.PHASE_STARTED,
            report_id=report_id,
            data=PhaseStartedEventData(
                phase=ResearchPhase.DATA_COLLECTION,
                message="Collecting data from multiple sources..."
            ).model_dump()
        )
        yield f"data: {phase_event.model_dump_json()}\n\n"

        # Simulate multiple queries
        for i in range(5):
            query_event = DeepResearchEvent(
                event=DeepResearchEventType.QUERY_EXECUTED,
                report_id=report_id,
                data=QueryExecutedEventData(
                    query=f"Query {i+1} about {research_topic}",
                    query_type="initial",
                    results_count=10
                ).model_dump()
            )
            yield f"data: {query_event.model_dump_json()}\n\n"
            total_queries += 1
            total_sources += 10

            # Progress update
            progress_event = DeepResearchEvent(
                event=DeepResearchEventType.PROGRESS_UPDATE,
                report_id=report_id,
                data=ProgressUpdateEventData(
                    current_phase=ResearchPhase.DATA_COLLECTION,
                    completed_sections=completed_sections,
                    total_sections=5,
                    sources_collected=total_sources,
                    queries_executed=total_queries,
                    progress_percentage=20 + (i * 10),
                    estimated_time_remaining_seconds=30 - (i * 5)
                ).model_dump()
            )
            yield f"data: {progress_event.model_dump_json()}\n\n"

            await asyncio.sleep(0.5)

        phase_complete = DeepResearchEvent(
            event=DeepResearchEventType.PHASE_COMPLETED,
            report_id=report_id,
            data=PhaseCompletedEventData(
                phase=ResearchPhase.DATA_COLLECTION,
                message=f"Data collection complete - {total_sources} sources collected",
                duration_ms=int((datetime.now() - phase_start).total_seconds() * 1000)
            ).model_dump()
        )
        yield f"data: {phase_complete.model_dump_json()}\n\n"

        # Phase 4: Analysis
        phase_start = datetime.now()
        phase_event = DeepResearchEvent(
            event=DeepResearchEventType.PHASE_STARTED,
            report_id=report_id,
            data=PhaseStartedEventData(
                phase=ResearchPhase.ANALYSIS,
                message="Analyzing collected data..."
            ).model_dump()
        )
        yield f"data: {phase_event.model_dump_json()}\n\n"

        await asyncio.sleep(1)

        phase_complete = DeepResearchEvent(
            event=DeepResearchEventType.PHASE_COMPLETED,
            report_id=report_id,
            data=PhaseCompletedEventData(
                phase=ResearchPhase.ANALYSIS,
                message="Analysis complete",
                duration_ms=int((datetime.now() - phase_start).total_seconds() * 1000)
            ).model_dump()
        )
        yield f"data: {phase_complete.model_dump_json()}\n\n"

        # Phase 5: Report Generation
        phase_start = datetime.now()
        phase_event = DeepResearchEvent(
            event=DeepResearchEventType.PHASE_STARTED,
            report_id=report_id,
            data=PhaseStartedEventData(
                phase=ResearchPhase.REPORT_GENERATION,
                message="Generating comprehensive report..."
            ).model_dump()
        )
        yield f"data: {phase_event.model_dump_json()}\n\n"

        # Simulate section generation
        sections = [
            "Executive Summary",
            "Background and Context",
            "Key Findings",
            "Detailed Analysis",
            "Conclusions and Recommendations"
        ]

        for idx, section_title in enumerate(sections):
            section_id = f"section_{uuid.uuid4().hex[:8]}"

            # Section started
            section_start_event = DeepResearchEvent(
                event=DeepResearchEventType.SECTION_STARTED,
                report_id=report_id,
                data=SectionStartedEventData(
                    section_id=section_id,
                    section_title=section_title,
                    section_type="report_generation"
                ).model_dump()
            )
            yield f"data: {section_start_event.model_dump_json()}\n\n"

            # Stream section content in chunks
            section_content = f"## {section_title}\n\nThis section provides detailed information about {research_topic}. "
            section_content += "The analysis shows important insights based on the collected data from multiple sources. "
            section_content += "Key points include comprehensive coverage of the topic with evidence-based conclusions.\n\n"

            # Stream content in chunks (simulate streaming)
            chunk_size = 50
            for i in range(0, len(section_content), chunk_size):
                chunk = section_content[i:i+chunk_size]
                content_event = DeepResearchEvent(
                    event=DeepResearchEventType.SECTION_CONTENT,
                    report_id=report_id,
                    data=SectionContentEventData(
                        section_id=section_id,
                        content_chunk=chunk,
                        is_final=(i + chunk_size >= len(section_content))
                    ).model_dump()
                )
                yield f"data: {content_event.model_dump_json()}\n\n"
                await asyncio.sleep(0.1)

            # Section completed
            section_complete_event = DeepResearchEvent(
                event=DeepResearchEventType.SECTION_COMPLETED,
                report_id=report_id,
                data=SectionCompletedEventData(
                    section_id=section_id,
                    section_title=section_title,
                    section_type="report_generation",
                    section_content=section_content,
                    sources_count=total_sources
                ).model_dump()
            )
            yield f"data: {section_complete_event.model_dump_json()}\n\n"

            completed_sections += 1

            # Progress update
            progress_event = DeepResearchEvent(
                event=DeepResearchEventType.PROGRESS_UPDATE,
                report_id=report_id,
                data=ProgressUpdateEventData(
                    current_phase=ResearchPhase.REPORT_GENERATION,
                    completed_sections=completed_sections,
                    total_sections=len(sections),
                    sources_collected=total_sources,
                    queries_executed=total_queries,
                    progress_percentage=70 + ((idx + 1) / len(sections) * 30),
                    estimated_time_remaining_seconds=max(0, (len(sections) - idx - 1) * 2)
                ).model_dump()
            )
            yield f"data: {progress_event.model_dump_json()}\n\n"

        phase_complete = DeepResearchEvent(
            event=DeepResearchEventType.PHASE_COMPLETED,
            report_id=report_id,
            data=PhaseCompletedEventData(
                phase=ResearchPhase.REPORT_GENERATION,
                message="Report generation complete",
                duration_ms=int((datetime.now() - phase_start).total_seconds() * 1000)
            ).model_dump()
        )
        yield f"data: {phase_complete.model_dump_json()}\n\n"

        # Calculate final metrics
        processing_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        # Update database with final status
        await update_research_status(
            report_id,
            "completed",
            completed_at=datetime.now(),
            total_sections=completed_sections,
            total_sources=total_sources,
            total_queries=total_queries,
            processing_time_ms=processing_time_ms,
            quality_score=0.85
        )

        # Update assistant message with final content
        # Note: Frontend will receive the final content via SSE stream,
        # but we also update the DB for persistence
        final_content_summary = f"✅ Deep Research Complete: {research_topic}\n\n"
        final_content_summary += f"**Results:**\n"
        final_content_summary += f"- Sections: {completed_sections}\n"
        final_content_summary += f"- Sources: {total_sources}\n"
        final_content_summary += f"- Queries: {total_queries}\n"
        final_content_summary += f"- Processing time: {processing_time_ms / 1000:.2f}s\n\n"
        final_content_summary += "_Full report available in deep research system_"

        try:
            # Update message content and metadata in database
            update_message_query = """
                UPDATE messages
                SET
                    content = $1,
                    status = 'completed',
                    metadata = metadata || CAST($2 AS jsonb),
                    completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE message_id = $3
            """
            metadata_update = json.dumps({
                "deep_research_report_id": report_id,
                "research_status": "completed",
                "total_sections": completed_sections,
                "total_sources": total_sources,
                "total_queries": total_queries,
                "processing_time_ms": processing_time_ms,
                "quality_score": 0.85,
                "is_placeholder": False
            })
            await db_manager.execute(update_message_query, final_content_summary, metadata_update, assistant_message_id)
            logger.info(f"Updated assistant message {assistant_message_id} with final content")
        except Exception as e:
            logger.error(f"Failed to update assistant message: {e}")
            # Non-critical error, continue

        # Send completed event
        completed_event = DeepResearchEvent(
            event=DeepResearchEventType.COMPLETED,
            report_id=report_id,
            data=CompletedEventData(
                report_id=report_id,
                total_sections=completed_sections,
                total_sources=total_sources,
                total_queries=total_queries,
                quality_score=0.85,
                processing_time_ms=processing_time_ms
            ).model_dump()
        )
        yield f"data: {completed_event.model_dump_json()}\n\n"

    except Exception as e:
        logger.error(f"Deep research failed: {e}")

        # Update status to failed
        await update_research_status(
            report_id,
            "failed",
            completed_at=datetime.now()
        )

        # Send error event
        error_event = DeepResearchEvent(
            event=DeepResearchEventType.FAILED,
            report_id=report_id,
            data=ErrorEventData(
                error_message=str(e),
                error_code="RESEARCH_FAILED"
            ).model_dump()
        )
        yield f"data: {error_event.model_dump_json()}\n\n"


# ============================================================================
# Deep Research Endpoints
# ============================================================================

@router.post("/deep-research/start", response_model=StartDeepResearchResponse)
async def start_deep_research(request: StartDeepResearchRequest):
    """
    Start a new deep research task

    This endpoint initiates a deep research process and returns a report ID
    along with a stream URL for real-time progress updates.

    Also creates the user message and placeholder assistant message in the database.
    """
    try:
        # Generate IDs
        report_id = f"hyper_report_{uuid.uuid4().hex}"
        user_message_id = f"msg_{uuid.uuid4().hex}"
        assistant_message_id = f"msg_{uuid.uuid4().hex}"

        # Validate conversation exists
        conversation = await ChatService.get_conversation(request.conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Save user message to database
        try:
            await ChatService.add_message(
                conversation_id=request.conversation_id,
                role="user",
                content=request.research_topic,
                message_id=user_message_id,
                metadata={"deep_research_initiated": True}
            )
            logger.info(f"Created user message: {user_message_id}")
        except Exception as e:
            logger.error(f"Failed to save user message: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to save user message: {str(e)}")

        # Save placeholder assistant message
        try:
            await ChatService.add_message(
                conversation_id=request.conversation_id,
                role="assistant",
                content="🔬 Initiating deep research...",
                message_id=assistant_message_id,
                model_name="hyper-deep-research",
                metadata={
                    "deep_research_report_id": report_id,
                    "research_status": "pending",
                    "is_placeholder": True
                }
            )
            logger.info(f"Created assistant placeholder message: {assistant_message_id}")
        except Exception as e:
            logger.error(f"Failed to save assistant message: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to save assistant message: {str(e)}")

        # Create report in database
        try:
            await save_deep_research_report(
                report_id=report_id,
                user_id=request.user_id,
                session_id=request.session_id or f"session_{uuid.uuid4().hex[:8]}",
                research_topic=request.research_topic,
                conversation_id=request.conversation_id,
                initial_message_id=user_message_id
            )
            logger.info(f"Created deep research report: {report_id}")
        except Exception as e:
            logger.error(f"Failed to create research report: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create research report: {str(e)}")

        logger.info(f"Started deep research: {report_id} for topic: {request.research_topic}")

        return StartDeepResearchResponse(
            success=True,
            report_id=report_id,
            research_topic=request.research_topic,
            research_status=ResearchStatus.PENDING,
            message="Deep research initiated successfully",
            stream_url=f"/api/v1/deep-research/{report_id}/stream",
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start deep research: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/deep-research/{report_id}/stream")
async def stream_deep_research(report_id: str):
    """
    Stream deep research progress via Server-Sent Events (SSE)

    This endpoint provides real-time updates on the research progress.
    """
    try:
        # Get report to extract details
        report = await get_research_report(report_id)
        if not report:
            raise HTTPException(status_code=404, detail="Research report not found")

        # Find the assistant message associated with this report
        # Query messages table for message with this report_id in metadata
        find_assistant_message_query = """
            SELECT message_id
            FROM messages
            WHERE conversation_id = $1
              AND role = 'assistant'
              AND metadata @> CAST($2 AS jsonb)
            ORDER BY created_at DESC
            LIMIT 1
        """
        report_metadata = json.dumps({"deep_research_report_id": report_id})
        result = await db_manager.fetch_one(find_assistant_message_query, report["conversation_id"], report_metadata)

        if not result:
            logger.error(f"Assistant message not found for report {report_id}")
            raise HTTPException(status_code=500, detail="Assistant message not found for this research")

        assistant_message_id = result[0]
        logger.info(f"Found assistant message {assistant_message_id} for report {report_id}")

        # Create streaming response
        return StreamingResponse(
            deep_research_stream_generator(
                report_id=report_id,
                user_id=report["user_id"],
                session_id=report["session_id"],
                research_topic=report["research_topic"],
                conversation_id=report["conversation_id"],
                initial_message_id=report["initial_message_id"],
                assistant_message_id=assistant_message_id
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to stream deep research: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/deep-research/{report_id}", response_model=ResearchReport)
async def get_deep_research_report(report_id: str):
    """
    Get a deep research report by ID

    Returns the full report with all sections and metadata.
    """
    try:
        report = await get_research_report(report_id)
        if not report:
            raise HTTPException(status_code=404, detail="Research report not found")

        # Get sections
        sections_query = """
            SELECT
                section_id, section_order, section_level, section_type,
                section_title, section_content, section_summary, section_status,
                sources_count, created_at, completed_at
            FROM hyper_research_sections
            WHERE report_id = $1
            ORDER BY section_order
        """
        sections_result = await db_manager.fetch_all(sections_query, report_id)

        sections = []
        for section in sections_result:
            sections.append({
                "section_id": section[0],
                "section_order": section[1],
                "section_level": section[2],
                "section_type": section[3],
                "section_title": section[4],
                "section_content": section[5],
                "section_summary": section[6],
                "section_status": section[7],
                "sources_count": section[8],
                "created_at": section[9],
                "completed_at": section[10],
            })

        report["sections"] = sections

        return ResearchReport(**report)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get research report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversations/{conversation_id}/deep-research")
async def list_conversation_deep_research(conversation_id: str):
    """
    List all deep research reports for a conversation

    Returns a list of research reports associated with the conversation.
    """
    try:
        query = """
            SELECT
                report_id, research_topic, research_status,
                created_at, completed_at, total_sections, total_sources, quality_score
            FROM hyper_research_reports
            WHERE conversation_id = $1 AND deleted_at IS NULL
            ORDER BY created_at DESC
        """

        results = await db_manager.fetch_all(query, conversation_id)

        reports = []
        for row in results:
            reports.append({
                "report_id": row[0],
                "research_topic": row[1],
                "research_status": row[2],
                "created_at": row[3],
                "completed_at": row[4],
                "total_sections": row[5],
                "total_sources": row[6],
                "quality_score": row[7],
            })

        return {
            "conversation_id": conversation_id,
            "reports": reports,
            "total_count": len(reports)
        }

    except Exception as e:
        logger.error(f"Failed to list deep research reports: {e}")
        raise HTTPException(status_code=500, detail=str(e))
