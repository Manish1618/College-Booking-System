"use client";

/*
 * A 3D cutaway of a guesthouse room, furnished from the room type's own facts: a single or double
 * bed by capacity, a second bed or sofa for family rooms, a desk in singles, and richer finishes
 * (wall art, armchair, pendant) as the price tier rises. Drawn with three.js, no model files.
 * The room eases toward the pointer; under reduced motion it stays still.
 */

import { ContactShadows, RoundedBox } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Component, useEffect, useRef, useState, type ReactNode } from "react";
import * as THREE from "three";

export interface RoomSceneProps {
  capacity: number;
  /** Price tier 1 (plainest) to 5 (finest). */
  tier: number;
  className?: string;
  label: string;
}

const GOLD = "#c9a445";
const WALL = "#262019";
const WALL_PANEL = "#1b1611";
const FLOOR = "#3a2a1c";
const LINEN = "#efe6d2";
const DUVET = "#d8c9a6";
const WOOD = "#4a3524";
const LAMP = "#ffc978";
const FABRIC = "#3d3a33";

function Bed({ width, x, throwColor }: { width: number; x: number; throwColor: string }) {
  const pillows = width > 1.3 ? [-width / 4, width / 4] : [0];
  return (
    <group position={[x, 0, -1.3]}>
      {/* Upholstered headboard with piping */}
      <RoundedBox args={[width + 0.3, 1.25, 0.14]} radius={0.06} smoothness={4} position={[0, 0.85, -1.08]} castShadow>
        <meshStandardMaterial color={FABRIC} roughness={0.95} />
      </RoundedBox>
      <mesh position={[0, 1.49, -1.08]}>
        <boxGeometry args={[width + 0.3, 0.025, 0.16]} />
        <meshStandardMaterial color={GOLD} metalness={0.85} roughness={0.3} />
      </mesh>
      {/* Frame, mattress, duvet */}
      <mesh position={[0, 0.16, 0]} castShadow receiveShadow>
        <boxGeometry args={[width + 0.12, 0.2, 2.12]} />
        <meshStandardMaterial color={WOOD} roughness={0.6} />
      </mesh>
      <RoundedBox args={[width, 0.26, 2.02]} radius={0.08} smoothness={4} position={[0, 0.39, 0]} castShadow receiveShadow>
        <meshStandardMaterial color={LINEN} roughness={0.9} />
      </RoundedBox>
      <RoundedBox args={[width + 0.06, 0.16, 1.36]} radius={0.07} smoothness={4} position={[0, 0.5, 0.34]} castShadow>
        <meshStandardMaterial color={DUVET} roughness={1} />
      </RoundedBox>
      {/* Turned-down sheet and a throw across the foot */}
      <RoundedBox args={[width + 0.07, 0.17, 0.22]} radius={0.06} smoothness={4} position={[0, 0.5, -0.38]}>
        <meshStandardMaterial color="#faf5e8" roughness={0.9} />
      </RoundedBox>
      <RoundedBox args={[width + 0.1, 0.19, 0.42]} radius={0.07} smoothness={4} position={[0, 0.5, 0.72]} castShadow>
        <meshStandardMaterial color={throwColor} roughness={0.85} metalness={0.15} />
      </RoundedBox>
      {pillows.map((px) => (
        <group key={px} position={[px, 0.6, -0.76]}>
          <RoundedBox args={[Math.min(0.72, width - 0.2), 0.17, 0.42]} radius={0.08} smoothness={4} rotation={[0.28, 0, 0]} castShadow>
            <meshStandardMaterial color="#fbf7ec" roughness={0.95} />
          </RoundedBox>
        </group>
      ))}
    </group>
  );
}

