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
from neos.config.settings import settings

# Import the deep research agent
from neos.agents.search_agents.hyper_deep_research.agent import HyperDeepResearchAgent as HyperDeepResearch

logger = get_logger(__name__)
router = APIRouter()


# ============================================================================
# Helper Functions
# ============================================================================

def map_section_type_to_event_type(section_type: str) -> str:
    """Map agent's internal section types to SSE event section types.

    Agent uses detailed types like 'topic_analysis', 'methodology', etc.
    SSE events use broader categories: 'planning', 'data_collection', 'analysis', 'report_generation'
    """
    mapping = {
        # Planning phase
        "topic_analysis": "planning",
        "methodology": "planning",

        # Data collection phase
        "initial_collection": "data_collection",
        "gap_analysis": "data_collection",

        # Analysis phase
        "deep_analysis": "analysis",
        "validation": "analysis",
        "critical_analysis": "analysis",

        # Report generation phase
        "final_report": "report_generation",
    }

    # Return mapped type or default to 'analysis' if unknown
    return mapping.get(section_type, "analysis")


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
    """Update research report status and other fields

    Security: Uses whitelist approach to prevent SQL injection
    """
    # Whitelist of allowed fields to prevent SQL injection
    ALLOWED_FIELDS = {
        "started_at": "started_at",
        "completed_at": "completed_at",
        "total_sections": "total_sections",
        "total_sources": "total_sources",
        "total_queries": "total_queries",
        "processing_time_ms": "processing_time_ms",
        "quality_score": "quality_score"
    }

    update_fields = ["research_status = $2"]
    values = [report_id, status]
    param_idx = 3

    # Only process whitelisted fields
    for key, value in kwargs.items():
        if key in ALLOWED_FIELDS and value is not None:
            # Use the whitelisted field name (safe from injection)
            field_name = ALLOWED_FIELDS[key]
            update_fields.append(f"{field_name} = ${param_idx}")
            values.append(value)
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
        logger.info(f"Initializing HyperDeepResearch agent for report {report_id}")
        try:
            agent = HyperDeepResearch()
            logger.info("HyperDeepResearch agent initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize agent: {e}", exc_info=True)
            raise

        # Start agent execution in background
        context = {
            "report_id": report_id,
            "user_id": user_id,
            "session_id": session_id
        }
        logger.info(f"Starting agent execution with context: {context}")
        agent_task = asyncio.create_task(agent.execute(research_topic, context))
        logger.info(f"Agent task created: {agent_task}")

        # Track progress by polling DB for sections
        # Use timestamp-based tracking to prevent race conditions
        processed_section_ids = set()
        last_processed_timestamp = start_time
        start_time = datetime.now()
        last_status = "in_progress"

        # Maximum polling duration (from settings)
        MAX_POLLING_DURATION_SECONDS = settings.DEEP_RESEARCH_MAX_POLLING_DURATION
        POLL_INTERVAL_SECONDS = settings.DEEP_RESEARCH_POLL_INTERVAL

        # Poll for progress while agent is running
        poll_count = 0
        while not agent_task.done():
            poll_count += 1

            # Check for timeout to prevent infinite polling
            elapsed_time = (datetime.now() - start_time).total_seconds()
            if elapsed_time > MAX_POLLING_DURATION_SECONDS:
                logger.error(f"Research timeout after {elapsed_time:.1f}s (max: {MAX_POLLING_DURATION_SECONDS}s)")
                # Cancel the agent task
                agent_task.cancel()
                raise TimeoutError(f"Deep research exceeded maximum time limit of {MAX_POLLING_DURATION_SECONDS}s")

            # Check if task failed
            if agent_task.done():
                try:
                    agent_task.result()
                except Exception as task_error:
                    logger.error(f"Agent task failed: {task_error}", exc_info=True)
                    raise

            logger.debug(f"Poll #{poll_count}: Checking for new sections (elapsed: {elapsed_time:.1f}s)...")

            # Query for NEW sections only (created after last processed timestamp)
            # This prevents race conditions by using timestamp-based filtering
            sections_query = """
                SELECT
                    section_id, section_order, section_type,
                    section_title, section_content, section_status,
                    sources_count, created_at, completed_at
                FROM hyper_research_sections
                WHERE report_id = $1 AND created_at > $2
                ORDER BY created_at, section_order
            """
            sections_result = await db_manager.fetch_all(sections_query, report_id, last_processed_timestamp)

            if sections_result:
                logger.debug(f"Poll #{poll_count}: Found {len(sections_result)} new sections since last poll")

            # Process new sections
            for section in sections_result:
                section_id = section[0]

                # Double-check to prevent duplicates (belt and suspenders approach)
                if section_id in processed_section_ids:
                    logger.debug(f"Skipping already processed section: {section_id}")
                    continue

                # Mark as processed and update timestamp
                processed_section_ids.add(section_id)
                section_created_at = section[7]
                if section_created_at and section_created_at > last_processed_timestamp:
                    last_processed_timestamp = section_created_at

                    section_order = section[1]
                    section_type = section[2]
                    section_title = section[3]
                    section_content = section[4]
                    section_status = section[5]
                    sources_count = section[6] or 0

                    logger.info(f"New section found: {section_title} (order: {section_order}, type: {section_type})")

                    # Map agent's section type to SSE event type
                    event_section_type = map_section_type_to_event_type(section_type)
                    logger.debug(f"Mapped section type '{section_type}' to event type '{event_section_type}'")

                    # Send section started event
                    section_start_event = DeepResearchEvent(
                        event=DeepResearchEventType.SECTION_STARTED,
                        report_id=report_id,
                        data=SectionStartedEventData(
                            section_id=section_id,
                            section_title=section_title,
                            section_type=event_section_type
                        ).model_dump()
                    )
                    yield f"data: {section_start_event.model_dump_json()}\n\n"

                    # Stream section content in chunks if available
                    if section_content:
                        chunk_size = settings.DEEP_RESEARCH_CHUNK_SIZE
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

                    # Send section completed event
                    section_complete_event = DeepResearchEvent(
                        event=DeepResearchEventType.SECTION_COMPLETED,
                        report_id=report_id,
                        data=SectionCompletedEventData(
                            section_id=section_id,
                            section_title=section_title,
                            section_type=event_section_type,
                            section_content=section_content or "",
                            sources_count=sources_count
                        ).model_dump()
                    )
                    yield f"data: {section_complete_event.model_dump_json()}\n\n"

            # Get updated report status
            report = await get_research_report(report_id)
            if report and report["research_status"] != last_status:
                last_status = report["research_status"]

                # Send progress update
                progress_event = DeepResearchEvent(
                    event=DeepResearchEventType.PROGRESS_UPDATE,
                    report_id=report_id,
                    data=ProgressUpdateEventData(
                        current_phase=ResearchPhase.ANALYSIS,  # Generic phase
                        completed_sections=len(processed_section_ids),
                        total_sections=report.get("total_sections") or 0,
                        sources_collected=report.get("total_sources") or 0,
                        queries_executed=report.get("total_queries") or 0,
                        progress_percentage=min(95, (len(processed_section_ids) / max(1, report.get("total_sections") or 1)) * 100),
                        estimated_time_remaining_seconds=0
                    ).model_dump()
                )
                yield f"data: {progress_event.model_dump_json()}\n\n"

            # Wait before next poll
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

        # Agent task is done
        logger.info(f"Agent task completed. Total polls: {poll_count}, Sections processed: {len(processed_section_ids)}")

        # Wait for agent to complete and get result
        try:
            agent_result = await agent_task
            logger.info(f"Agent completed successfully: {agent_result}")
        except Exception as e:
            logger.error(f"Agent execution failed with exception: {e}", exc_info=True)
            raise

        # Get final report data
        final_report = await get_research_report(report_id)
        completed_sections = final_report.get("total_sections") or len(processed_section_ids)
        total_sources = final_report.get("total_sources") or 0
        total_queries = final_report.get("total_queries") or 0
        processing_time_ms = final_report.get("processing_time_ms") or int((datetime.now() - start_time).total_seconds() * 1000)

        # Update database with final status
        await update_research_status(
            report_id,
            "completed",
            completed_at=datetime.now(),
            total_sections=completed_sections,
            total_sources=total_sources,
            total_queries=total_queries,
            processing_time_ms=processing_time_ms,
            quality_score=settings.DEEP_RESEARCH_DEFAULT_QUALITY_SCORE
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

        # Track warnings for non-critical errors
        warnings = []

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
                "quality_score": settings.DEEP_RESEARCH_DEFAULT_QUALITY_SCORE,
                "is_placeholder": False
            })
            await db_manager.execute(update_message_query, final_content_summary, metadata_update, assistant_message_id)
            logger.info(f"Updated assistant message {assistant_message_id} with final content")
        except Exception as e:
            logger.error(f"Failed to update assistant message: {e}")
            warnings.append(f"Message update failed: {str(e)}")
            # Non-critical error, but track warning

        # If there are warnings, add them to report metadata
        if warnings:
            try:
                warning_update_query = """
                    UPDATE hyper_research_reports
                    SET metadata = metadata || CAST($1 AS jsonb)
                    WHERE report_id = $2
                """
                warning_metadata = json.dumps({"warnings": warnings})
                await db_manager.execute(warning_update_query, warning_metadata, report_id)
                logger.warning(f"Research completed with {len(warnings)} warning(s): {warnings}")
            except Exception as e:
                logger.error(f"Failed to record warnings: {e}")

        # Send completed event
        completed_event = DeepResearchEvent(
            event=DeepResearchEventType.COMPLETED,
            report_id=report_id,
            data=CompletedEventData(
                report_id=report_id,
                total_sections=completed_sections,
                total_sources=total_sources,
                total_queries=total_queries,
                quality_score=settings.DEEP_RESEARCH_DEFAULT_QUALITY_SCORE,
                processing_time_ms=processing_time_ms
            ).model_dump()
        )
        yield f"data: {completed_event.model_dump_json()}\n\n"

    except TimeoutError as e:
        logger.error(f"Deep research timeout: {e}")

        # Update status to failed
        await update_research_status(
            report_id,
            "failed",
            completed_at=datetime.now()
        )

        # Send timeout error event
        error_event = DeepResearchEvent(
            event=DeepResearchEventType.FAILED,
            report_id=report_id,
            data=ErrorEventData(
                error_message=str(e),
                error_code="RESEARCH_TIMEOUT"
            ).model_dump()
        )
        yield f"data: {error_event.model_dump_json()}\n\n"

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


