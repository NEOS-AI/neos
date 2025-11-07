"use client";

import { useChatStore } from "@/lib/stores/chat-store";
import { Settings, X } from "lucide-react";
import { useState } from "react";

export default function SettingsPanel() {
  const { settings, updateSettings } = useChatStore();
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      {/* Settings Button */}
      <button
        onClick={() => setIsOpen(true)}
        className="p-2 rounded-lg hover:bg-claude-light transition-colors"
        title="Chat Settings"
      >
        <Settings className="w-5 h-5 text-claude-text-secondary" />
      </button>

      {/* Settings Modal */}
      {isOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-claude-dark border border-claude-border rounded-xl shadow-2xl w-full max-w-md mx-4 max-h-[80vh] overflow-auto">
            {/* Header */}
            <div className="flex items-center justify-between p-4 border-b border-claude-border">
              <h2 className="text-lg font-semibold text-claude-text">
                Chat Settings
              </h2>
              <button
                onClick={() => setIsOpen(false)}
                className="p-1 rounded-lg hover:bg-claude-light transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Content */}
            <div className="p-4 space-y-6">
              {/* General Settings */}
              <div className="space-y-3">
                <h3 className="text-sm font-medium text-claude-text">
                  General
                </h3>

                <div className="space-y-2">
                  <label className="text-xs text-claude-text-secondary">
                    Model
                  </label>
                  <select
                    value={settings.model_name}
                    onChange={(e) =>
                      updateSettings({ model_name: e.target.value })
                    }
                    className="w-full px-3 py-2 bg-claude-light border border-claude-border rounded-lg text-sm text-claude-text focus:outline-none focus:ring-2 focus:ring-primary"
                  >
                    <option value="claude-sonnet-4-5-20250929">
                      Claude 4.5 Sonnet
                    </option>
                    <option value="claude-opus-4-1-20250805">
                      Claude 4.1 Opus
                    </option>
                    <option value="claude-haiku-4-5-20251001">
                      Claude 4.5 Haiku
                    </option>
                  </select>
                </div>

                <div className="space-y-2">
                  <label className="text-xs text-claude-text-secondary flex items-center justify-between">
                    <span>Temperature: {settings.temperature.toFixed(1)}</span>
                  </label>
                  <input
                    type="range"
                    min="0"
                    max="2"
                    step="0.1"
                    value={settings.temperature}
                    onChange={(e) =>
                      updateSettings({ temperature: parseFloat(e.target.value) })
                    }
                    className="w-full"
                  />
                  <div className="flex justify-between text-xs text-claude-text-secondary">
                    <span>Precise</span>
                    <span>Creative</span>
                  </div>
                </div>

                <div className="flex items-center justify-between">
                  <span className="text-xs text-claude-text-secondary">
                    Streaming
                  </span>
                  <button
                    onClick={() => updateSettings({ stream: !settings.stream })}
                    className={`
                      relative inline-flex h-6 w-11 items-center rounded-full
                      transition-colors
                      ${settings.stream ? "bg-primary" : "bg-claude-border"}
                    `}
                  >
                    <span
                      className={`
                        inline-block h-4 w-4 transform rounded-full bg-white
                        transition-transform
                        ${settings.stream ? "translate-x-6" : "translate-x-1"}
                      `}
                    />
                  </button>
                </div>
              </div>

              {/* RAG Settings */}
              {settings.mode === "rag" && (
                <div className="space-y-3">
                  <h3 className="text-sm font-medium text-claude-text">
                    RAG Settings
                  </h3>

                  <div className="flex items-center justify-between">
                    <span className="text-xs text-claude-text-secondary">
                      Enable RAG
                    </span>
                    <button
                      onClick={() =>
                        updateSettings({ rag_enabled: !settings.rag_enabled })
                      }
                      className={`
                        relative inline-flex h-6 w-11 items-center rounded-full
                        transition-colors
                        ${settings.rag_enabled ? "bg-primary" : "bg-claude-border"}
                      `}
                    >
                      <span
                        className={`
                          inline-block h-4 w-4 transform rounded-full bg-white
                          transition-transform
                          ${settings.rag_enabled ? "translate-x-6" : "translate-x-1"}
                        `}
                      />
                    </button>
                  </div>

                  <div className="space-y-2">
                    <label className="text-xs text-claude-text-secondary">
                      Retrieved Messages: {settings.rag_top_k}
                    </label>
                    <input
                      type="range"
                      min="1"
                      max="10"
                      step="1"
                      value={settings.rag_top_k}
                      onChange={(e) =>
                        updateSettings({ rag_top_k: parseInt(e.target.value) })
                      }
                      className="w-full"
                    />
                  </div>

                  <div className="flex items-center justify-between">
                    <span className="text-xs text-claude-text-secondary">
                      Cross-Conversation Search
                    </span>
                    <button
                      onClick={() =>
                        updateSettings({
                          rag_cross_conversation: !settings.rag_cross_conversation,
                        })
                      }
                      className={`
                        relative inline-flex h-6 w-11 items-center rounded-full
                        transition-colors
                        ${
                          settings.rag_cross_conversation
                            ? "bg-primary"
                            : "bg-claude-border"
                        }
                      `}
                    >
                      <span
                        className={`
                          inline-block h-4 w-4 transform rounded-full bg-white
                          transition-transform
                          ${
                            settings.rag_cross_conversation
                              ? "translate-x-6"
                              : "translate-x-1"
                          }
                        `}
                      />
                    </button>
                  </div>
                </div>
              )}

              {/* Similarity Settings */}
              {settings.mode === "similarity" && (
                <div className="space-y-3">
                  <h3 className="text-sm font-medium text-claude-text">
                    Similarity Settings
                  </h3>

                  <div className="space-y-2">
                    <label className="text-xs text-claude-text-secondary">
                      Retrieved Messages: {settings.similarity_top_k}
                    </label>
                    <input
                      type="range"
                      min="1"
                      max="10"
                      step="1"
                      value={settings.similarity_top_k}
                      onChange={(e) =>
                        updateSettings({
                          similarity_top_k: parseInt(e.target.value),
                        })
                      }
                      className="w-full"
                    />
                  </div>

                  <div className="space-y-2">
                    <label className="text-xs text-claude-text-secondary">
                      Similarity Threshold:{" "}
                      {settings.similarity_threshold?.toFixed(2)}
                    </label>
                    <input
                      type="range"
                      min="0"
                      max="1"
                      step="0.05"
                      value={settings.similarity_threshold}
                      onChange={(e) =>
                        updateSettings({
                          similarity_threshold: parseFloat(e.target.value),
                        })
                      }
                      className="w-full"
                    />
                    <div className="flex justify-between text-xs text-claude-text-secondary">
                      <span>Relaxed</span>
                      <span>Strict</span>
                    </div>
                  </div>

                  <div className="flex items-center justify-between">
                    <span className="text-xs text-claude-text-secondary">
                      Cross-Conversation Search
                    </span>
                    <button
                      onClick={() =>
                        updateSettings({
                          similarity_cross_conversation:
                            !settings.similarity_cross_conversation,
                        })
                      }
                      className={`
                        relative inline-flex h-6 w-11 items-center rounded-full
                        transition-colors
                        ${
                          settings.similarity_cross_conversation
                            ? "bg-primary"
                            : "bg-claude-border"
                        }
                      `}
                    >
                      <span
                        className={`
                          inline-block h-4 w-4 transform rounded-full bg-white
                          transition-transform
                          ${
                            settings.similarity_cross_conversation
                              ? "translate-x-6"
                              : "translate-x-1"
                          }
                        `}
                      />
                    </button>
                  </div>

                  <div className="flex items-center justify-between">
                    <span className="text-xs text-claude-text-secondary">
                      Auto-Generate Embeddings
                    </span>
                    <button
                      onClick={() =>
                        updateSettings({
                          enable_auto_embedding: !settings.enable_auto_embedding,
                        })
                      }
                      className={`
                        relative inline-flex h-6 w-11 items-center rounded-full
                        transition-colors
                        ${
                          settings.enable_auto_embedding
                            ? "bg-primary"
                            : "bg-claude-border"
                        }
                      `}
                    >
                      <span
                        className={`
                          inline-block h-4 w-4 transform rounded-full bg-white
                          transition-transform
                          ${
                            settings.enable_auto_embedding
                              ? "translate-x-6"
                              : "translate-x-1"
                          }
                        `}
                      />
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="flex justify-end p-4 border-t border-claude-border">
              <button
                onClick={() => setIsOpen(false)}
                className="px-4 py-2 bg-primary hover:bg-primary-hover text-white rounded-lg text-sm font-medium transition-colors"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