function Nightstand({ x }: { x: number }) {
  return (
    <group position={[x, 0, -2.05]}>
      <RoundedBox args={[0.5, 0.5, 0.44]} radius={0.03} smoothness={3} position={[0, 0.25, 0]} castShadow receiveShadow>
        <meshStandardMaterial color={WOOD} roughness={0.55} />
      </RoundedBox>
      <mesh position={[0, 0.3, 0.225]}>
        <boxGeometry args={[0.16, 0.02, 0.02]} />
        <meshStandardMaterial color={GOLD} metalness={0.9} roughness={0.3} />
      </mesh>
      {/* Lamp */}
      <mesh position={[0, 0.53, 0]}>
        <cylinderGeometry args={[0.07, 0.09, 0.05, 20]} />
        <meshStandardMaterial color={GOLD} metalness={0.9} roughness={0.3} />
      </mesh>
      <mesh position={[0, 0.66, 0]}>
        <cylinderGeometry args={[0.012, 0.012, 0.24, 8]} />
        <meshStandardMaterial color={GOLD} metalness={0.9} roughness={0.3} />
      </mesh>
      <mesh position={[0, 0.86, 0]}>
        <cylinderGeometry args={[0.1, 0.15, 0.2, 24, 1, true]} />
        <meshStandardMaterial color={LAMP} emissive={LAMP} emissiveIntensity={0.9} side={THREE.DoubleSide} toneMapped={false} />
      </mesh>
      <pointLight position={[0, 0.9, 0.1]} color="#ffb861" intensity={2.2} distance={3.2} decay={2} />
    </group>
  );
}

function Window() {
  return (
    <group position={[-2.96, 1.55, 0.2]} rotation={[0, Math.PI / 2, 0]}>
      <mesh>
        <planeGeometry args={[1.5, 1.7]} />
        <meshStandardMaterial color="#1a2740" emissive="#31476e" emissiveIntensity={0.9} toneMapped={false} />
      </mesh>
      {/* Frame and mullions */}
      {[
        [0, 0.87, 1.6, 0.06],
        [0, -0.87, 1.6, 0.06],
        [-0.77, 0, 0.06, 1.8],
        [0.77, 0, 0.06, 1.8],
        [0, 0, 0.035, 1.7],
      ].map(([px, py, w, h], i) => (
        <mesh key={i} position={[px, py, 0.02]}>
          <boxGeometry args={[w, h, 0.05]} />
          <meshStandardMaterial color={WOOD} roughness={0.5} />
        </mesh>
      ))}
      {/* Curtains, gathered in folds */}
      {[-1.05, 1.05].map((side) => (
        <group key={side} position={[side, -0.2, 0.1]}>
          {[0, 1, 2, 3].map((f) => (
            <mesh key={f} position={[(f - 1.5) * 0.11, 0, (f % 2) * 0.04]} castShadow>
              <cylinderGeometry args={[0.065, 0.075, 2.5, 10]} />
              <meshStandardMaterial color="#6b5a3a" roughness={0.95} />
            </mesh>
          ))}
        </group>
      ))}
      <mesh position={[0, 1.08, 0.12]} rotation={[0, 0, Math.PI / 2]}>
        <cylinderGeometry args={[0.018, 0.018, 2.9, 8]} />
        <meshStandardMaterial color={GOLD} metalness={0.9} roughness={0.3} />
      </mesh>
      <pointLight position={[0, 0, 0.6]} intensity={3} distance={5} decay={2} color="#8fa9e6" />
    </group>
  );
}

function Desk() {
  return (
    <group position={[2.1, 0, -2.05]}>
      <mesh position={[0, 0.74, 0]} castShadow receiveShadow>
        <boxGeometry args={[1.2, 0.05, 0.55]} />
        <meshStandardMaterial color={WOOD} roughness={0.5} />
      </mesh>
      {[-0.55, 0.55].map((lx) => (
        <mesh key={lx} position={[lx, 0.37, 0]} castShadow>
          <boxGeometry args={[0.04, 0.74, 0.5]} />
          <meshStandardMaterial color={GOLD} metalness={0.85} roughness={0.35} />
        </mesh>
      ))}
      {/* Chair */}
      <group position={[0, 0, 0.55]}>
        <RoundedBox args={[0.46, 0.08, 0.44]} radius={0.03} position={[0, 0.46, 0]} castShadow>
          <meshStandardMaterial color={FABRIC} roughness={0.9} />
        </RoundedBox>
        <RoundedBox args={[0.46, 0.5, 0.06]} radius={0.03} position={[0, 0.76, 0.2]} castShadow>
          <meshStandardMaterial color={FABRIC} roughness={0.9} />
        </RoundedBox>
        {[
          [-0.19, -0.18],
          [0.19, -0.18],
          [-0.19, 0.18],
          [0.19, 0.18],
        ].map(([cx, cz]) => (
          <mesh key={`${cx}${cz}`} position={[cx, 0.21, cz]}>
            <cylinderGeometry args={[0.018, 0.018, 0.42, 8]} />
            <meshStandardMaterial color={GOLD} metalness={0.85} roughness={0.35} />
          </mesh>
        ))}
      </group>
      {/* Books and a small lamp glow */}
      <mesh position={[-0.3, 0.8, -0.1]} castShadow>
        <boxGeometry args={[0.3, 0.07, 0.2]} />
        <meshStandardMaterial color="#7a2e2e" roughness={0.8} />
      </mesh>
      <mesh position={[0.35, 0.86, -0.12]}>
        <sphereGeometry args={[0.09, 20, 20]} />
        <meshStandardMaterial color={LAMP} emissive={LAMP} emissiveIntensity={0.8} toneMapped={false} />
      </mesh>
    </group>
  );
}

