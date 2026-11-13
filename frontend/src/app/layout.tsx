import type { Metadata, Viewport } from "next";
import { Suspense } from "react";

import { Header } from "@/components/header";
import { Providers } from "@/components/providers";

import "./globals.css";

export const metadata: Metadata = {
  title: "College Guesthouse",
  description: "Check availability and book a room at the college guesthouse.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col font-sans">
        <Providers>
          <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:bg-white focus:p-3">
            Skip to content
          </a>
          <Header />
          <main id="main" className="mx-auto w-full max-w-5xl flex-1 px-4 py-8">
            <Suspense fallback={<p className="py-8 text-center text-slate-500">Loading…</p>}>{children}</Suspense>
          </main>
        </Providers>
      </body>
    </html>
  );
}
