'use client';

import Image from 'next/image';
import { useEffect, useRef, useState } from 'react';
import { smoothMouth, targetMouthOpen, type RafiiAvatarMode } from './avatar-state';

const MODEL_URL = '/raffi/raffi-live-v1.glb';
const FALLBACK_URL = '/raffi/full-512.png';

type LiveProps = {
  mode: RafiiAvatarMode;
  level: number;
  outputMuted: boolean;
  reducedMotion: boolean;
};

type LiveState = LiveProps;

type VecLike = {
  x: number;
  y: number;
  z: number;
  set: (x: number, y: number, z: number) => void;
};

type DisposableLike = { dispose?: () => void };

type MaterialLike = Record<string, unknown> & DisposableLike;

type SceneNode = {
  position: VecLike;
  rotation: VecLike;
  scale: VecLike;
  geometry?: DisposableLike;
  material?: MaterialLike | MaterialLike[];
  morphTargetDictionary?: Record<string, number>;
  morphTargetInfluences?: number[];
  getObjectByName?: (name: string) => SceneNode | undefined;
  traverse?: (callback: (object: SceneNode) => void) => void;
};

type SceneLike = {
  add: (...objects: unknown[]) => void;
};

type CameraLike = {
  fov: number;
  aspect: number;
  position: VecLike;
  updateProjectionMatrix: () => void;
  lookAt: (x: number, y: number, z: number) => void;
};

type RendererLike = {
  domElement: HTMLCanvasElement;
  setClearColor: (color: number, alpha: number) => void;
  setPixelRatio: (ratio: number) => void;
  setSize: (width: number, height: number, updateStyle?: boolean) => void;
  render: (scene: SceneLike, camera: CameraLike) => void;
  dispose: () => void;
  forceContextLoss?: () => void;
  outputColorSpace: unknown;
};

type GltfLike = { scene: SceneNode };

function coarsePointer(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(pointer: coarse)').matches;
}

function finiteLevel(value: number): number {
  return Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0;
}

/**
 * Decorative real-time Rafii stage. Voice audio remains owned entirely by
 * voice-session.ts; this component only observes its state and output level.
 */
