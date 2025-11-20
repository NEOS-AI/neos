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
        className="p-2.5 rounded-xl bg-gradient-to-br from-white/50 to-gray-100/50 dark:from-claude-light/50 dark:to-claude-dark/50 hover:from-white hover:to-gray-100 dark:hover:from-claude-light dark:hover:to-claude-dark border border-gray-200/50 dark:border-claude-border transition-all duration-300 hover:scale-110 hover:shadow-md"
        title="Chat Settings"
        aria-label="Open chat settings"
      >
        <Settings className="w-5 h-5 text-claude-text-secondary hover:text-brand-accent transition-colors" />
      </button>

      {/* Settings Modal */}
      {isOpen && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 animate-fade-in" onClick={() => setIsOpen(false)}>
          <div className="bg-gradient-to-br from-white to-gray-50 dark:from-claude-dark dark:to-black border-2 border-gray-200 dark:border-claude-border rounded-3xl shadow-2xl w-full max-w-md mx-4 max-h-[85vh] overflow-hidden animate-scale-in" onClick={(e) => e.stopPropagation()}>
            {/* Header */}
            <div className="flex items-center justify-between p-5 border-b-2 border-gray-200 dark:border-claude-border bg-gradient-to-r from-orange-400/10 to-amber-600/10">
              <div className="flex items-center gap-3">
                <Settings className="w-6 h-6 text-brand-accent" />
                <h2 className="text-xl font-bold bg-gradient-to-r from-gray-900 to-gray-700 dark:from-gray-100 dark:to-gray-300 bg-clip-text text-transparent">
                  Chat Settings
                </h2>
              </div>
              <button
                onClick={() => setIsOpen(false)}
                className="p-2 rounded-xl hover:bg-red-100 dark:hover:bg-red-900/30 transition-all duration-300 hover:scale-110 group"
                aria-label="Close settings"
              >
                <X className="w-5 h-5 text-gray-600 dark:text-gray-400 group-hover:text-red-600 dark:group-hover:text-red-400" />
              </button>
            </div>

            {/* Content */}
            <div className="p-5 space-y-6 overflow-y-auto max-h-[calc(85vh-180px)]">
              {/* General Settings */}
              <div className="space-y-4 p-4 bg-gradient-to-br from-gray-50 to-white dark:from-gray-900/50 dark:to-black/50 rounded-2xl border border-gray-200 dark:border-claude-border">
                <h3 className="text-base font-bold text-gray-900 dark:text-claude-text flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-gradient-to-r from-orange-400 to-amber-600"></span>
                  General
                </h3>

                <div className="space-y-2">
                  <label className="text-xs font-semibold text-gray-700 dark:text-claude-text-secondary">
                    Model
                  </label>
                  <select
                    value={settings.model_name}
                    onChange={(e) =>
                      updateSettings({ model_name: e.target.value })
                    }
                    className="w-full px-4 py-2.5 bg-white dark:bg-claude-light border-2 border-gray-300 dark:border-claude-border rounded-xl text-sm font-medium text-gray-900 dark:text-claude-text focus:outline-none focus:ring-2 focus:ring-brand-accent focus:border-brand-accent transition-all duration-300 hover:border-brand-accent/50"
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

                <div className="flex items-center justify-between p-3 bg-gradient-to-r from-gray-100 to-gray-50 dark:from-gray-800 dark:to-gray-900 rounded-xl">
                  <span className="text-sm font-semibold text-gray-900 dark:text-claude-text-secondary">
                    Streaming
                  </span>
                  <button
                    onClick={() => updateSettings({ stream: !settings.stream })}
                    className={`
                      relative inline-flex h-7 w-12 items-center rounded-full
                      transition-all duration-300 shadow-md hover:scale-110
                      ${settings.stream ? "bg-gradient-to-r from-blue-500 to-purple-600" : "bg-gray-300 dark:bg-claude-border"}
                    `}
                    aria-label={`Toggle streaming ${settings.stream ? 'off' : 'on'}`}
                  >
                    <span
                      className={`
                        inline-block h-5 w-5 transform rounded-full bg-white shadow-lg
                        transition-transform duration-300
                        ${settings.stream ? "translate-x-6" : "translate-x-1"}
                      `}
                    />
                  </button>
                </div>
              </div>

              {/* RAG Settings */}
              {settings.mode === "rag" && (
                <div className="space-y-4 p-4 bg-gradient-to-br from-gray-50 to-white dark:from-gray-900/50 dark:to-black/50 rounded-2xl border border-gray-200 dark:border-claude-border animate-fade-in">
                  <h3 className="text-base font-bold text-gray-900 dark:text-claude-text flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-gradient-to-r from-blue-400 to-purple-600"></span>
                    RAG Settings
                  </h3>

                  <div className="flex items-center justify-between p-3 bg-gradient-to-r from-gray-100 to-gray-50 dark:from-gray-800 dark:to-gray-900 rounded-xl">
                    <span className="text-sm font-semibold text-gray-900 dark:text-claude-text-secondary">
                      Enable RAG
                    </span>
                    <button
                      onClick={() =>
                        updateSettings({ rag_enabled: !settings.rag_enabled })
                      }
                      className={`
                        relative inline-flex h-7 w-12 items-center rounded-full
                        transition-all duration-300 shadow-md hover:scale-110
                        ${settings.rag_enabled ? "bg-gradient-to-r from-blue-500 to-purple-600" : "bg-gray-300 dark:bg-claude-border"}
                      `}
                      aria-label={`Toggle RAG ${settings.rag_enabled ? 'off' : 'on'}`}
                    >
                      <span
                        className={`
                          inline-block h-5 w-5 transform rounded-full bg-white shadow-lg
                          transition-transform duration-300
                          ${settings.rag_enabled ? "translate-x-6" : "translate-x-1"}
                        `}
                      />
                    </button>
                  </div>

                  <div className="space-y-2">
                    <label className="text-xs font-semibold text-gray-700 dark:text-claude-text-secondary flex items-center justify-between">
                      <span>Retrieved Messages</span>
                      <span className="text-brand-accent">{settings.rag_top_k}</span>
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
                    <div className="flex justify-between text-xs text-claude-text-secondary">
                      <span>1</span>
                      <span>10</span>
                    </div>
                  </div>

                  <div className="flex items-center justify-between p-3 bg-gradient-to-r from-gray-100 to-gray-50 dark:from-gray-800 dark:to-gray-900 rounded-xl">
                    <span className="text-sm font-semibold text-gray-900 dark:text-claude-text-secondary">
                      Cross-Conversation Search
                    </span>
                    <button
                      onClick={() =>
                        updateSettings({
                          rag_cross_conversation: !settings.rag_cross_conversation,
                        })
                      }
                      className={`
                        relative inline-flex h-7 w-12 items-center rounded-full
                        transition-all duration-300 shadow-md hover:scale-110
                        ${
                          settings.rag_cross_conversation
                            ? "bg-gradient-to-r from-blue-500 to-purple-600"
                            : "bg-gray-300 dark:bg-claude-border"
                        }
                      `}
                      aria-label={`Toggle cross-conversation search ${settings.rag_cross_conversation ? 'off' : 'on'}`}
                    >
                      <span
                        className={`
                          inline-block h-5 w-5 transform rounded-full bg-white shadow-lg
                          transition-transform duration-300
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
                <div className="space-y-4 p-4 bg-gradient-to-br from-gray-50 to-white dark:from-gray-900/50 dark:to-black/50 rounded-2xl border border-gray-200 dark:border-claude-border animate-fade-in">
                  <h3 className="text-base font-bold text-gray-900 dark:text-claude-text flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-gradient-to-r from-purple-400 to-pink-600"></span>
                    Similarity Settings
                  </h3>

                  <div className="space-y-2">
                    <label className="text-xs font-semibold text-gray-700 dark:text-claude-text-secondary flex items-center justify-between">
                      <span>Retrieved Messages</span>
                      <span className="text-brand-accent">{settings.similarity_top_k}</span>
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
                    <div className="flex justify-between text-xs text-claude-text-secondary">
                      <span>1</span>
                      <span>10</span>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <label className="text-xs font-semibold text-gray-700 dark:text-claude-text-secondary flex items-center justify-between">
                      <span>Similarity Threshold</span>
                      <span className="text-brand-accent">{settings.similarity_threshold?.toFixed(2)}</span>
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

                  <div className="flex items-center justify-between p-3 bg-gradient-to-r from-gray-100 to-gray-50 dark:from-gray-800 dark:to-gray-900 rounded-xl">
                    <span className="text-sm font-semibold text-gray-900 dark:text-claude-text-secondary">
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
                        relative inline-flex h-7 w-12 items-center rounded-full
                        transition-all duration-300 shadow-md hover:scale-110
                        ${
                          settings.similarity_cross_conversation
                            ? "bg-gradient-to-r from-blue-500 to-purple-600"
                            : "bg-gray-300 dark:bg-claude-border"
                        }
                      `}
                      aria-label={`Toggle cross-conversation search ${settings.similarity_cross_conversation ? 'off' : 'on'}`}
                    >
                      <span
                        className={`
                          inline-block h-5 w-5 transform rounded-full bg-white shadow-lg
                          transition-transform duration-300
                          ${
                            settings.similarity_cross_conversation
                              ? "translate-x-6"
                              : "translate-x-1"
                          }
                        `}
                      />
                    </button>
                  </div>

                  <div className="flex items-center justify-between p-3 bg-gradient-to-r from-gray-100 to-gray-50 dark:from-gray-800 dark:to-gray-900 rounded-xl">
                    <span className="text-sm font-semibold text-gray-900 dark:text-claude-text-secondary">
                      Auto-Generate Embeddings
                    </span>
                    <button
                      onClick={() =>
                        updateSettings({
                          enable_auto_embedding: !settings.enable_auto_embedding,
                        })
                      }
                      className={`
                        relative inline-flex h-7 w-12 items-center rounded-full
                        transition-all duration-300 shadow-md hover:scale-110
                        ${
                          settings.enable_auto_embedding
                            ? "bg-gradient-to-r from-blue-500 to-purple-600"
                            : "bg-gray-300 dark:bg-claude-border"
                        }
                      `}
                      aria-label={`Toggle auto-generate embeddings ${settings.enable_auto_embedding ? 'off' : 'on'}`}
                    >
                      <span
                        className={`
                          inline-block h-5 w-5 transform rounded-full bg-white shadow-lg
                          transition-transform duration-300
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
            <div className="flex justify-end gap-3 p-5 border-t-2 border-gray-200 dark:border-claude-border bg-gradient-to-r from-gray-50 to-white dark:from-gray-900/50 dark:to-black/50">
              <button
                onClick={() => setIsOpen(false)}
                className="px-6 py-3 bg-gradient-to-br from-blue-600 via-blue-500 to-purple-600 hover:from-blue-700 hover:via-blue-600 hover:to-purple-700 text-white rounded-xl text-sm font-bold transition-all duration-300 hover:scale-105 hover:shadow-xl hover:shadow-blue-500/50 active:scale-95"
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
