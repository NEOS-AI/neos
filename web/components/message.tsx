"use client";
import type { UseChatHelpers } from "@ai-sdk/react";
import equal from "fast-deep-equal";
import { memo, useState } from "react";
import { forgetActiveRun } from "@/lib/deep-analysis/active-run-store";
import type { Vote } from "@/lib/db/schema";
import type { ApprovalRequest } from "@/lib/open-responses-types";
import type { ChatMessage } from "@/lib/types";
import { cn, sanitizeText } from "@/lib/utils";
import { ArtifactBlock } from "./artifact-block";
import { UIFrameRenderer } from "./ui-frame/UIFrameRenderer";
import { MermaidDiagram } from "./mermaid-diagram";
import { DataChart } from "./data-chart";
import { useDataStream } from "./data-stream-provider";
import { DocumentToolResult } from "./document";
import { DocumentPreview } from "./document-preview";
import { ErrorBoundary } from "./error-boundary";
import { MessageContent } from "./elements/message";
import { Response } from "./elements/response";
import {
  Tool,
  ToolContent,
  ToolHeader,
  ToolInput,
  ToolOutput,
} from "./elements/tool";
import { CheckCircleFillIcon, SparklesIcon, StopIcon } from "./icons";
import { DeepAnalysisStatus } from "./deep-analysis-status";
import { HarnessStatus } from "./harness-status";
import { MessageActions } from "./message-actions";
import { MessageEditor } from "./message-editor";
import { MessageReasoning } from "./message-reasoning";
import { PreviewAttachment } from "./preview-attachment";
import { Button } from "./ui/button";
import { Weather } from "./weather";