async def _cleanup_failed_research(
    user_message_id: str = None,
    assistant_message_id: str = None,
    report_id: str = None
) -> None:
    """Cleanup resources created during failed research initiation

    Performs soft delete to maintain audit trail while ensuring data consistency
    """
    try:
        # Delete user message (soft delete)
        if user_message_id:
            try:
                delete_msg_query = """
                    UPDATE messages
                    SET deleted_at = CURRENT_TIMESTAMP
                    WHERE message_id = $1
                """
                await db_manager.execute(delete_msg_query, user_message_id)
                logger.info(f"Cleaned up user message: {user_message_id}")
            except Exception as e:
                logger.error(f"Failed to cleanup user message: {e}")

        # Delete assistant message (soft delete)
        if assistant_message_id:
            try:
                delete_msg_query = """
                    UPDATE messages
                    SET deleted_at = CURRENT_TIMESTAMP
                    WHERE message_id = $1
                """
                await db_manager.execute(delete_msg_query, assistant_message_id)
                logger.info(f"Cleaned up assistant message: {assistant_message_id}")
            except Exception as e:
                logger.error(f"Failed to cleanup assistant message: {e}")

        # Delete research report (soft delete)
        if report_id:
            try:
                delete_report_query = """
                    UPDATE hyper_research_reports
                    SET deleted_at = CURRENT_TIMESTAMP, research_status = 'failed'
                    WHERE report_id = $1
                """
                await db_manager.execute(delete_report_query, report_id)
                logger.info(f"Cleaned up research report: {report_id}")
            except Exception as e:
                logger.error(f"Failed to cleanup research report: {e}")

    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        # Don't raise - cleanup is best effort


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

    Transaction safety: If any step fails, cleanup is performed to maintain data consistency.
    """
    # Generate IDs upfront
    report_id = f"hyper_report_{uuid.uuid4().hex}"
    user_message_id = f"msg_{uuid.uuid4().hex}"
    assistant_message_id = f"msg_{uuid.uuid4().hex}"

    # Track created resources for cleanup on failure
    created_user_message = False
    created_assistant_message = False
    created_report = False

    try:
        # Validate conversation exists
        conversation = await ChatService.get_conversation(request.conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Step 1: Save user message to database
        try:
            await ChatService.add_message(
                conversation_id=request.conversation_id,
                role="user",
                content=request.research_topic,
                message_id=user_message_id,
                metadata={"deep_research_initiated": True}
            )
            created_user_message = True
            logger.info(f"Created user message: {user_message_id}")
        except Exception as e:
            logger.error(f"Failed to save user message: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to save user message: {str(e)}")

        # Step 2: Save placeholder assistant message
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
            created_assistant_message = True
            logger.info(f"Created assistant placeholder message: {assistant_message_id}")
        except Exception as e:
            logger.error(f"Failed to save assistant message: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to save assistant message: {str(e)}")

        # Step 3: Create report in database
        try:
            await save_deep_research_report(
                report_id=report_id,
                user_id=request.user_id,
                session_id=request.session_id or f"session_{uuid.uuid4().hex[:8]}",
                research_topic=request.research_topic,
                conversation_id=request.conversation_id,
                initial_message_id=user_message_id
            )
            created_report = True
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
        # Cleanup on failure to maintain data consistency
        await _cleanup_failed_research(
            user_message_id if created_user_message else None,
            assistant_message_id if created_assistant_message else None,
            report_id if created_report else None
        )
        raise
    except Exception as e:
        logger.error(f"Failed to start deep research: {e}", exc_info=True)
        # Cleanup on failure
        await _cleanup_failed_research(
            user_message_id if created_user_message else None,
            assistant_message_id if created_assistant_message else None,
            report_id if created_report else None
        )
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
