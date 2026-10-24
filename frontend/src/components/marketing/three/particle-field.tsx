"use client";

import { useEffect, useRef } from "react";

import { cn } from "@/lib/utils";

/**
 * A field of points rolling like a slow sea, drawn with three.js behind a band.
 * The pointer sends a ripple through it.
 *
 * Decorative and cheap by construction:
 *   - three.js is imported inside the effect, so it is a separate chunk that loads
 *     after the page is interactive and never on the server;
 *   - the wave is computed in the vertex shader, so a frame is one draw call;
 *   - it renders only while on screen and while the tab is visible;
 *   - with reduced motion it draws a single still frame;
 *   - without WebGL nothing is drawn, and the band's CSS grid and glow remain.
 */

type Tone = "night" | "blue";

const TONES: Record<Tone, { low: string; high: string; opacity: number; additive: boolean }> = {
  night: { low: "#2447f5", high: "#c9d2ff", opacity: 0.95, additive: true },
  blue: { low: "#ffffff", high: "#ffffff", opacity: 0.5, additive: false },
};

const VERTEX = /* glsl */ `
  uniform float uTime;
  uniform vec2 uPointer;
  uniform float uPointerStrength;
  uniform float uSize;
  uniform float uPixelRatio;
  attribute float aSeed;
  varying float vHeight;
  varying float vFade;

  void main() {
    vec3 p = position;
    float t = uTime;
    float h = sin(p.x * 0.32 + t * 0.55) * 0.55
            + cos(p.z * 0.41 + t * 0.42) * 0.45
            + sin((p.x + p.z) * 0.17 + t * 0.28) * 0.35;
    float d = distance(p.xz, uPointer);
    h += exp(-d * d * 0.06) * sin(d * 1.3 - t * 2.4) * 0.9 * uPointerStrength;
    p.y += h;

    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = uSize * uPixelRatio * (0.55 + aSeed * 0.9) / -mv.z;

    vHeight = clamp(h * 0.55 + 0.5, 0.0, 1.0);
    vFade = (1.0 - smoothstep(7.0, 46.0, -mv.z)) * smoothstep(0.6, 4.0, -mv.z);
  }
`;

const FRAGMENT = /* glsl */ `
  uniform vec3 uLow;
  uniform vec3 uHigh;
  uniform float uOpacity;
  varying float vHeight;
  varying float vFade;

  void main() {
    float r = length(gl_PointCoord - 0.5);
    if (r > 0.5) discard;
    float a = (1.0 - smoothstep(0.05, 0.5, r)) * vFade * uOpacity * (0.35 + vHeight * 0.65);
    gl_FragColor = vec4(mix(uLow, uHigh, vHeight), a);
  }
`;

export function ParticleField({ tone = "night", className }: { tone?: Tone; className?: string }) {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = host.current;
    if (!node) return;
    let cancelled = false;
    let teardown = () => {};

    // A failed download (offline, or a deploy mid-visit) leaves the band's CSS
    // grid and glow on their own, as without WebGL.
    import("three")
      .then((THREE) => {
        if (!cancelled) teardown = mount(THREE, node, TONES[tone]);
      })
      .catch(() => {});

    return () => {
      cancelled = true;
      teardown();
    };
  }, [tone]);

  return <div ref={host} className={cn("mk-field", className)} aria-hidden />;
}

