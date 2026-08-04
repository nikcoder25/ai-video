import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ClipViral — long video in, viral 9:16 clips out",
  description:
    "Paste a YouTube link or drop a video file. ClipViral finds the moments that hook and cuts them into captioned, reframed 9:16 clips.",
};

export const viewport: Viewport = {
  themeColor: "#0a0a0c",
  colorScheme: "dark",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-dvh antialiased">{children}</body>
    </html>
  );
}