function Seat({ wide, position, rotation = 0 }: { wide: boolean; position: [number, number, number]; rotation?: number }) {
  const w = wide ? 1.7 : 0.8;
  return (
    <group position={position} rotation={[0, rotation, 0]}>
      <RoundedBox args={[w, 0.3, 0.75]} radius={0.09} smoothness={4} position={[0, 0.3, 0]} castShadow receiveShadow>
        <meshStandardMaterial color="#5a4a2f" roughness={0.95} />
      </RoundedBox>
      <RoundedBox args={[w, 0.55, 0.18]} radius={0.08} smoothness={4} position={[0, 0.58, -0.3]} castShadow>
        <meshStandardMaterial color="#5a4a2f" roughness={0.95} />
      </RoundedBox>
      {[-w / 2 + 0.08, w / 2 - 0.08].map((ax) => (
        <RoundedBox key={ax} args={[0.16, 0.42, 0.75]} radius={0.07} smoothness={4} position={[ax, 0.42, 0]} castShadow>
          <meshStandardMaterial color="#5a4a2f" roughness={0.95} />
        </RoundedBox>
      ))}
      <RoundedBox args={[0.34, 0.3, 0.12]} radius={0.05} position={[wide ? -0.45 : 0, 0.56, -0.12]} rotation={[-0.25, 0, 0.1]} castShadow>
        <meshStandardMaterial color={GOLD} roughness={0.7} metalness={0.2} />
      </RoundedBox>
    </group>
  );
}

