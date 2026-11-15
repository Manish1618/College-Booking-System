"use client";

/*
 * A small procedural 3D model of the guesthouse for the home page: a two-storey block with wings,
 * a columned porch, lit windows and trees on a round plinth, drawn with three.js. No model files
 * are downloaded. It turns slowly and leans toward the pointer; with reduced motion it stands still,
 * and it stops rendering while it is off screen.
 */

import { ContactShadows, Sparkles } from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import { Component, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import * as THREE from "three";

const GOLD = "#d4af37";
const STONE = "#2a2620";
const STONE_LIGHT = "#3a342a";
const TRIM = "#b8953a";
const WINDOW = "#ffb44d";
const LEAF = "#1f2a1c";

function Windows({ width, floors, y0, z, columns, skip = [] as number[] }: { width: number; floors: number; y0: number; z: number; columns: number; skip?: number[] }) {
  const items = [];
  const step = width / columns;
  for (let f = 0; f < floors; f++) {
    for (let c = 0; c < columns; c++) {
      if (skip.includes(c)) continue;
      // Some windows stay dark so the house looks lived in rather than lit like a sign.
      const lit = (c * 7 + f * 3) % 5 !== 0;
      items.push(
        <group key={`${f}-${c}`} position={[-width / 2 + step * (c + 0.5), y0 + f * 1.05, z]}>
          <mesh position={[0, 0, -0.01]}>
            <boxGeometry args={[0.46, 0.66, 0.04]} />
            <meshStandardMaterial color={TRIM} metalness={0.7} roughness={0.35} />
          </mesh>
          <mesh position={[0, 0, 0.012]}>
            <planeGeometry args={[0.36, 0.56]} />
            <meshStandardMaterial color={lit ? WINDOW : "#14120e"} emissive={lit ? WINDOW : "#000"} emissiveIntensity={lit ? 0.85 : 0} toneMapped={false} />
          </mesh>
        </group>,
      );
    }
  }
  return <>{items}</>;
}

function Block({ width, height, depth, position, columns, skip }: { width: number; height: number; depth: number; position: [number, number, number]; columns: number; skip?: number[] }) {
  return (
    <group position={position}>
      <mesh castShadow receiveShadow position={[0, height / 2, 0]}>
        <boxGeometry args={[width, height, depth]} />
        <meshStandardMaterial color={STONE} roughness={0.85} />
      </mesh>
      {/* Gold cornice and floor band. */}
      <mesh position={[0, height + 0.06, 0]}>
        <boxGeometry args={[width + 0.16, 0.12, depth + 0.16]} />
        <meshStandardMaterial color={GOLD} metalness={0.85} roughness={0.3} />
      </mesh>
      <mesh position={[0, 1.18, 0]}>
        <boxGeometry args={[width + 0.04, 0.05, depth + 0.04]} />
        <meshStandardMaterial color={TRIM} metalness={0.7} roughness={0.4} />
      </mesh>
      <Windows width={width} floors={2} y0={0.62} z={depth / 2 + 0.01} columns={columns} skip={skip} />
      <group rotation={[0, Math.PI, 0]}>
        <Windows width={width} floors={2} y0={0.62} z={depth / 2 + 0.01} columns={columns} />
      </group>
    </group>
  );
}

function Tree({ position, scale = 1 }: { position: [number, number, number]; scale?: number }) {
  return (
    <group position={position} scale={scale}>
      <mesh castShadow position={[0, 0.35, 0]}>
        <cylinderGeometry args={[0.05, 0.07, 0.7, 8]} />
        <meshStandardMaterial color="#3b2c1a" roughness={0.9} />
      </mesh>
      <mesh castShadow position={[0, 0.95, 0]}>
        <icosahedronGeometry args={[0.42, 1]} />
        <meshStandardMaterial color={LEAF} roughness={0.8} flatShading />
      </mesh>
      <mesh castShadow position={[0.12, 1.3, 0.05]}>
        <icosahedronGeometry args={[0.28, 1]} />
        <meshStandardMaterial color="#26331f" roughness={0.8} flatShading />
      </mesh>
    </group>
  );
}

function Porch() {
  const pediment = useMemo(() => {
    const shape = new THREE.Shape();
    shape.moveTo(-1.05, 0);
    shape.lineTo(1.05, 0);
    shape.lineTo(0, 0.55);
    shape.closePath();
    return new THREE.ExtrudeGeometry(shape, { depth: 0.18, bevelEnabled: false });
  }, []);
  return (
    <group position={[0, 0, 1.35]}>
      {/* Steps */}
      {[0, 1, 2].map((i) => (
        <mesh key={i} receiveShadow position={[0, 0.06 + i * 0.1, 0.55 - i * 0.16]}>
          <boxGeometry args={[2.2 - i * 0.1, 0.1, 0.5]} />
          <meshStandardMaterial color={STONE_LIGHT} roughness={0.7} />
        </mesh>
      ))}
      {/* Columns */}
      {[-0.85, -0.3, 0.3, 0.85].map((x) => (
        <mesh key={x} castShadow position={[x, 1.2, 0.15]}>
          <cylinderGeometry args={[0.07, 0.085, 1.95, 16]} />
          <meshStandardMaterial color="#e9dcc0" roughness={0.45} />
        </mesh>
      ))}
      <mesh position={[0, 2.22, 0.08]}>
        <boxGeometry args={[2.2, 0.12, 0.5]} />
        <meshStandardMaterial color={GOLD} metalness={0.85} roughness={0.3} />
      </mesh>
      <mesh geometry={pediment} position={[0, 2.28, -0.12]}>
        <meshStandardMaterial color={STONE_LIGHT} roughness={0.6} />
      </mesh>
      {/* Door with warm light spilling out */}
      <mesh position={[0, 0.85, -0.04]}>
        <planeGeometry args={[0.5, 0.95]} />
        <meshStandardMaterial color={WINDOW} emissive={WINDOW} emissiveIntensity={1.2} toneMapped={false} />
      </mesh>
      <pointLight position={[0, 1.2, 0.6]} color="#ffbe5c" intensity={6} distance={4} decay={2} />
    </group>
  );
}

function House({ animate }: { animate: boolean }) {
  const group = useRef<THREE.Group>(null);
  useFrame((state, delta) => {
    const g = group.current;
    if (!g || !animate) return;
    // Slow turn plus a lean toward the pointer, eased so it never snaps.
    const targetX = state.pointer.y * 0.12;
    const spin = g.userData.spin ?? -0.5;
    g.userData.spin = spin + delta * 0.12;
    const targetY = g.userData.spin + state.pointer.x * 0.35;
    g.rotation.y += (targetY - g.rotation.y) * Math.min(1, delta * 3);
    g.rotation.x += (targetX - g.rotation.x) * Math.min(1, delta * 3);
  });
  return (
    <group ref={group} rotation={[0.04, -0.5, 0]} position={[0, -0.9, 0]}>
      {/* Plinth */}
      <mesh receiveShadow position={[0, -0.12, 0]}>
        <cylinderGeometry args={[4.6, 4.75, 0.24, 96]} />
        <meshStandardMaterial color="#120f0b" roughness={0.6} metalness={0.2} />
      </mesh>
      <mesh position={[0, 0.005, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[4.5, 4.6, 128]} />
        <meshStandardMaterial color={GOLD} metalness={0.9} roughness={0.25} emissive={GOLD} emissiveIntensity={0.25} />
      </mesh>
      {/* Lawn and path */}
      <mesh receiveShadow position={[0, 0.01, 0.4]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[4.4, 64]} />
        <meshStandardMaterial color="#141a12" roughness={0.95} />
      </mesh>
      <mesh position={[0, 0.02, 3]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[0.9, 2.6]} />
        <meshStandardMaterial color="#3a3226" roughness={0.8} />
      </mesh>

      <Block width={3.6} height={2.3} depth={2.4} position={[0, 0, 0]} columns={5} skip={[2]} />
      <Block width={1.9} height={1.9} depth={2} position={[-2.75, 0, -0.1]} columns={3} />
      <Block width={1.9} height={1.9} depth={2} position={[2.75, 0, -0.1]} columns={3} />
      {/* Hipped roof on the main block */}
      <mesh castShadow position={[0, 2.62, 0]} rotation={[0, Math.PI / 4, 0]} scale={[1.33, 1, 0.9]}>
        <coneGeometry args={[1.9, 0.75, 4]} />
        <meshStandardMaterial color="#1a1612" roughness={0.6} metalness={0.3} />
      </mesh>
      <Porch />

      <Tree position={[-3.4, 0, 2]} scale={1.1} />
      <Tree position={[3.5, 0, 1.8]} />
      <Tree position={[-1.6, 0, 3.2]} scale={0.8} />
      <Tree position={[2, 0, 3.3]} scale={0.85} />
      <Tree position={[0.5, 0, -3]} scale={1.2} />
      <Tree position={[-3, 0, -2.4]} />

      {/* Garden lamps along the path */}
      {[-0.7, 0.7].map((x) =>
        [2.4, 3.6].map((z) => (
          <group key={`${x}-${z}`} position={[x, 0, z]}>
            <mesh position={[0, 0.3, 0]}>
              <cylinderGeometry args={[0.02, 0.02, 0.6, 6]} />
              <meshStandardMaterial color={GOLD} metalness={0.9} roughness={0.3} />
            </mesh>
            <mesh position={[0, 0.63, 0]}>
              <sphereGeometry args={[0.06, 12, 12]} />
              <meshStandardMaterial color={WINDOW} emissive={WINDOW} emissiveIntensity={2} toneMapped={false} />
            </mesh>
          </group>
        )),
      )}
    </group>
  );
}

/** Keeps a WebGL failure inside the hero: the page around it (dates, rooms) must stay usable. */
class ModelBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function hasWebGL() {
  try {
    const canvas = document.createElement("canvas");
    return !!(canvas.getContext("webgl2") ?? canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

/** Shown when the browser cannot draw 3D: a quiet gold glow instead of the model. */
function StillFallback() {
  return (
    <div className="grid size-full place-items-center">
      <div className="size-48 rounded-full border border-gold/30 bg-[radial-gradient(circle_at_40%_35%,rgb(212_175_55/0.35),transparent_65%)] shadow-[0_0_80px_-10px_rgb(212_175_55/0.4)]" />
    </div>
  );
}

export default function GuesthouseModel({ className }: { className?: string }) {
  const host = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(true);
  const [reduced, setReduced] = useState(false);
  const [webgl] = useState(hasWebGL);

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(media.matches);
    update();
    media.addEventListener("change", update);
    const node = host.current;
    const observer = node ? new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting)) : null;
    if (node && observer) observer.observe(node);
    return () => {
      media.removeEventListener("change", update);
      observer?.disconnect();
    };
  }, []);

  return (
    <div ref={host} className={className} role="img" aria-label="3D model of the college guesthouse at night">
      {!webgl ? (
        <StillFallback />
      ) : (
        <ModelBoundary fallback={<StillFallback />}>
          <Canvas
            shadows
            dpr={[1, 2]}
            frameloop={visible ? (reduced ? "demand" : "always") : "never"}
            camera={{ position: [0, 5.2, 14.5], fov: 34 }}
            gl={{ antialias: true, alpha: true }}
          >
            <ambientLight intensity={0.35} />
            <hemisphereLight args={["#c9d6ff", "#2a1f0f", 0.45]} />
            <directionalLight
              castShadow
              position={[5, 8, 4]}
              intensity={1.4}
              color="#ffe9b8"
              shadow-mapSize-width={1024}
              shadow-mapSize-height={1024}
              shadow-camera-left={-6}
              shadow-camera-right={6}
              shadow-camera-top={6}
              shadow-camera-bottom={-6}
            />
            <directionalLight position={[-6, 3, -4]} intensity={0.5} color="#8aa0ff" />
            <House animate={!reduced} />
            <ContactShadows position={[0, -1.3, 0]} opacity={0.6} scale={14} blur={2.6} far={3} />
            {!reduced && <Sparkles count={40} scale={[9, 4, 6]} position={[0, 1.2, 0]} size={2.2} speed={0.25} color={GOLD} opacity={0.7} />}
          </Canvas>
        </ModelBoundary>
      )}
    </div>
  );
}