const PurePreviewMessage = ({
  chatId,
  message,
  vote,
  isLoading,
  setMessages,
  regenerate,
  isReadonly,
  requiresScrollPadding: _requiresScrollPadding,
}: {
  chatId: string;
  message: ChatMessage;
  vote: Vote | undefined;
  isLoading: boolean;
  setMessages: UseChatHelpers<ChatMessage>["setMessages"];
  regenerate: UseChatHelpers<ChatMessage>["regenerate"];
  isReadonly: boolean;
  requiresScrollPadding: boolean;
}) => {
  const [mode, setMode] = useState<"view" | "edit">("view");
  const [approvalStatuses, setApprovalStatuses] = useState<Record<string, string>>({});

  const attachmentsFromMessage = message.parts.filter(
    (part) => part.type === "file"
  );

  useDataStream();

  const updateApprovalMessage = ({
    text,
    responseStatus,
    clearApprovals = false,
  }: {
    text?: string;
    responseStatus?: "completed" | "failed" | "incomplete";
    clearApprovals?: boolean;
  }) => {
    setMessages((prev) =>
      prev.map((item) => {
        if (item.id !== message.id) return item;

        let textApplied = text === undefined;
        const parts = item.parts.map((part: any) => {
          if (!textApplied && part.type === "text") {
            textApplied = true;
            return { ...part, text };
          }
          return part;
        });
        if (!textApplied && text !== undefined) {
          parts.push({ type: "text", text } as any);
        }

        return {
          ...item,
          parts,
          metadata: {
            createdAt: item.metadata?.createdAt ?? new Date().toISOString(),
            ...item.metadata,
            ...(responseStatus ? { responseStatus } : {}),
            ...(clearApprovals ? { approval_requests: [] } : {}),
          },
        };
      })
    );
  };

  /**
   * deep_analysis 종결 처리 — 리포트를 이 어시스턴트 메시지 본문에 넣고
   * job 상태를 못박는다.
   *
   * 백엔드도 완료 시 리포트를 메시지에 영속화하므로 새로고침해도 남는다.
   * 여기서 하는 일은 **즉시 보여주기**와, 다시 구독하지 않도록 상태를
   * `completed`/`failed`로 확정하는 것뿐이다.
   */
  const settleDeepAnalysis = (
    status: "completed" | "failed",
    text?: string
  ) => {
    // 진행 중 run 포인터를 지운다 — 이 대화를 새로고침해도 다시 붙지 않는다.
    forgetActiveRun(chatId);

    setMessages((prev) =>
      prev.map((item) => {
        if (item.id !== message.id) {
          return item;
        }

        let parts = item.parts;
        if (text) {
          let applied = false;
          parts = item.parts.map((part: any) => {
            // 비어 있는 텍스트 파트에만 채운다. 이미 본문이 있으면
            // (영속화된 리포트를 복원한 경우) 덮어쓰지 않는다.
            if (!applied && part.type === "text" && !part.text?.trim()) {
              applied = true;
              return { ...part, text };
            }
            return part;
          });
          if (!applied && !item.parts.some((p: any) => p.type === "text" && p.text?.trim())) {
            parts = [...parts, { type: "text", text } as any];
          }
        }

        return {
          ...item,
          parts,
          metadata: {
            createdAt: item.metadata?.createdAt ?? new Date().toISOString(),
            ...item.metadata,
            responseStatus: status === "failed" ? "failed" : "completed",
            deep_analysis: {
              ...(item.metadata?.deep_analysis ?? { run_id: "" }),
              status,
            },
          },
        };
      })
    );
  };

  const applyDeepAnalysisReport = (reportMarkdown: string | null) => {
    settleDeepAnalysis("completed", reportMarkdown ?? undefined);
  };

  const applyDeepAnalysisFailure = (_error: string) => {
    // 에러 문구 자체는 `DeepAnalysisStatus`가 인라인으로 보여준다.
    // 여기서는 메시지 상태만 실패로 확정한다(토스트를 띄우지 않는다 —
    // job 실패는 대화 안에서 설명되는 편이 낫다).
    settleDeepAnalysis("failed");
  };

  const readApprovalResumeStream = async (sessionId: string) => {
    const response = await fetch(
      `/api/approval/stream/${encodeURIComponent(sessionId)}`
    );
    if (!response.ok) {
      throw new Error("Failed to resume approval stream");
    }
    if (!response.body) return;

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let eventName = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (line.startsWith("event: ")) {
          eventName = line.slice("event: ".length).trim();
          continue;
        }
        if (!line.startsWith("data: ")) continue;

        const payloadText = line.slice("data: ".length).trim();
        const payload = JSON.parse(payloadText);
        if (eventName === "completed") {
          const responseText =
            payload.response || payload.data?.response || "";
          updateApprovalMessage({
            text: responseText,
            responseStatus: "completed",
            clearApprovals: true,
          });
          return;
        }
        if (eventName === "error") {
          throw new Error(payload.message || "Approval resume failed");
        }
      }
    }
  };

  const respondToApproval = async (
    approval: ApprovalRequest,
    decision: "approved" | "rejected"
  ) => {
    const sessionId = message.metadata?.approval_session_id ?? chatId;
    setApprovalStatuses((prev) => ({
      ...prev,
      [approval.request_id]: "submitting",
    }));

    try {
      const response = await fetch("/api/approval/respond", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          request_id: approval.request_id,
          decision,
          skill_name: approval.skill_name,
        }),
      });
      if (!response.ok) {
        throw new Error("Approval response failed");
      }

      setApprovalStatuses((prev) => ({
        ...prev,
        [approval.request_id]: decision,
      }));
      await readApprovalResumeStream(sessionId);
      setApprovalStatuses((prev) => ({
        ...prev,
        [approval.request_id]: "completed",
      }));
    } catch (error) {
      setApprovalStatuses((prev) => ({
        ...prev,
        [approval.request_id]: "error",
      }));
      updateApprovalMessage({
        responseStatus: "failed",
      });
    }
  };

  return (
    <div
      className="group/message fade-in w-full animate-in duration-200"
      data-role={message.role}
      data-testid={`message-${message.role}`}
    >
      <div
        className={cn("flex w-full items-start gap-2 md:gap-3", {
          "justify-end": message.role === "user" && mode !== "edit",
          "justify-start": message.role === "assistant",
        })}
      >
        {message.role === "assistant" && (
          <div className="-mt-1 flex size-8 shrink-0 items-center justify-center rounded-full bg-background ring-1 ring-border">
            <SparklesIcon size={14} />
          </div>
        )}

        <div
          className={cn("flex flex-col", {
            "gap-2 md:gap-4": message.parts?.some(
              (p) => p.type === "text" && p.text?.trim()
            ),
            "w-full":
              (message.role === "assistant" &&
                message.parts?.some(
                  (p) => p.type === "text" && p.text?.trim()
                )) ||
              mode === "edit",
            "max-w-[calc(100%-2.5rem)] sm:max-w-[min(fit-content,80%)]":
              message.role === "user" && mode !== "edit",
          })}
        >
          {attachmentsFromMessage.length > 0 && (
            <div
              className="flex flex-row justify-end gap-2"
              data-testid={"message-attachments"}
            >
              {attachmentsFromMessage.map((attachment) => (
                <PreviewAttachment
                  attachment={{
                    name: attachment.filename ?? "file",
                    contentType: attachment.mediaType,
                    url: attachment.url,
                  }}
                  key={attachment.url}
                />
              ))}
            </div>
          )}

          {/* Workflow Agents (rendered as Tools) */}
          {message.role === "assistant" &&
            message.metadata?.workflow_agents &&
            message.metadata.workflow_agents.map((agent, index) => (
              <Tool
                defaultOpen={false}
                key={`workflow-agent-${message.id}-${agent.node_name}-${index}`}
              >
                <ToolHeader
                  state={agent.status as "input-available" | "output-available"}
                  type={`workflow-${agent.agent_name}` as any}
                />
                <ToolContent>
                  {agent.status === "input-available" && (
                    <div className="text-sm text-muted-foreground">
                      Processing: {agent.agent_name}
                    </div>
                  )}
                  {agent.status === "output-available" && (
                    <div className="text-sm text-green-600">
                      ✓ {agent.agent_name} completed
                    </div>
                  )}
                </ToolContent>
              </Tool>
            ))}

          {message.role === "assistant" &&
            message.metadata?.approval_requests &&
            message.metadata.approval_requests.map((approval, index) => (
              <Tool
                defaultOpen={true}
                key={`approval-${message.id}-${approval.request_id}-${index}`}
              >
                <ToolHeader
                  state={"approval-requested" as any}
                  title={`Approval required: ${approval.skill_name}`}
                  type={`workflow-${approval.skill_name}` as any}
                />
                <ToolContent>
                  <div className="space-y-2 p-4 text-sm">
                    <div className="text-muted-foreground">
                      This workflow is paused until the requested action is approved.
                    </div>
                    {approval.params && (
                      <pre className="overflow-x-auto rounded-md bg-muted/50 p-3 text-xs">
                        {JSON.stringify(approval.params, null, 2)}
                      </pre>
                    )}
                    <div className="flex flex-wrap gap-2">
                      <Button
                        disabled={approvalStatuses[approval.request_id] === "submitting"}
                        onClick={() => respondToApproval(approval, "approved")}
                        size="sm"
                        type="button"
                      >
                        <CheckCircleFillIcon size={14} />
                        Approve
                      </Button>
                      <Button
                        disabled={approvalStatuses[approval.request_id] === "submitting"}
                        onClick={() => respondToApproval(approval, "rejected")}
                        size="sm"
                        type="button"
                        variant="outline"
                      >
                        <StopIcon size={14} />
                        Reject
                      </Button>
                      {approvalStatuses[approval.request_id] === "error" && (
                        <span className="self-center text-destructive text-xs">
                          Approval response failed
                        </span>
                      )}
                    </div>
                  </div>
                </ToolContent>
              </Tool>
            ))}

          {message.role === "assistant" && message.metadata?.harness && (
            <HarnessStatus harness={message.metadata.harness} />
          )}

          {message.role === "assistant" && message.metadata?.deep_analysis && (
            <DeepAnalysisStatus
              deepAnalysis={message.metadata.deep_analysis}
              onCompleted={applyDeepAnalysisReport}
              onFailed={applyDeepAnalysisFailure}
            />
          )}

          {message.parts?.map((part, index) => {
            const { type } = part;
            const key = `message-${message.id}-part-${index}`;

            if (type === "reasoning" && part.text?.trim().length > 0) {
              return (
                <MessageReasoning
                  isLoading={isLoading}
                  key={key}
                  reasoning={part.text}
                />
              );
            }

            if (type === "text") {
              if (mode === "view") {
                return (
                  <div key={key}>
                    <MessageContent
                      className={cn({
                        "w-fit break-words rounded-2xl px-3 py-2 text-right text-white":
                          message.role === "user",
                        "bg-transparent px-0 py-0 text-left":
                          message.role === "assistant",
                      })}
                      data-testid="message-content"
                      style={
                        message.role === "user"
                          ? { backgroundColor: "#006cff" }
                          : undefined
                      }
                    >
                      <Response>{sanitizeText(part.text)}</Response>
                    </MessageContent>
                  </div>
                );
              }

              if (mode === "edit") {
                return (
                  <div
                    className="flex w-full flex-row items-start gap-3"
                    key={key}
                  >
                    <div className="size-8" />
                    <div className="min-w-0 flex-1">
                      <MessageEditor
                        key={message.id}
                        message={message}
                        regenerate={regenerate}
                        setMessages={setMessages}
                        setMode={setMode}
                      />
                    </div>
                  </div>
                );
              }
            }

            if (type === "tool-getWeather") {
              const { toolCallId, state } = part;

              return (
                <Tool defaultOpen={true} key={toolCallId}>
                  <ToolHeader state={state} type="tool-getWeather" />
                  <ToolContent>
                    {state === "input-available" && (
                      <ToolInput input={part.input} />
                    )}
                    {state === "output-available" && (
                      <ToolOutput
                        errorText={undefined}
                        output={<Weather weatherAtLocation={part.output} />}
                      />
                    )}
                  </ToolContent>
                </Tool>
              );
            }

            if (type === "tool-createDocument") {
              const { toolCallId } = part;

              if (part.output && "error" in part.output) {
                return (
                  <div
                    className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-500 dark:bg-red-950/50"
                    key={toolCallId}
                  >
                    Error creating document: {String(part.output.error)}
                  </div>
                );
              }

              return (
                <DocumentPreview
                  isReadonly={isReadonly}
                  key={toolCallId}
                  result={part.output}
                />
              );
            }

            if (type === "tool-updateDocument") {
              const { toolCallId } = part;

              if (part.output && "error" in part.output) {
                return (
                  <div
                    className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-500 dark:bg-red-950/50"
                    key={toolCallId}
                  >
                    Error updating document: {String(part.output.error)}
                  </div>
                );
              }

              return (
                <div className="relative" key={toolCallId}>
                  <DocumentPreview
                    args={{ ...part.output, isUpdate: true }}
                    isReadonly={isReadonly}
                    result={part.output}
                  />
                </div>
              );
            }

            if (type === "tool-requestSuggestions") {
              const { toolCallId, state } = part;

              return (
                <Tool defaultOpen={true} key={toolCallId}>
                  <ToolHeader state={state} type="tool-requestSuggestions" />
                  <ToolContent>
                    {state === "input-available" && (
                      <ToolInput input={part.input} />
                    )}
                    {state === "output-available" && (
                      <ToolOutput
                        errorText={undefined}
                        output={
                          "error" in part.output ? (
                            <div className="rounded border p-2 text-red-500">
                              Error: {String(part.output.error)}
                            </div>
                          ) : (
                            <DocumentToolResult
                              isReadonly={isReadonly}
                              result={part.output}
                              type="request-suggestions"
                            />
                          )
                        }
                      />
                    )}
                  </ToolContent>
                </Tool>
              );
            }

            return null;
          })}

          {/* 아티팩트 블록 표시 (어시스턴트 메시지이고 artifact 메타데이터가 있는 경우) */}
          {message.role === "assistant" && message.metadata?.artifact && (
            <ArtifactBlock
              artifact={{
                id: message.metadata.artifact.id,
                title: message.metadata.artifact.title,
                kind: message.metadata.artifact.kind,
              }}
            />
          )}

          {/* Phase 8 (A2UI): UIFrame 렌더링 */}
          {message.role === "assistant" && message.metadata?.ui_frame && (
            <UIFrameRenderer uiFrame={message.metadata.ui_frame} />
          )}

          {/* Inline Visualization — renderDiagram / renderChart 결과 */}
          {message.role === "assistant" &&
            message.metadata?.inline_visualizations &&
            message.metadata.inline_visualizations.length > 0 && (
              <div className="mt-2 flex flex-col gap-3">
                {message.metadata.inline_visualizations.map((viz) => {
                  if (viz.viz_type === "mermaid") {
                    return (
                      <MermaidDiagram
                        key={viz.id}
                        code={viz.data.mermaidCode}
                        title={viz.data.title}
                        description={viz.data.description}
                      />
                    );
                  }
                  return (
                    <DataChart
                      key={viz.id}
                      type={viz.data.type}
                      data={viz.data.data}
                      title={viz.data.title}
                    />
                  );
                })}
              </div>
            )}

          {!isReadonly && (
            <MessageActions
              chatId={chatId}
              isLoading={isLoading}
              key={`action-${message.id}`}
              message={message}
              setMode={setMode}
              vote={vote}
            />
          )}
        </div>
      </div>
    </div>
  );
};

