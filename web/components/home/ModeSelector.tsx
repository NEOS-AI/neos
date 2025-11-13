"use client";

import { useState, useRef, useEffect } from "react";
import { ChevronDown, Check } from "lucide-react";

export interface Mode {
  id: string;
  label: string;
  description?: string;
}

interface ModeSelectorProps {
  modes: Mode[];
  selectedMode: string;
  onModeChange: (modeId: string) => void;
  label?: string;
}

export default function ModeSelector({
  modes,
  selectedMode,
  onModeChange,
  label = "Mode"
}: ModeSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const selectedModeData = modes.find(m => m.id === selectedMode) || modes[0];

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [isOpen]);

  const handleSelect = (modeId: string) => {
    onModeChange(modeId);
    setIsOpen(false);
  };

  return (
    <div className="relative" ref={dropdownRef}>
      {/* Trigger button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="
          inline-flex items-center gap-2 px-4 py-2
          bg-chip-bg border border-chip-line rounded-xl
          text-text-primary text-sm font-medium
          transition-all duration-200
          hover:border-brand-accent/50 hover:bg-action-hover
          focus:outline-none focus:ring-2 focus:ring-brand-accent/50
        "
        aria-label={`Select ${label}`}
        aria-expanded={isOpen}
        aria-haspopup="listbox"
      >
        <span className="text-text-muted text-xs uppercase tracking-wider">
          {label}
        </span>
        <span>{selectedModeData.label}</span>
        <ChevronDown
          className={`w-4 h-4 text-text-secondary transition-transform duration-200 ${
            isOpen ? "rotate-180" : ""
          }`}
        />
      </button>

      {/* Dropdown menu */}
      {isOpen && (
        <div
          className="
            absolute top-full right-0 mt-2 w-64
            bg-bg-surface border border-line-soft rounded-xl
            shadow-soft-lg
            overflow-hidden
            z-50
          "
          role="listbox"
        >
          {modes.map((mode) => {
            const isSelected = mode.id === selectedMode;
            return (
              <button
                key={mode.id}
                onClick={() => handleSelect(mode.id)}
                className="
                  w-full flex items-start gap-3 px-4 py-3
                  text-left
                  transition-colors duration-150
                  hover:bg-action-hover
                "
                role="option"
                aria-selected={isSelected}
              >
                {/* Checkmark */}
                <div className="flex-shrink-0 w-5 h-5 mt-0.5">
                  {isSelected && (
                    <Check className="w-5 h-5 text-brand-accent" />
                  )}
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className={`text-sm font-medium ${
                    isSelected ? "text-brand-accent" : "text-text-primary"
                  }`}>
                    {mode.label}
                  </div>
                  {mode.description && (
                    <div className="text-xs text-text-secondary mt-1 leading-relaxed">
                      {mode.description}
                    </div>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
