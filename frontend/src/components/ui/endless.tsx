"use client";

/*
 * "Endless" 3D image corridor from 21st.dev, made data driven for the guesthouse: the planes come
 * from `slides` (a photo, or a gold glass card when a room type has no photo yet), the title and
 * caption are props, and `children` render above the corridor (the corridor itself ignores the
 * pointer). Animation and layout are the original GSAP code.
 */

import { useEffect, useRef, type CSSProperties, type ReactNode } from "react";
import { gsap } from "gsap";

export interface EndlessSlide {
  /** Photo URL. Without one the plane is drawn as a glass card showing the label. */
  src?: string;
  label: string;
  sublabel?: string;
}

export interface EndlessProps {
  slides: EndlessSlide[];
  title?: ReactNode;
  caption?: ReactNode;
  /** Height of the corridor, any CSS length. */
  height?: string;
  className?: string;
  "aria-label"?: string;
  children?: ReactNode;
}

/** Fewer planes than this leave visible gaps in the corridor, so short lists are repeated. */
const MIN_PLANES = 12;
const Z_FAR = -2400;
const Z_NEAR = 780;
const RANGE = Z_NEAR - Z_FAR;
const DURATION = 16;
const FADE_IN = 0.06;
const FADE_OUT = 0.04;

const css = `
/* The reset stops at the corridor: the title and overlay hold the page's own (Tailwind) content. */
.endless-root,
.endless-root .endless-scene *,
.endless-root .endless-scene *::before,
.endless-root .endless-scene *::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

.endless-root {
  position: relative;
  width: 100%;
  height: var(--endless-height, 100vh);
  overflow: hidden;
  background-color: #000000;
  color: #ffffff;
  font-family: inherit;
  user-select: none;
  pointer-events: none;
}

.endless-root .endless-scene {
  position: absolute;
  inset: 0;
  -webkit-perspective: 1100px;
  perspective: 1100px;
  -webkit-perspective-origin: 50% 50%;
  perspective-origin: 50% 50%;
  -webkit-transform-style: preserve-3d;
  transform-style: preserve-3d;
}

.endless-root .endless-world {
  position: absolute;
  inset: 0;
  -webkit-transform: translate3d(0, 0, 0);
  transform: translate3d(0, 0, 0);
  -webkit-transform-style: preserve-3d;
  transform-style: preserve-3d;
}

.endless-root .endless-plane {
  position: absolute;
  top: 50%;
  left: 50%;
  background-color: #000000;
  -webkit-transform-style: preserve-3d;
  transform-style: preserve-3d;
  transform-origin: 50% 50%;
  -webkit-backface-visibility: hidden;
  backface-visibility: hidden;
  will-change: transform;
}

.endless-root .endless-plane-card {
  display: flex;
  width: 100%;
  height: 100%;
  flex-direction: column;
  justify-content: flex-end;
  gap: 0.35rem;
  padding: 8%;
  border: 1px solid rgba(212, 175, 55, 0.45);
  background:
    radial-gradient(120% 80% at 20% 0%, rgba(212, 175, 55, 0.28), transparent 60%),
    linear-gradient(160deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0.02));
  color: #f3e3b5;
  font-family: inherit;
}

.endless-root .endless-plane-card strong {
  font-size: clamp(0.8rem, 1.8vw, 1.6rem);
  font-weight: 500;
  letter-spacing: 0.02em;
  line-height: 1.15;
}

.endless-root .endless-plane-card span {
  color: #b8a06a;
  font-size: clamp(0.6rem, 1vw, 0.9rem);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.endless-root .endless-plane img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  pointer-events: none;
  -webkit-transform: translateZ(0);
  transform: translateZ(0);
}

.endless-root .endless-title {
  position: absolute;
  top: 50%;
  left: 50%;
  z-index: 50;
  transform: translate(-50%, -50%);
  color: #ffffff;
  font-family: inherit;
  font-size: 0.625rem;
  text-align: center;
  font-weight: 500;
  letter-spacing: 0.08em;
  line-height: 1;
  white-space: nowrap;
}

.endless-root .endless-title:has(> *) {
  width: min(92%, 56rem);
  white-space: normal;
}

@media (min-width: 768px) {
  .endless-root .endless-title {
    font-size: 1.375rem;
  }
}

@media (min-width: 1200px) {
  .endless-root .endless-title {
    font-size: 1.875rem;
  }
}

.endless-root .endless-overlay {
  position: absolute;
  inset: 0;
  z-index: 60;
  pointer-events: none;
}

.endless-root .endless-overlay > * {
  pointer-events: auto;
}

.endless-root .endless-footer {
  position: absolute;
  bottom: 2.5rem;
  left: 50%;
  z-index: 50;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  transform: translateX(-50%);
  color: #707070;
}

@media (min-width: 768px) {
  .endless-root .endless-overlay {
  position: absolute;
  inset: 0;
  z-index: 60;
  pointer-events: none;
}

.endless-root .endless-overlay > * {
  pointer-events: auto;
}

.endless-root .endless-footer {
    bottom: 2rem;
  }
}

.endless-root .endless-globe {
  display: block;
  flex-shrink: 0;
}

.endless-root .endless-caption {
  color: #707070;
  font-family: inherit;
  font-size: 0.875rem;
  font-weight: 500;
  letter-spacing: 0.04em;
  line-height: 1.3;
  text-align: center;
  white-space: nowrap;
}

/* iOS WebKit flattens nested 3D when an ancestor uses overflow: hidden. */
@supports (-webkit-touch-callout: none) {
  .endless-root {
    overflow: visible;
    -webkit-clip-path: inset(0);
    clip-path: inset(0);
  }
}
`;

