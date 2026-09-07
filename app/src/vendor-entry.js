// Everything the renderer needs from npm, bundled into one ES module so the
// page can load it from file:// without an import map or a dev server.
export * as THREE from 'three';
export { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
export { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';
