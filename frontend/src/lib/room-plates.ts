import type { DishTier } from "@/components/ui/sushi-conveyor-menu";
import type { RoomType } from "@/lib/types";

/**
 * Price tier 1 to 5 for each room type, spread over the distinct nightly prices so the cheapest
 * room is tier 1 and the dearest tier 5. Types without a price sit in tier 1.
 */
export function priceTiers(types: RoomType[]): Map<string, DishTier> {
  const prices = [...new Set(types.map((t) => Number(t.price_per_night)).filter((p) => Number.isFinite(p) && p > 0))].sort(
    (a, b) => a - b,
  );
  const tierOf = (price: number) => {
    const index = prices.indexOf(price);
    if (index < 0) return 1;
    if (prices.length === 1) return 3;
    return (1 + Math.round((index * 4) / (prices.length - 1))) as DishTier;
  };
  return new Map(types.map((t) => [t.id, tierOf(Number(t.price_per_night)) as DishTier]));
}

/**
 * A top-down drawing of a made bed on a black-and-gold plate, used on the room carousel until a
 * room type has a photo. One pillow for a single room, two for anything larger.
 */
export function bedPlate(capacity: number): string {
  const double = capacity >= 2;
  const width = double ? 84 : 60;
  const x = 100 - width / 2;
  const pillows = double
    ? `<rect x="${x + 8}" y="56" width="${width / 2 - 12}" height="20" rx="7" fill="#f4ead2"/><rect x="${100 + 4}" y="56" width="${width / 2 - 12}" height="20" rx="7" fill="#f4ead2"/>`
    : `<rect x="${x + 8}" y="56" width="${width - 16}" height="20" rx="7" fill="#f4ead2"/>`;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">
<defs>
<radialGradient id="p" cx="45%" cy="38%" r="70%"><stop offset="0" stop-color="#2a2417"/><stop offset="1" stop-color="#0c0a07"/></radialGradient>
<linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#f6e3a1"/><stop offset=".5" stop-color="#d4af37"/><stop offset="1" stop-color="#8c6420"/></linearGradient>
</defs>
<circle cx="100" cy="100" r="94" fill="url(#p)"/>
<circle cx="100" cy="100" r="94" fill="none" stroke="url(#g)" stroke-width="3"/>
<circle cx="100" cy="100" r="80" fill="none" stroke="#d4af37" stroke-opacity=".28" stroke-width="1"/>
<rect x="${x - 4}" y="44" width="${width + 8}" height="10" rx="4" fill="#5a4626"/>
<rect x="${x}" y="50" width="${width}" height="104" rx="8" fill="#e9dcc0"/>
${pillows}
<rect x="${x}" y="88" width="${width}" height="66" rx="8" fill="url(#g)"/>
<rect x="${x}" y="88" width="${width}" height="9" fill="#f6e3a1" fill-opacity=".7"/>
<path d="M${x + 6} 120h${width - 12}" stroke="#8c6420" stroke-opacity=".5" stroke-width="1.5"/>
</svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}