export function RafiiLiveAvatar({ mode, level, outputMuted, reducedMotion }: LiveProps) {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const mountRef = useRef<HTMLDivElement | null>(null);
  const kickRef = useRef<() => void>(() => {});
  const latest = useRef<LiveState>({ mode, level, outputMuted, reducedMotion });
  const [renderState, setRenderState] = useState<'loading' | 'ready' | 'fallback'>('loading');
  const fallback = renderState === 'fallback';

  // Keep the animation loop on current Voice Mode data without rebuilding WebGL.
  latest.current = { mode, level: finiteLevel(level), outputMuted, reducedMotion };

  useEffect(() => {
    kickRef.current();
  }, [mode, level, outputMuted, reducedMotion]);

  useEffect(() => {
    const stage = stageRef.current;
    const mount = mountRef.current;
    if (!stage || !mount) return;

    let cancelled = false;
    let renderer: RendererLike | null = null;
    let scene: SceneLike | null = null;
    let camera: CameraLike | null = null;
    let model: SceneNode | null = null;
    let rafId: number | null = null;
    let resizeObserver: ResizeObserver | null = null;
    let lastTime = performance.now();
    let mouthOpen = 0;
    let modelReady = false;
    let visibilityHandler: (() => void) | null = null;
    let contextLostHandler: ((event: Event) => void) | null = null;

    const nodes: Record<string, SceneNode | undefined> = {};
    const bases: Record<string, { px: number; py: number; pz: number; rx: number; ry: number; rz: number; sx: number; sy: number; sz: number }> = {};

    const remember = (name: string) => {
      const node = model?.getObjectByName?.(name);
      if (!node) return;
      nodes[name] = node;
      bases[name] = {
        px: node.position.x,
        py: node.position.y,
        pz: node.position.z,
        rx: node.rotation.x,
        ry: node.rotation.y,
        rz: node.rotation.z,
        sx: node.scale.x,
        sy: node.scale.y,
        sz: node.scale.z
      };
    };

    const restoreAxis = (name: string) => {
      const node = nodes[name];
      const base = bases[name];
      if (!node || !base) return;
      node.position.set(base.px, base.py, base.pz);
      node.rotation.set(base.rx, base.ry, base.rz);
      node.scale.set(base.sx, base.sy, base.sz);
    };

    const setMorph = (name: string, value: number) => {
      const mouth = nodes.Mouth;
      if (!mouth || !mouth.morphTargetInfluences) return;
      const index = mouth.morphTargetDictionary?.[name];
      if (typeof index !== 'number') return;
      mouth.morphTargetInfluences[index] = Math.min(1, Math.max(0, value));
    };

    const renderPose = (dt: number, now: number) => {
      if (!renderer || !scene || !camera || !modelReady) return;
      const state = latest.current;
      const seconds = now / 1000;
      const target = targetMouthOpen({ mode: state.mode, level: state.level, outputMuted: state.outputMuted });
      mouthOpen = smoothMouth(mouthOpen, target, dt);
      if (state.outputMuted || state.mode !== 'speaking') mouthOpen = 0;

      stage.dataset.rafiiMouthOpen = mouthOpen.toFixed(3);
      stage.dataset.rafiiContinuousMotion = state.reducedMotion ? 'off' : 'on';

      // Always restore from the authored pose before layering this frame.
      for (const name of ['Body', 'Head', 'EarL', 'EarR', 'EyeL', 'EyeR', 'ArmL', 'ArmR', 'Tail01', 'Tail02', 'Tail03', 'Tail04']) restoreAxis(name);

      setMorph('Open', mouthOpen);
      setMorph('Wide', state.mode === 'speaking' ? mouthOpen * (0.18 + 0.11 * Math.sin(seconds * 7.0)) : 0);
      setMorph('Round', state.mode === 'speaking' ? mouthOpen * (0.12 + 0.08 * Math.sin(seconds * 5.2 + 0.9)) : 0);
      setMorph('Smile', state.mode === 'speaking' ? 0.12 + mouthOpen * 0.10 : state.mode === 'listening' ? 0.10 : 0.05);

      if (!state.reducedMotion) {
        const body = nodes.Body;
        const head = nodes.Head;
        const earL = nodes.EarL;
        const earR = nodes.EarR;
        const armL = nodes.ArmL;
        const armR = nodes.ArmR;
        const eyeL = nodes.EyeL;
        const eyeR = nodes.EyeR;

        const breath = Math.sin(seconds * 2.1) * 0.008;
        if (body) body.scale.y *= 1 + breath;

        const attentive = state.mode === 'listening' ? 1 : 0;
        const thinking = state.mode === 'thinking' ? 1 : 0;
        const speaking = state.mode === 'speaking' ? 1 : 0;
        const interrupted = state.mode === 'interrupted' ? 1 : 0;

        if (head) {
          head.rotation.z += attentive * -0.055 + thinking * 0.075 + speaking * Math.sin(seconds * 2.9) * 0.020;
          head.rotation.x += interrupted * -0.025 + speaking * Math.sin(seconds * 3.7 + 0.5) * 0.012;
        }
        if (earL) earL.rotation.z += attentive * -0.065 + interrupted * -0.085 + Math.sin(seconds * 1.5) * 0.010;
        if (earR) earR.rotation.z += attentive * 0.065 + interrupted * 0.085 - Math.sin(seconds * 1.5) * 0.010;
        if (armL) armL.rotation.z += speaking * (0.045 + Math.sin(seconds * 3.1) * 0.028);
        if (armR) armR.rotation.z -= speaking * (0.045 + Math.sin(seconds * 3.1 + 1.1) * 0.028);

        // A short natural blink every ~4.8 s, with no random eye darting.
        const blinkPhase = seconds % 4.8;
        const blink = blinkPhase < 0.13 ? Math.sin((blinkPhase / 0.13) * Math.PI) : 0;
        if (eyeL) eyeL.scale.y *= 1 - blink * 0.78;
        if (eyeR) eyeR.scale.y *= 1 - blink * 0.78;

        const tailEnergy = state.mode === 'speaking' ? 0.11 : state.mode === 'listening' ? 0.07 : state.mode === 'thinking' ? 0.035 : 0.05;
        ['Tail01', 'Tail02', 'Tail03', 'Tail04'].forEach((name, index) => {
          const tail = nodes[name];
          if (!tail) return;
          tail.rotation.z += Math.sin(seconds * (1.3 + tailEnergy * 3) - index * 0.52) * tailEnergy * (0.8 + index * 0.16);
        });
      }

      renderer.render(scene, camera);
    };

    const frame = (now: number) => {
      rafId = null;
      if (cancelled || document.hidden) return;
      const dt = Math.min(0.05, Math.max(0, (now - lastTime) / 1000));
      lastTime = now;
      renderPose(dt, now);

      // Reduced motion is event-driven: one frame per incoming voice/state change.
      if (!latest.current.reducedMotion) rafId = requestAnimationFrame(frame);
    };

    const ensureLoop = () => {
      if (cancelled || !modelReady || document.hidden) return;
      if (rafId !== null) return;
      lastTime = performance.now();
      rafId = requestAnimationFrame(frame);
    };

    kickRef.current = ensureLoop;

    const fail = () => {
      if (cancelled) return;
      if (rafId !== null) cancelAnimationFrame(rafId);
      rafId = null;
      setRenderState('fallback');
    };

    void (async () => {
      try {
        // These are runtime dependencies. The project currently ships Three without
        // declaration packages, so keep the 3D implementation isolated from app types.
        // @ts-expect-error three ships as a runtime dependency in this project
        const THREE = await import('three');
        // @ts-expect-error GLTFLoader runtime module has no project-local declaration
        const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js');
        if (cancelled) return;

        const liveScene: SceneLike = new THREE.Scene();
        const liveCamera: CameraLike = new THREE.PerspectiveCamera(28, 1, 0.05, 100);
        const liveRenderer: RendererLike = new THREE.WebGLRenderer({ alpha: true, antialias: !coarsePointer(), powerPreference: 'high-performance' });
        scene = liveScene;
        camera = liveCamera;
        renderer = liveRenderer;

        liveRenderer.setClearColor(0x000000, 0);
        liveRenderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, coarsePointer() ? 1.5 : 2));
        liveRenderer.outputColorSpace = THREE.SRGBColorSpace;
        liveRenderer.domElement.setAttribute('aria-hidden', 'true');
        liveRenderer.domElement.style.width = '100%';
        liveRenderer.domElement.style.height = '100%';
        liveRenderer.domElement.style.display = 'block';
        liveRenderer.domElement.style.pointerEvents = 'none';
        mount.replaceChildren(liveRenderer.domElement);

        liveScene.add(new THREE.HemisphereLight(0xfff8ee, 0x807a78, 2.15));
        const key = new THREE.DirectionalLight(0xfff0dd, 2.7);
        key.position.set(-3.5, 4.8, 5.5);
        liveScene.add(key);
        const fill = new THREE.DirectionalLight(0xddeaff, 1.35);
        fill.position.set(4.2, 2.2, 3.0);
        liveScene.add(fill);

        const resize = () => {
          const rect = mount.getBoundingClientRect();
          const width = Math.max(1, Math.round(rect.width));
          const height = Math.max(1, Math.round(rect.height));
          liveRenderer.setSize(width, height, false);
          liveCamera.aspect = width / height;
          liveCamera.updateProjectionMatrix();
          if (modelReady) renderPose(0, performance.now());
        };
        resizeObserver = new ResizeObserver(resize);
        resizeObserver.observe(mount);

        contextLostHandler = (event: Event) => {
          event.preventDefault();
          fail();
        };
        liveRenderer.domElement.addEventListener('webglcontextlost', contextLostHandler);

        const loader = new GLTFLoader();
        loader.load(
          MODEL_URL,
          (gltf: GltfLike) => {
            if (cancelled) {
              gltf.scene?.traverse?.((object: SceneNode) => object.geometry?.dispose?.());
              return;
            }
            model = gltf.scene;
            liveScene.add(model);

            const box = new THREE.Box3().setFromObject(model);
            const size = box.getSize(new THREE.Vector3());
            const center = box.getCenter(new THREE.Vector3());
            model.position.x -= center.x;
            model.position.y -= center.y - size.y * 0.07;
            model.position.z -= center.z;

            const framedHeight = Math.max(1, size.y * 0.90);
            const distance = framedHeight / (2 * Math.tan(THREE.MathUtils.degToRad(liveCamera.fov * 0.5)));
            liveCamera.position.set(0, size.y * 0.03, Math.max(distance * 0.86, size.z * 3.2));
            liveCamera.lookAt(0, size.y * 0.08, 0);

            for (const name of ['Body', 'Head', 'EarL', 'EarR', 'EyeL', 'EyeR', 'Mouth', 'ArmL', 'ArmR', 'Tail01', 'Tail02', 'Tail03', 'Tail04']) remember(name);
            modelReady = true;
            setRenderState('ready');
            resize();
            ensureLoop();
          },
          undefined,
          fail
        );

        visibilityHandler = () => {
          if (document.hidden) {
            if (rafId !== null) cancelAnimationFrame(rafId);
            rafId = null;
          } else {
            ensureLoop();
          }
        };
        document.addEventListener('visibilitychange', visibilityHandler);
        resize();
      } catch {
        fail();
      }
    })();

    return () => {
      cancelled = true;
      kickRef.current = () => {};
      if (rafId !== null) cancelAnimationFrame(rafId);
      if (visibilityHandler) document.removeEventListener('visibilitychange', visibilityHandler);
      resizeObserver?.disconnect();
      if (renderer?.domElement && contextLostHandler) renderer.domElement.removeEventListener('webglcontextlost', contextLostHandler);

      model?.traverse?.((object: SceneNode) => {
        object.geometry?.dispose?.();
        const materials = Array.isArray(object.material) ? object.material : object.material ? [object.material] : [];
        for (const material of materials) {
          for (const value of Object.values(material)) {
            if (value && typeof value === 'object' && 'isTexture' in (value as Record<string, unknown>)) (value as { dispose: () => void }).dispose();
          }
          material.dispose?.();
        }
      });
      if (renderer) {
        renderer.dispose();
        renderer.forceContextLoss?.();
      }
      mount.replaceChildren();
    };
  }, []);

  return (
    <div
      ref={stageRef}
      aria-hidden='true'
      className='pointer-events-none relative h-[clamp(180px,32vw,240px)] w-full min-w-0 overflow-hidden'
      data-rafii-3d={fallback ? 'fallback' : 'live'}
      data-rafii-avatar-mode={mode}
      data-rafii-mouth-open='0.000'
      data-rafii-model-ready={renderState}
      data-rafii-continuous-motion={reducedMotion ? 'off' : 'on'}
    >
      {fallback ? (
        <Image src={FALLBACK_URL} alt='' fill sizes='(max-width: 640px) 100vw, 480px' className='object-contain object-center' priority={false} />
      ) : (
        <div ref={mountRef} className='size-full' />
      )}
    </div>
  );
}
