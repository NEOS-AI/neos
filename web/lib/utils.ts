import type {
  CoreAssistantMessage,
  CoreToolMessage,
  UIMessage,
  UIMessagePart,
} from 'ai';
import { type ClassValue, clsx } from 'clsx';
import { formatISO } from 'date-fns';
import { twMerge } from 'tailwind-merge';
import type { DBMessage, Document } from '@/lib/db/schema';
import { deepAnalysisFromMessageMetadata } from './deep-analysis/metadata';
import { applyHarnessMetadata } from './harness/metadata';
import { ChatSDKError, type ErrorCode } from './errors';
import type { ChatMessage, ChatTools, CustomUIDataTypes } from './types';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const fetcher = async (url: string) => {
  const response = await fetch(url);

  if (!response.ok) {
    const { code, cause } = await response.json();
    throw new ChatSDKError(code as ErrorCode, cause);
  }

  return response.json();
};

export async function fetchWithErrorHandlers(
  input: RequestInfo | URL,
  init?: RequestInit,
) {
  try {
    const response = await fetch(input, init);

    if (!response.ok) {
      const { code, cause } = await response.json();
      throw new ChatSDKError(code as ErrorCode, cause);
    }

    return response;
  } catch (error: unknown) {
    if (typeof navigator !== 'undefined' && !navigator.onLine) {
      throw new ChatSDKError('offline:chat');
    }

    throw error;
  }
}

export function getLocalStorage(key: string) {
  if (typeof window !== 'undefined') {
    return JSON.parse(localStorage.getItem(key) || '[]');
  }
  return [];
}

