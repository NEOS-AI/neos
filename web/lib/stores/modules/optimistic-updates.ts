/**
 * Optimistic Update Utilities
 * Helpers for implementing optimistic UI updates with rollback on error
 */

/**
 * Execute an action with optimistic update and rollback on failure
 *
 * @param optimisticUpdate - Function to update state optimistically
 * @param apiCall - Async API call to execute
 * @param rollback - Function to rollback state on error
 * @param errorCallback - Optional callback to handle errors
 */
export async function withOptimisticUpdate<T>(
  optimisticUpdate: () => void,
  apiCall: () => Promise<T>,
  rollback: (error: unknown) => void,
  errorCallback?: (error: unknown) => void
): Promise<T | null> {
  // Apply optimistic update
  optimisticUpdate();

  try {
    // Execute API call
    const result = await apiCall();
    return result;
  } catch (error) {
    // Rollback on error
    rollback(error);

    // Optional error callback
    if (errorCallback) {
      errorCallback(error);
    }

    return null;
  }
}

/**
 * Create a rollback function for conversation list updates
 */
export function createConversationRollback(
  setState: (state: any) => void,
  previousConversations: any[],
  errorMessage?: string
) {
  return (error: unknown) => {
    console.error("Rolling back conversation update:", error);
    setState({
      conversations: previousConversations,
      error: errorMessage || "Operation failed. Please try again.",
    });
  };
}

/**
 * Create a rollback function for conversation ID updates
 */
export function createConversationIdRollback(
  setState: (state: any) => void,
  previousConversations: any[],
  previousConversationId: string | null,
  errorMessage?: string
) {
  return (error: unknown) => {
    console.error("Rolling back conversation ID update:", error);
    setState({
      conversations: previousConversations,
      currentConversationId: previousConversationId,
      error: errorMessage || "Operation failed. Please try again.",
    });
  };
}
