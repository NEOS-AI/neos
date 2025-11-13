"use client";

import { useState, useEffect } from "react";
import { Settings } from "lucide-react";
import ModeSelector, { Mode } from "./ModeSelector";

interface TopBarProps {
  showModeSelector?: boolean;
  modes?: Mode[];
  selectedMode?: string;
  onModeChange?: (modeId: string) => void;
  showSettings?: boolean;
  onSettingsClick?: () => void;
}

export default function TopBar({
  showModeSelector = false,
  modes = [],
  selectedMode = "",
  onModeChange = () => {},
  showSettings = true,
  onSettingsClick = () => {}
}: TopBarProps) {
  const [isScrolled, setIsScrolled] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      setIsScrolled(window.scrollY > 10);
    };

    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  return (
    <header
      className={`
        sticky top-0 z-40
        transition-all duration-200
        ${isScrolled
          ? "bg-bg-surface/95 backdrop-blur-sm border-b border-line-soft shadow-sm"
          : "bg-transparent"
        }
      `}
      role="banner"
    >
      <div className="max-w-6xl mx-auto px-6 py-4">
        <div className="flex items-center justify-between">
          {/* Left side - could add breadcrumbs or title */}
          <div className="flex-1">
            {/* Empty for now, but reserved for future use */}
          </div>

          {/* Right side - Mode selector & Settings */}
          <div className="flex items-center gap-3">
            {showModeSelector && modes.length > 0 && (
              <ModeSelector
                modes={modes}
                selectedMode={selectedMode}
                onModeChange={onModeChange}
                label="Mode"
              />
            )}

            {showSettings && (
              <button
                onClick={onSettingsClick}
                className="
                  p-2 rounded-xl
                  text-text-secondary hover:text-text-primary hover:bg-action-hover
                  transition-all duration-200
                  focus:outline-none focus:ring-2 focus:ring-brand-accent/50
                "
                title="Settings"
                aria-label="Open settings"
              >
                <Settings className="w-5 h-5" />
              </button>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
