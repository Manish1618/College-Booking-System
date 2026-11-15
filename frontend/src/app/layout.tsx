import type { Metadata, Viewport } from "next";
import { Cormorant_Garamond, Manrope } from "next/font/google";
import { Suspense, type ReactNode } from "react";

import { Header } from "@/components/header";
import { Providers } from "@/components/providers";

import "./globals.css";

export const metadata: Metadata = {
  title: "College Guesthouse",
  description: "Check availability and book a room at the college guesthouse.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#0a0907" };

const display = Cormorant_Garamond({ subsets: ["latin"], weight: ["500", "600"], variable: "--font-cormorant", display: "swap" });
const sans = Manrope({ subsets: ["latin"], variable: "--font-manrope", display: "swap" });

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`dark h-full antialiased ${display.variable} ${sans.variable}`}>
      <body className="flex min-h-full flex-col font-sans">
        <Providers>
          <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:rounded-md focus:bg-card focus:p-3">
            Skip to content
          </a>
          <Suspense fallback={<div className="h-[61px] border-b border-gold/15" />}>
            <Header />
          </Suspense>
          <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-10">
            <Suspense fallback={<p className="py-8 text-center text-slate-500">Loading…</p>}>{children}</Suspense>
          </main>
        </Providers>
      </body>
    </html>
  );
}
