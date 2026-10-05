import type { Metadata } from "next";

import { AppHeader } from "@/components/AppHeader";
import { ThemeProvider, themeInitScript } from "@/components/ThemeProvider";

import "./globals.css";

export const metadata: Metadata = {
  title: "DocuMind",
  description: "Ask questions about your PDFs and get cited, grounded answers.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased" suppressHydrationWarning>
      <head>
        {/* Applies the saved theme before first paint to avoid a flash. */}
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="flex h-full flex-col">
        <ThemeProvider>
          <AppHeader />
          <main className="flex min-h-0 flex-1 flex-col">{children}</main>
        </ThemeProvider>
      </body>
    </html>
  );
}
