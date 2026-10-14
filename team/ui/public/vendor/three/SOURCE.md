# three.js (vendored)

Package: `three@0.186.1` (npm, latest stable on 2026-10-14), downloaded via jsDelivr.

Licence: MIT (copyright 2010-2026 three.js authors), see `LICENSE`.

Files are unmodified jsDelivr output. `build/three.module.min.js` imports `./three.core.js`, so the minified core (`build/three.core.min.js`) is stored under the name `three.core.js`. `GLTFLoader.js` imports `three`, `../utils/BufferGeometryUtils.js` and `../utils/SkeletonUtils.js`; the addons are not minified.

| File | Source URL | Bytes | SHA-256 |
|---|---|---|---|
| `three.module.min.js` | https://cdn.jsdelivr.net/npm/three@0.186.1/build/three.module.min.js | 392831 | `3bc833fceb6577bd1a380388f832ae61cd6e2f78ad02b0bf0d5adf5a4a9334fe` |
| `three.core.js` | https://cdn.jsdelivr.net/npm/three@0.186.1/build/three.core.min.js | 415816 | `3b346151f65ffdfca3e4c002bd58966b78c423087fb48a873f83200de1bffc48` |
| `addons/loaders/GLTFLoader.js` | https://cdn.jsdelivr.net/npm/three@0.186.1/examples/jsm/loaders/GLTFLoader.js | 117570 | `131c0f78c01d19368ae495caa65b3adaa10487810a36a05bb5901b769a35ac16` |
| `addons/utils/BufferGeometryUtils.js` | https://cdn.jsdelivr.net/npm/three@0.186.1/examples/jsm/utils/BufferGeometryUtils.js | 37712 | `9fb63427ce6641fa14fd0baff9cc4d1b5f9c3d85fd084bf2e90e803c44ec1797` |
| `addons/utils/SkeletonUtils.js` | https://cdn.jsdelivr.net/npm/three@0.186.1/examples/jsm/utils/SkeletonUtils.js | 11535 | `b1632a703206c3d830de9fcbe515696770d04b71a15ee6b50afa6d2c3298c86f` |
| `LICENSE` | https://cdn.jsdelivr.net/npm/three@0.186.1/LICENSE | 1081 | `8b378ebe60e2fe500158cb0ac71cb5e8b7d92953c2abcc63a0eb90499653b5bc` |

Total: 976545 bytes (without SOURCE.md).

Import map the page needs (paths relative to the HTML page in `public/`):

```html
<script type="importmap">
{"imports": {"three": "./vendor/three/three.module.min.js", "three/addons/": "./vendor/three/addons/"}}
</script>
```

Usage: `import * as THREE from 'three'; import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';`
