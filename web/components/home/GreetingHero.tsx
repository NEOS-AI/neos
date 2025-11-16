"use client";

import { Sparkles } from "lucide-react";

interface GreetingHeroProps {
  greeting?: string;
  subtext?: string;
}

export default function GreetingHero({
  greeting = "Welcome to NEOS",
  subtext
}: GreetingHeroProps) {
  return (
    <div className="flex items-start gap-4">
      <div className="flex-shrink-0 w-12 h-12 rounded-2xl bg-brand-accent/10 flex items-center justify-center">
        <Sparkles className="w-6 h-6 text-brand-accent" />
      </div>
      <div className="flex-1 pt-1">
        <h1 className="text-display-1 text-text-primary font-semibold leading-tight">
          {greeting}
        </h1>
        {subtext && (
          <p className="text-body-m text-text-secondary mt-2">
            {subtext}
          </p>
        )}
      </div>
    </div>
  );
}
