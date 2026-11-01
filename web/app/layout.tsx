import type { Metadata } from "next";
import Link from "next/link";
import AppVersion from "./AppVersion";
import "./globals.css";

export const metadata: Metadata = {
  title: "Job Search Lab",
  description: "Personal AI job-search dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="topbar">
          <span className="brand">Job Search Lab</span>
          <nav>
            <Link href="/">Dashboard</Link>
            <Link href="/insights">Insights</Link>
            <Link href="/cv">CV &amp; Profile</Link>
            <Link href="/queries">Queries</Link>
            <Link href="/prompts">Prompts</Link>
          </nav>
          <AppVersion />
        </header>
        <main className="container">{children}</main>
      </body>
    </html>
  );
}
