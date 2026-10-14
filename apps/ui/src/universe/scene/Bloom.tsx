// Bloom for the Ultra and High presets (SPEC §7: post-processing behind quality settings). Takes over
// rendering while mounted (a useFrame with priority 1 replaces R3F's own render).
import { tokens } from '@universe/design-tokens';
import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useRef } from 'react';
import { Vector2 } from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';

export function Bloom({ strength = 0.7 }: { strength?: number }) {
  const { gl, scene, camera, size } = useThree();
  const composer = useRef<EffectComposer | null>(null);
  useEffect(() => {
    const c = new EffectComposer(gl);
    c.addPass(new RenderPass(scene, camera));
    c.addPass(new UnrealBloomPass(new Vector2(256, 256), strength, 0.45, 0.2));
    c.addPass(new OutputPass());
    composer.current = c;
    return () => {
      for (const pass of c.passes) pass.dispose(); // the composer frees only its own targets
      c.dispose();
      composer.current = null;
    };
  }, [gl, scene, camera, strength]);
  useEffect(() => {
    composer.current?.setSize(size.width, size.height);
  }, [size]);
  useFrame(() => composer.current?.render(), 1);
  // The composer's output is opaque: paint the space colour rather than lose the backdrop to black.
  return <color attach="background" args={[tokens.color.space['0']]} />;
}
