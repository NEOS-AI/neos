"use client";

import { useEffect, useState } from "react";

// 모듈 레벨 싱글톤 — initialize()는 테마 변경 시에만 재호출
let mermaidInitialized = false;
let mermaidInitializedTheme: "dark" | "neutral" | null = null;

interface MermaidDiagramProps {
  code: string;
  title?: string;
  description?: string;
}

export function MermaidDiagram({ code, title, description }: MermaidDiagramProps) {
  const [svgContent, setSvgContent] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function render() {
      try {
        const mermaid = (await import("mermaid")).default;

        const isDark = document.documentElement.classList.contains("dark");
        const currentTheme: "dark" | "neutral" = isDark ? "dark" : "neutral";

        if (!mermaidInitialized || mermaidInitializedTheme !== currentTheme) {
          mermaid.initialize({
            startOnLoad: false,
            theme: currentTheme,
            securityLevel: "strict",
            fontFamily: "inherit",
          });
          mermaidInitialized = true;
          mermaidInitializedTheme = currentTheme;
        }

        const id = `mermaid-${Math.random().toString(36).slice(2)}`;
        const { svg } = await mermaid.render(id, code);

        if (!cancelled) {
          setSvgContent(svg);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Diagram render error");
        }
      }
    }

    render();
    return () => {
      cancelled = true;
    };
  }, [code]);

  if (error) {
    return (
      <div className="rounded-md border border-destructive/50 bg-destructive/5 p-3 my-2">
        <p className="text-xs text-muted-foreground mb-1">Diagram render failed</p>
        <pre className="text-xs font-mono text-foreground/70 whitespace-pre-wrap overflow-auto max-h-40">
          {code}
        </pre>
      </div>
    );
  }

  return (
    <div className="my-2 rounded-lg border bg-card p-3 shadow-sm overflow-auto">
      {title && (
        <p className="text-sm font-medium text-foreground mb-2">{title}</p>
      )}
      {svgContent ? (
        <div
          // biome-ignore lint/security/noDangerouslySetInnerHtml: mermaid SVG output is sanitized
          dangerouslySetInnerHTML={{ __html: svgContent }}
          className="flex justify-center"
        />
      ) : (
        <div className="h-20 flex items-center justify-center">
          <span className="text-xs text-muted-foreground animate-pulse">
            Rendering diagram...
          </span>
        </div>
      )}
      {description && (
        <p className="text-xs text-muted-foreground mt-2">{description}</p>
      )}
    </div>
  );
}