function Room({ capacity, tier, animate }: { capacity: number; tier: number; animate: boolean }) {
  const group = useRef<THREE.Group>(null);
  const born = useRef(0);
  useFrame((state, delta) => {
    const g = group.current;
    if (!g) return;
    if (!animate) {
      g.scale.setScalar(1);
      return;
    }
    // Settle in on first sight, then lean a little toward the pointer.
    born.current = Math.min(1, born.current + delta * 1.6);
    const ease = 1 - Math.pow(1 - born.current, 3);
    g.scale.setScalar(0.9 + 0.1 * ease);
    const targetY = -0.12 + state.pointer.x * 0.22 + (1 - ease) * 0.5;
    const targetX = -state.pointer.y * 0.06;
    g.rotation.y += (targetY - g.rotation.y) * Math.min(1, delta * 3.5);
    g.rotation.x += (targetX - g.rotation.x) * Math.min(1, delta * 3.5);
  });

  const double = capacity >= 2;
  const family = capacity >= 3;
  const bedWidth = double ? 1.75 : 1.05;
  const bedX = family ? -1.25 : double ? -0.35 : -1.1;
  const fine = tier >= 4;
  const throwColor = tier >= 3 ? GOLD : "#8a6a3c";

  return (
    <group ref={group} position={[0, -1.25, 0]}>
      {/* Floor: boards with a dark border */}
      <mesh position={[0, -0.08, 0]} receiveShadow>
        <boxGeometry args={[6.1, 0.16, 5.1]} />
        <meshStandardMaterial color="#1c140d" roughness={0.8} />
      </mesh>
      {Array.from({ length: 12 }, (_, i) => (
        <mesh key={i} position={[-2.75 + i * 0.5, 0.003, 0]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
          <planeGeometry args={[0.485, 4.98]} />
          <meshStandardMaterial color={i % 3 === 0 ? "#402e1f" : i % 3 === 1 ? FLOOR : "#35261a"} roughness={0.42} metalness={0.08} />
        </mesh>
      ))}

      {/* Back and left walls with a panelled lower third and a gold rail */}
      <mesh position={[0, 1.5, -2.55]} receiveShadow>
        <boxGeometry args={[6.1, 3, 0.1]} />
        <meshStandardMaterial color={WALL} roughness={0.95} />
      </mesh>
      <mesh position={[-3.05, 1.5, 0]} receiveShadow>
        <boxGeometry args={[0.1, 3, 5.1]} />
        <meshStandardMaterial color={WALL} roughness={0.95} />
      </mesh>
      <mesh position={[0, 0.5, -2.49]}>
        <boxGeometry args={[6, 1, 0.03]} />
        <meshStandardMaterial color={WALL_PANEL} roughness={0.8} />
      </mesh>
      <mesh position={[0, 1.01, -2.48]}>
        <boxGeometry args={[6, 0.03, 0.04]} />
        <meshStandardMaterial color={GOLD} metalness={0.85} roughness={0.3} />
      </mesh>
      <mesh position={[-2.99, 0.5, 0]}>
        <boxGeometry args={[0.03, 1, 5]} />
        <meshStandardMaterial color={WALL_PANEL} roughness={0.8} />
      </mesh>
      <mesh position={[-2.98, 1.01, 0]}>
        <boxGeometry args={[0.04, 0.03, 5]} />
        <meshStandardMaterial color={GOLD} metalness={0.85} roughness={0.3} />
      </mesh>

      <Window />

      {/* Rug */}
      <RoundedBox args={[family ? 4.4 : 3.2, 0.03, 2.2]} radius={0.012} position={[family ? 0 : bedX + 0.3, 0.02, 0.2]} receiveShadow>
        <meshStandardMaterial color="#6d5b3d" roughness={1} />
      </RoundedBox>
      <RoundedBox args={[family ? 4.1 : 2.9, 0.032, 1.9]} radius={0.012} position={[family ? 0 : bedX + 0.3, 0.022, 0.2]} receiveShadow>
        <meshStandardMaterial color="#2b2620" roughness={1} />
      </RoundedBox>

      <Bed width={bedWidth} x={bedX} throwColor={throwColor} />
      <Nightstand x={bedX - bedWidth / 2 - 0.42} />
      {double && <Nightstand x={bedX + bedWidth / 2 + 0.42} />}

      {family && <Bed width={1.05} x={1.75} throwColor={throwColor} />}
      {capacity >= 4 && <Seat wide position={[1.6, 0, 1.6]} rotation={Math.PI} />}
      {!double && <Desk />}
      {double && !family && <Seat wide={fine} position={[2.05, 0, fine ? 0.9 : 0.4]} rotation={-Math.PI / 2} />}
      {double && !family && fine && (
        <group position={[1.15, 0, 0.9]}>
          <mesh position={[0, 0.36, 0]} castShadow>
            <cylinderGeometry args={[0.38, 0.38, 0.04, 32]} />
            <meshStandardMaterial color="#1a1612" roughness={0.25} metalness={0.4} />
          </mesh>
          <mesh position={[0, 0.18, 0]}>
            <cylinderGeometry args={[0.03, 0.2, 0.36, 16]} />
            <meshStandardMaterial color={GOLD} metalness={0.9} roughness={0.3} />
          </mesh>
        </group>
      )}

      {/* Framed art above the bed, in gold for the finer rooms */}
      {tier >= 2 && (
        <group position={[bedX, 2.1, -2.47]}>
          <mesh>
            <boxGeometry args={[fine ? 1.3 : 0.9, 0.6, 0.04]} />
            <meshStandardMaterial color={GOLD} metalness={0.85} roughness={0.3} />
          </mesh>
          <mesh position={[0, 0, 0.022]}>
            <planeGeometry args={[fine ? 1.2 : 0.8, 0.5]} />
            <meshStandardMaterial color="#2a3a44" roughness={0.6} />
          </mesh>
          <mesh position={[fine ? 0.2 : 0.1, -0.05, 0.024]}>
            <circleGeometry args={[0.13, 24]} />
            <meshStandardMaterial color="#d9a441" emissive="#d9a441" emissiveIntensity={0.25} />
          </mesh>
        </group>
      )}

      {/* Pendant in the finest rooms */}
      {tier >= 5 && (
        <group position={[0.8, 2.75, 0.3]}>
          <mesh position={[0, 0.2, 0]}>
            <cylinderGeometry args={[0.008, 0.008, 0.5, 6]} />
            <meshStandardMaterial color={GOLD} metalness={0.9} roughness={0.3} />
          </mesh>
          <mesh>
            <sphereGeometry args={[0.16, 24, 24]} />
            <meshStandardMaterial color={LAMP} emissive={LAMP} emissiveIntensity={1} toneMapped={false} />
          </mesh>
          <pointLight color="#ffc77a" intensity={3} distance={5} decay={2} />
        </group>
      )}

      {/* A plant by the window softens the corner */}
      <group position={[-2.5, 0, 2]}>
        <mesh position={[0, 0.2, 0]} castShadow>
          <cylinderGeometry args={[0.2, 0.15, 0.4, 20]} />
          <meshStandardMaterial color="#16120e" roughness={0.4} metalness={0.3} />
        </mesh>
        {[0, 1, 2, 3, 4].map((leaf) => (
          <mesh key={leaf} position={[Math.sin(leaf * 1.3) * 0.16, 0.75 + (leaf % 2) * 0.18, Math.cos(leaf * 1.3) * 0.16]} rotation={[Math.sin(leaf) * 0.5, leaf, Math.cos(leaf) * 0.5]} castShadow>
            <sphereGeometry args={[0.24, 8, 6]} />
            <meshStandardMaterial color="#27351f" roughness={0.9} flatShading />
          </mesh>
        ))}
      </group>
    </group>
  );
}

/** Keeps the whole room in frame: the narrower the stage, the further back the camera stands. */
function Rig() {
  const { camera, size } = useThree();
  useEffect(() => {
    const aspect = size.width / Math.max(1, size.height);
    const back = Math.max(1.14, 1.5 / aspect);
    camera.position.set(7.2 * back, 4.6 * back, 8.4 * back);
    camera.lookAt(0, 0.1, 0);
    camera.updateProjectionMatrix();
  }, [camera, size]);
  return null;
}

class SceneBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
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

export default function RoomScene({ capacity, tier, className, label }: RoomSceneProps) {
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

  const fallback = (
    <div className="grid size-full place-items-center text-sm text-muted-foreground">3D preview is not available in this browser.</div>
  );

  return (
    <div ref={host} className={className} role="img" aria-label={label}>
      {!webgl ? (
        fallback
      ) : (
        <SceneBoundary fallback={fallback}>
          <Canvas
            shadows
            dpr={[1, 2]}
            frameloop={visible ? (reduced ? "demand" : "always") : "never"}
            camera={{ position: [7.2, 4.6, 8.4], fov: 27 }}
            gl={{ antialias: true, alpha: true }}
          >
            <Rig />
            <ambientLight intensity={0.8} color="#ffe8c7" />
            <hemisphereLight args={["#ffe2b0", "#1a120a", 0.8]} />
            <directionalLight
              castShadow
              position={[4.5, 7, 5]}
              intensity={2}
              color="#ffdca8"
              shadow-mapSize-width={2048}
              shadow-mapSize-height={2048}
              shadow-camera-left={-5}
              shadow-camera-right={5}
              shadow-camera-top={5}
              shadow-camera-bottom={-5}
              shadow-radius={6}
              shadow-bias={-0.0004}
            />
            {/* One group per room type so each one settles in afresh when chosen. */}
            <Room key={`${capacity}-${tier}`} capacity={capacity} tier={tier} animate={!reduced} />
            <ContactShadows position={[0, -1.42, 0]} opacity={0.55} scale={12} blur={2.8} far={2.5} />
          </Canvas>
        </SceneBoundary>
      )}
    </div>
  );
}