function mount(THREE: typeof import("three"), node: HTMLDivElement, colors: (typeof TONES)[Tone]): () => void {
  let renderer: import("three").WebGLRenderer;
  try {
    renderer = new THREE.WebGLRenderer({ alpha: true, antialias: false, powerPreference: "low-power" });
  } catch {
    return () => {};
  }

  const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const narrow = node.clientWidth < 640;
  const cols = narrow ? 90 : 170;
  const rows = narrow ? 48 : 80;
  const gap = 0.5;

  const positions = new Float32Array(cols * rows * 3);
  const seeds = new Float32Array(cols * rows);
  for (let i = 0; i < cols; i++) {
    for (let j = 0; j < rows; j++) {
      const k = i * rows + j;
      positions[k * 3] = (i - cols / 2) * gap;
      positions[k * 3 + 2] = 4 - j * gap;
      seeds[k] = Math.random();
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("aSeed", new THREE.BufferAttribute(seeds, 1));

  const pixelRatio = Math.min(window.devicePixelRatio || 1, 1.75);
  const uniforms = {
    uTime: { value: 0 },
    uPointer: { value: new THREE.Vector2(0, -6) },
    uPointerStrength: { value: 0 },
    uSize: { value: narrow ? 30 : 36 },
    uPixelRatio: { value: pixelRatio },
    uLow: { value: new THREE.Color(colors.low) },
    uHigh: { value: new THREE.Color(colors.high) },
    uOpacity: { value: colors.opacity },
  };

  const material = new THREE.ShaderMaterial({
    uniforms,
    vertexShader: VERTEX,
    fragmentShader: FRAGMENT,
    transparent: true,
    depthWrite: false,
    blending: colors.additive ? THREE.AdditiveBlending : THREE.NormalBlending,
  });

  const scene = new THREE.Scene();
  scene.add(new THREE.Points(geometry, material));

  const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 100);
  camera.position.set(0, 3.4, 9);
  camera.lookAt(0, -0.6, -8);

  renderer.setPixelRatio(pixelRatio);
  renderer.setClearColor(0x000000, 0);
  node.appendChild(renderer.domElement);

  const resize = () => {
    const width = node.clientWidth;
    const height = node.clientHeight;
    if (!width || !height) return;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  };
  resize();

  // The pointer, projected onto the sea's resting plane.
  const ray = new THREE.Raycaster();
  const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  const ndc = new THREE.Vector2();
  const hit = new THREE.Vector3();
  const target = new THREE.Vector2(0, -6);
  let strength = 0;
  const onPointer = (event: PointerEvent) => {
    const box = node.getBoundingClientRect();
    if (event.clientY < box.top || event.clientY > box.bottom) {
      strength = 0;
      return;
    }
    ndc.set(((event.clientX - box.left) / box.width) * 2 - 1, -((event.clientY - box.top) / box.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    if (ray.ray.intersectPlane(plane, hit)) {
      target.set(hit.x, hit.z);
      strength = 1;
    }
  };

  let last = performance.now();
  let frame = 0;
  let onScreen = true;
  let first = true;

  const draw = () => {
    const now = performance.now();
    const dt = Math.min((now - last) / 1000, 0.05);
    last = now;
    uniforms.uTime.value += dt;
    uniforms.uPointer.value.lerp(target, 0.06);
    uniforms.uPointerStrength.value += (strength - uniforms.uPointerStrength.value) * 0.05;
    renderer.render(scene, camera);
    if (first) {
      first = false;
      node.dataset.ready = "";
    }
  };

  const loop = () => {
    draw();
    frame = requestAnimationFrame(loop);
  };

  const start = () => {
    if (still || frame || !onScreen || document.hidden) return;
    last = performance.now();
    frame = requestAnimationFrame(loop);
  };
  const stop = () => {
    cancelAnimationFrame(frame);
    frame = 0;
  };

  const visibility = new IntersectionObserver(([entry]) => {
    onScreen = Boolean(entry?.isIntersecting);
    if (onScreen) start();
    else stop();
  });
  visibility.observe(node);

  const sizing = new ResizeObserver(() => {
    resize();
    if (still) draw();
  });
  sizing.observe(node);

  const onTab = () => (document.hidden ? stop() : start());
  document.addEventListener("visibilitychange", onTab);

  if (still) {
    uniforms.uTime.value = 4;
    draw();
  } else {
    window.addEventListener("pointermove", onPointer, { passive: true });
    start();
  }

  return () => {
    stop();
    visibility.disconnect();
    sizing.disconnect();
    document.removeEventListener("visibilitychange", onTab);
    window.removeEventListener("pointermove", onPointer);
    geometry.dispose();
    material.dispose();
    renderer.dispose();
    renderer.domElement.remove();
  };
}
