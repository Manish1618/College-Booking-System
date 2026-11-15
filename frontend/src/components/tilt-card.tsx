"use client";

import { motion, useMotionValue, useReducedMotion, useSpring, useTransform, type HTMLMotionProps } from "motion/react";
import type { PointerEvent, ReactNode } from "react";

/** A card that tilts toward the pointer in 3D, with a gold light that follows it. Still under reduced motion and on touch. */
export function TiltCard({ children, className, style, ...rest }: Omit<HTMLMotionProps<"article">, "children"> & { children: ReactNode }) {
  const reduce = useReducedMotion();
  const x = useMotionValue(0.5);
  const y = useMotionValue(0.5);
  const spring = { stiffness: 180, damping: 18, mass: 0.6 };
  const rotateX = useSpring(useTransform(y, [0, 1], [5, -5]), spring);
  const rotateY = useSpring(useTransform(x, [0, 1], [-7, 7]), spring);
  const glow = useTransform(
    [x, y] as const,
    ([gx, gy]: number[]) => `radial-gradient(420px circle at ${gx * 100}% ${gy * 100}%, rgb(212 175 55 / 0.14), transparent 45%)`,
  );

  const move = (event: PointerEvent<HTMLElement>) => {
    if (reduce || event.pointerType !== "mouse") return;
    const box = event.currentTarget.getBoundingClientRect();
    x.set((event.clientX - box.left) / box.width);
    y.set((event.clientY - box.top) / box.height);
  };
  const leave = () => {
    x.set(0.5);
    y.set(0.5);
  };

  return (
    <motion.article
      {...rest}
      onPointerMove={move}
      onPointerLeave={leave}
      style={reduce ? style : { ...style, rotateX, rotateY, transformPerspective: 1100 }}
      className={`relative [transform-style:preserve-3d] ${className ?? ""}`}
    >
      {!reduce && <motion.span aria-hidden="true" className="pointer-events-none absolute inset-0 rounded-[inherit]" style={{ background: glow }} />}
      {children}
    </motion.article>
  );
}
