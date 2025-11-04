import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "var(--background)",
        foreground: "var(--foreground)",
        border: "var(--border)",
        primary: {
          DEFAULT: "#CC785C",
          hover: "#B86A4E",
        },
        claude: {
          dark: "#1A1A1A",
          darker: "#0F0F0F",
          light: "#2A2A2A",
          border: "#2A2A2A",
          text: "#E5E5E5",
          "text-secondary": "#9CA3AF",
        },
      },
      fontFamily: {
        sans: [
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        mono: ["Menlo", "Monaco", "Courier New", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
