"use client";

// Skeleton loader for sidebar conversations
export function ConversationSkeleton() {
  return (
    <div className="p-3 rounded-xl animate-pulse">
      <div className="flex items-center gap-3">
        <div className="w-4 h-4 bg-gradient-to-br from-gray-200 to-gray-300 dark:from-claude-border dark:to-claude-light rounded animate-shimmer bg-[length:200%_100%]" />
        <div className="flex-1 space-y-2">
          <div className="h-3 bg-gradient-to-r from-gray-200 via-gray-300 to-gray-200 dark:from-claude-border dark:via-claude-light dark:to-claude-border rounded-full w-3/4 animate-shimmer bg-[length:200%_100%]" />
          <div className="h-2 bg-gradient-to-r from-gray-200 via-gray-300 to-gray-200 dark:from-claude-border dark:via-claude-light dark:to-claude-border rounded-full w-1/2 animate-shimmer bg-[length:200%_100%]" />
        </div>
      </div>
    </div>
  );
}

// Skeleton loader for messages
export function MessageSkeleton() {
  return (
    <div className="max-w-3xl mx-auto px-6 py-6 animate-fade-in-up">
      <div className="flex gap-4 items-start">
        <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-gray-200 to-gray-300 dark:from-claude-border dark:to-claude-light shadow-md animate-pulse" />
        <div className="flex-1 space-y-3">
          <div className="h-3 bg-gradient-to-r from-gray-200 via-gray-300 to-gray-200 dark:from-claude-border dark:via-claude-light dark:to-claude-border rounded-full w-1/4 animate-shimmer bg-[length:200%_100%]" />
          <div className="space-y-2">
            <div className="h-3 bg-gradient-to-r from-gray-200 via-gray-300 to-gray-200 dark:from-claude-border dark:via-claude-light dark:to-claude-border rounded-full animate-shimmer bg-[length:200%_100%]" />
            <div className="h-3 bg-gradient-to-r from-gray-200 via-gray-300 to-gray-200 dark:from-claude-border dark:via-claude-light dark:to-claude-border rounded-full w-5/6 animate-shimmer bg-[length:200%_100%]" />
            <div className="h-3 bg-gradient-to-r from-gray-200 via-gray-300 to-gray-200 dark:from-claude-border dark:via-claude-light dark:to-claude-border rounded-full w-4/6 animate-shimmer bg-[length:200%_100%]" />
          </div>
        </div>
      </div>
    </div>
  );
}

// Loading spinner
export function LoadingSpinner({ size = "md" }: { size?: "sm" | "md" | "lg" }) {
  const sizeClasses = {
    sm: "w-5 h-5",
    md: "w-7 h-7",
    lg: "w-10 h-10",
  };

  const borderClasses = {
    sm: "border-2",
    md: "border-3",
    lg: "border-4",
  };

  return (
    <div className="flex items-center justify-center">
      <div
        className={`${sizeClasses[size]} ${borderClasses[size]} border-gray-200 dark:border-claude-border border-t-blue-600 dark:border-t-primary rounded-full animate-spin`}
        style={{
          boxShadow: '0 0 20px rgba(59, 130, 246, 0.5)',
        }}
      />
    </div>
  );
}

// Full page loading
export function PageLoading() {
  return (
    <div className="flex items-center justify-center min-h-screen bg-gradient-to-br from-gray-50 via-white to-gray-100 dark:from-claude-darker dark:via-black dark:to-claude-darker">
      <div className="text-center space-y-6 animate-scale-in">
        <div className="w-20 h-20 rounded-3xl bg-gradient-to-br from-orange-400 via-amber-500 to-amber-600 flex items-center justify-center text-white text-4xl font-bold mx-auto shadow-2xl shadow-orange-500/30 animate-pulse-subtle">
          N
        </div>
        <div className="space-y-3">
          <LoadingSpinner size="lg" />
          <p className="text-gray-600 dark:text-claude-text-secondary text-sm font-medium animate-pulse">
            Loading NEOS...
          </p>
        </div>
      </div>
    </div>
  );
}
