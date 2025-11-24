"use client";

import { useChatStore } from "@/lib/stores/chat-store";
import { Settings, Info } from "lucide-react";
import { useState } from "react";
import { AI_SETTINGS } from "@/lib/constants";

export default function SimilaritySettings() {
  const { settings, updateSettings } = useChatStore();
  const [isOpen, setIsOpen] = useState(false);

  // Only show for similarity mode
  if (settings.mode !== "similarity") {
    return null;
  }

  return (
    <div className="relative">
      {/* Settings Toggle Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-3 py-2 text-xs font-medium text-claude-text-secondary hover:text-claude-text-primary bg-claude-light hover:bg-claude-border rounded-lg transition-all"
        title="Similarity Search Settings"
      >
        <Settings className="w-4 h-4" />
        <span>Settings</span>
      </button>

      {/* Settings Panel */}
      {isOpen && (
        <div className="absolute top-12 right-0 z-50 w-80 p-4 bg-claude-dark border border-claude-border rounded-lg shadow-lg">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-claude-text-primary">
              Similarity Search Settings
            </h3>
            <button
              onClick={() => setIsOpen(false)}
              className="text-claude-text-secondary hover:text-claude-text-primary"
            >
              ×
            </button>
          </div>

          <div className="space-y-4">
            {/* Top K Setting */}
            <div>
              <label className="flex items-center gap-2 text-xs font-medium text-claude-text-secondary mb-2">
                Number of Similar Messages (top_k)
                <div className="group relative">
                  <Info className="w-3 h-3" />
                  <div className="invisible group-hover:visible absolute left-0 top-5 w-48 p-2 bg-gray-900 text-white text-xs rounded shadow-lg z-10">
                    Number of similar messages to retrieve for context
                  </div>
                </div>
              </label>
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min="1"
                  max="10"
                  value={settings.similarity_top_k}
                  onChange={(e) =>
                    updateSettings({ similarity_top_k: parseInt(e.target.value) })
                  }
                  className="flex-1 h-2 bg-claude-light rounded-lg appearance-none cursor-pointer accent-primary"
                />
                <span className="text-sm font-semibold text-primary w-8 text-center">
                  {settings.similarity_top_k}
                </span>
              </div>
            </div>

            {/* Similarity Threshold Setting */}
            <div>
              <label className="flex items-center gap-2 text-xs font-medium text-claude-text-secondary mb-2">
                Similarity Threshold
                <div className="group relative">
                  <Info className="w-3 h-3" />
                  <div className="invisible group-hover:visible absolute left-0 top-5 w-48 p-2 bg-gray-900 text-white text-xs rounded shadow-lg z-10">
                    Minimum similarity score (0.0 to 1.0). Higher values mean stricter matching.
                  </div>
                </div>
              </label>
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={(settings.similarity_threshold ?? AI_SETTINGS.SIMILARITY_THRESHOLD_LOW) * 100}
                  onChange={(e) =>
                    updateSettings({
                      similarity_threshold: parseInt(e.target.value) / 100,
                    })
                  }
                  className="flex-1 h-2 bg-claude-light rounded-lg appearance-none cursor-pointer accent-primary"
                />
                <span className="text-sm font-semibold text-primary w-12 text-center">
                  {(settings.similarity_threshold ?? AI_SETTINGS.SIMILARITY_THRESHOLD_LOW).toFixed(2)}
                </span>
              </div>
              <div className="flex justify-between text-xs text-claude-text-tertiary mt-1">
                <span>Broad (0.5)</span>
                <span>Moderate (0.7)</span>
                <span>Strict (0.9)</span>
              </div>
            </div>

            {/* Cross Conversation Setting */}
            <div>
              <label className="flex items-center gap-2 text-xs font-medium text-claude-text-secondary mb-2">
                Search Across Conversations
                <div className="group relative">
                  <Info className="w-3 h-3" />
                  <div className="invisible group-hover:visible absolute left-0 top-5 w-48 p-2 bg-gray-900 text-white text-xs rounded shadow-lg z-10">
                    Search for similar messages in all your conversations, not just the current one
                  </div>
                </div>
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="cross-conversation"
                  checked={settings.similarity_cross_conversation}
                  onChange={(e) =>
                    updateSettings({
                      similarity_cross_conversation: e.target.checked,
                    })
                  }
                  className="w-4 h-4 text-primary bg-claude-light border-claude-border rounded focus:ring-primary focus:ring-2"
                />
                <label
                  htmlFor="cross-conversation"
                  className="text-sm text-claude-text-primary cursor-pointer"
                >
                  Enable cross-conversation search
                </label>
              </div>
            </div>

            {/* Auto Embedding Setting */}
            <div>
              <label className="flex items-center gap-2 text-xs font-medium text-claude-text-secondary mb-2">
                Auto-Generate Embeddings
                <div className="group relative">
                  <Info className="w-3 h-3" />
                  <div className="invisible group-hover:visible absolute left-0 top-5 w-48 p-2 bg-gray-900 text-white text-xs rounded shadow-lg z-10">
                    Automatically generate embeddings for new messages to improve future searches
                  </div>
                </div>
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="auto-embedding"
                  checked={settings.enable_auto_embedding}
                  onChange={(e) =>
                    updateSettings({ enable_auto_embedding: e.target.checked })
                  }
                  className="w-4 h-4 text-primary bg-claude-light border-claude-border rounded focus:ring-primary focus:ring-2"
                />
                <label
                  htmlFor="auto-embedding"
                  className="text-sm text-claude-text-primary cursor-pointer"
                >
                  Enable automatic embedding generation
                </label>
              </div>
            </div>

            {/* Presets */}
            <div className="pt-3 border-t border-claude-border">
              <label className="text-xs font-medium text-claude-text-secondary mb-2 block">
                Quick Presets
              </label>
              <div className="grid grid-cols-3 gap-2">
                <button
                  onClick={() =>
                    updateSettings({
                      similarity_top_k: 3,
                      similarity_threshold: AI_SETTINGS.SIMILARITY_THRESHOLD_LOW,
                      similarity_cross_conversation: false,
                    })
                  }
                  className="px-2 py-1.5 text-xs bg-claude-light hover:bg-claude-border rounded transition-colors"
                >
                  Standard
                </button>
                <button
                  onClick={() =>
                    updateSettings({
                      similarity_top_k: 5,
                      similarity_threshold: AI_SETTINGS.SIMILARITY_THRESHOLD_MEDIUM,
                      similarity_cross_conversation: true,
                    })
                  }
                  className="px-2 py-1.5 text-xs bg-claude-light hover:bg-claude-border rounded transition-colors"
                >
                  Cross-Conv
                </button>
                <button
                  onClick={() =>
                    updateSettings({
                      similarity_top_k: 3,
                      similarity_threshold: AI_SETTINGS.SIMILARITY_THRESHOLD_HIGH,
                      similarity_cross_conversation: false,
                    })
                  }
                  className="px-2 py-1.5 text-xs bg-claude-light hover:bg-claude-border rounded transition-colors"
                >
                  High Conf
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