export function generateUUID(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

type ResponseMessageWithoutId = CoreToolMessage | CoreAssistantMessage;
type ResponseMessage = ResponseMessageWithoutId & { id: string };

export function getMostRecentUserMessage(messages: UIMessage[]) {
  const userMessages = messages.filter((message) => message.role === 'user');
  return userMessages.at(-1);
}

export function getDocumentTimestampByIndex(
  documents: Document[],
  index: number,
) {
  if (!documents) { return new Date(); }
  if (index > documents.length) { return new Date(); }

  return documents[index].createdAt;
}

export function getTrailingMessageId({
  messages,
}: {
  messages: ResponseMessage[];
}): string | null {
  const trailingMessage = messages.at(-1);

  if (!trailingMessage) { return null; }

  return trailingMessage.id;
}

export function sanitizeText(text: string) {
  return text.replace('<has_function_call>', '');
}

export function convertToUIMessages(messages: DBMessage[]): ChatMessage[] {
  return messages.map((message) => ({
    id: message.id,
    role: message.role as 'user' | 'assistant' | 'system',
    parts: message.parts as UIMessagePart<CustomUIDataTypes, ChatTools>[],
    metadata: {
      createdAt: formatISO(message.createdAt),
    },
  }));
}

/**
 * BE `MessageResponse.attachments` (`{type, url, name, size, metadata}`) 를
 * FE file 파트로 되살린다.
 *
 * FE file 파트의 필드명은 `filename` 이다 (`name` 이 아니다) — Task 3 이 정한
 * 정본 모양이고 `components/message.tsx` 가 `attachment.filename` 을 읽는다.
 * `mediaType` 은 `attachment.metadata.mediaType` 에 들어 있다
 * (`extractAttachments`, `lib/message-parts.ts:97`가 내보낼 때 그 자리에 넣는다).
 *
 * 방어: `attachments` 가 없거나 배열이 아니거나 항목에 `url` 이 없으면 그
 * 항목(또는 전체)을 조용히 건너뛴다 — 첨부 하나가 깨졌다고 메시지 렌더가
 * 죽으면 안 된다 (`lib/harness/metadata.ts` 와 같은 이유).
 */
function attachmentsToFileParts(
  attachments: unknown
): UIMessagePart<CustomUIDataTypes, ChatTools>[] {
  if (!Array.isArray(attachments)) {
    return [];
  }

  const fileParts: UIMessagePart<CustomUIDataTypes, ChatTools>[] = [];

  for (const attachment of attachments) {
    if (!attachment || typeof attachment !== 'object') {
      continue;
    }

    const { url, name, metadata } = attachment as {
      url?: unknown;
      name?: unknown;
      metadata?: unknown;
    };

    if (typeof url !== 'string') {
      continue;
    }

    const mediaType =
      metadata && typeof metadata === 'object'
        ? (metadata as Record<string, unknown>).mediaType
        : undefined;

    fileParts.push({
      type: 'file',
      url,
      ...(typeof name === 'string' ? { filename: name } : {}),
      ...(typeof mediaType === 'string' ? { mediaType } : {}),
    } as UIMessagePart<CustomUIDataTypes, ChatTools>);
  }

  return fileParts;
}

/**
 * 백엔드 메시지 메타데이터 → 첨부 안내 문자열 목록 (런타임 검증)
 *
 * 백엔드는 상한(20MB)·PDF 페이지 수·해석 실패로 **모델에 싣지 못한** 첨부의
 * 사유를 `attachment_notices` 로 남긴다. 그것이 화면에 닿지 않으면 사용자는
 * 모델이 왜 그 파일을 못 봤는지 알 수 없다 — 첨부 기능이 고치려던 조용한
 * 실패가 마지막 한 홉에서 되살아난다.
 *
 * `convertBackendMessagesToUI` 의 일반 통과 경로가 이 키를 **무검증으로**
 * 복사하므로, `lib/harness/metadata.ts` 와 같은 이유로 여기서 모양을 확정한다:
 * 배열이 아니면 렌더의 `.map` 이 터지고 그 어시스턴트 메시지 전체가 에러
 * 카드로 대체된다. 문자열이 아닌 항목은 걸러내고, 남는 것이 없으면 undefined
 * 를 돌려 "보여줄 안내 없음" 과 "빈 배열" 을 같게 만든다.
 */
export function attachmentNoticesFromMessageMetadata(
  metadata: unknown
): string[] | undefined {
  if (!metadata || typeof metadata !== 'object') {
    return undefined;
  }

  const raw = (metadata as Record<string, unknown>).attachment_notices;
  if (!Array.isArray(raw)) {
    return undefined;
  }

  const notices = raw.filter(
    (notice): notice is string => typeof notice === 'string'
  );

  return notices.length > 0 ? notices : undefined;
}


export function convertBackendMessagesToUI(
  backendMessages: any[]
): ChatMessage[] {
  return backendMessages.map((msg) => {
    const metadata: any = {
      createdAt: msg.created_at,
      sequenceNumber: msg.sequence_number,
      modelName: msg.model_name,
      totalTokens: msg.total_tokens,
    };

    // 백엔드 metadata에서 artifact 정보 추출 및 변환
    if (msg.metadata && msg.metadata.artifact) {
      metadata.artifact = {
        id: msg.metadata.artifact.id,
        title: msg.metadata.artifact.title,
        kind: msg.metadata.artifact.kind,
      };
    }

    // 나머지 metadata 필드도 포함
    if (msg.metadata) {
      Object.keys(msg.metadata).forEach((key) => {
        if (key !== 'artifact' && !metadata[key]) {
          metadata[key] = msg.metadata[key];
        }
      });
    }

    // 백엔드 키(`deep_analysis_run_id`)를 프론트 모양(`deep_analysis`)으로 옮긴다.
    // 이 브리지가 없으면 새로고침 후 진행 카드가 통째로 사라진다 — 강등 경고만이
    // 아니라 카드 자체가. 자세한 근거는 `lib/deep-analysis/metadata.ts` 주석 참조.
    const deepAnalysis = deepAnalysisFromMessageMetadata(msg.metadata);
    if (deepAnalysis) {
      metadata.deep_analysis = deepAnalysis;
    }

    // `harness` 는 백엔드가 같은 이름으로 쓰므로 위 통과 경로가 이미 복사해
    // 뒀다 -- **검증하지 않은 채로.** 스키마에 맞으면 검증된 값으로 바꾸고,
    // 아니면 지운다. 지우지 않으면 통과 경로가 남긴 원본이 그대로 컴포넌트에
    // 도달하고, 잘못된 모양 다섯 중 하나는 렌더를 던져 그 메시지 전체가
    // 에러 카드로 대체된다(`lib/harness/metadata.ts` 주석).
    applyHarnessMetadata(metadata, msg.metadata);

    // `attachment_notices` 도 백엔드가 같은 이름으로 쓰므로 위 통과 경로가 이미
    // 복사해 뒀다 -- 역시 무검증으로. 검증본으로 갈아끼우거나, 모양이 아니면
    // 지운다.
    const attachmentNotices = attachmentNoticesFromMessageMetadata(msg.metadata);
    if (attachmentNotices) {
      metadata.attachment_notices = attachmentNotices;
    } else {
      delete metadata.attachment_notices;
    }

    return {
      id: msg.message_id,
      role: msg.role as 'user' | 'assistant' | 'system',
      parts: [
        {
          type: 'text' as const,
          text: msg.content,
        },
        ...attachmentsToFileParts(msg.attachments),
      ] as UIMessagePart<CustomUIDataTypes, ChatTools>[],
      metadata,
    };
  });
}

export function getTextFromMessage(message: ChatMessage | UIMessage): string {
  return message.parts
    .filter((part) => part.type === 'text')
    .map((part) => (part as { type: 'text'; text: string}).text)
    .join('');
}