const MemoizedPreviewMessage = memo(
  PurePreviewMessage,
  (prevProps, nextProps) => {
    if (prevProps.isLoading !== nextProps.isLoading) {
      return false;
    }
    if (prevProps.message.id !== nextProps.message.id) {
      return false;
    }
    if (prevProps.requiresScrollPadding !== nextProps.requiresScrollPadding) {
      return false;
    }
    if (!equal(prevProps.message.parts, nextProps.message.parts)) {
      return false;
    }
    if (!equal(prevProps.message.metadata, nextProps.message.metadata)) {
      return false;
    }
    if (!equal(prevProps.vote, nextProps.vote)) {
      return false;
    }

    return true; // props가 모두 같으면 재렌더링 불필요
  }
);

// Wrap with ErrorBoundary to prevent page crashes
export const PreviewMessage = (props: Parameters<typeof MemoizedPreviewMessage>[0]) => (
  <ErrorBoundary>
    <MemoizedPreviewMessage {...props} />
  </ErrorBoundary>
);

export const ThinkingMessage = () => {
  return (
    <div
      className="group/message fade-in w-full animate-in duration-300"
      data-role="assistant"
      data-testid="message-assistant-loading"
    >
      <div className="flex items-start justify-start gap-3">
        <div className="-mt-1 flex size-8 shrink-0 items-center justify-center rounded-full bg-background ring-1 ring-border">
          <div className="animate-pulse">
            <SparklesIcon size={14} />
          </div>
        </div>

        <div className="flex w-full flex-col gap-2 md:gap-4">
          <div className="flex items-center gap-1 p-0 text-muted-foreground text-sm">
            <span className="animate-pulse">Thinking</span>
            <span className="inline-flex">
              <span className="animate-bounce [animation-delay:0ms]">.</span>
              <span className="animate-bounce [animation-delay:150ms]">.</span>
              <span className="animate-bounce [animation-delay:300ms]">.</span>
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
