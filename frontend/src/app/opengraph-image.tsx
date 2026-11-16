import { ImageResponse } from "next/og";

export const alt = "College Guesthouse: rooms on campus";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/** The preview shown when the site's link is shared, for example on WhatsApp. */
export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: 72,
          background: "#0e0d0b",
          color: "#ebe4d4",
          fontFamily: "serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", fontSize: 24, letterSpacing: 6, textTransform: "uppercase", color: "#979081", fontFamily: "sans-serif" }}>
          <svg width="44" height="44" viewBox="0 0 32 32" fill="none" style={{ marginRight: 20 }}>
            <path d="M6 28V14a10 10 0 0 1 20 0v14" stroke="#b8935a" strokeWidth="1.5" />
            <path d="M12 28V15.5a4 4 0 0 1 8 0V28" stroke="#b8935a" strokeWidth="1.5" />
            <path d="M3 28h26" stroke="#b8935a" strokeWidth="1.5" />
          </svg>
          Rooms on campus
        </div>
        <div style={{ display: "flex", flexDirection: "column", fontSize: 132, lineHeight: 1 }}>
          <span>College</span>
          <span style={{ color: "#b8935a", fontStyle: "italic" }}>Guesthouse</span>
        </div>
        <div style={{ display: "flex", borderTop: "1px solid #2b2924", paddingTop: 28, fontSize: 28, color: "#979081", fontFamily: "sans-serif" }}>
          Check availability and request a room online.
        </div>
      </div>
    ),
    size,
  );
}