function opacityForProgress(progress: number) {
  if (progress < FADE_IN) return Math.max(0, progress / FADE_IN);
  if (progress > 1 - FADE_OUT) return Math.max(0, (1 - progress) / FADE_OUT);
  return 1;
}

function getLayout() {
  const width = window.innerWidth;
  const planeW = width < 768 ? Math.min(width * 0.26, 200) : Math.min(width * 0.26, 440);
  return {
    planeW,
    planeH: planeW * (4 / 3),
    offsetX: width * 0.33,
    angle: 24,
  };
}

export default function Endless({
  slides,
  title,
  caption,
  height,
  className,
  "aria-label": ariaLabel = "Endless 3D image corridor",
  children,
}: EndlessProps) {
  const worldRef = useRef<HTMLDivElement>(null);
  const planeSlides = slides.length === 0 ? [] : Array.from({ length: Math.max(MIN_PLANES, slides.length) }, (_, i) => slides[i % slides.length]);
  const signature = planeSlides.map((slide) => `${slide.src ?? ""}|${slide.label}`).join("\n");

  useEffect(() => {
    const world = worldRef.current;
    if (!world) return;

    const planes = Array.from(world.querySelectorAll<HTMLElement>(".endless-plane"));
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const tweens: gsap.core.Tween[] = [];

    gsap.ticker.lagSmoothing(0);
    gsap.set(world, { force3D: true });

    const applyLayout = () => {
      const { planeW, planeH, offsetX, angle } = getLayout();
      planes.forEach((plane, index) => {
        const isLeft = index % 2 === 0;
        plane.style.width = `${planeW}px`;
        plane.style.height = `${planeH}px`;
        gsap.set(plane, {
          xPercent: -50,
          yPercent: -50,
          x: isLeft ? -offsetX : offsetX,
          y: 0,
          rotationY: isLeft ? angle : -angle,
          force3D: true,
        });
      });
    };

    applyLayout();

    planes.forEach((plane, index) => {
      const img = plane.firstElementChild as HTMLElement;
      const startProgress = index / planes.length;

      gsap.set(plane, { z: Z_FAR + startProgress * RANGE });
      img.style.opacity = String(opacityForProgress(startProgress));
      plane.style.zIndex = String(Math.round(startProgress * 1000));

      if (reduceMotion) return;

      const tween = gsap.fromTo(
        plane,
        { z: Z_FAR },
        {
          z: Z_NEAR,
          duration: DURATION,
          ease: "none",
          repeat: -1,
          immediateRender: false,
          onUpdate() {
            const progress = this.progress();
            img.style.opacity = String(opacityForProgress(progress));
            plane.style.zIndex = String(Math.round(progress * 1000));
          },
        },
      );

      tween.progress(startProgress);
      tweens.push(tween);
    });

    window.addEventListener("resize", applyLayout);

    return () => {
      window.removeEventListener("resize", applyLayout);
      tweens.forEach((tween) => tween.kill());
      gsap.killTweensOf(planes);
    };
  }, [signature]);

  return (
    <section
      className={`endless-root ${className ?? ""}`}
      aria-label={ariaLabel}
      style={height ? ({ "--endless-height": height } as CSSProperties) : undefined}
    >
      <style>{css}</style>
      <div className="endless-scene" aria-hidden="true">
        <div className="endless-world" ref={worldRef}>
          {planeSlides.map((slide, index) => (
            <div className="endless-plane" key={index}>
              {slide.src ? (
                // eslint-disable-next-line @next/next/no-img-element -- photos come from the API's own resized set
                <img src={slide.src} alt="" loading="eager" decoding="async" />
              ) : (
                <div className="endless-plane-card">
                  {slide.sublabel && <span>{slide.sublabel}</span>}
                  <strong>{slide.label}</strong>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
      {title && <h1 className="endless-title">{title}</h1>}
      {caption && (
        <div className="endless-footer">
          <svg
            className="endless-globe"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            height="24"
            width="24"
            aria-hidden="true"
          >
            <path
              stroke="currentColor"
              strokeWidth="1"
              d="M23 12c0 -6.075 -4.925 -11 -11 -11m11 11c0 6.075 -4.925 11 -11 11m11 -11c0 2.21 -4.925 4 -11 4S1 14.21 1 12M12 1C5.925 1 1 5.925 1 12M12 1c2.761 0 5 4.925 5 11s-2.239 11 -5 11m0 -22C9.239 1 7 5.925 7 12s2.239 11 5 11M1 12c0 6.075 4.925 11 11 11"
            />
          </svg>
          <p className="endless-caption">{caption}</p>
        </div>
      )}
      {children && <div className="endless-overlay">{children}</div>}
    </section>
  );
}
export { Endless as Component };
