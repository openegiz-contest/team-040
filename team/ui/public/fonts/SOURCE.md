# Fonts: IBM Plex Sans and IBM Plex Mono

Packages: `@fontsource/ibm-plex-sans@5.3.0`, `@fontsource/ibm-plex-mono@5.3.0` (npm, via jsDelivr).

Licence: SIL Open Font License 1.1 (copyright IBM Corp.); the licence texts are `LICENSE-ibm-plex-sans` and `LICENSE-ibm-plex-mono` (each as shipped in its package).

Subsets: `cyrillic` and `latin`, normal style; Sans 400/500/600, Mono 400/500. `fonts.css` is built from the `<weight>.css` files of the packages (unicode-range copied, `url()` made relative, `font-display: swap`, the `.woff` fallback dropped).

Note: the `cyrillic` subset covers U+0400-045F, U+0490-0491, U+04B0-04B1 (Russian, Ukrainian). The Kazakh letters (Ә Ғ Қ Ң Ө Ү Ұ Һ І, U+04xx above 045F) live in the `cyrillic-ext` subset, which is NOT vendored; those glyphs fall back to the next font in the stack.

| File | Source URL | Bytes | SHA-256 |
|---|---|---|---|
| `ibm-plex-sans-cyrillic-400-normal.woff2` | https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-sans@5.3.0/files/ibm-plex-sans-cyrillic-400-normal.woff2 | 14800 | `69afad88a0740b6e5647f1104c9176a261f1ad9d60202f605456a983799752e9` |
| `ibm-plex-sans-latin-400-normal.woff2` | https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-sans@5.3.0/files/ibm-plex-sans-latin-400-normal.woff2 | 22588 | `3b646991d30055a93a4ecc499713d4347953a74a947ecab435ab72070cbdab0e` |
| `ibm-plex-sans-cyrillic-500-normal.woff2` | https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-sans@5.3.0/files/ibm-plex-sans-cyrillic-500-normal.woff2 | 15000 | `200be3a2a6b1789fb8824a4a74c7cccb7137e83fde6200ea78d8829f99d43546` |
| `ibm-plex-sans-latin-500-normal.woff2` | https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-sans@5.3.0/files/ibm-plex-sans-latin-500-normal.woff2 | 24184 | `0717336fb31fcdcde4b8deb3675bb4a0f7f6d484864afcd6751ac29975962203` |
| `ibm-plex-sans-cyrillic-600-normal.woff2` | https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-sans@5.3.0/files/ibm-plex-sans-cyrillic-600-normal.woff2 | 15040 | `730becc6f005c18c31440f14d34677f2704a85e6afffd4bee6a64d5c95f45a55` |
| `ibm-plex-sans-latin-600-normal.woff2` | https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-sans@5.3.0/files/ibm-plex-sans-latin-600-normal.woff2 | 24252 | `8960851d691c054ed38e259bdcf1a6190d157b4203ed5bb32c632a863fb8ec2f` |
| `LICENSE-ibm-plex-sans` | https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-sans@5.3.0/LICENSE | 4429 | `d0283623ef57e722fd0eb688a8041589670c608ab780cd3612d06ba6f153d3fd` |
| `ibm-plex-mono-cyrillic-400-normal.woff2` | https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-mono@5.3.0/files/ibm-plex-mono-cyrillic-400-normal.woff2 | 8356 | `7635422bd10ddbbcb0e0caa1154b928298f5c8319b8c00b30978d4395f4783ce` |
| `ibm-plex-mono-latin-400-normal.woff2` | https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-mono@5.3.0/files/ibm-plex-mono-latin-400-normal.woff2 | 14708 | `08949f728dc52d528e69b1667d15c89a5686a4ee9a296ff90983985f99c380f7` |
| `ibm-plex-mono-cyrillic-500-normal.woff2` | https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-mono@5.3.0/files/ibm-plex-mono-cyrillic-500-normal.woff2 | 8460 | `1d89462e86cb8e87e7e9d6f6635605bd7c3081baca6caaecee84916bf7b60edc` |
| `ibm-plex-mono-latin-500-normal.woff2` | https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-mono@5.3.0/files/ibm-plex-mono-latin-500-normal.woff2 | 14888 | `01d285447409c8a588692162439a038b8cbd7871309ee20267b0d2d91c6e8e22` |
| `LICENSE-ibm-plex-mono` | https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-mono@5.3.0/LICENSE | 5299 | `23b0a9d0c6d3f140a0b77e483c5cfa6bba574325ef5cb189ed9f2fec4884533f` |
