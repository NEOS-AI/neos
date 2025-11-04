import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NEOS - Intelligent Search and Analysis",
  description: "AI-powered search and analysis platform with multi-agent workflow",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">
        {children}
      </body>
    </html>
  );
}
