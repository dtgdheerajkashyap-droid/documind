"use client";

import { BrainCircuit, FileText, MessageSquare, Moon, Sun } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useTheme } from "@/components/ThemeProvider";

const NAV = [
  { href: "/", label: "Chat", icon: MessageSquare },
  { href: "/documents", label: "Documents", icon: FileText },
];

export function AppHeader() {
  const pathname = usePathname();
  const { theme, toggleTheme } = useTheme();

  return (
    <header className="border-border bg-surface flex h-14 shrink-0 items-center gap-2 border-b px-3 sm:px-5">
      <Link href="/" className="mr-2 flex items-center gap-2 font-semibold sm:mr-6">
        <span className="bg-accent text-accent-fg flex size-8 items-center justify-center rounded-lg">
          <BrainCircuit className="size-5" aria-hidden />
        </span>
        <span className="hidden text-lg tracking-tight sm:inline">DocuMind</span>
      </Link>

      <nav className="flex items-center gap-1" aria-label="Main">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                active
                  ? "bg-accent-soft text-accent"
                  : "text-muted hover:bg-surface-2 hover:text-text"
              }`}
            >
              <Icon className="size-4" aria-hidden />
              {label}
            </Link>
          );
        })}
      </nav>

      <button
        type="button"
        onClick={toggleTheme}
        className="text-muted hover:bg-surface-2 hover:text-text ml-auto rounded-lg p-2 transition-colors"
        aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
        title="Toggle theme"
      >
        {theme === "dark" ? <Sun className="size-5" /> : <Moon className="size-5" />}
      </button>
    </header>
  );
}
